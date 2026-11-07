"""Starts a task in the background when the main agent hands one over to an agent."""

import asyncio
import contextlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage

from computer_use.agent.background import MAX_TASKS, Background, Resource
from computer_use.agent.inbox import Inbox
from computer_use.agent.subagent import MakeAgent, Subagent
from computer_use.agent.trajectory import Trajectory
from computer_use.prompts import notes
from computer_use.storage import MAIN
from computer_use.tools.common import not_executed
from computer_use.tools.tasks import START_TASK, TaskTool

ENDED, STOPPED, FAILED = "ended", "stopped", "error"


@dataclass(frozen=True)
class Handed:
    """The rules a task is handed over with: word for word for its agent, by id and text for its log."""

    text: str = ""
    rules: Sequence[dict[str, str]] = ()


class SessionMemory(Protocol):
    """What a session remembers for its user, as far as its agents need."""

    async def recall(self) -> bool: ...  # once, as the session begins: whether it has rules to hand over
    def middleware(self, run: str) -> list[AgentMiddleware]: ...  # around the main agent's calls in this turn
    async def hand(self, ids: list[str]) -> Handed: ...  # the rules a task goes with, each counted as used


def task_tool(
    kind: type[Subagent], make: MakeAgent, background: Background, user: Inbox, turn: Callable[[], Trajectory],
    session: str, thread: str, memory: SessionMemory | None = None, resource: Resource | None = None,
) -> TaskTool:
    """`kind`'s part of start_task. Tasks that need a `resource` run one at a time and hold it, under their log's name,
    until they end. `memory` supplies the remembered rules a task is handed over with, by id."""

    async def start(title: str, task: str, rules: list[str], call_id: str) -> str | ToolMessage:
        # One hand-over at a time: what refuses one is decided before its log exists, as the one before left things.
        async with background.starting:
            return await begin(title, task, rules, call_id)

    async def begin(title: str, task: str, rules: list[str], call_id: str) -> str | ToolMessage:
        call = {"id": call_id, "name": START_TASK}
        if resource is not None and (using := background.working(kind.agent)) is not None:
            return not_executed(call, *resource.in_use(using.id))
        if background.full:
            return not_executed(call, notes.full(MAX_TASKS), "tooManyTasks")
        if resource is not None and (refused := await resource.unavailable()) is not None:
            return not_executed(call, *refused)
        parent = turn()
        if resource is not None and (refused := resource.acquire(parent.run)) is not None:
            return not_executed(call, *refused)
        log = await Trajectory.open(parent.store, parent.listeners)
        handed = await memory.hand(rules) if memory is not None and rules else Handed()
        log.start_task(thread, session, parent.run, background.number(), kind.agent, task, title)
        if resource is not None:
            resource.taken_by(log.run)

        worker = make(log, handed.text)

        async def work(id: str, told: Inbox):
            if handed.rules:  # the page shows them in the task
                log.note(notes.following(len(handed.rules)), "memoryUsed", rules=list(handed.rules))
            ending, reply, by = FAILED, "", None
            try:
                result = await worker.run(task, told)
                ending, reply = ENDED, result[1].get("reply", "")
                return result
            except asyncio.CancelledError as stop:
                ending, by = STOPPED, next(iter(stop.args), None)
                raise
            finally:
                background.latest[kind.agent] = worker.stop_reason  # for the turn's end
                log.end(ending, reply, worker.stop_reason, by=by)
                with contextlib.suppress(Exception):  # the stop or error is what to tell; the store logs its own
                    await log.store.flush(log.run)
                if resource is not None:
                    resource.release()

        return notes.started(background.start(
            kind.agent, task, work, worker.steps, turn=parent, record=log.run, heard=len(user.read(MAIN)),
            title=title,
        ))

    return TaskTool(kind.agent, kind.about, start)
