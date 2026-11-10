"""The plan's tools: the main agent writes it; its tasks' agents read the blackboard, report steps done and ask."""

from collections.abc import Callable
from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool, ToolException, tool
from pydantic import BaseModel, Field

from computer_use.agent.blackboard import Blackboard
from computer_use.agent.inbox import SUBAGENT, Inbox
from computer_use.agent.plan import Plan, PlanError, Step
from computer_use.agent.trajectory import Trajectory
from computer_use.prompts import notes
from computer_use.prompts.main import (
    ASK_QUESTION_TO_MAIN, ASK_TOOL, FINISH_STEP_TOOL, FINISHED_STEPS, PLAN_STEPS, READ_BLACKBOARD_TOOL, STEP_DONE,
    STEP_DONE_WHEN, STEP_ID, STEP_NEEDS, STEP_REOPEN, STEP_TITLE, WRITE_PLAN_TOOL,
)
from computer_use.tools.common import CallId

WRITE_PLAN = "write_plan"
READ_BLACKBOARD = "read_blackboard"
FINISH_STEP = "finish_step"
ASK = "ask"


class PlannedStep(BaseModel):
    id: Annotated[str, Field(description=STEP_ID)]
    title: Annotated[str, Field(description=STEP_TITLE)]
    done_when: Annotated[str, Field(description=STEP_DONE_WHEN)] = ""
    needs: Annotated[list[str], Field(description=STEP_NEEDS)] = []
    done: Annotated[bool, Field(description=STEP_DONE)] = False
    reopen: Annotated[bool, Field(description=STEP_REOPEN)] = False


def plan_tool(plan: Plan, written: Callable[[bool], None]) -> BaseTool:
    """write_plan, on `plan`; `written` is told, once it has changed, whether its steps were revised."""

    # Async, as the plan's tools all are: a plain function runs on a worker thread, and logs are written on the loop.
    @tool(WRITE_PLAN, description=WRITE_PLAN_TOOL)
    async def write_plan(steps: Annotated[list[PlannedStep], Field(description=PLAN_STEPS)]) -> str:
        before = plan.steps
        try:
            plan.write(
                [Step(step.id, step.title, step.done_when, tuple(step.needs)) for step in steps],
                finished=[step.id for step in steps if step.done],
                reopened=[step.id for step in steps if step.reopen],
            )
        except PlanError as error:
            raise ToolException(str(error)) from error
        written(bool(before) and plan.steps != before)
        return notes.PLAN_WRITTEN

    write_plan.handle_tool_error = True
    return write_plan


def task_tools(board: Blackboard, task_id: str, told: Inbox, log: Trajectory) -> list[BaseTool]:
    """What every task's agent has of the plan. `told` is the task's inbox, where the main agent's answer arrives."""

    @tool(READ_BLACKBOARD, description=READ_BLACKBOARD_TOOL)
    async def read_blackboard() -> str:
        return (await board.read(task_id)).text or notes.EMPTY_BOARD

    @tool(FINISH_STEP, description=FINISH_STEP_TOOL)
    async def finish_step(steps: Annotated[list[str], Field(description=FINISHED_STEPS)]) -> str:
        unknown = board.plan.finish(steps)
        board.show(log)
        return notes.steps_finished(unknown)

    @tool(ASK, description=ASK_TOOL)
    async def ask(
        question: Annotated[str, Field(min_length=1, description=ASK_QUESTION_TO_MAIN)], *, call_id: CallId,
    ) -> ToolMessage:
        answer = await board.tasks.ask(task_id, question)
        heard = "\n\n".join(message.text for message in told.take(SUBAGENT))  # with what the user said, for the agent
        return ToolMessage(content=heard, tool_call_id=call_id, name=ASK, artifact={"answer": answer})

    return [read_blackboard, finish_step, ask]
