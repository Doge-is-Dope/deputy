"""Cross-process desktop ownership, run locks and pending approvals.

Agent and live-view input obey the same control file. Ownership changes between
actions under ControlFile.locked, then releases held keys and buttons. Only the
user returns control to the agent.

RunLock allows one desktop task across all processes, such as the web page's
server and the eval's (eval/README.md). ApprovalFile holds one pending call for
the user to answer, from the web page or the command line."""

import asyncio
import contextlib
import fcntl
import json
import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Literal, Protocol, TextIO

from computer_use.computers import Computer, ComputerError

Owner = Literal["agent", "user"]
Decision = Literal["approve", "reject"]
# How often a wait for control to come back looks at the control file.
POLL_SECONDS = 1.0
# How often a wait for the user's approval looks for their answer: the approved step goes out this soon after.
APPROVAL_POLL_SECONDS = 0.25
# How often a wait for the control lock tries again; an action holds it for a second or so, a held key up to 10 s.
LOCK_POLL_SECONDS = 0.01

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ControlState:
    owner: Owner
    since: float
    reason: str = ""


class Control(Protocol):
    def read(self) -> ControlState: ...
    def write(self, owner: Owner, reason: str = "") -> ControlState: ...
    def locked(self) -> AbstractAsyncContextManager[ControlState]: ...
    async def wait_for_agent(self) -> float | None: ...


class ControlFile:
    def __init__(self, path: Path):
        self.path = path

    def read(self) -> ControlState:
        try:
            return ControlState(**json.loads(self.path.read_text()))
        except FileNotFoundError:  # never switched: the agent's since the start of time
            return ControlState("agent", 0.0)

    def write(self, owner: Owner, reason: str = "") -> ControlState:
        state = ControlState(owner, time.time(), reason)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(state)))
        tmp.replace(self.path)
        return state

    @contextlib.asynccontextmanager
    async def locked(self) -> AsyncIterator[ControlState]:
        """Who has control, kept so until the block ends, across processes: the agent sends an action inside it,
        and a handover waits until that action is sent."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix(".lock").open("a") as file:  # closing it lets go of the lock
            while True:
                try:
                    fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:  # waited for here, so the event loop keeps running and a stop gets through
                    await asyncio.sleep(LOCK_POLL_SECONDS)
            yield self.read()

    async def wait_for_agent(self) -> float | None:
        """Block while the user has control; return how long they had it, or None if they never did."""
        state = self.read()
        if state.owner == "agent":
            return None
        while self.read().owner != "agent":
            await asyncio.sleep(POLL_SECONDS)
        return time.time() - state.since


@dataclass(frozen=True)
class Approval:
    """A step the agent asked the user to approve, and their answer once they give it. `id` is the tool call's, so an
    answer can only ever approve the call it was asked for."""

    id: str
    run: str
    tool: str
    consequence: str  # what the step will do, in the agent's words
    screenshot: str | None  # the screen it decided from, its target marked: a file in the run's folder
    since: float
    decision: Decision | None = None
    note: str = ""  # what the user said with a rejection
    by: str = ""  # where they answered: "web" or "cli"


class ApprovalFile:
    """The step waiting for the user's approval, at most one: one run has the desktop and runs one tool call at a time.
    A file in the data directory, like control, so every server sharing the desktop sees the same one."""

    def __init__(self, path: Path):
        self.path = path

    def read(self) -> Approval | None:
        try:
            return Approval(**json.loads(self.path.read_text()))
        except (FileNotFoundError, ValueError, TypeError):
            return None

    def _write(self, approval: Approval) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(approval)))
        tmp.replace(self.path)

    def ask(self, approval: Approval) -> None:
        self._write(approval)

    def pending(self, run: str | None) -> Approval | None:
        """The step awaiting an answer, if it belongs to `run`, the one that has the desktop: a run that crashed while
        asking leaves its file behind, and no answer can reach it."""
        approval = self.read()
        if approval is None or approval.decision is not None or approval.run != run:
            return None
        return approval

    def decide(self, id: str, decision: Decision, note: str = "", by: str = "") -> bool:
        """Answer the step `id` once; False when it is not the one awaiting an answer, or already has one."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix(".lock").open("a") as file:  # the web page and the command line may answer at once
            fcntl.flock(file, fcntl.LOCK_EX)
            approval = self.read()
            if approval is None or approval.id != id or approval.decision is not None:
                return False
            self._write(replace(approval, decision=decision, note=note, by=by))
            return True

    def clear(self, id: str) -> None:
        approval = self.read()
        if approval is not None and approval.id == id:
            self.path.unlink(missing_ok=True)

    async def wait(self, id: str, control: Control) -> Approval | None:
        """Block until the user answers the step `id`; None if they take the desktop instead, which answers it too.
        Nothing but an answer approves: no answer waits for ever, and a request gone missing reads as a rejection."""
        while True:
            if control.read().owner == "user":
                return None
            approval = self.read()
            if approval is None or approval.id != id:
                return Approval(id, "", "", "", None, time.time(), "reject")
            if approval.decision is not None:
                return approval
            await asyncio.sleep(APPROVAL_POLL_SECONDS)


async def hand_over(control: Control, computer: Computer, owner: Owner, reason: str) -> ControlState:
    """Give the desktop to owner once the action in flight is sent, then let go of every key and button still down:
    after a takeover the agent sends nothing more, and neither side keeps what the other held down."""
    async with control.locked():
        state = control.write(owner, reason)
        await let_go(computer)
    return state


async def release_input(control: Control, computer: Computer, owner: Owner) -> None:
    """Let go of every key and button still down while owner has the desktop: what a run left down when it ends, or
    what the user held when the live view closed."""
    async with control.locked() as state:
        if state.owner == owner:
            await let_go(computer)


async def let_go(computer: Computer) -> None:
    """Let go of every key and button still down."""
    try:
        await computer.release_all()
    except ComputerError as error:  # e.g. the display is gone: nothing is held there, and control changes anyway
        logger.warning("could not let go of held keys and buttons: %s", error)


class DesktopBusy(RuntimeError):
    """Another run has the desktop: `run` is its id, None while it is starting."""

    def __init__(self, run: str | None):
        super().__init__(f"another run has the desktop: {run or 'one that is starting'}")
        self.run = run


class RunLock:
    """Cross-process lock held only while a run uses the desktop.

    The kernel releases it on process exit, including crashes. The file records the
    run and PID so other processes can display and stop the owner."""

    def __init__(self, path: Path):
        self.path = path
        self._file: TextIO | None = None

    @property
    def held(self) -> bool:
        return self._file is not None

    def acquire(self, run: str | None = None) -> None:
        """Take the desktop for run (named later, with `name`, when its log does not exist yet), or raise DesktopBusy
        naming the run that has it."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        file = open(os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644), "r+", encoding="utf-8")
        try:
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            file.close()
            holder = self.holder()
            raise DesktopBusy(holder.get("run") if holder else None) from None
        self._file = file
        self._write({"run": run, "pid": os.getpid()} if run else {"pid": os.getpid()})

    def release(self) -> None:
        self._file.truncate(0)
        self._file.close()  # closing it lets go of the lock
        self._file = None

    def __enter__(self) -> "RunLock":
        self.acquire()
        return self

    def __exit__(self, *error) -> None:
        self.release()

    def name(self, run: str) -> None:
        """Say which run has the desktop, once its log exists."""
        self._write({"run": run, "pid": os.getpid()})

    def _write(self, holder: dict) -> None:
        self._file.seek(0)
        self._file.truncate()
        self._file.write(json.dumps(holder))
        self._file.flush()

    def holder(self) -> dict | None:
        """The run that has the desktop, as {"run", "pid"} ("run" missing while it starts), or None when it is free.
        Reads the file without taking the lock, so asking never makes a run that is starting find the desktop busy.
        A write empties the file before it fills it, so an empty read is tried once more."""
        for _ in range(2):
            try:
                text = self.path.read_text(encoding="utf-8")
            except FileNotFoundError:
                return None
            if text:
                break
        try:
            holder = json.loads(text or "null")
        except ValueError:
            return None
        return holder if isinstance(holder, dict) and _running(holder.get("pid")) else None


def _running(pid) -> bool:
    """Whether a process is still running: the file of a run that crashed still names it."""
    if not isinstance(pid, int):
        return False
    try:
        os.kill(pid, 0)
    except PermissionError:  # another user's process
        return True
    except (OSError, OverflowError):
        return False
    return True
