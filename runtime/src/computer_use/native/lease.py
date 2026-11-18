"""The host's lease, kept in step with who has the desktop.

The host runs commands only for the holder of a lease that lasts a few seconds unless renewed, and stops what is
running when it ends: so a runtime that dies, or a user who takes the desktop, leaves nothing running on Windows."""

import asyncio
import contextlib
import time

from computer_use.computers import Status
from computer_use.desktop.control import Control
from computer_use.native import Channel, HostError

# The host's lease lasts 5 to 10 s; renewed this often, it survives two lost renewals.
BEAT_SECONDS = 1.5
BEAT_TIMEOUT_SECONDS = 3.0
# Outside a desktop task, whether the host answers is checked again once the last check is this old.
STATUS_SECONDS = 30.0


class Lease:
    def __init__(self, channel: Channel, control: Control):
        self.channel = channel
        self.control = control
        self.target: dict | None = None  # the session and lease commands are sent for; None while not held
        self.problem = "not started yet"  # why it is not held, in words for the agent
        self._task: asyncio.Task | None = None
        self._checked: tuple[float, Status] | None = None

    async def status(self) -> Status:
        """Whether the host answers: so while the lease is held, else as a describe found it, kept a while."""
        if self.target is not None:
            return Status(True)
        if self._checked is None or time.monotonic() - self._checked[0] >= STATUS_SECONDS:
            try:
                await self.channel.call("describe", timeout=BEAT_TIMEOUT_SECONDS)
                status = Status(True)
            except HostError as error:
                status = Status(False, str(error))
            self._checked = (time.monotonic(), status)
        return self._checked[1]

    async def start(self) -> None:
        await self.step()
        self._task = asyncio.create_task(self._run())

    async def close(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None
        await self._give_up("the desktop task ended")

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(BEAT_SECONDS)
            await self.step()

    async def step(self) -> None:
        """Hold the lease while the agent has the desktop, and only then. A fault changes nothing about who has it:
        the lease is taken again once the host answers."""
        if not self.control.read().allows_input("agent"):
            await self._give_up("the user has control of the desktop")
            return
        try:
            if self.target is None:
                described = await self.channel.call("describe", timeout=BEAT_TIMEOUT_SECONDS)
                resumed = await self.channel.call("control.resume", described["target"], timeout=BEAT_TIMEOUT_SECONDS)
                self.target, self.problem = resumed["target"], ""
            else:
                await self.channel.call("control.heartbeat", self.target, timeout=BEAT_TIMEOUT_SECONDS)
        except (HostError, KeyError) as error:
            self.target = None
            self.problem = str(error) or type(error).__name__

    async def _give_up(self, why: str) -> None:
        target, self.target, self.problem = self.target, None, why
        if target is not None:
            with contextlib.suppress(HostError):  # an unreachable host lets the lease run out by itself
                await self.channel.call("control.takeover", target, timeout=BEAT_TIMEOUT_SECONDS)
