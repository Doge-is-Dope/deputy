"""Control the Windows RDP session shown on the container's X display.

Text uses the RDP Unicode pipe; shortcuts use xdotool. Streamed human input, single wheel
notches and pointer reads use a persistent X connection."""

import asyncio
import contextlib
import fcntl
import io
import logging
import os
import stat
import termios
import time
from array import array
from asyncio import subprocess
from collections.abc import Sequence
from pathlib import Path

from PIL import Image, ImageGrab
from Xlib import XK, X
from Xlib import display as xlib
from Xlib.ext import damage

from computer_use.computers import Button, Combo, ComputerError, Direction, Frame, Point, Status

BUTTONS = {"left": 1, "middle": 2, "right": 3}
SCROLL_BUTTONS = {"up": 4, "down": 5, "left": 6, "right": 7}

# X keysyms for the key names in `keys` that differ from them; ctrl, alt, shift, space, letters and digits
# are keysyms already.
KEYSYMS = {
    "win": "super",
    "enter": "Return",
    "esc": "Escape",
    "tab": "Tab",
    "backspace": "BackSpace",
    "delete": "Delete",
    "insert": "Insert",
    "up": "Up",
    "down": "Down",
    "left": "Left",
    "right": "Right",
    "home": "Home",
    "end": "End",
    "pageup": "Prior",
    "pagedown": "Next",
    "/": "slash",
    "\\": "backslash",
    "-": "minus",
    "=": "equal",
    ",": "comma",
    ".": "period",
    ";": "semicolon",
    "'": "apostrophe",
    "`": "grave",
    "[": "bracketleft",
    "]": "bracketright",
}

# Full keysym names for the modifiers, which xdotool also takes by their short names.
FULL_KEYSYMS = {"ctrl": "Control_L", "alt": "Alt_L", "shift": "Shift_L", "super": "Super_L"}

TEXT_TIMEOUT_SECONDS = 3
# A command still running after this has hung: even a 10 s hold_key takes far less.
COMMAND_TIMEOUT_SECONDS = 60

logger = logging.getLogger(__name__)


def keysym(key: str) -> str:
    if key in KEYSYMS:
        return KEYSYMS[key]
    if key[:1] == "f" and key[1:].isdigit():
        return key.upper()  # "f4" -> "F4"
    return key


def full_keysym(key: str) -> str:
    """The X keysym name for a key, as XTest needs it."""
    name = keysym(key)
    return FULL_KEYSYMS.get(name, name)


def xdotool_combo(combo: Combo) -> str:
    return "+".join(keysym(key) for key in combo)


def held(modifiers: Combo, *actions: str) -> list[str]:
    """xdotool arguments that press the modifiers, run the actions, then release them."""
    down = [arg for key in modifiers for arg in ("keydown", keysym(key))]
    up = [arg for key in reversed(modifiers) for arg in ("keyup", keysym(key))]
    return [*down, *actions, *up]


def moved(point: Point | None, here: Point | None) -> list[str]:
    """Move only when needed: xdotool --sync can stall on an unchanged position.

    Debian's 3.20160805 waits about 15 s on Xvfb; upstream fix: jordansissel/xdotool#463."""
    if point is None:
        return []
    return ["mousemove", *(["--sync"] if point != here else []), str(point[0]), str(point[1])]


def settled(point: Point, here: Point | None) -> list[str]:
    """Move to point so Windows registers it: over RDP it applies a pointer move only when the next one
    arrives (measured with a drag selection box), so nudge one pixel aside and come back."""
    x, y = point
    aside = (x - 1 if x > 0 else x + 1, y)
    return [*moved(point, here), "sleep", "0.05", *moved(aside, point), "sleep", "0.05", *moved(point, aside)]


class ScreenChanges:
    """Counts changes to the display's contents, which the X DAMAGE extension reports."""

    def __init__(self, display: str):
        self.count = 0
        self._changed = asyncio.Event()
        self._x = xlib.Display(display)
        self._x.damage_query_version()
        self._damage = self._x.screen().root.damage_create(damage.DamageReportNonEmpty)
        self._x.flush()
        asyncio.get_running_loop().add_reader(self._x.fileno(), self._on_events)

    def _on_events(self) -> None:
        for _ in range(self._x.pending_events()):
            self._x.next_event()
        self._x.damage_subtract(self._damage)  # a non-empty damage is reported once until it is subtracted
        self._x.flush()
        self.count += 1
        changed, self._changed = self._changed, asyncio.Event()
        changed.set()

    async def after(self, seen: int, timeout: float) -> int:
        if self.count == seen:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._changed.wait(), timeout)
        return self.count


class RdpComputer:
    def __init__(self, display: str, keyboard_pipe: Path = Path("/tmp/rdp-keyboard")):
        self.display = display
        self.keyboard_pipe = keyboard_pipe
        self._typing = asyncio.Lock()
        self._env = {**os.environ, "DISPLAY": display}
        self._xtest: xlib.Display | None = None  # the lasting connection (_lasting), opened on first use
        self._changes: ScreenChanges | None = None  # watched once the live view first asks
        self._no_changes = False  # the display reports no changes: every call counts as one

    async def _run(self, *args: str, timeout: float = COMMAND_TIMEOUT_SECONDS) -> None:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env=self._env,
        )
        try:
            _, err = await asyncio.wait_for(proc.communicate(), timeout)
        except (asyncio.CancelledError, TimeoutError) as stopped:  # stopped, or it hung: don't leave it running
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            if isinstance(stopped, TimeoutError):
                raise ComputerError(
                    f"{args[0]} did not finish within {timeout:g} seconds and was stopped. It may have done part of "
                    "the action: look at the screen before doing it again."
                ) from None
            raise
        if proc.returncode != 0:
            detail = err.decode(errors="replace").strip() if err else f"exit code {proc.returncode}"
            raise ComputerError(f"{args[0]} failed: {detail}")

    async def status(self) -> Status:
        # xfreerdp maps its window (WM_CLASS set by the entrypoint) only once the session is up.
        proc = await asyncio.create_subprocess_exec(
            "xdotool", "search", "--onlyvisible", "--class", "rdp-session",
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=self._env,
        )
        connected = await proc.wait() == 0
        return Status(connected, f"RDP session: {'connected' if connected else 'DISCONNECTED'}")

    async def screenshot(self) -> Frame:
        return await asyncio.to_thread(self._grab)

    async def image(self) -> Image.Image:
        return await asyncio.to_thread(self._capture)

    def _capture(self) -> Image.Image:
        try:
            return ImageGrab.grab(xdisplay=self.display)
        except OSError as error:  # e.g. no X server at the display
            raise ComputerError(f"screenshot failed: {error}") from error

    def _grab(self) -> Frame:
        image = self._capture()
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return Frame(buffer.getvalue(), image.width, image.height)

    async def click(self, point: Point | None, button: Button, count: int, modifiers: Combo) -> None:
        click = ["click", "--repeat", str(count), "--delay", "50" if count == 1 else "80", str(BUTTONS[button])]
        await self._run("xdotool", *moved(point, await self._here(point)), *held(modifiers, *click))

    async def drag(self, path: Sequence[Point], modifiers: Combo) -> None:
        start, *between, end = path
        # Windows starts a drag only after the pointer moves while pressed, so pass a midpoint on the way.
        between = between or [((start[0] + end[0]) // 2, (start[1] + end[1]) // 2)]
        steps, here = ["mousedown", "1", "sleep", "0.1"], start
        for point in between:
            steps += [*moved(point, here), "sleep", "0.1"]
            here = point
        steps += [*settled(end, here), "sleep", "0.1", "mouseup", "1"]
        await self._run("xdotool", *moved(start, await self.cursor_position()), *held(modifiers, *steps))

    async def _here(self, point: Point | None) -> Point | None:
        """Where the pointer is, when an action is about to move it to point."""
        return None if point is None else await self.cursor_position()

    def _lasting(self) -> xlib.Display:
        """The lasting X connection: a call over it takes a few hundred microseconds where xdotool takes several
        milliseconds to start."""
        if self._xtest is None:
            self._xtest = xlib.Display(self.display)
        return self._xtest

    def _fake_input(self, event_type: int, detail: int = 0, x: int = 0, y: int = 0) -> None:
        """One input event over the lasting connection, with XTest."""
        try:
            self._lasting().xtest_fake_input(event_type, detail, x=x, y=y)
            self._xtest.sync()
        except Exception as error:  # e.g. the display restarted: reconnect on the next event
            self._xtest = None
            raise ComputerError(f"XTest input failed: {error}") from error

    async def move(self, point: Point, settle: bool = True) -> None:
        if settle:
            await self._run("xdotool", *settled(point, await self.cursor_position()))
        else:
            self._fake_input(X.MotionNotify, x=point[0], y=point[1])

    async def mouse_button(self, down: bool, button: Button = "left") -> None:
        self._fake_input(X.ButtonPress if down else X.ButtonRelease, BUTTONS[button])

    async def release_all(self) -> None:
        """Let go of the keys and mouse buttons the display has down, as XTest events that xfreerdp passes on to
        Windows; only those, so nothing else reaches it. Keys and buttons stay down when xdotool is killed partway,
        between its keydown and keyup or mousedown and mouseup."""
        try:
            display = self._lasting()
            keymap = display.query_keymap()  # one bit per key code
            buttons = display.screen().root.query_pointer().mask
        except Exception as error:  # e.g. the display restarted: reconnect on the next call
            self._xtest = None
            raise ComputerError(f"reading which keys are down failed: {error}") from error
        for code in (8 * index + bit for index, byte in enumerate(keymap) for bit in range(8) if byte >> bit & 1):
            self._fake_input(X.KeyRelease, code)
        for button, mask in ((1, X.Button1Mask), (2, X.Button2Mask), (3, X.Button3Mask)):
            if buttons & mask:
                self._fake_input(X.ButtonRelease, button)

    async def scroll(self, point: Point | None, direction: Direction, amount: int, modifiers: Combo) -> None:
        if amount == 1 and not modifiers:  # one notch, as the live view streams them: xdotool waits out its delay
            if point is not None:
                self._fake_input(X.MotionNotify, x=point[0], y=point[1])
            self._fake_input(X.ButtonPress, SCROLL_BUTTONS[direction])
            self._fake_input(X.ButtonRelease, SCROLL_BUTTONS[direction])
            return
        wheel =["click", "--repeat", str(amount), "--delay", "50", str(SCROLL_BUTTONS[direction])]
        await self._run("xdotool", *moved(point, await self._here(point)), *held(modifiers, *wheel))

    async def type_text(self, text: str) -> None:
        async with self._typing:
            for number, line in enumerate(text.replace("\r\n", "\n").split("\n")):
                if number:
                    await self.press([["enter"]])
                chunk = ""
                for char in line:
                    if len((chunk + char).encode()) > 60:
                        await self._unicode_chunk(chunk)
                        chunk = ""
                    chunk += char
                if chunk:
                    await self._unicode_chunk(chunk)

    async def _unicode_chunk(self, text: str) -> None:
        # FreeRDP reads 63 bytes at a time. Keep every write on a UTF-8 character boundary,
        # wait until it has been read, then allow the reader to dispatch it before a control key.
        reader = None
        try:
            writer = os.open(self.keyboard_pipe, os.O_WRONLY | os.O_NONBLOCK)
            try:
                if not stat.S_ISFIFO(os.fstat(writer).st_mode):
                    raise ComputerError("The RDP text input path is not a pipe; nothing was sent.")
                reader = os.open(self.keyboard_pipe, os.O_RDONLY | os.O_NONBLOCK)
                payload = text.encode("utf-8")
                if os.write(writer, payload) != len(payload):
                    raise ComputerError("The RDP text transfer was partial; check the screen before retrying.")
            finally:
                os.close(writer)
            due = time.monotonic() + TEXT_TIMEOUT_SECONDS
            while True:
                pending = array("i", [0])
                fcntl.ioctl(reader, termios.FIONREAD, pending, True)
                if not pending[0]:
                    break
                if time.monotonic() >= due:
                    raise ComputerError("RDP did not take the text; check the connection before retrying.")
                await asyncio.sleep(0.002)
            await asyncio.sleep(0.01 + len(text.encode("utf-16-le")) * 0.0015)
        except OSError as error:
            raise ComputerError("The RDP text input pipe is unavailable; check the desktop connection.") from error
        finally:
            if reader is not None:
                os.close(reader)

    async def press(self, combos: Sequence[Combo]) -> None:
        # Keep the default 12 ms key delay: longer Alt holds can open the task switcher.
        await self._run("xdotool", "key", "--delay", "12", *(xdotool_combo(combo) for combo in combos))

    async def key_state(self, key: str, down: bool) -> None:
        code = 0
        with contextlib.suppress(Exception):  # no display: _fake_input fails below, or xdotool takes over
            code = self._lasting().keysym_to_keycode(XK.string_to_keysym(full_keysym(key)))
        if code:
            self._fake_input(X.KeyPress if down else X.KeyRelease, code)
        else:  # not on the keyboard map: xdotool maps it to a spare key code
            await self._run("xdotool", "keydown" if down else "keyup", keysym(key))

    async def next_change(self, seen: int, timeout: float) -> int:
        if self._no_changes:
            return seen + 1
        if self._changes is None:
            try:
                self._changes = ScreenChanges(self.display)
            except Exception as error:
                logger.warning("the display reports no changes (%s); the live view captures at its full rate", error)
                self._no_changes = True
                return seen + 1
        return await self._changes.after(seen, timeout)

    async def hold(self, combo: Combo, seconds: float) -> None:
        keys = xdotool_combo(combo)
        await self._run("xdotool", "keydown", keys, "sleep", str(seconds), "keyup", keys)

    async def cursor_position(self) -> Point:
        try:
            pointer = self._lasting().screen().root.query_pointer()
        except Exception as error:  # e.g. the display restarted: reconnect on the next call
            self._xtest = None
            raise ComputerError(f"pointer query failed: {error}") from error
        return pointer.root_x, pointer.root_y
