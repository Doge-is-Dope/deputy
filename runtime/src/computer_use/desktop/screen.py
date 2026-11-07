"""Screenshot descriptions, change detection, settling and approval target marks."""

import asyncio
import io
from collections.abc import Sequence

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from computer_use.computers import Computer, Frame, Point, Status

# A pixel has changed when its gray level moves by more than this; RDP is lossless here, so only drawing does.
PIXEL_DELTA = 32
# Fewer changed pixels than this is noise. Measured at 1280x800 over RDP (2026-10-06): the taskbar clock turning a
# minute changes 28-39 pixels and a still screen none; the smallest real effects seen were 69 (Paint's status bar
# after ctrl+s) and 104-123 (one digit or "enter" in Notepad, caret and status bar included).
NOISE = 50
# Half the width and height of the patch around a pointer target: what is under the pointer is what counts. Under 14
# high, since a hover tooltip appears from 14 pixels below the point (measured over RDP on Excel and Explorer).
PATCH = (30, 12)
# A pixel this close to one that moved between two frames counts as moving too: marching ants run along a line,
# so the pixels that toggled are spread along it rather than covering it.
MOVING_MARGIN = 4
# After an action, wait until its effect has drawn and the screen has been still for SETTLE_QUIET_SECONDS, at most
# SETTLE_MAX_SECONDS; if nothing visible changes, for as long as the executor says (executor.SETTLE_SECONDS).
SETTLE_QUIET_SECONDS = 0.5
SETTLE_MAX_SECONDS = 3.0
SETTLE_POLL_SECONDS = 0.1
# A screen as the model gets it, and in gray for comparing.
Shot = tuple[Frame, Image.Image]
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
    return Frame.encode(image).png


def describe(note: str, frame: Frame, status: Status) -> str:
    text = f"{note}\nScreen {frame.width}x{frame.height}; coordinates are screenshot pixels from the top-left."
    return f"{text} {status.detail}." if status.detail else text


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


def changed_pixels(before: Image.Image, after: Image.Image, around: Sequence[Point] = ()) -> int:
    """How many pixels differ between two gray screens: on the whole screen or, with points, in the busiest patch
    around one of them. NOISE or more is a change."""
    return _count(_changes(before, after), around)


def lasting_changed_pixels(
    seen: Image.Image, now: Image.Image, later: Image.Image, around: Sequence[Point] = ()
) -> int:
    """Like changed_pixels(seen, later), leaving out what moved between now and later and the pixels next to it:
    a change that stays, not marching ants, a spinner or a video playing."""
    # Within MOVING_MARGIN of a pixel that moved is where a box blur of the changes is above zero: the same pixels a
    # MaxFilter finds, in 3 ms rather than 70 with the GIL held throughout.
    moving = _changes(now, later).filter(ImageFilter.BoxBlur(MOVING_MARGIN)).point(lambda value: 255 if value else 0)
    return _count(ImageChops.subtract(_changes(seen, later), moving), around)


async def diff(before: Image.Image, after: Image.Image, around: Sequence[Point] = ()) -> int:
    """changed_pixels off the event loop, which would hold up every stream and request meanwhile."""
    return await asyncio.to_thread(changed_pixels, before, after, around)


async def lasting_diff(seen: Image.Image, now: Image.Image, later: Image.Image, around: Sequence[Point] = ()) -> int:
    """lasting_changed_pixels off the event loop, as diff is."""
    return await asyncio.to_thread(lasting_changed_pixels, seen, now, later, around)


def _compare(old: Image.Image, image: Image.Image) -> tuple[Image.Image, bool]:
    """The screen `image` in gray, and whether it changed from the gray screen `old`."""
    new = image.convert("L")
    return new, _count(_changes(old, new), ()) >= NOISE


def _shot(image: Image.Image) -> Shot:
    return Frame.encode(image), image.convert("L")


async def gray(computer: Computer) -> Image.Image:
    """The screen in gray, to compare with others: cheaper than a screenshot, which is encoded."""
    image = await computer.image()
    return await asyncio.to_thread(image.convert, "L")


async def capture(computer: Computer) -> Shot:
    image = await computer.image()
    return await asyncio.to_thread(_shot, image)


async def settle(computer: Computer, before: Image.Image, no_change_seconds: float) -> Shot:
    """Wait for drawing to stop after the gray screen `before`, or for `no_change_seconds` if nothing draws.

    App launches can outlast the no-change timeout. Return the current screen and
    let the agent decide whether to wait longer rather than delay every input.
    Polls compare raw captures; only the returned frame is encoded as PNG."""
    loop = asyncio.get_running_loop()
    start = still_since = loop.time()
    image = await computer.image()
    gray, moved = await asyncio.to_thread(_compare, before, image)
    while True:
        now = loop.time()
        if moved and (now - still_since >= SETTLE_QUIET_SECONDS or now - start >= SETTLE_MAX_SECONDS):
            return await asyncio.to_thread(Frame.encode, image), gray
        if not moved and now - start >= no_change_seconds:
            return await asyncio.to_thread(Frame.encode, image), gray
        await asyncio.sleep(SETTLE_POLL_SECONDS)
        image = await computer.image()
        gray, changed = await asyncio.to_thread(_compare, gray, image)
        if changed:
            moved, still_since = True, loop.time()
