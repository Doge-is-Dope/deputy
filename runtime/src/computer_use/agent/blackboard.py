"""The conversation as the agents of its tasks read it: the plan, the tasks at work and what was done so far."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from computer_use.agent.history import tasks, user_messages
from computer_use.agent.plan import Plan
from computer_use.agent.trajectory import Trajectory
from computer_use.events import PlanStep
from computer_use.prompts import notes
from computer_use.storage import TURN, RunSummary, Runs


class Tasks(Protocol):
    """A session's running tasks, as far as the blackboard goes."""

    def on_steps(self) -> dict[str, list[str]]: ...  # their ids, by the plan's step they were handed
    def at_work(self) -> list[dict]: ...  # each one's id, agent, title and steps
    async def ask(self, id: str, question: str) -> str: ...  # put to the main agent; its answer, once it gave one


@dataclass(frozen=True)
class Board:
    """The conversation as one task reads it: the user's messages before this session's, every task that has ended, this
    session's included, the plan and the tasks at work."""

    reader: str
    requests: list[str]
    tasks: list[dict]
    plan: Sequence[PlanStep] = ()
    running: Sequence[dict] = ()

    @property
    def text(self) -> str:
        parts = (notes.plan_on_board(self.plan, self.reader), notes.others_at_work(self.running, self.reader),
                 notes.blackboard(self.requests, self.tasks))
        return "\n\n".join(part for part in parts if part)


@dataclass
class Blackboard:
    """A session's view of its conversation."""

    store: Runs
    thread: str
    session: str
    plan: Plan
    tasks: Tasks
    finished: dict[str, tuple[list[str], list[dict]]] = field(default_factory=dict)  # what a turn that ended holds

    async def read(self, reader: str) -> Board:
        """The board as task `reader` reads it now."""
        requests, ended = [], []
        for summary in await self.store.runs(self.thread):
            if summary.kind == TURN:
                said, done = self.finished.get(summary.id) or await self.turn(summary)
                requests += said
                ended += done
        return Board(reader, requests, ended, self.plan.view(self.tasks.on_steps()), self.tasks.at_work())

    async def turn(self, summary: RunSummary) -> tuple[list[str], list[dict]]:
        events = await self.store.events(summary.id)
        other_session = bool(events) and events[0]["type"] == "start" and events[0]["session"] != self.session
        read = user_messages(events) if other_session else [], tasks(events)
        if summary.ended is not None:
            self.finished[summary.id] = read
        return read

    def show(self, log: Trajectory) -> None:
        """Log the plan as it stands, for the page; a conversation without one logs nothing."""
        if self.plan.steps:
            log.plan(self.plan.snapshot(self.tasks.on_steps()))
