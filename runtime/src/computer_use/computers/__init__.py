"""Desktop backend contract: lossless screenshots and mouse/keyboard input.

Executor applies agent input rules; desktop.webrtc handles human input. Backends map
the normalized names in desktop.keys to their own key codes."""

import io
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from PIL import Image

from computer_use.config import Settings

Point = tuple[int, int]
Button = Literal["left", "middle", "right"]
Direction = Literal["up", "down", "left", "right"]
Combo = Sequence[str]  # keys pressed together, e.g. ["ctrl", "s"]


class ComputerError(RuntimeError):
    """Input or a screenshot could not be delivered."""


@dataclass(frozen=True)
class Frame:
    """One lossless screenshot. Coordinates in actions are pixels of the screen it shows."""

    png: bytes
    width: int
    height: int

    @classmethod
    def of(cls, png: bytes) -> "Frame":
        with Image.open(io.BytesIO(png)) as image:
            return cls(png, image.width, image.height)


@dataclass(frozen=True)
class Status:
    connected: bool
    detail: str = ""  # shown to the model with every screenshot, e.g. "RDP session: connected"


class Computer(Protocol):
    # A point of None means "where the pointer already is"; modifiers are held during the action.
    async def status(self) -> Status: ...
    async def screenshot(self) -> Frame: ...
    async def image(self) -> Image.Image: ...  # the screen unencoded, for the live view's video; cheaper than a PNG
    async def click(self, point: Point | None, button: Button, count: int, modifiers: Combo) -> None: ...
    async def drag(self, path: Sequence[Point], modifiers: Combo) -> None: ...
    # A person's pointer moves come in a stream, so they need no settling; the agent's single moves do.
    async def move(self, point: Point, settle: bool = True) -> None: ...
    async def mouse_button(self, down: bool, button: Button = "left") -> None: ...
    async def scroll(self, point: Point | None, direction: Direction, amount: int, modifiers: Combo) -> None: ...
    async def type_text(self, text: str) -> None: ...  # a newline presses Enter
    async def press(self, combos: Sequence[Combo]) -> None: ...
    async def hold(self, combo: Combo, seconds: float) -> None: ...
    async def key_state(self, key: str, down: bool) -> None: ...  # one key down or up, for a person's typing
    # Lets go of every key and mouse button still down, and only those: after input stopped partway, or a handover.
    async def release_all(self) -> None: ...
    # Waits until the screen may have changed since `seen` (0, or what the last call returned), or `timeout` seconds
    # pass; returns the number to pass next time. Lets the live view capture right after a change.
    async def next_change(self, seen: int, timeout: float) -> int: ...
    async def cursor_position(self) -> Point: ...


def build_computer(settings: Settings) -> Computer:
    # RDP only so far; other backends plug in here behind a setting.
    from computer_use.computers.rdp import RdpComputer

    return RdpComputer(settings.display, settings.keyboard_pipe)
