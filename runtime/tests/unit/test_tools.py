import asyncio
import base64
import io
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw
from pydantic import ValidationError

import computer_use.desktop.executor
import computer_use.desktop.screen
from computer_use.agent.tools import BatchAction, desktop_tools
from computer_use.desktop.actions import CONFIRMABLE
from computer_use.computers import ComputerError, Frame
from computer_use.desktop.screen import NOISE, changed_pixels, lasting_changed_pixels, mark, settle
from conftest import fixture_png, tool_call


@pytest.fixture
def tools(executor):
    return {tool.name: tool for tool in desktop_tools(executor)}


async def call(tools, name, **args):
    return await tools[name].ainvoke(tool_call(f"call_{name}", name, **args))


async def test_actions_return_text_then_screenshot(tools, computer):
    result = await call(tools, "double_click", coordinate=[100, 200])
    text, image = result.content
    assert "Double click at (100, 200)" in text["text"]
    assert "Screen 1280x800" in text["text"] and "Test session: connected" in text["text"]
    assert image["type"] == "image" and image["mime_type"] == "image/png"
    assert computer.calls == [("click", (100, 200), "left", 2, [])]


async def test_actions_say_when_the_screen_has_not_changed(tools, computer):
    screens = iter([fixture_png("Desktop")])
    computer.screen = lambda: next(screens, fixture_png("Search: notepad"))
    opened = await call(tools, "key", text="win+s")
    again = await call(tools, "key", text="win+s")  # the same screen before and after, like a menu not open yet
    assert "has not changed" not in opened.content[0]["text"]
    assert "has not changed yet" in again.content[0]["text"]


async def test_clicks_and_drags_outside_the_screen_are_rejected(tools, computer):
    click = await call(tools, "left_click", coordinate=[1280, 10])
    drag = await call(tools, "left_click_drag", start_coordinate=[10, 20], coordinate=[10, 900])
    assert click.status == "error" and "outside the 1280x800 screen" in click.content
    assert drag.status == "error" and "outside" in drag.content
    assert computer.calls == []


async def test_blocked_input_never_reaches_the_computer(tools, computer):
    keys = await call(tools, "key", text="ctrl+alt+delete")
    assert keys.status == "error" and "ctrl+alt+delete opens the security screen" in keys.content
    await call(tools, "key", text="ctrl+s")
    assert computer.calls == [("press", [["ctrl", "s"]])]


async def test_unknown_keys_and_computer_failures_become_tool_errors(tools, computer):
    unknown = await call(tools, "key", text="ctrl+banana")
    assert unknown.status == "error" and "Unknown key" in unknown.content

    computer.fail_next = "xdotool failed: no display"
    failed = await call(tools, "left_click", coordinate=[10, 10])
    text, image = failed.content  # with the screen as it is now: the click may have landed or not
    assert failed.status == "error" and image["type"] == "image"
    assert text["text"].startswith("xdotool failed: no display")


def test_the_tools_are_anthropics_computer_use_actions_and_a_batch_of_them(tools):
    assert list(tools) == [
        "screenshot", "zoom", "left_click", "right_click", "middle_click", "double_click", "triple_click",
        "left_click_drag", "mouse_move", "left_mouse_down", "left_mouse_up", "cursor_position", "scroll",
        "type", "key", "hold_key", "wait", "computer_batch",
    ]


def test_every_input_action_must_say_whether_it_needs_the_users_approval(tools):
    for name, each in tools.items():
        schema = each.args_schema.model_json_schema()
        assert ("needs_confirmation" in schema.get("required", [])) == (name in CONFIRMABLE), name
        assert ("consequence" in schema["properties"]) == (name in CONFIRMABLE), name
    # A batch says it once, for all its actions.
    assert "needs_confirmation" not in BatchAction.model_json_schema()["properties"]


async def test_an_input_action_without_the_flag_sends_nothing(tools, computer):
    # In the agent, LangChain hands the model this error to fix (test_confirm); nothing reaches the computer.
    unflagged = {"type": "tool_call", "name": "key", "args": {"text": "ctrl+s"}, "id": "call_key"}
    with pytest.raises(ValidationError, match="needs_confirmation"):
        await tools["key"].ainvoke(unflagged)
    assert computer.calls == []


def test_a_mark_rings_where_a_step_acts_and_nothing_else():
    screen = screen_with()
    marked = mark(screen, [(100, 100)])
    assert changed_pixels(screen, marked, around=[(100, 100)]) >= NOISE
    assert changed_pixels(screen, marked, around=[(600, 400)]) == 0
    drag = mark(screen, [(100, 100), (500, 100)])
    assert changed_pixels(screen, drag, around=[(300, 100)]) >= NOISE


def screen_with(*boxes, ants: int | None = None):
    """A 1280x800 screen with black boxes, each (x0, y0, x1, y1), and with ants, Paint's select-all border as
    marching ants, its dashes shifted by that many pixels."""
    image = Image.new("RGB", (1280, 800), "white")
    draw = ImageDraw.Draw(image)
    for box in boxes:
        draw.rectangle(box, fill="black")
    if ants is not None:
        x0, y0, x1, y1 = 255, 201, 1025, 683  # measured on the run where these ants refused Delete
        for x in range(x0, x1 + 1):
            if (x + ants) // 4 % 2:
                draw.point([(x, y0), (x, y1)], fill="black")
        for y in range(y0, y1 + 1):
            if (y + ants) // 4 % 2:
                draw.point([(x0, y), (x1, y)], fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_changes_count_on_the_whole_screen_or_around_pointer_targets():
    before, after = screen_with(), screen_with((1000, 700, 1100, 760))  # e.g. a toast in the corner
    assert changed_pixels(before, after) >= NOISE
    assert changed_pixels(before, after, around=[(100, 100)]) == 0
    assert changed_pixels(before, after, around=[(100, 100), (1050, 700)]) >= NOISE


def test_one_typed_character_is_a_change_and_the_clock_turning_a_minute_is_not():
    # Sizes as measured over RDP: one digit typed in Notepad changes 104-123 pixels, the clock 28-39.
    blank, digit, clock = screen_with(), screen_with((100, 100, 107, 114)), screen_with((1200, 770, 1205, 775))
    assert changed_pixels(blank, digit) >= NOISE > changed_pixels(blank, clock)


def test_a_change_that_stays_counts_and_marching_ants_do_not():
    seen, now, later = screen_with(ants=0), screen_with(ants=2), screen_with(ants=5)
    assert changed_pixels(seen, now) >= NOISE
    assert lasting_changed_pixels(seen, now, later) < NOISE
    dialog = (400, 300, 700, 500)
    now, later = screen_with(dialog, ants=2), screen_with(dialog, ants=5)
    assert lasting_changed_pixels(seen, now, later) >= NOISE


async def test_input_is_held_back_when_the_screen_changed_where_it_would_land(executor, computer, monkeypatch):
    monkeypatch.setattr(computer_use.desktop.executor, "MOVING_WATCH_SECONDS", 0)
    # Sizes as measured over RDP: Windows redrawing the taskbar after a window switch, 168 pixels; the taskbar's
    # two-item menu, 2301; one digit typed, 120.
    taskbar, menu, digit = (300, 770, 320, 777), (330, 690, 380, 735), (636, 396, 643, 410)
    computer.screen = lambda: screen_with()
    await executor.observe("Start.")

    # Keys go wherever the focus is: a change too small to be a menu or dialog does not hold them back, a menu does.
    computer.screen = lambda: screen_with(taskbar)
    assert (await executor.run("key", {"text": "ctrl+a"})).ok
    computer.screen = lambda: screen_with(taskbar, menu)
    assert not (await executor.run("key", {"text": "ctrl+a"})).ok
    # A click lands where it points, here where the pointer is: a change there as small as one digit holds it back.
    computer.screen = lambda: screen_with(taskbar, menu, digit)
    assert not (await executor.run("left_click", {})).ok

    assert computer.calls == [("press", [["ctrl", "a"]])]


async def test_settle_waits_for_a_late_effect_to_finish_drawing(computer, settings, fast_polls):
    # Like "enter" in Windows search: nothing for a while, then the app draws in two frames and holds still.
    desktop, half, app = screen_with(), screen_with((0, 0, 640, 400)), screen_with((0, 0, 1280, 400))
    frames = iter([desktop] * 5 + [half] + [app] * 1000)
    computer.screen = lambda: next(frames)
    settings.settle_seconds, settings.settle_quiet_seconds, settings.settle_max_seconds = 1.0, 0.05, 2.0
    assert changed_pixels((await settle(computer, settings, Frame.of(desktop))).png, app) == 0


async def test_settle_stops_waiting_when_nothing_changes(computer, settings, fast_polls):
    settings.settle_seconds, settings.settle_quiet_seconds, settings.settle_max_seconds = 0.05, 0.5, 2.0
    started = asyncio.get_running_loop().time()
    await settle(computer, settings, await computer.screenshot())
    assert asyncio.get_running_loop().time() - started < 0.5


async def test_clicks_drags_and_scrolls_can_hold_modifiers(tools, computer):
    await call(tools, "left_click", coordinate=[10, 20], text="ctrl")
    await call(tools, "right_click")
    await call(tools, "left_click_drag", start_coordinate=[10, 20], coordinate=[300, 40], text="shift")
    await call(tools, "scroll", scroll_direction="right", scroll_amount=2, coordinate=[5, 5], text="ctrl+shift")
    assert computer.calls == [
        ("click", (10, 20), "left", 1, ["ctrl"]),
        ("click", None, "right", 1, []),
        ("drag", [(10, 20), (300, 40)], ["shift"]),
        ("scroll", (5, 5), "right", 2, ["ctrl", "shift"]),
    ]


async def test_only_modifier_keys_can_be_held_during_a_click(tools, computer):
    result = await call(tools, "left_click", coordinate=[10, 20], text="r")
    assert result.status == "error" and "Hold only" in result.content
    assert computer.calls == []


async def test_pointer_tools(tools, computer):
    moved = await call(tools, "mouse_move", coordinate=[30, 40])
    await call(tools, "left_mouse_down")
    await call(tools, "left_mouse_up")
    position = await call(tools, "cursor_position")
    assert "has not changed" not in moved.content[0]["text"]  # hovering often changes nothing
    assert position.content == "The pointer is at (640, 400)."
    assert computer.calls == [("move", (30, 40)), ("mouse_button", True), ("mouse_button", False)]


async def test_key_repeats_and_hold_key_holds_one_combo(tools, computer):
    pressed = await call(tools, "key", text="down", repeat=3)
    await call(tools, "hold_key", text="shift", duration=1.5)
    several = await call(tools, "hold_key", text="ctrl a", duration=1)
    blocked = await call(tools, "hold_key", text="win+x", duration=1)
    assert several.status == "error" and blocked.status == "error"
    assert "Pressed down down down." in pressed.content[0]["text"]
    assert computer.calls == [("press", [["down"], ["down"], ["down"]]), ("hold", ["shift"], 1.5)]


@pytest.mark.parametrize("text,repeat,configured,expected", [
    ("Home", 1, 1.5, 0.8), ("End", 1, 1.5, 0.8), ("CTRL+A", 1, 1.5, 0.8),
    ("Control+A", 1, 1.5, 0.8), ("home", 1, 0.2, 0.2),
    ("home", 2, 1.5, 1.5), ("end", 2, 1.5, 1.5), ("ctrl+a", 2, 1.5, 1.5),
    ("ctrl+home", 1, 1.5, 1.5), ("shift+end", 1, 1.5, 1.5),
    ("ctrl+a Delete", 1, 1.5, 1.5), ("home end", 1, 1.5, 1.5), ("enter", 1, 1.5, 1.5),
])
async def test_only_single_home_end_and_select_all_shorten_no_change_wait(
    tools, executor, settings, monkeypatch, text, repeat, configured, expected,
):
    settings.settle_seconds, settings.settle_quiet_seconds, settings.settle_max_seconds = configured, 0.5, 3.0
    observed = []

    async def capture_settings(computer, current, before):
        observed.append((current.settle_seconds, current.settle_quiet_seconds, current.settle_max_seconds))
        return await computer.screenshot()

    monkeypatch.setattr(computer_use.desktop.executor, "settle", capture_settings)
    assert (await call(tools, "key", text=text, repeat=repeat)).status == "success"
    assert observed == [(expected, 0.5, 3.0)]
    assert executor.settings is settings and settings.settle_seconds == configured


async def test_batch_shortcuts_keep_the_configured_wait(tools, settings, monkeypatch):
    settings.settle_seconds = 1.5
    waits = []

    async def capture_settings(computer, current, before):
        waits.append(current.settle_seconds)
        return await computer.screenshot()

    monkeypatch.setattr(computer_use.desktop.executor, "settle", capture_settings)
    result = await call_batch(tools, *(("key", {"text": key}) for key in ["home", "end", "ctrl+a"]))
    assert result.status == "success" and waits == [1.5, 1.5, 1.5]
    await call(tools, "key", text="home")
    assert waits == [1.5, 1.5, 1.5, 0.8] and settings.settle_seconds == 1.5


async def test_same_shortcut_in_and_out_of_a_batch_still_counts_as_repeated(executor):
    await executor.observe("Start.")
    await executor.run("key", {"text": "home"})
    await executor.run_batch([("key", {"text": "home"})])
    result = await executor.run("key", {"text": "home"})
    assert executor.repeats == executor.unchanged == 3
    assert "Do not repeat" in result.text


@pytest.mark.parametrize("key", ["home", "end", "ctrl+a"])
async def test_shortcut_wait_captures_a_700ms_effect_before_the_next_input(
    executor, computer, settings, monkeypatch, key,
):
    settings.settle_seconds, settings.settle_quiet_seconds, settings.settle_max_seconds = 1.5, 0.5, 3.0
    elapsed, pending, deleted = 0.0, False, False
    before, selected, after = (fixture_png(label) for label in ["Before shortcut", "Shortcut applied", "Deleted"])

    async def sleep(seconds):
        nonlocal elapsed
        elapsed += seconds

    monkeypatch.setattr(computer_use.desktop.screen, "asyncio", SimpleNamespace(
        get_running_loop=lambda: SimpleNamespace(time=lambda: elapsed), sleep=sleep, to_thread=asyncio.to_thread,
    ))
    computer.screen = lambda: after if deleted else selected if pending and elapsed >= 0.7 else before
    press = computer.press

    async def delayed_press(combos):
        nonlocal pending, deleted
        await press(combos)
        if not pending:
            pending = True
        else:
            assert elapsed >= 1.2  # the delayed effect plus the unchanged 0.5-second quiet period
            deleted = True

    computer.press = delayed_press
    result = await executor.run("key", {"text": key})
    assert result.ok and result.frame.png == selected and 1.2 <= elapsed < 1.5
    result = await executor.run("key", {"text": "delete" if key == "home" else "backspace"})
    assert result.ok and result.frame.png == after and len(computer.calls) == 2


async def test_zoom_enlarges_a_region_of_the_screen(tools):
    result = await call(tools, "zoom", region=[0, 0, 320, 100])
    text, image = result.content
    assert "enlarged 4.0x" in text["text"]
    assert Image.open(io.BytesIO(base64.b64decode(image["base64"]))).size == (1280, 400)
    outside = await call(tools, "zoom", region=[0, 0, 2000, 100])
    assert outside.status == "error"


async def call_batch(tools, *actions):
    batch = [{"action": name, **args} for name, args in actions]
    return await tools["computer_batch"].ainvoke(tool_call("call_batch", "computer_batch", actions=batch))


async def test_a_batch_sends_its_actions_in_order_and_returns_the_screen_after_the_last(tools, computer):
    result = await call_batch(
        tools, ("left_click", {"coordinate": [640, 60]}), ("type", {"text": "cats"}), ("key", {"text": "enter"})
    )
    text, image = result.content
    assert text["text"].startswith("1. Left click at (640, 60).")
    assert "\n2. Typed 4 characters." in text["text"] and "\n3. Pressed enter." in text["text"]
    assert "Screen 1280x800" in text["text"] and image["type"] == "image"
    assert computer.calls == [("click", (640, 60), "left", 1, []), ("type_text", "cats"), ("press", [["enter"]])]


async def test_a_batch_stops_at_the_first_action_that_fails(tools, computer):
    async def type_text(text):
        raise ComputerError("RDP text delivery was partial")

    computer.type_text = type_text
    result = await call_batch(
        tools, ("left_click", {"coordinate": [10, 10]}), ("type", {"text": "x"}), ("key", {"text": "enter"})
    )
    text, image = result.content
    assert result.status == "error" and image["type"] == "image"
    assert text["text"].startswith(
        "Stopped at action 2 of 3: RDP text delivery was partial\n1. Left click at (10, 10)."
    )
    assert "\nAction 3 was not sent.\nScreen 1280x800" in text["text"]
    assert computer.calls == [("click", (10, 10), "left", 1, [])]


async def test_input_that_fails_comes_back_with_the_screen_as_it_is_then(tools, executor, computer):
    computer.screen = lambda: fixture_png("Save As: file list")
    await executor.observe("Save As.")

    async def type_text(text):  # the text field changed before delivery failed
        computer.screen = lambda: fixture_png("Save As: partial text")
        raise ComputerError("RDP text delivery was partial")

    computer.type_text = type_text
    result = await call(tools, "type", text="Case-Test.txt")
    text, image = result.content
    assert result.status == "error"
    assert text["text"].startswith("RDP text delivery was partial\nScreen 1280x800")
    now = fixture_png("Save As: partial text")
    assert base64.b64decode(image["base64"]) == now
    assert executor.shown.png == now  # the next action is checked against this screen, not the one before


async def test_input_that_fails_says_why_when_the_screen_cannot_be_seen_either(tools, computer):
    def gone():
        raise ComputerError("screenshot failed: the display is gone")

    async def type_text(text):
        computer.screen = gone
        raise ComputerError("The RDP text input pipe is unavailable")

    computer.type_text = type_text
    result = await call(tools, "type", text="x")
    assert result.status == "error" and result.content == "The RDP text input pipe is unavailable"


async def test_a_batch_stops_when_the_screen_changes_after_an_action_settled(tools, executor, computer, monkeypatch):
    monkeypatch.setattr(computer_use.desktop.executor, "MOVING_WATCH_SECONDS", 0)
    menu = (330, 690, 380, 735)  # the taskbar's menu, big enough to take the focus from the keys that follow
    screens = iter([screen_with()] * 3)  # the first screen, before win+s and once it has settled
    computer.screen = lambda: next(screens, screen_with(menu))
    await executor.observe("Start.")
    result = await call_batch(
        tools, ("key", {"text": "win+s"}), ("type", {"text": "notepad"}), ("key", {"text": "enter"})
    )
    text, image = result.content
    assert result.status == "error" and image["type"] == "image"
    assert text["text"].startswith(
        "Stopped at action 2 of 3: Not executed: the screen changed since your last screenshot."
    )
    assert "\n1. Pressed win+s." in text["text"] and "\nAction 3 was not sent.\n" in text["text"]
    assert computer.calls == [("press", [["win", "s"]])]


async def test_a_wait_in_a_batch_lets_the_screen_change_before_the_next_action(executor, computer):
    screens = iter([fixture_png("Search")] * 3)  # until enter has settled; then the app opens during the wait
    computer.screen = lambda: next(screens, fixture_png("Notepad"))
    await executor.observe("Start.")
    result = await executor.run_batch([("key", {"text": "enter"}), ("wait", {"duration": 0}), ("type", {"text": "hi"})])
    assert result.ok and "\n2. Waited 0 seconds.\n3. Typed 2 characters." in result.text
    assert computer.calls == [("press", [["enter"]]), ("type_text", "hi")]


async def test_a_batch_checks_the_arguments_of_every_action_before_sending_any(tools, computer):
    invalid = await call_batch(tools, ("key", {"text": "ctrl+s"}), ("wait", {"duration": 100}))
    missing = await call_batch(tools, ("type", {}))
    assert invalid.status == "error" and invalid.content.startswith("Nothing was sent: action 2 of 2 (wait): duration")
    assert missing.status == "error" and missing.content.startswith("Nothing was sent: action 1 of 1 (type): text")
    assert computer.calls == []
    # Input the agent may not send is refused when its turn comes, like a single action.
    blocked = await call_batch(tools, ("key", {"text": "ctrl+s"}), ("key", {"text": "ctrl+alt+delete"}))
    assert blocked.status == "error" and blocked.content.startswith("Stopped at action 2 of 2: Not allowed")
    assert computer.calls == [("press", [["ctrl", "s"]])]


async def test_a_batch_ignores_arguments_its_actions_do_not_take(tools, computer):
    result = await call_batch(tools, ("left_click", {"coordinate": [10, 10], "repeat": 3, "duration": 1}))
    assert result.status == "success" and computer.calls == [("click", (10, 10), "left", 1, [])]


async def test_only_input_and_wait_can_be_batched(executor, computer):
    result = await executor.run_batch([("left_click", {"coordinate": [10, 10]}), ("screenshot", {})])
    assert not result.ok and result.text == "Nothing was sent: screenshot cannot be part of a batch."
    assert computer.calls == []


async def test_scripts_reach_the_computer(tools, computer):
    await call(tools, "key", text="win+r")
    await call(tools, "type", text="powershell -NoProfile -Command Get-Date")
    assert computer.calls == [("press", [["win", "r"]]), ("type_text", "powershell -NoProfile -Command Get-Date")]
