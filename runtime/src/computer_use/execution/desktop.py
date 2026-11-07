"""A desktop task's tools, with the middleware that holds, stops and re-observes around them (middleware.desktop), for
whichever agent runs the task; and the desktop a task holds while it runs."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from computer_use.agent.background import Refusal
from computer_use.agent.inbox import Inbox
from computer_use.agent.review import Verdict
from computer_use.agent.trajectory import Trajectory
from computer_use.computers import Computer
from computer_use.desktop.control import ApprovalFile, Control, DesktopBusy, RunLock, release_input
from computer_use.desktop.executor import Executor
from computer_use.execution.approvals import Confirmations
from computer_use.middleware.desktop import DesktopMiddleware
from computer_use.prompts.computer import DESKTOP_BUSY, computer_in_use, desktop_offline
from computer_use.tools.desktop import desktop_tools, takeover_tool


@dataclass(frozen=True)
class DesktopResource:
    """The desktop a task holds while it runs: a hand-over starts it only while the computer is free and connected,
    and the task keeps the run lock until it ends."""

    computer: Computer
    lock: RunLock

    def in_use(self, task: str) -> Refusal:
        return computer_in_use(task), "computerInUse"

    async def unavailable(self) -> Refusal | None:
        status = await self.computer.status()
        return None if status.connected else (desktop_offline(status.detail), "disconnected")

    def acquire(self, run: str) -> Refusal | None:
        if self.lock.held:  # a message for the desktop took it as its run began
            return None
        try:
            self.lock.acquire(run)
        except DesktopBusy:
            return DESKTOP_BUSY, "desktopBusy"
        return None

    def taken_by(self, run: str) -> None:
        self.lock.name(run)

    def release(self) -> None:
        if self.lock.held:
            self.lock.release()


class DesktopExecution:
    """One desktop task's executor, approvals, tools and middleware, made fresh for each task so nothing carries over.
    Use them inside `async with`: leaving it lets go of whatever the task left held down, after its last screen."""

    def __init__(
        self, computer: Computer, control: Control, approvals: ApprovalFile, log: Trajectory,
        review: Callable[[str, bytes | None], Awaitable[Verdict]], auto: Callable[[], bool],
        on_request: Callable[[str], None], web_url: str, inbox: Inbox,
    ):
        self.executor = Executor(computer, control)
        self.confirm = Confirmations(approvals, control, self.executor, log, review, auto)
        self.tools = [*desktop_tools(self.executor), takeover_tool(control, computer, on_request)]
        self.middleware = DesktopMiddleware(self.executor, control, log, web_url, self.confirm, inbox)

    async def __aenter__(self) -> "DesktopExecution":
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        await release_input(self.executor.control, self.executor.computer, "agent")
