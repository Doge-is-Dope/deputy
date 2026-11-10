"""Background task lifecycle and completion reports for the main agent.

A session's tasks run at once, up to MAX_TASKS, each under an id and with a log of its own. A task's end or failure
wakes the main agent with a runtime-authored report."""

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from langchain_core.messages import HumanMessage

from computer_use.agent.failures import error_code
from computer_use.agent.inbox import Inbox
from computer_use.agent.subagent import Result, StopReason
from computer_use.agent.trajectory import Trajectory
from computer_use.events import ActionReason
from computer_use.prompts import notes

MAX_TASKS = 6
# How much of a failure the main agent reads.
FAILURE_CHARS = 1000
# Who stopped a task the user stopped on its own, as its log's end says.
USER = "user"


# Why a hand-over is turned away: in the main agent's words, and as a code the page reads.
Refusal = tuple[str, ActionReason]


class Resource(Protocol):
    """What only one task at a time may hold. A hand-over asks in this order; the task holds it from `acquire` until
    `release`."""

    def in_use(self, task: str) -> Refusal: ...  # why not while this session's `task` holds it
    async def unavailable(self) -> Refusal | None: ...  # why not now, whoever holds it
    def acquire(self, run: str) -> Refusal | None: ...  # why not, if another conversation holds it; held already: None
    def taken_by(self, run: str) -> None: ...  # the log that holds it from here on
    def release(self) -> None: ...  # not held: nothing to do


@dataclass
class Job:
    id: str
    record: str  # its log's run id
    agent: str
    brief: str
    started: float
    inbox: Inbox
    steps: Callable[[], Awaitable[list[str]]]  # a line per step so far, read back from the log
    task: asyncio.Task
    title: str = ""
    heard: int = 0  # the user's messages it has heard of, from its brief and what it was told since
    stopped: bool = False  # the main agent stopped it
    missed: list[str] = field(default_factory=list)  # what it was told and ended before reading
    plan_steps: Sequence[str] = ()  # the ids of the plan's steps it was handed
    plan_note: str = ""  # how the plan stands once it ended, said after its result
    answered: asyncio.Event = field(default_factory=asyncio.Event)  # the main agent told it something since it asked
    answer: str = ""  # the main agent's words in what it last told it, without what the runtime added


def runtime_message(text: str, event: str, content: list[dict] | None = None, **fields) -> HumanMessage:
    """A message from the runtime to the main agent: in the user's turn, as model APIs take it, but marked as not
    theirs in its words and in `additional_kwargs`, which model APIs do not send."""
    blocks = [{"type": "text", "text": f"{notes.FROM_RUNTIME} {text}"}, *(content or [])]
    return HumanMessage(content=blocks, additional_kwargs={"runtime": {"event": event, **fields}})


def missed(job: Job) -> list[dict]:
    if not job.missed:
        return []
    return [{"type": "text", "text": notes.missed(job.missed)}]


def report(job: Job, outcome: Result | BaseException) -> HumanMessage:
    if isinstance(outcome, BaseException):
        error = f"{type(outcome).__name__}: {outcome}"[:FAILURE_CHARS]
        if error_code(outcome).startswith("E-MODEL"):  # said by the model API, of itself
            error = f"the model service reported an error. {error}"
        return runtime_message(notes.task_failed(job.id, job.agent, job.brief, error), "task_failed", missed(job),
                               id=job.id, agent=job.agent, brief=job.brief)
    content, artifact = outcome
    plan = [{"type": "text", "text": job.plan_note}] if job.plan_note else []
    return runtime_message(notes.task_ended(job.id, job.agent, job.brief), "task_ended", content + plan + missed(job),
                           id=job.id, agent=job.agent, brief=job.brief, artifact=artifact)


def from_user(message) -> bool:
    return isinstance(message, HumanMessage) and "runtime" not in message.additional_kwargs


class Background:
    """A session's tasks in the background, and those that ended and the main agent has not heard of yet."""

    def __init__(self, on_task: Callable[["Job", Result | BaseException | None], None] = lambda *_: None):
        self.on_task = on_task  # told of each task's start, and of its end with its outcome, if a stop left it one
        self.jobs: dict[str, Job] = {}
        self.started = 0
        self.ended: list[tuple[Job, Result | BaseException]] = []
        self.asked: list[tuple[Job, str]] = []  # what tasks asked the main agent, which it has not heard yet
        self.starting = asyncio.Lock()  # held while a task is handed over
        self.told: list[HumanMessage] = []  # what to tell the main agent at its next call, without waking it
        self.latest: dict[str, StopReason | None] = {}  # how each agent's latest task ended
        self._changed = asyncio.Event()

    @property
    def running(self) -> bool:
        return bool(self.jobs)

    @property
    def full(self) -> bool:
        return len(self.jobs) >= MAX_TASKS

    def working(self, agent: str) -> Job | None:
        return next((job for job in self.jobs.values() if job.agent == agent), None)

    def on_steps(self) -> dict[str, list[str]]:
        """The ids of the running tasks, by the plan's step they were handed."""
        running: dict[str, list[str]] = {}
        for job in self.jobs.values():
            for step in job.plan_steps:
                running.setdefault(step, []).append(job.id)
        return running

    def at_work(self) -> list[dict]:
        return [{"id": job.id, "agent": job.agent, "title": job.title, "steps": list(job.plan_steps)}
                for job in self.jobs.values()]

    @property
    def news(self) -> bool:
        """Whether a task has ended or asked something the main agent has not heard yet."""
        return bool(self.ended or self.asked)

    def number(self) -> str:
        return f"t{self.started + 1}"

    def start(self, agent: str, brief: str, work: Callable[[str, Inbox], Awaitable[Result]],
              steps: Callable[[], Awaitable[list[str]]], *, turn: Trajectory, record: str, heard: int = 0,
              title: str = "", plan_steps: Sequence[str] = ()) -> str:
        id, inbox = self.number(), Inbox()
        self.started += 1
        job = Job(id, record, agent, brief, time.time(), inbox, steps, asyncio.create_task(work(id, inbox)), title,
                  heard, plan_steps=plan_steps)
        self.jobs[id] = job
        turn.task(id, agent, brief, title, record)
        job.task.add_done_callback(lambda _: self._end(job))
        self.on_task(job, None)
        return id

    def _end(self, job: Job) -> None:
        self.jobs.pop(job.id, None)
        self.asked = [each for each in self.asked if each[0] is not job]
        # It reads what it was told before it ends (middleware.subagent), but words can still land after that check.
        job.missed = [message.text for message in job.inbox.pending()]
        job.inbox.close()
        outcome = None
        if not job.task.cancelled():  # stopped: the main agent knows, from stop_task, or the run itself was stopped
            outcome = job.task.exception() or job.task.result()
            self.ended.append((job, outcome))
        self._changed.set()  # first: what follows logs, and the main agent must hear of this whatever becomes of that
        self.on_task(job, outcome)

    async def stop_for_user(self, record: str) -> bool:
        """Stop the task logging to `record` for the user and tell the main agent at its next call; False if none."""
        job = next((each for each in self.jobs.values() if each.record == record), None)
        if job is None:
            return False
        await self.stop(job.id, USER)
        self.told.append(runtime_message(notes.stopped_by_user(job.id, job.agent, job.brief), "task_stopped",
                                         id=job.id, agent=job.agent, record=job.record))
        return True

    def tell(self, id: str, text: str) -> None:
        self.jobs[id].inbox.put(text)
        self.jobs[id].answered.set()

    def notify(self, text: str) -> None:
        """Tell every running task something from the runtime: no answer to what one of them asked."""
        for job in self.jobs.values():
            job.inbox.put(text)

    async def ask(self, id: str, question: str) -> str:
        """Put a task's question to the main agent, which it wakes, and wait for what it tells the task: its words.
        There is no time limit: the main agent may be asking the user."""
        job = self.jobs[id]
        job.answered.clear()
        self.asked.append((job, question))
        self._changed.set()
        await job.answered.wait()
        return job.answer

    async def stop(self, id: str | None = None, by: str | None = None) -> None:
        """Stop a task, or every task, and wait until they have let go of what they held; `by` is recorded in the
        log's end."""
        jobs = [self.jobs[id]] if id is not None else list(self.jobs.values())
        for job in jobs:
            job.stopped = True
            job.task.cancel(by)
        await asyncio.gather(*(job.task for job in jobs), return_exceptions=True)

    async def wait(self) -> None:
        while not self.news and self.jobs:
            self._changed.clear()
            await self._changed.wait()

    def reports(self) -> list[HumanMessage]:
        """The messages that tasks asked something, ended or failed, once each, after what else waits to be told."""
        asked = [runtime_message(notes.task_asks(job.id, job.agent, question), "task_asked", id=job.id, agent=job.agent)
                 for job, question in self.asked]
        messages = [*self.told, *asked, *[report(job, outcome) for job, outcome in self.ended]]
        self.asked.clear()
        self.ended.clear()
        self.told.clear()
        return messages

    async def status(self) -> HumanMessage | None:
        """The running tasks' state, from the log, for the main agent to answer from rather than guess."""
        if not self.jobs:
            return None
        parts = [
            notes.task_running(job.id, job.agent, time.time() - job.started, job.brief, await job.steps())
            for job in self.jobs.values()
        ]
        return runtime_message("\n\n".join(parts), "task_status", ids=list(self.jobs))
