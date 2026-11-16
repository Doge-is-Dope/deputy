"""The host's lease, kept in step with who has the desktop.

The host runs commands only for the holder of a lease that lasts a few seconds unless renewed, and stops what is
running when it ends: so a runtime that dies, or a user who takes the desktop, leaves nothing running on Windows."""

import asyncio
import contextlib
import secrets

from computer_use.desktop.control import Control
from computer_use.native import Channel, HostError
from computer_use.native.launcher import Launcher
from computer_use.native.mcp import CredentialFile, Credentials

# The host's lease lasts 5 to 10 s; renewed this often, it survives two lost renewals.
BEAT_SECONDS = 1.5
BEAT_TIMEOUT_SECONDS = 3.0


class Lease:
    def __init__(self, channel: Channel, control: Control):
        self.channel = channel
        self.control = control
        self.target: dict | None = None  # the session and lease commands are sent for; None while not held
        self.problem = "not started yet"  # why it is not held, in words for the agent and the status
        self._task: asyncio.Task | None = None
        self._stepping = asyncio.Lock()  # the loop and a task starting the host both step

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def close(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        await self._give_up("the runtime stopped")

    async def _run(self) -> None:
        while True:
            await self.step()
            await asyncio.sleep(BEAT_SECONDS)

    async def step(self) -> None:
        """Hold the lease while the agent has the desktop, and only then. A fault changes nothing about who has it:
        the lease is taken again once the host answers."""
        async with self._stepping:
            await self._step()

    async def _step(self) -> None:
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
            # A host not started yet says nothing new: why it could not be started stays.
            if not (isinstance(error, HostError) and error.code == "not_started" and self.problem):
                self.problem = str(error) or type(error).__name__

    async def _give_up(self, why: str) -> None:
        target, self.target, self.problem = self.target, None, why
        if target is not None:
            with contextlib.suppress(HostError):  # an unreachable host lets the lease run out by itself
                await self.channel.call("control.takeover", target, timeout=BEAT_TIMEOUT_SECONDS)


# After the host is started it binds its port; the lease is tried this many times, this far apart.
STARTED_TRIES = 20
STARTED_POLL_SECONDS = 0.5


class WindowsTools:
    """One desktop's host: how to reach it, its lease, and, where the runtime starts it itself, how."""

    def __init__(self, channel: Channel, lease: Lease, store: CredentialFile, launcher: Launcher | None = None):
        self.channel = channel
        self.lease = lease
        self.store = store
        self.launcher = launcher

    async def ensure(self) -> None:
        """Before a desktop task acts: have the host running, starting it if it does not answer. Starting it types
        on the desktop, so it happens only here, with the desktop the task's and the agent in control; a failure
        leaves the task its mouse and keyboard, and the lease says why."""
        if self.launcher is None or not self.lease.control.read().allows_input("agent"):
            return
        await self.lease.step()
        if self.lease.target is not None:
            return
        try:
            token = secrets.token_hex(32)
            fingerprint = await self.launcher.start(token)
        except HostError as error:
            self.lease.problem = str(error)
            return
        self.store.write(Credentials(token, fingerprint))
        for _ in range(STARTED_TRIES):
            await self.lease.step()
            if self.lease.target is not None:
                return
            await asyncio.sleep(STARTED_POLL_SECONDS)
