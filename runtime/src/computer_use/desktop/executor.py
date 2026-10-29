"""Validate and dispatch every agent action through one controlled path.

Input requires agent ownership, a connected desktop and a screen matching the
last observation. The control lock prevents takeover racing with dispatch.
Actions return a settled screenshot; interrupted input releases held keys and
buttons. Batches stop at the first failed or blocked action."""

import asyncio
import io
import json
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from functools import partial

from PIL import Image

from computer_use.computers import Combo, Computer, ComputerError, Frame, Point
from computer_use.config import Settings
from computer_use.events import ActionReason
from computer_use.desktop.actions import BATCHABLE, CLICKS
from computer_use.desktop.control import Control, ControlState, let_go
from computer_use.desktop.keys import blocked_combo, parse_combos, parse_modifiers
from computer_use.desktop.screen import NOISE, describe, diff, lasting_diff, settle

# Unchanged input prompts replanning; only repeated identical actions stop the task.
REPLAN_UNCHANGED = 3
STOP_REPEATS = 6
# How long to watch a screen that changed since the model saw it, so that what keeps moving on its own (marching
# ants, a spinner) is told apart from a change that stays.
MOVING_WATCH_SECONDS = 0.25
# Poll for reconnection and stop the task after the limit; entrypoint.sh reconnects RDP.
RECONNECT_POLL_SECONDS = 1.0
RECONNECT_LIMIT_SECONDS = 60
# Keys go wherever the focus is, so for them the screen has moved on only when a menu or dialog may have taken it.
# Measured at 1280x800 over RDP (2026-10-06): the smallest such change, the taskbar's two-item menu, is 2301 pixels;
# Windows redrawing the taskbar about a second after a window switch, well after the switch has settled, is 68-249.
FOCUS_CHANGE = 1000


@dataclass(frozen=True)
class ActionResult:
    ok: bool
    text: str
    frame: Frame | None = None  # a screenshot that goes with the text
    changed: bool | None = None  # input meant to change the screen: whether the screen the model saw changed
    reason: ActionReason | None = None  # a deliberate refusal, distinct from input that failed or may have arrived


class Rejected(Exception):
    """An action that is not sent: a point outside the screen, an unknown key, or input the agent may not send."""


class Disconnected(Exception):
    """The desktop did not reconnect within RECONNECT_LIMIT_SECONDS."""

    def __init__(self, seconds: float):
        self.seconds = seconds
        super().__init__(f"the desktop did not reconnect within {seconds:g} seconds")


class Executor:
    def __init__(self, computer: Computer, control: Control, settings: Settings):
        self.computer = computer
        self.control = control
        self.settings = settings
        self.shown: Frame | None = None  # the newest full screen given to the model
        self.shown_at: float | None = None  # when it was given, on the clock Control's `since` uses
        self.unchanged = 0  # input actions in a row that left that screen as it was
        self.repeats = 0  # of those, the latest action and its repeats right before it
        self._last_unchanged: str | None = None  # that action, as JSON
        self.approved = False  # the next action was approved on the screen it was decided from (agent.confirm)
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
        }

    @property
    def stuck(self) -> bool:
        return self.repeats >= STOP_REPEATS

    def clear_unchanged(self) -> None:
        """Start counting afresh: the screen changed some other way, e.g. the user worked on it."""
        self.unchanged, self.repeats, self._last_unchanged = 0, 0, None

    async def observe(self, note: str, frame: Frame | None = None) -> ActionResult:
        """A note and the screen (fresh unless given), which the model decides its next action from."""
        frame = frame or await self.computer.screenshot()
        self.shown, self.shown_at = frame, time.time()
        return ActionResult(True, describe(note, frame, await self.computer.status()), frame)

    async def wait_for_connection(self) -> float | None:
        """Block while the desktop is disconnected; return how long it was, or None if it never was. The backend
        reconnects on its own (for RDP, entrypoint.sh); Disconnected if it is not back within RECONNECT_LIMIT_SECONDS."""
        if (await self.computer.status()).connected:
            return None
        started = time.monotonic()
        while not (await self.computer.status()).connected:
            if time.monotonic() - started >= RECONNECT_LIMIT_SECONDS:
                raise Disconnected(RECONNECT_LIMIT_SECONDS)
            await asyncio.sleep(RECONNECT_POLL_SECONDS)
        return time.monotonic() - started

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
        if control.owner != "agent":
            # Checked right before dispatch: the user may have taken over since the model call.
            return ActionResult(False, "Not executed: the user has control of the desktop.", reason="userControl")
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
        """Input that failed, or may not have arrived: why, with the screen as it
        is now, so the model decides again from it rather than from the screen before; only why when the screen cannot
        be seen either."""
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
        *, no_change_seconds: float | None = None,
    ) -> ActionResult:
        """Send input if the screen still looks as the model saw it (around `points`, where a pointer action lands,
        or anywhere for keys); return the screen once it is still."""
        seen, now = self.shown, await self.computer.screenshot()
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
        settings = self.settings
        if no_change_seconds is not None and no_change_seconds < settings.settle_seconds:
            settings = settings.model_copy(update={"settle_seconds": no_change_seconds})
        after = await settle(self.computer, settings, now)
        if not expect_change:
            return await self.observe(note, after)
        if await diff(now.png, after.png) < NOISE:
            # Windows panels can take seconds to open; without this the model repeats toggles like "win".
            note += " The screen has not changed yet; it may still be loading. Use wait and look again before repeating it."
        result = await self.observe(note, after)
        return result if seen is None else replace(result, changed=await diff(seen.png, after.png) >= NOISE)

    async def _held_back(self, control: ControlState) -> ActionResult | None:
        """Why no input may be sent now, with the screen to decide again from when there is one; None if it may."""
        if control.owner != "agent":
            return ActionResult(False, "Not executed: the user has control of the desktop.", reason="userControl")
        if self.shown_at is not None and control.since > self.shown_at:
            # The user took over and gave control back while the model was deciding from an older screen. The
            # screen check in _send compares only the patch around a click, so it misses a change elsewhere.
            self.clear_unchanged()
            note = "Not executed: the user had control after your last screenshot. This is the current screen; decide again."
            return replace(await self.observe(note), ok=False, reason="userActed")
        return None

    async def _stale(self, seen: Frame, now: Frame, points: Sequence[Point]) -> bool:
        """Whether the screen moved on from what the model saw: around the pointer targets or, for keys, enough for
        the focus to have moved. A change is watched for MOVING_WATCH_SECONDS, and what kept moving meanwhile does
        not count."""
        if not points and self.approved:
            # Approval delays can change taskbar widgets or tooltips without moving keyboard focus.
            # Send approved keys without this stale-screen check; pointer targets are still checked.
            return False
        least = NOISE if points else FOCUS_CHANGE
        if await diff(seen.png, now.png, points) < least:
            return False
        await asyncio.sleep(MOVING_WATCH_SECONDS)
        later = await self.computer.screenshot()
        return await lasting_diff(seen.png, now.png, later.png, points) >= least

    async def _target(self, point: Point | None) -> list[Point]:
        """Where a pointer action lands: at the point, or where the pointer is."""
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
        frame = await self.computer.screenshot()
        x0, y0, x1, y1 = region
        if not (0 <= x0 < x1 <= frame.width and 0 <= y0 < y1 <= frame.height):
            raise Rejected(f"{region} is not a region inside the {frame.width}x{frame.height} screen")
        image = Image.open(io.BytesIO(frame.png)).crop((x0, y0, x1, y1))
        scale = max(1.0, min(frame.width / image.width, frame.height / image.height))
        image = image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        # An enlarged crop, not the screen: it does not change what the model has seen.
        crop = Frame(buffer.getvalue(), image.width, image.height)
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
