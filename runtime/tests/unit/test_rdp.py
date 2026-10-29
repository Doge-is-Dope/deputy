from types import SimpleNamespace

import pytest
from Xlib import X

import computer_use.computers.rdp
from computer_use.computers import ComputerError
from computer_use.computers.rdp import RdpComputer, full_keysym, xdotool_combo
from computer_use.desktop.keys import parse_combos


class RecordingRdp(RdpComputer):
    """Records Unicode and shell input instead of sending it to Windows."""

    def __init__(self):
        super().__init__(":1")
        self.commands: list[tuple] = []
        self.pointer = (0, 0)

    async def _unicode_chunk(self, text):
        self.commands.append(("unicode", text))

    async def cursor_position(self):
        return self.pointer

    async def _run(self, *args, timeout=None):
        self.commands.append(args)


def sent(rdp: RecordingRdp) -> list[tuple]:
    short = []
    for command in rdp.commands:
        if command[0] == "unicode":
            short.append(command)
        elif command[:2] == ("xdotool", "key"):
            short.append(("key", *command[4:]))
    return short


def test_keys_map_to_xdotool_keysyms():
    combos = parse_combos("ctrl+S win Enter alt+F4 pagedown ctrl+/ BackSpace")
    assert [xdotool_combo(combo) for combo in combos] == [
        "ctrl+s", "super", "Return", "alt+F4", "Next", "ctrl+slash", "BackSpace",
    ]


def test_keys_map_to_full_keysyms_for_xtest():
    assert [full_keysym(key) for key in ["ctrl", "win", "enter", "a", "/", "f4"]] == [
        "Control_L", "Super_L", "Return", "a", "slash", "F4",
    ]


async def test_modifiers_are_held_as_keysyms():
    rdp = RecordingRdp()
    await rdp.click((10, 20), "left", 1, ["win"])
    (command,) = rdp.commands
    assert " keydown super click " in " ".join(command) and command[-2:] == ("keyup", "super")


async def test_unicode_preserves_text_surrogates_and_newlines():
    rdp = RecordingRdp()
    text = "Ab中🙂🚀" * 40
    await rdp.type_text(text + "\r\n下一行\n")
    chunks = [command[1] for command in sent(rdp) if command[0] == "unicode"]
    assert "".join(chunks) == text + "下一行"
    assert all(0 < len(chunk.encode()) <= 60 for chunk in chunks)
    assert [command for command in sent(rdp) if command[0] == "key"] == [("key", "Return")] * 2


async def test_unicode_pipe_must_exist_and_be_a_fifo(tmp_path):
    rdp = RdpComputer(":1", tmp_path / "missing")
    with pytest.raises(ComputerError, match="pipe is unavailable"):
        await rdp.type_text("中文🙂")
    target = tmp_path / "regular-file"
    target.write_text("original")
    rdp.keyboard_pipe = target
    with pytest.raises(ComputerError, match="not a pipe"):
        await rdp.type_text("must not overwrite")
    assert target.read_text() == "original"


async def test_a_unicode_failure_does_not_send_enter_or_remaining_lines():
    rdp = RecordingRdp()

    async def fail(text):
        rdp.commands.append(("unicode", text))
        raise ComputerError("text delivery failed")

    rdp._unicode_chunk = fail
    with pytest.raises(ComputerError, match="text delivery failed"):
        await rdp.type_text("first\nsecond")
    assert rdp.commands == [("unicode", "first")]


def moves(rdp: RecordingRdp) -> list[tuple]:
    """Each pointer move the recorded xdotool commands make: (waits for it, x, y)."""
    found = []
    for command in rdp.commands:
        for index, arg in enumerate(command):
            if arg == "mousemove":
                waits = command[index + 1] == "--sync"
                x, y = command[index + 2: index + 4] if waits else command[index + 1: index + 3]
                found.append((waits, int(x), int(y)))
    return found


async def test_a_move_to_where_the_pointer_already_is_does_not_wait():
    # Debian's xdotool waits 15 s for a --sync move that leaves the pointer where it is.
    rdp = RecordingRdp()
    rdp.pointer = (100, 100)
    await rdp.click((100, 100), "left", 1, [])
    await rdp.click((200, 150), "left", 1, [])
    await rdp.scroll((100, 100), "down", 3, [])
    await rdp.move((100, 100))
    assert moves(rdp) == [
        (False, 100, 100), (True, 200, 150), (False, 100, 100), (False, 100, 100), (True, 99, 100), (True, 100, 100),
    ]


async def test_a_drag_from_the_pointer_waits_only_for_moves_that_move_it():
    rdp = RecordingRdp()
    rdp.pointer = (430, 400)
    await rdp.drag([(430, 400), (550, 550)], [])
    await rdp.drag([(10, 10), (10, 10)], [])
    assert moves(rdp) == [
        (False, 430, 400), (True, 490, 475), (True, 550, 550), (True, 549, 550), (True, 550, 550),
        (True, 10, 10), (False, 10, 10), (False, 10, 10), (True, 9, 10), (True, 10, 10),
    ]


class FakeDisplay:
    """The lasting X connection: which keys and buttons are down, and the XTest input sent over it."""

    def __init__(self, keys_down=(), buttons=0):
        self.keymap = [0] * 32  # one bit per key code, as X reports it
        for code in keys_down:
            self.keymap[code // 8] |= 1 << code % 8
        self.buttons = buttons
        self.sent: list[tuple] = []

    def query_keymap(self):
        return self.keymap

    def screen(self):
        return SimpleNamespace(root=SimpleNamespace(query_pointer=lambda: SimpleNamespace(mask=self.buttons)))

    def xtest_fake_input(self, event_type, detail=0, x=0, y=0):
        self.sent.append((event_type, x, y) if event_type == X.MotionNotify else (event_type, detail))

    def sync(self):
        pass


async def test_letting_go_releases_only_the_keys_and_buttons_that_are_down():
    rdp = RecordingRdp()
    rdp._xtest = FakeDisplay(keys_down=[37, 64], buttons=X.Button1Mask)  # Control_L and Alt_L, the left button

    await rdp.release_all()

    assert rdp._xtest.sent == [(X.KeyRelease, 37), (X.KeyRelease, 64), (X.ButtonRelease, 1)]
    assert rdp.commands == []  # no xdotool process: a release is not held up by one


async def test_one_notch_moves_there_and_turns_the_wheel_over_xtest():
    rdp = RecordingRdp()
    rdp._xtest = FakeDisplay()

    await rdp.scroll((300, 200), "down", 1, [])
    await rdp.scroll((10, 20), "up", 1, [])
    await rdp.scroll(None, "right", 1, [])

    assert rdp._xtest.sent == [
        (X.MotionNotify, 300, 200), (X.ButtonPress, 5), (X.ButtonRelease, 5),
        (X.MotionNotify, 10, 20), (X.ButtonPress, 4), (X.ButtonRelease, 4),
        (X.ButtonPress, 7), (X.ButtonRelease, 7),
    ]
    assert rdp.commands == []  # no xdotool process, so no 50 ms click delay


async def test_more_notches_or_held_modifiers_still_scroll_with_xdotool():
    rdp = RecordingRdp()
    rdp._xtest = FakeDisplay()
    rdp.pointer = (300, 200)

    await rdp.scroll((300, 200), "down", 3, [])
    await rdp.scroll((300, 200), "up", 1, ["ctrl"])

    assert rdp._xtest.sent == []
    assert rdp.commands == [
        ("xdotool", "mousemove", "300", "200", "click", "--repeat", "3", "--delay", "50", "5"),
        ("xdotool", "mousemove", "300", "200", "keydown", "ctrl", "click", "--repeat", "1", "--delay", "50", "4",
         "keyup", "ctrl"),
    ]


async def test_a_notch_without_a_display_fails_and_reconnects_next_time():
    class Gone(FakeDisplay):
        def xtest_fake_input(self, *args, **kwargs):
            raise OSError("connection closed")

    rdp = RecordingRdp()
    rdp._xtest = Gone()
    with pytest.raises(ComputerError, match="XTest input failed"):
        await rdp.scroll((300, 200), "down", 1, [])
    assert rdp._xtest is None


async def test_a_command_that_hangs_is_stopped_and_fails():
    with pytest.raises(ComputerError, match="did not finish within 0.2 seconds and was stopped"):
        await RdpComputer(":1")._run("sleep", "30", timeout=0.2)


async def test_a_screenshot_without_a_display_fails_as_the_desktop(monkeypatch):
    def no_display(xdisplay):
        raise OSError("X connection failed: error 1")

    monkeypatch.setattr(computer_use.computers.rdp.ImageGrab, "grab", no_display)
    with pytest.raises(ComputerError, match="screenshot failed: X connection failed"):
        await RdpComputer(":1").screenshot()
