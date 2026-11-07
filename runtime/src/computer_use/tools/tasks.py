"""The main agent's task tools: hand a task over to an agent, tell it something while it runs, stop it."""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Annotated, Literal

from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool, tool
from pydantic import Field, WithJsonSchema

from computer_use.agent.background import MAX_TASKS, Background
from computer_use.agent.inbox import Inbox
from computer_use.prompts import notes
from computer_use.prompts.main import AGENT, BRIEF, TITLE, start_task
from computer_use.storage import MAIN
from computer_use.tools.common import CallId, not_executed

START_TASK = "start_task"
TELL_TASK = "tell_task"
STOP_TASK = "stop_task"
RULES = "The ids of the remembered rules that apply to this task, for its agent to follow; none if none apply."


@dataclass(frozen=True)
class TaskTool:
    """An agent start_task hands tasks to: its name, its line in the tool's description, and what starts its task
    (its title, the task, the ids of the rules it follows and the call's id in; the call's result out)."""

    agent: str
    about: str
    start: Callable[[str, str, list[str], str], Awaitable[str | ToolMessage]]


def handover_tools(
    tasks: Sequence[TaskTool], background: Background, user: Inbox, *, with_rules: bool = False
) -> list[BaseTool]:
    """start_task, which hands work over to these agents in the background, and the tools that tell or stop it while it
    runs."""
    tools = [handover_tool(tasks, with_rules=with_rules)]

    @tool(TELL_TASK)
    def tell_task(
        task_id: Annotated[str, Field(description="The task's id, as handing it over returned it.")],
        message: Annotated[str, Field(description="What changes, in your words.")],
        *,
        call_id: CallId,
    ) -> str | ToolMessage:
        """Tell a running background task something, such as what the user changed. It reads it before its next
        step, along with what the user said since it last heard from them, word for word. The call ends your turn, as
        start_task does, so say what you need to say with it."""
        job = background.jobs.get(task_id)
        if job is None:
            return not_executed({"id": call_id, "name": TELL_TASK}, notes.no_task(task_id), "noTask")
        said = [sent.text for sent in user.read(MAIN)[job.heard:]]
        job.heard += len(said)
        background.tell(task_id, message + notes.since_heard(said))
        return notes.TOLD

    @tool(STOP_TASK)
    async def stop_task(
        task_id: Annotated[str, Field(description="The task's id, as handing it over returned it.")],
        *,
        call_id: CallId,
    ) -> str | ToolMessage:
        """Stop a running background task. It stops at once; whatever its current step was doing may or may not have
        happened."""
        if task_id not in background.jobs:
            return not_executed({"id": call_id, "name": STOP_TASK}, notes.no_task(task_id), "noTask")
        await background.stop(task_id)
        return notes.TASK_STOPPED_BY_YOU

    tools += [tell_task, stop_task]
    for each in tools:  # a refused call reaches the main agent as a failed call, not a failed run
        each.handle_tool_error = True
    return tools


def handover_tool(tasks: Sequence[TaskTool], *, with_rules: bool) -> BaseTool:
    """start_task, for these agents; `with_rules`, it also takes the ids of the remembered rules that apply."""
    starts = {each.agent: each.start for each in tasks}
    # An enum even for one agent, as for several: a single choice would come out as a const.
    Agent = Annotated[Literal[tuple(starts)], WithJsonSchema({"type": "string", "enum": list(starts)})]

    async def hand_task(
        agent: Annotated[Agent, Field(description=AGENT)],
        title: Annotated[str, Field(description=TITLE)],
        task: Annotated[str, Field(description=BRIEF)],
        *,
        call_id: CallId,
    ) -> str | ToolMessage:
        return await starts[agent](title, task, [], call_id)

    async def hand_task_with_rules(
        agent: Annotated[Agent, Field(description=AGENT)],
        title: Annotated[str, Field(description=TITLE)],
        task: Annotated[str, Field(description=BRIEF)],
        rules: Annotated[list[str] | None, Field(description=RULES)] = None,
        *,
        call_id: CallId,
    ) -> str | ToolMessage:
        return await starts[agent](title, task, rules or [], call_id)

    handing = hand_task_with_rules if with_rules else hand_task
    description = start_task(MAX_TASKS, [(each.agent, each.about) for each in tasks])
    return tool(START_TASK, description=description)(handing)
