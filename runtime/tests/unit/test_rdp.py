"""The RDP backend's own work: key names to X keysyms, typing through the clipboard, and pointer moves."""

import asyncio
from types import SimpleNamespace

import pytest
from Xlib import X

import computer_use.computers.rdp
from computer_use.computers import ComputerError
from computer_use.computers.rdp import RdpComputer, full_keysym, xdotool_combo
from computer_use.desktop.keys import parse_combos


class RecordingRdp(RdpComputer):
    """Records the xdotool and xclip commands instead of running them, and keeps the clipboard."""

    def __init__(self, type_mode="paste"):
        super().__init__(":1", type_mode)
        self.commands: list[tuple] = []
        self.clipboard: str | None = None
        self.fetches = True  # Windows fetches each pasted text; False: the clipboard sync stalled
        self.xclip_error: str | None = None
        self.pointer = (0, 0)
        self.timeouts: list[float | None] = []  # each command's own time limit, None for the usual one

    async def cursor_position(self):
        return self.pointer

    async def _run(self, *args, stdin=None, capture=True, timeout=None):
        self.timeouts.append(timeout)
        if args[0] == "xclip" and "-o" in args:
            if self.clipboard is None:
                raise ComputerError("xclip failed: target UTF8_STRING not available")
            return self.clipboard
        if args[0] == "xclip":
            if self.xclip_error:
                raise ComputerError(f"xclip failed: {self.xclip_error}")
            self.clipboard = stdin.decode()
            self.commands.append(("clipboard", self.clipboard))
            if "-loops" in args and not self.fetches:
                await asyncio.Event().wait()  # serves the text until cancelled
        else:
            self.commands.append(args)
        return ""


def sent(rdp: RecordingRdp) -> list[tuple]:
    """The input, short: ("clipboard", text), ("key", keysyms...), ("type", text) or ("reconnect",)."""
    short = []
    for command in rdp.commands:
        if command[0] == "clipboard":
            short.append(command)
        elif command[:2] == ("xdotool", "key"):
            short.append(("key", *command[4:]))
        elif command[:2] == ("xdotool", "type"):
            short.append(("type", command[-1]))
        elif command[-1] == "windowkill":
            short.append(("reconnect",))
    return short


@pytest.fixture(autouse=True)
def no_paste_wait(monkeypatch):
    monkeypatch.setattr(computer_use.computers.rdp, "PASTE_WAIT_SECONDS", 0)
    monkeypatch.setattr(computer_use.computers.rdp, "FETCH_TIMEOUT_SECONDS", 0.01)


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


async def test_typing_pastes_everything_by_default():
    rdp = RecordingRdp()
    await rdp.type_text("C:\\agent-output\\result.txt")
    assert sent(rdp) == [("clipboard", "C:\\agent-output\\result.txt"), ("key", "ctrl+v")]


async def test_pasted_newlines_press_enter():
    rdp = RecordingRdp()
    await rdp.type_text("第一行\r\n第二行\n\nnotepad\n")
    assert sent(rdp) == [
        ("clipboard", "第一行"), ("key", "ctrl+v"), ("key", "Return"),
        ("clipboard", "第二行"), ("key", "ctrl+v"), ("key", "Return"), ("key", "Return"),
        ("clipboard", "notepad"), ("key", "ctrl+v"), ("key", "Return"),
    ]


async def test_typing_puts_the_clipboard_back():
    rdp = RecordingRdp()
    rdp.clipboard = "copied before typing"
    await rdp.type_text("你好")
    assert sent(rdp) == [("clipboard", "你好"), ("key", "ctrl+v"), ("clipboard", "copied before typing")]
    assert rdp.clipboard == "copied before typing"


async def test_a_paste_windows_does_not_take_fails_without_restarting_the_session():
    rdp = RecordingRdp()
    rdp.clipboard = "copied before typing"
    rdp.fetches = False  # e.g. the focus is on a Save As dialog's file list, which takes no text
    with pytest.raises(ComputerError, match="did not confirm taking the pasted text"):
        await rdp.type_text("notepad\nmore")
    # The lines after it are not typed: Enter could act on the wrong text, or press a dialog's default button.
    assert sent(rdp) == [("clipboard", "notepad"), ("key", "ctrl+v"), ("clipboard", "copied before typing")]


async def test_a_paste_after_one_windows_did_not_take_goes_through():
    rdp = RecordingRdp()
    rdp.clipboard = "copied before typing"
    rdp.fetches = False
    with pytest.raises(ComputerError):
        await rdp.type_text("Case-Test.txt")
    rdp.fetches = True  # the agent clicked the file name field
    await rdp.type_text("Case-Test.txt")
    assert sent(rdp) == [("clipboard", "Case-Test.txt"), ("key", "ctrl+v"), ("clipboard", "copied before typing")] * 2


async def test_a_clipboard_that_cannot_be_set_pastes_nothing():
    rdp = RecordingRdp()
    rdp.xclip_error = "Can't open display: :1"
    with pytest.raises(ComputerError, match="Can't open display"):
        await rdp.type_text("你好")
    assert sent(rdp) == []


async def test_auto_typing_pastes_non_ascii_and_types_ascii():
    rdp = RecordingRdp("auto")
    await rdp.type_text("hello")
    await rdp.type_text("你好")
    assert sent(rdp) == [("type", "hello"), ("clipboard", "你好"), ("key", "ctrl+v")]


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
    await rdp.drag([(430, 400), (550, 550)], [])  # starts where the last drag ended
    await rdp.drag([(10, 10), (10, 10)], [])  # nowhere: midpoint and end are the start
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
    await rdp.scroll(None, "right", 1, [])  # where the pointer is

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


async def test_typing_keystrokes_gets_more_time_than_other_commands():
    rdp = RecordingRdp(type_mode="keys")
    await rdp.type_text("a" * 2000)  # 40 ms a key: 80 s
    await rdp.press([["enter"]])

    assert rdp.timeouts == [computer_use.computers.rdp.COMMAND_TIMEOUT_SECONDS + 80, None]


async def test_a_screenshot_without_a_display_fails_as_the_desktop(monkeypatch):
    def no_display(xdisplay):
        raise OSError("X connection failed: error 1")

    monkeypatch.setattr(computer_use.computers.rdp.ImageGrab, "grab", no_display)
    with pytest.raises(ComputerError, match="screenshot failed: X connection failed"):
        await RdpComputer(":1").screenshot()
