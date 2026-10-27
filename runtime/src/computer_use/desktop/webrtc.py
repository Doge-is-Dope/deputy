"""WebRTC video and pointer updates, with human input over a data channel.

Input requires user ownership. The browser draws the pointer separately from
video; models still receive lossless screenshots. TURN relays media when the
browser cannot reach the container's addresses."""

import asyncio
import contextlib
import fractions
import json
import logging
import os
import time
from collections import deque

from aiortc import MediaStreamTrack, RTCConfiguration, RTCDataChannel, RTCPeerConnection, RTCSessionDescription
from aiortc import rtcrtpsender
from aiortc.codecs import get_encoder, h264, vpx
from av import CodecContext, VideoFrame

from computer_use.computers import Computer, Point
from computer_use.desktop.control import Control, release_input
from computer_use.desktop.keys import normalize_key

logger = logging.getLogger(__name__)

# Capture on screen changes, capped by ownership mode; a fixed polling tick adds latency.
WATCH_FPS = 30
CONTROL_FPS = 60
# A still screen still sends a frame this often.
KEEPALIVE_SECONDS = 1.0
CLOCK_RATE = 90_000  # RTP's video clock
# Use a fixed bitrate on this local path: aiortc's REMB ramp repeatedly rebuilds the encoder.
# A deployment across a real network needs congestion control.
BITRATE = 3_000_000
for codec in (vpx, h264):
    codec.MIN_BITRATE = codec.DEFAULT_BITRATE = codec.MAX_BITRATE = BITRATE


class ScreenEncoder(vpx.Vp8Encoder):
    """aiortc's VP8 encoder with the settings libwebrtc uses to share a screen instead of aiortc's camera ones: no
    noise reduction, which smears small text, and blocks that barely change are skipped. aiortc 1.15 keeps a codec
    that is already open at the frame's size and bitrate, so this opens it with those settings."""

    def encode(self, frame: VideoFrame, force_keyframe: bool = False) -> tuple[list[bytes], int]:
        opened = self.codec and (self.codec.width, self.codec.height, self.codec.bit_rate)
        if opened != (frame.width, frame.height, self.target_bitrate):
            codec = self.codec = CodecContext.create("libvpx", "w")
            codec.width, codec.height = frame.width, frame.height
            codec.bit_rate = self.target_bitrate
            codec.pix_fmt = "yuv420p"
            codec.gop_size = 3000
            codec.qmin, codec.qmax = 2, 56
            codec.options = {
                # aiortc's: real time, a constant bitrate with a 1 s buffer
                "bufsize": str(self.target_bitrate),
                "cpu-used": "-6",
                "deadline": "realtime",
                "lag-in-frames": "0",
                "minrate": str(self.target_bitrate),
                "maxrate": str(self.target_bitrate),
                "overshoot-pct": "15",
                "undershoot-pct": "100",
                # libwebrtc's for a screen, where aiortc has 4 and 1. Not its screen-content-mode 2, which sharpened
                # nothing measurable and drops a frame that overshoots: aiortc still numbers the dropped frame, so
                # Chrome waited about 3 s for it, then asked for a keyframe (2026-10-06).
                "noise-sensitivity": "0",
                "static-thresh": "100",
            }
            codec.thread_count = vpx.number_of_threads(frame.width * frame.height, os.cpu_count() or 1)
        return super().encode(frame, force_keyframe)


# aiortc picks each sender's encoder through this name.
rtcrtpsender.get_encoder = lambda codec: (
    ScreenEncoder() if codec.mimeType.lower() == "video/vp8" else get_encoder(codec)
)

BUTTONS = ("left", "middle", "right")
DIRECTIONS = ("up", "down", "left", "right")


class ScreenTrack(MediaStreamTrack):
    """The screen as video: a frame each time the screen changes, at most CONTROL_FPS frames a second while the user
    has control and WATCH_FPS otherwise. Screen captures leave the pointer out; the page draws it (ScreenShare)."""

    kind = "video"

    def __init__(self, computer: Computer, control: Control):
        super().__init__()
        self.computer = computer
        self.control = control
        self.start: float | None = None
        self.due = 0.0  # when the next frame may be taken
        self.seen = 0  # the screen's change count at the last frame (Computer.next_change)

    async def recv(self) -> VideoFrame:
        if self.start is None:
            self.start = self.due = time.monotonic()
        else:
            self.due += 1 / (CONTROL_FPS if self.control.read().owner == "user" else WATCH_FPS)
            await asyncio.sleep(max(0.0, self.due - time.monotonic()))
            self.seen = await self.computer.next_change(self.seen, KEEPALIVE_SECONDS)
            self.due = max(self.due, time.monotonic())  # a late frame does not set off a burst to catch up
        while True:
            try:
                image = await self.computer.image()
                break
            except Exception as error:  # e.g. the display is not up yet: keep the stream, try again
                logger.warning("live view capture failed: %s", error)
                await asyncio.sleep(1)
        frame = VideoFrame.from_image(image)
        frame.pts = round((self.due - self.start) * CLOCK_RATE)
        frame.time_base = fractions.Fraction(1, CLOCK_RATE)
        return frame


class ScreenShare:
    """The page's WebRTC connections: the screen and the agent's pointer out, the user's input in while they have
    control."""

    def __init__(self, computer: Computer, control: Control):
        self.computer = computer
        self.control = control
        self.peers: set[RTCPeerConnection] = set()

    async def answer(self, offer: str) -> str:
        """Accept the page's SDP offer and return the answer, with every local candidate in it."""
        # No ICE servers: aiortc would otherwise ask Google's STUN server. The browser brings the TURN server.
        peer = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        self.peers.add(peer)

        @peer.on("connectionstatechange")
        async def on_state() -> None:
            if peer.connectionState in ("failed", "closed"):
                self.peers.discard(peer)
                await peer.close()

        @peer.on("datachannel")
        def on_channel(channel: RTCDataChannel) -> None:
            self._take_input(channel)
            self._report_pointer(channel)

        await peer.setRemoteDescription(RTCSessionDescription(sdp=offer, type="offer"))
        for transceiver in peer.getTransceivers():
            if transceiver.kind == "video":
                peer.addTrack(ScreenTrack(self.computer, self.control))
        await peer.setLocalDescription(await peer.createAnswer())
        return peer.localDescription.sdp

    def _take_input(self, channel: RTCDataChannel) -> None:
        """Apply a channel's events in order. Pointer moves arrive faster than they can be applied, so a move
        still waiting is replaced by the next one."""
        waiting: deque[dict] = deque()
        ready = asyncio.Event()

        def on_message(message: str | bytes) -> None:
            try:
                event = json.loads(message)
            except ValueError:
                return
            if not isinstance(event, dict):
                return
            if event.get("type") == "move" and waiting and waiting[-1].get("type") == "move":
                waiting[-1] = event
            else:
                waiting.append(event)
            ready.set()

        async def apply_all() -> None:
            try:
                while True:
                    await ready.wait()
                    ready.clear()
                    while waiting:
                        await self.apply(waiting.popleft())
            finally:  # the page went away: a key or button the user still held would stay down on Windows
                await release_input(self.control, self.computer, "user")

        worker = asyncio.ensure_future(apply_all())
        channel.on("message", on_message)
        channel.on("close", worker.cancel)

    def _report_pointer(self, channel: RTCDataChannel) -> None:
        """Tell the page on the channel where the agent's pointer is whenever it moves, looked up WATCH_FPS times a
        second, and null while the user has control (the page draws theirs at their mouse). Screen captures leave the
        pointer out, and the page draws it sharper than the video could, at one size and in its theme."""

        async def report() -> None:
            sent: Point | None = None  # what the page last heard; it starts with nothing to draw
            while True:
                await asyncio.sleep(1 / WATCH_FPS)
                point = None
                if self.control.read().owner != "user":
                    with contextlib.suppress(Exception):  # e.g. the display is not up yet: nothing to draw
                        point = await self.computer.cursor_position()
                if point != sent and channel.readyState == "open":
                    channel.send(json.dumps({"type": "pointer", "point": point}))
                    sent = point

        reporter = asyncio.ensure_future(report())
        channel.on("close", reporter.cancel)

    async def apply(self, event: dict) -> None:
        """One input event from the page; ignored unless the user has control."""
        if self.control.read().owner != "user":
            return
        try:
            match event:
                case {"type": "move", "x": int(x), "y": int(y)}:
                    await self.computer.move((x, y), settle=False)
                case {"type": "button", "button": str(button), "down": bool(down)} if button in BUTTONS:
                    await self.computer.mouse_button(down, button)
                case {"type": "wheel", "direction": str(direction), "x": int(x), "y": int(y)} if direction in DIRECTIONS:
                    await self.computer.scroll((x, y), direction, 1, [])
                case {"type": "key", "key": str(key), "down": bool(down)}:
                    await self.computer.key_state(normalize_key(key), down)
                case {"type": "text", "text": str(text)} if text:
                    await self.computer.type_text(text)
        except Exception as error:  # an unknown key or a failed input: drop it, keep the channel
            logger.warning("live view input %s failed: %s", event.get("type"), error)

    async def close(self) -> None:
        await asyncio.gather(*(peer.close() for peer in self.peers))
        self.peers.clear()
