"""Screenshot descriptions, change detection, settling and approval target marks."""

import asyncio
import io
from collections.abc import Sequence

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from computer_use.computers import Computer, Frame, Point, Status
from computer_use.config import Settings

# A pixel has changed when its gray level moves by more than this; RDP is lossless here, so only drawing does.
PIXEL_DELTA = 32
# Fewer changed pixels than this is noise. Measured at 1280x800 over RDP (2026-10-06): the taskbar clock turning a
# minute changes 28-39 pixels and a still screen none; the smallest real effects seen were 69 (Paint's status bar
# after ctrl+s) and 104-123 (one digit or "enter" in Notepad, caret and status bar included).
NOISE = 50
# Half the width and height of the patch around a pointer target: what is under the pointer is what counts.
PATCH = (60, 40)
# A pixel this close to one that moved between two frames counts as moving too: marching ants run along a line,
# so the pixels that toggled are spread along it rather than covering it.
MOVING_MARGIN = 4
SETTLE_POLL_SECONDS = 0.1
# The ring around a point a step acts on, as the user sees it when asked to approve the step: red on white, so it
# stands out on light and dark windows alike.
MARK_RADIUS = 18
MARK_COLORS = ((255, 255, 255), (230, 40, 40))


def mark(png: bytes, points: Sequence[Point]) -> bytes:
    """The screenshot with a ring around each point a step acts on, and a line between them for a drag's two."""
    image = Image.open(io.BytesIO(png)).convert("RGB")
    draw = ImageDraw.Draw(image)
    for color, width in zip(MARK_COLORS, (7, 3)):
        if len(points) == 2:
            draw.line([*points[0], *points[1]], fill=color, width=width)
        for x, y in points:
            r = MARK_RADIUS
            draw.ellipse((x - r, y - r, x + r, y + r), outline=color, width=width)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def describe(note: str, frame: Frame, status: Status) -> str:
    """The text sent with a screenshot: what happened, the screen size, and the connection."""
    text = f"{note}\nScreen {frame.width}x{frame.height}; coordinates are screenshot pixels from the top-left."
    return f"{text} {status.detail}." if status.detail else text


def _gray(png: bytes) -> Image.Image:
    return Image.open(io.BytesIO(png)).convert("L")


def _changes(old: Image.Image, new: Image.Image) -> Image.Image:
    """The pixels that differ between two gray screens, white on black. Screens of different sizes differ everywhere."""
    if old.size != new.size:
        return Image.new("L", new.size, 255)
    return ImageChops.difference(old, new).point(lambda value: 255 if value > PIXEL_DELTA else 0)


def _count(changes: Image.Image, around: Sequence[Point]) -> int:
    """White pixels on the whole screen or, with points, in the busiest patch around one of them."""
    if not around:
        return changes.histogram()[255]
    dx, dy = PATCH
    return max(changes.crop((x - dx, y - dy, x + dx, y + dy)).histogram()[255] for x, y in around)


def changed_pixels(before: bytes, after: bytes, around: Sequence[Point] = ()) -> int:
    """How many pixels differ between two screenshots: on the whole screen or, with points, in the busiest patch
    around one of them. NOISE or more is a change."""
    return 0 if before == after else _count(_changes(_gray(before), _gray(after)), around)


def lasting_changed_pixels(seen: bytes, now: bytes, later: bytes, around: Sequence[Point] = ()) -> int:
    """Like changed_pixels(seen, later), leaving out what moved between now and later and the pixels next to it:
    a change that stays, not marching ants, a spinner or a video playing."""
    # Within MOVING_MARGIN of a pixel that moved is where a box blur of the changes is above zero: the same pixels a
    # MaxFilter finds, in 3 ms rather than 70 with the GIL held throughout.
    seen, now, later = (_gray(png) for png in (seen, now, later))
    moving = _changes(now, later).filter(ImageFilter.BoxBlur(MOVING_MARGIN)).point(lambda value: 255 if value else 0)
    return _count(ImageChops.subtract(_changes(seen, later), moving), around)


async def diff(before: bytes, after: bytes, around: Sequence[Point] = ()) -> int:
    """changed_pixels off the event loop: decoding and comparing two screens takes tens of milliseconds, which would
    hold up every stream and request meanwhile."""
    return 0 if before == after else await asyncio.to_thread(changed_pixels, before, after, around)


async def lasting_diff(seen: bytes, now: bytes, later: bytes, around: Sequence[Point] = ()) -> int:
    """lasting_changed_pixels off the event loop, as diff is."""
    return await asyncio.to_thread(lasting_changed_pixels, seen, now, later, around)


def _compare(old: Image.Image, image: Image.Image) -> tuple[Image.Image, bool]:
    """The screen `image` in gray, and whether it changed from the gray screen `old`."""
    new = image.convert("L")
    return new, _count(_changes(old, new), ()) >= NOISE


def _frame(image: Image.Image) -> Frame:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return Frame(buffer.getvalue(), image.width, image.height)


async def settle(computer: Computer, settings: Settings, before: Frame) -> Frame:
    """Wait for drawing to stop, bounded by the configured settle timeouts.

    App launches can outlast the no-change timeout. Return the current screen and
    let the agent decide whether to wait longer rather than delay every input.
    Polls compare raw captures; only the returned frame is encoded as PNG."""
    loop = asyncio.get_running_loop()
    start = still_since = loop.time()
    gray = await asyncio.to_thread(_gray, before.png)
    image = await computer.image()
    gray, moved = await asyncio.to_thread(_compare, gray, image)
    while True:
        now = loop.time()
        if moved and (now - still_since >= settings.settle_quiet_seconds or now - start >= settings.settle_max_seconds):
            return await asyncio.to_thread(_frame, image)
        if not moved and now - start >= settings.settle_seconds:
            return await asyncio.to_thread(_frame, image)
        await asyncio.sleep(SETTLE_POLL_SECONDS)
        image = await computer.image()
        gray, changed = await asyncio.to_thread(_compare, gray, image)
        if changed:
            moved, still_since = True, loop.time()
