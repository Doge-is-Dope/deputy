"""Validate and dispatch every agent action through one controlled path.

Input requires agent ownership, a connected desktop and a screen matching the
last observation. The control lock prevents takeover racing with dispatch.
Actions return a settled screenshot; interrupted input releases held keys and
buttons. Batches stop at the first failed or blocked action."""

import asyncio
import json
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from functools import partial

from PIL import Image

from computer_use.computers import Combo, Computer, ComputerError, Frame, Point
from computer_use.events import ActionReason
from computer_use.desktop.actions import BATCHABLE, CLICKS
from computer_use.desktop.control import Control, ControlState, let_go
from computer_use.desktop.judge import ScreenJudge
from computer_use.desktop.keys import blocked_combo, parse_combos, parse_modifiers
from computer_use.desktop.screen import NOISE, Shot, capture, describe, diff, gray, lasting_diff, settle, settle_judged

# How long to wait after an action for a change that never comes (screen.settle); some keys say less.
SETTLE_SECONDS = 1.5
# Unchanged input prompts replanning; only repeated identical actions stop the task.
REPLAN_UNCHANGED = 3
STOP_REPEATS = 6
# How long to watch a screen that changed since the model saw it, so that what keeps moving on its own (marching
# ants, a spinner) is told apart from a change that stays.
MOVING_WATCH_SECONDS = 0.25
# Poll for reconnection and stop the task after the limit; rdp-entrypoint.sh reconnects RDP. It usually takes 8-27 s;
# the longest seen is 97 s (measured 2026-11-06).
RECONNECT_POLL_SECONDS = 1.0
RECONNECT_LIMIT_SECONDS = 120
# The session window appears before Windows has signed in and drawn the desktop: black and sign-in screens for 1.3-1.6 s
# (measured 2026-11-06). A sign-in screen looks like a still one, so waiting for the screen to settle would not do.
RECONNECT_SIGN_IN_SECONDS = 3.0
# Keys go wherever the focus is, so for them the screen has moved on only when a menu or dialog may have taken it.
# Measured at 1280x800 over RDP (2026-10-06): the smallest such change, the taskbar's two-item menu, is 2301 pixels;
# Windows redrawing the taskbar about a second after a window switch, well after the switch has settled, is 68-249.
FOCUS_CHANGE = 1000
# A press in press_while is held this long: games read the keys once a frame and miss a 12 ms tap.
PRESS_HOLD_SECONDS = 0.2
# How many times press_while waits out a screen still moving after a press (screen.settle, up to its cap each).
PRESS_ANIMATION_WAITS = 3


@dataclass(frozen=True)
class ActionResult:
    ok: bool
    text: str
    frame: Frame | None = None
    changed: bool | None = None  # input meant to change the screen: whether the screen the model saw changed
    reason: ActionReason | None = None  # a deliberate refusal, distinct from input that failed or may have arrived
    judged: bool | None = None  # the screen judge's verdict on the returned screen, when one was asked (press_while)


class Rejected(Exception):
    """An action that is not sent: a point outside the screen, an unknown key, or input the agent may not send."""


class Disconnected(Exception):
    """The desktop did not reconnect within RECONNECT_LIMIT_SECONDS."""

    def __init__(self, seconds: float):
        self.seconds = seconds
        super().__init__(f"the desktop did not reconnect within {seconds:g} seconds")


class Executor:
    def __init__(self, computer: Computer, control: Control, judge: ScreenJudge | None = None):
        self.computer = computer
        self.control = control
        self.judge = judge
        self.shown: Frame | None = None
        self._seen: Image.Image | None = None  # that screen in gray, to compare later screens with
        self.shown_at: float | None = None  # when it was given, on the clock Control's `since` uses
        self.unchanged = 0  # input actions in a row that left that screen as it was
        self.repeats = 0  # of those, the latest action and its repeats right before it
        self._last_unchanged: str | None = None  # that action, as JSON
        self.approved = False  # the next action was approved on the screen it was decided from (execution.approvals)
        self._actions: dict[str, Callable[..., Awaitable[ActionResult]]] = {
            "screenshot": self._screenshot,
            "zoom": self._zoom,
            **{name: partial(self._click, name) for name in CLICKS},
            "left_click_drag": self._drag,
            "mouse_move": self._move,
            "left_mouse_down": partial(self._mouse_button, True),
            "left_mouse_up": partial(self._mouse_button, False),
            "cursor_position": self._cursor_position,
            "scroll": self._scroll,
            "type": self._type,
            "key": self._key,
            "hold_key": self._hold_key,
            "wait": self._wait,
            "press_while": self._press_while,
        }

    @property
    def stuck(self) -> bool:
        return self.repeats >= STOP_REPEATS

    def clear_unchanged(self) -> None:
        """Start counting afresh: the screen changed some other way, e.g. the user worked on it."""
        self.unchanged, self.repeats, self._last_unchanged = 0, 0, None

    async def observe(self, note: str, shot: Shot | None = None) -> ActionResult:
        """A note and the screen (fresh unless given), which the model decides its next action from."""
        frame, self._seen = shot or await capture(self.computer)
        self.shown, self.shown_at = frame, time.time()
        return ActionResult(True, describe(note, frame, await self.computer.status()), frame)

    async def wait_for_connection(self) -> float | None:
        """Block while the desktop is disconnected and until its session has drawn; return how long it was gone, or
        None if it never was. The backend reconnects on its own; Disconnected if it is not back within
        RECONNECT_LIMIT_SECONDS."""
        if (await self.computer.status()).connected:
            return None
        started = time.monotonic()
        while not (await self.computer.status()).connected:
            if time.monotonic() - started >= RECONNECT_LIMIT_SECONDS:
                raise Disconnected(RECONNECT_LIMIT_SECONDS)
            await asyncio.sleep(RECONNECT_POLL_SECONDS)
        gone = time.monotonic() - started
        await asyncio.sleep(RECONNECT_SIGN_IN_SECONDS)
        return gone

    def approve_next(self) -> None:
        """The next action was approved, by the user or auto review, on the screen it was decided from."""
        self.approved = True

    async def run(self, name: str, args: dict, *, in_batch: bool = False) -> ActionResult:
        try:
            return await self._run(name, args, in_batch=in_batch)
        finally:  # an approval covers the one action it was given for
            self.approved = False

    async def _run(self, name: str, args: dict, *, in_batch: bool = False) -> ActionResult:
        action = self._actions.get(name)
        if action is None:
            return ActionResult(False, f"Unknown action {name!r}")
        control = self.control.read()
        if blocked := self._control_blocked(control):
            return blocked
        if not (await self.computer.status()).connected:
            # Input would reach no desktop, and a screenshot would show none.
            return ActionResult(False, "Not executed: the desktop is disconnected.", reason="disconnected")
        if held_back := await self._held_back(control):
            return held_back
        try:
            action_args = {**args, "no_change_seconds": None} if in_batch and name == "key" else args
            result = await action(**action_args)
        except Rejected as error:
            return ActionResult(False, str(error))
        except ComputerError as error:
            return await self._failed(str(error))
        return self._count_unchanged(name, args, result)

    async def _failed(self, reason: str) -> ActionResult:
        """Input that failed, or may not have arrived: why, with the screen as it is now, so the model decides again
        from it. Only why when the screen cannot be seen either."""
        try:
            return replace(await self.observe(reason), ok=False)
        except ComputerError:
            return ActionResult(False, reason)

    async def run_batch(self, steps: Sequence[tuple[str, dict]]) -> ActionResult:
        """Several actions decided from one screenshot (see BATCHABLE), run one after another through `run`: each is
        sent once the one before has settled, and only if the screen still looks as it did then. The first that
        fails or is held back stops the rest. Returns what each did and the screen after the last."""
        if not steps:
            return ActionResult(False, "Nothing was sent: the batch has no actions.")
        if others := [name for name, _ in steps if name not in BATCHABLE]:
            return ActionResult(False, f"Nothing was sent: {', '.join(others)} cannot be part of a batch.")
        done: list[str] = []
        for name, args in steps:
            result = await self.run(name, args, in_batch=True)
            if not result.ok:
                return _stopped(done, result, len(steps))
            done.append(result.text)
        *earlier, last = done
        return replace(result, text="\n".join(_numbered([*map(_first_line, earlier), last])))

    def _count_unchanged(self, name: str, args: dict, result: ActionResult) -> ActionResult:
        """Keep count of input actions in a row that left the screen as the model saw it, and of the same one
        repeated; from REPLAN_UNCHANGED on, tell the model to try another way."""
        if result.changed is None:  # not input meant to change the screen
            return result
        if result.changed:
            self.clear_unchanged()
            return result
        action = json.dumps([name, args], sort_keys=True)
        self.repeats = self.repeats + 1 if action == self._last_unchanged else 1
        self.unchanged, self._last_unchanged = self.unchanged + 1, action
        if self.unchanged < REPLAN_UNCHANGED:
            return result
        replan = (
            f"Your last {self.unchanged} actions did not change the screen. Do not repeat them: look at the screen "
            "again and try another way (a different control or a keyboard shortcut), or stop and say what blocks you."
        )
        return replace(result, text=f"{result.text}\n{replan}")

    async def _send(
        self, send: Callable[[], Awaitable[None]], note: str, points: Sequence[Point] = (), expect_change: bool = True,
        *, no_change_seconds: float | None = None, condition: str | None = None,
    ) -> ActionResult:
        """Send input if the screen still looks as the model saw it (around `points`, where a pointer action lands,
        or anywhere for keys); return the screen once it is still."""
        seen, now = self._seen, await gray(self.computer)
        if seen is not None and await self._stale(seen, now, points):
            # The model takes seconds to decide; an app that finished loading meanwhile can put something else under
            # the click, or in front of the window keys would go to.
            self.clear_unchanged()
            stale = "Not executed: the screen changed since your last screenshot. This is the current screen; decide again."
            return replace(await self.observe(stale), ok=False, reason="screenChanged")
        # Control changes only between actions: a takeover during the screen check holds this input back, and one
        # from now on waits until it is sent.
        async with self.control.locked() as control:
            if held_back := await self._held_back(control):
                return held_back
            try:
                await send()
            except (asyncio.CancelledError, Exception):
                # Stopped or failed partway, e.g. a drag between press and release: let go of what is still down.
                await let_go(self.computer)
                raise
        wait = SETTLE_SECONDS if no_change_seconds is None else min(no_change_seconds, SETTLE_SECONDS)
        judged = None
        if self.judge and condition:  # press_while: judge the screen while it settles
            shot, judged = await settle_judged(self.computer, now, wait, partial(self.judge.holds, condition=condition))
        else:
            shot = await settle(self.computer, now, wait)
        if not expect_change:
            return await self.observe(note, shot)
        after = shot[1]
        if await diff(now, after) < NOISE:
            # Windows panels can take seconds to open; without this the model repeats toggles like "win".
            note += " The screen has not changed yet; it may still be loading. Use wait and look again before repeating it."
        result = replace(await self.observe(note, shot), judged=judged)
        return result if seen is None else replace(result, changed=await diff(seen, after) >= NOISE)

    def _control_blocked(self, control: ControlState) -> ActionResult | None:
        if control.allows_input("agent"):
            return None
        message = "the user has control of the desktop." if control.ready else "desktop control is being synchronized."
        return ActionResult(False, f"Not executed: {message}", reason="userControl")

    async def _held_back(self, control: ControlState) -> ActionResult | None:
        """Why no input may be sent now, with the screen to decide again from when there is one; None if it may."""
        if blocked := self._control_blocked(control):
            return blocked
        if self.shown_at is not None and control.since > self.shown_at:
            # The user took over and gave control back while the model was deciding from an older screen. The
            # screen check in _send compares only the patch around a click, so it misses a change elsewhere.
            self.clear_unchanged()
            note = "Not executed: the user had control after your last screenshot. This is the current screen; decide again."
            return replace(await self.observe(note), ok=False, reason="userActed")
        return None

    async def _stale(self, seen: Image.Image, now: Image.Image, points: Sequence[Point]) -> bool:
        """Whether the screen moved on from what the model saw: around the pointer targets or, for keys, enough for
        the focus to have moved. A change is watched for MOVING_WATCH_SECONDS, and what kept moving meanwhile does
        not count."""
        if not points and self.approved:
            # Approval delays can change taskbar widgets or tooltips without moving keyboard focus.
            # Send approved keys without this stale-screen check; pointer targets are still checked.
            return False
        least = NOISE if points else FOCUS_CHANGE
        if await diff(seen, now, points) < least:
            return False
        await asyncio.sleep(MOVING_WATCH_SECONDS)
        if await lasting_diff(seen, now, await gray(self.computer), points) < least:
            return False
        if points or self.judge is None or self.shown is None:
            return True
        # A window animating on its own (a game's title, text printing) moves more than a menu would, yet it is the
        # same screen and the keys still mean what the model meant.
        return not await self.judge.same_screen(self.shown.png, (await self.computer.screenshot()).png)

    async def _target(self, point: Point | None) -> list[Point]:
        return [point if point is not None else await self.computer.cursor_position()]

    async def _point(self, coordinate: Sequence[int] | None) -> Point | None:
        if coordinate is None:
            return None
        screen = self.shown or await self.computer.screenshot()
        x, y = coordinate
        if not (0 <= x < screen.width and 0 <= y < screen.height):
            raise Rejected(f"({x}, {y}) is outside the {screen.width}x{screen.height} screen")
        return x, y

    async def _screenshot(self) -> ActionResult:
        return await self.observe("Current screen.")

    async def _zoom(self, region: Sequence[int]) -> ActionResult:
        screen = await self.computer.image()
        x0, y0, x1, y1 = region
        if not (0 <= x0 < x1 <= screen.width and 0 <= y0 < y1 <= screen.height):
            raise Rejected(f"{region} is not a region inside the {screen.width}x{screen.height} screen")
        # An enlarged crop, not the screen: it does not change what the model has seen.
        crop, scale = await asyncio.to_thread(_enlarged, screen, (x0, y0, x1, y1))
        return ActionResult(True, f"Region ({x0}, {y0})-({x1}, {y1}) enlarged {scale:.1f}x.", crop)

    async def _click(self, name: str, coordinate: Sequence[int] | None = None, text: str | None = None) -> ActionResult:
        button, count, what = CLICKS[name]
        point, modifiers = await self._point(coordinate), _modifiers(text)
        note = f"{what} {_at(point)}{_holding(modifiers)}."
        click = partial(self.computer.click, point, button, count, modifiers)
        return await self._send(click, note, await self._target(point))

    async def _drag(
        self, start_coordinate: Sequence[int], coordinate: Sequence[int], text: str | None = None
    ) -> ActionResult:
        start, end, modifiers = await self._point(start_coordinate), await self._point(coordinate), _modifiers(text)
        note = f"Dragged from {start} to {end}{_holding(modifiers)}."
        return await self._send(lambda: self.computer.drag([start, end], modifiers), note, [start, end])

    async def _move(self, coordinate: Sequence[int]) -> ActionResult:
        point = await self._point(coordinate)
        note = f"Moved the pointer to {point}."
        return await self._send(lambda: self.computer.move(point), note, [point], expect_change=False)

    async def _mouse_button(self, down: bool) -> ActionResult:
        note = "Left button pressed." if down else "Left button released."
        press = partial(self.computer.mouse_button, down)
        return await self._send(press, note, await self._target(None), expect_change=not down)

    async def _cursor_position(self) -> ActionResult:
        x, y = await self.computer.cursor_position()
        return ActionResult(True, f"The pointer is at ({x}, {y}).")

    async def _scroll(
        self, scroll_direction: str, scroll_amount: int = 3, coordinate: Sequence[int] | None = None, text: str | None = None
    ) -> ActionResult:
        point, modifiers = await self._point(coordinate), _modifiers(text)
        note = f"Scrolled {scroll_direction} {scroll_amount} {_at(point)}{_holding(modifiers)}."
        scroll = partial(self.computer.scroll, point, scroll_direction, scroll_amount, modifiers)
        return await self._send(scroll, note, await self._target(point))

    async def _type(self, text: str) -> ActionResult:
        return await self._send(lambda: self.computer.type_text(text), f"Typed {len(text)} characters.")

    async def _key(self, text: str, repeat: int = 1, no_change_seconds: float | None = 0.8) -> ActionResult:
        sequence = _combos(text) * repeat
        note = f"Pressed {' '.join('+'.join(combo) for combo in sequence)}."
        # Only these single shortcuts use the shorter no-change wait; drawing still uses the usual quiet wait.
        if repeat != 1 or sequence not in ([["home"]], [["end"]], [["ctrl", "a"]]):
            no_change_seconds = None
        return await self._send(lambda: self.computer.press(sequence), note, no_change_seconds=no_change_seconds)

    async def _hold_key(self, text: str, duration: float) -> ActionResult:
        combos = _combos(text)
        if len(combos) != 1:
            raise Rejected("Hold one key or combo at a time")
        combo = combos[0]
        note = f"Held {'+'.join(combo)} for {duration:g} seconds."
        return await self._send(lambda: self.computer.hold(combo, duration), note)

    async def _press_while(self, text: str, condition: str, max_presses: int = 20) -> ActionResult:
        """Press a key again and again while the judge finds the condition on the screen, checked before each press."""
        combos = _combos(text)
        if self.judge is None:
            raise Rejected("press_while needs a screen judge, and none is set up")
        if len(combos) != 1:
            raise Rejected("Press one key or combo at a time")
        combo, pressed, waits, result = combos[0], 0, 0, None
        key = '+'.join(combo)
        why = f"it reached {max_presses} presses"
        while pressed < max_presses:
            if result and result.judged is not None:
                held = result.judged  # judged while the screen settled after the last press
            else:
                shown = result.frame if result else self.shown
                held = shown is not None and await self.judge.holds(shown.png, condition)
            if not held:
                why = "the condition no longer held"
                break
            press = partial(self.computer.hold, combo, PRESS_HOLD_SECONDS)
            sent = await self._send(press, f"Held {key}.", condition=condition)
            if not sent.ok and not (pressed and sent.reason == "screenChanged"):
                return sent
            if not sent.ok:  # still moving after the last press, e.g. a scene's animation: wait for it, then judge
                waits += 1
                if waits > PRESS_ANIMATION_WAITS:
                    result, why = sent, "the screen kept changing after the last press"
                    break
                result = await self.observe(f"Held {key}.", await settle(self.computer, await gray(self.computer), 0))
                continue
            result = sent
            pressed += 1
            if result.changed is False or "has not changed yet" in result.text:
                why = "the last press left the screen unchanged"
                break
        note = f"Pressed {key} {pressed} times; stopped because {why}."
        if result is None:
            return await self.observe(note)
        # A last press refused because the screen kept moving does not undo the presses before it.
        return replace(result, ok=True, reason=None, text=describe(note, result.frame, await self.computer.status()))

    async def _wait(self, duration: float = 2.0) -> ActionResult:
        await asyncio.sleep(duration)
        return await self.observe(f"Waited {duration:g} seconds.")



def _modifiers(text: str | None) -> list[str]:
    try:
        return parse_modifiers(text)
    except ValueError as error:
        raise Rejected(str(error)) from error


def _combos(text: str) -> list[list[str]]:
    try:
        combos = parse_combos(text)
    except ValueError as error:
        raise Rejected(str(error)) from error
    if reason := blocked_combo(combos):
        raise Rejected(f"Not allowed: {reason}")
    return combos


def _stopped(done: list[str], failed: ActionResult, total: int) -> ActionResult:
    """A batch stopped at an action that failed or was held back: why, then what was sent before it and what was
    left out, then the screen that came with the failure, if any."""
    reason, _, screen = failed.text.partition("\n")
    number = len(done) + 1
    lines = [f"Stopped at action {number} of {total}: {reason}" if done else reason]
    lines += _numbered(map(_first_line, done))
    if number + 1 == total:
        lines.append(f"Action {total} was not sent.")
    elif number < total:
        lines.append(f"Actions {number + 1} to {total} were not sent.")
    # A later refusal does not mean the whole batch was held back: earlier actions already reached the desktop.
    return replace(failed, text="\n".join([*lines, screen] if screen else lines), reason=failed.reason if not done else None)


def _first_line(text: str) -> str:
    return text.split("\n", 1)[0]


def _numbered(lines) -> list[str]:
    return [f"{number}. {line}" for number, line in enumerate(lines, 1)]


def _at(point: Point | None) -> str:
    return "at the pointer" if point is None else f"at ({point[0]}, {point[1]})"


def _holding(modifiers: Combo) -> str:
    return f" holding {'+'.join(modifiers)}" if modifiers else ""


def _enlarged(screen: Image.Image, box: tuple[int, int, int, int]) -> tuple[Frame, float]:
    """The region of the screen enlarged as far as it fits the screen, and by how much."""
    image = screen.crop(box)
    scale = max(1.0, min(screen.width / image.width, screen.height / image.height))
    image = image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)
    return Frame.encode(image), scale
