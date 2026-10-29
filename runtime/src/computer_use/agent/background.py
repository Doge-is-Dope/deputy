"""Background task lifecycle and completion reports for the main agent.

A run's tasks run at once, up to MAX_TASKS, each under an id. Steering messages
reach a task's inbox before its next model call; completion wakes the main agent
with a runtime-authored report."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from langchain_core.messages import HumanMessage

from computer_use.agent.inbox import Inbox
from computer_use.agent.subagent import Result
from computer_use.agent.trajectory import TASK, Trajectory
from computer_use.prompts import notes

# Tasks at work at once.
MAX_TASKS = 6


@dataclass
class Job:
    id: str
    tool: str  # the main agent's tool that started it
    brief: str  # what it asked
    started: float
    inbox: Inbox  # what the main agent tells it while it works
    steps: Callable[[], Awaitable[list[str]]]  # what it has done so far, a line per step, read back from the log
    task: asyncio.Task
    title: str = ""  # what the user sees for it
    computer: bool = False  # it uses the computer, which one task at a time does
    heard: int = 0  # the user's messages it has heard of, from its brief and what it was told since
    stopped: bool = False  # the main agent stopped it
    missed: list[str] = field(default_factory=list)  # what it was told and ended before reading


def runtime_message(text: str, event: str, content: list[dict] | None = None, **fields) -> HumanMessage:
    """A message from the runtime to the main agent: in the user's turn, as model APIs take it, but marked as not
    theirs, in its words and in the log (`additional_kwargs`, which model APIs do not send)."""
    blocks = [{"type": "text", "text": f"{notes.FROM_RUNTIME} {text}"}, *(content or [])]
    return HumanMessage(content=blocks, additional_kwargs={"runtime": {"event": event, **fields}})


def missed(job: Job) -> list[dict]:
    """What a task was told and ended before reading, for the main agent to see it was not acted on."""
    if not job.missed:
        return []
    return [{"type": "text", "text": notes.missed(job.missed)}]


def from_user(message) -> bool:
    """Whether a message is the user's own, not the runtime's."""
    return isinstance(message, HumanMessage) and "runtime" not in message.additional_kwargs


class Background:
    """A run's tasks in the background, and those that ended and the main agent has not heard of yet."""

    def __init__(self, log: Trajectory):
        self.log = log
        self.jobs: dict[str, Job] = {}
        self.started = 0
        self.ended: list[tuple[Job, Result]] = []
        self.error: BaseException | None = None  # a task that failed outright fails the run, as it did before
        self._changed = asyncio.Event()

    @property
    def running(self) -> bool:
        return bool(self.jobs)

    @property
    def full(self) -> bool:
        return len(self.jobs) >= MAX_TASKS

    @property
    def computer(self) -> Job | None:
        """The task using the computer, if any."""
        return next((job for job in self.jobs.values() if job.computer), None)

    def start(self, tool: str, brief: str, work: Callable[[str, Inbox], Awaitable[Result]],
              steps: Callable[[], Awaitable[list[str]]], heard: int = 0, computer: bool = False, title: str = "") -> str:
        """Start a task; its id. What it logs carries the id."""
        self.started += 1
        id, inbox = f"t{self.started}", Inbox()

        async def tagged() -> Result:
            TASK.set(id)
            return await work(id, inbox)

        job = Job(id, tool, brief, time.time(), inbox, steps, asyncio.create_task(tagged()), title, computer, heard)
        self.jobs[id] = job
        self.log.task("started", id, tool, brief, title)
        job.task.add_done_callback(lambda _: self._end(job))
        return id

    def _end(self, job: Job) -> None:
        self.jobs.pop(job.id, None)
        # It reads what it was told before it ends (agent.middleware), but words can still land after that check.
        job.missed = [message.text for message in job.inbox.pending()]
        job.inbox.close()
        self.log.task("stopped" if job.stopped else "ended", job.id, job.tool, job.brief, job.title)
        if job.task.cancelled():
            pass  # stopped: the main agent knows, from stop_task, or the run itself was stopped
        elif (error := job.task.exception()) is not None:
            self.error = error
        else:
            self.ended.append((job, job.task.result()))
        self._changed.set()

    def tell(self, id: str, text: str) -> None:
        self.jobs[id].inbox.put(text)

    async def stop(self, id: str | None = None) -> None:
        """Stop a task, or every task, and wait until they have let go of what they held."""
        jobs = [self.jobs[id]] if id is not None else list(self.jobs.values())
        for job in jobs:
            job.stopped = True
            job.task.cancel()
        await asyncio.gather(*(job.task for job in jobs), return_exceptions=True)

    async def wait(self) -> None:
        """Until a task has ended or failed."""
        while not self.ended and self.error is None:
            self._changed.clear()
            await self._changed.wait()

    def reports(self) -> list[HumanMessage]:
        """The runtime's messages that tasks ended, with their results, once each; the main agent checks them."""
        messages = [
            runtime_message(
                notes.task_ended(job.id, job.tool, job.brief),
                "task_ended", content + missed(job), id=job.id, tool=job.tool, brief=job.brief, artifact=artifact,
            )
            for job, (content, artifact) in self.ended
        ]
        self.ended.clear()
        return messages

    async def status(self) -> HumanMessage | None:
        """The running tasks' state, from the log, for the main agent to answer the user from rather than guess: what
        each was asked, for how long it has been at it, and its latest steps."""
        if not self.jobs:
            return None
        parts = [
            notes.task_running(job.id, job.tool, time.time() - job.started, job.brief, await job.steps())
            for job in self.jobs.values()
        ]
        return runtime_message("\n\n".join(parts), "task_status", ids=list(self.jobs))
