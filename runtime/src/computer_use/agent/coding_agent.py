"""Coding tasks in the conversation's folder on the isolated code runner; files persist across its tasks."""

from langchain_core.messages import HumanMessage

from computer_use.agent.inbox import Inbox
from computer_use.middleware.skills import SkillsMiddleware
from computer_use.middleware.subagent import SubagentMiddleware
from computer_use.agent.models import build_chat_model, chosen
from computer_use.agent.subagent import Result, Subagent, TaskContext
from computer_use.agent.trajectory import Trajectory
from computer_use.sandbox import CodeRunner, CodeRunnerError
from computer_use.tools.coding import Attached, coding_tools
from computer_use.prompts.coding import ABOUT, CODING_PROMPT, working_folder, runner_unusable, stopped


class CodingAgent(Subagent):
    """The coding agent of one task, with fresh model context."""

    agent = "coding"
    name = "coding agent"
    about = ABOUT

    def __init__(self, context: TaskContext, log: Trajectory, taught: str, runner: CodeRunner, attached: Attached):
        super().__init__(context, log, taught)
        self.runner, self.attached = runner, attached

    async def run(self, task: str, told: Inbox) -> Result:
        reason = ""
        try:
            if not (status := await self.runner.status()).connected:  # down as it starts: nothing to try
                raise CodeRunnerError(status.detail)
            await self.attached.place()
            opening = self.opening(task, await self.context.blackboard.read(self.task_id))
            folder = f"/workspace/{self.context.thread}"
            start = HumanMessage(content=f"{opening}\n\n{working_folder(folder)}")
            await self.log.input(start, "task")
            self._start = start
            choice = chosen(self.context.settings, self.agent, self.context.choices.agents)
            self.log.uses(choice.model, name=self.agent)
            reply = await self.invoke(
                build_chat_model(choice, self.context.settings),
                coding_tools(self.runner, self.context.thread, self.log.run),
                CODING_PROMPT, SubagentMiddleware(self.log, told), start, middleware=[SkillsMiddleware(self.agent)],
            )
        except CodeRunnerError as error:
            self.stop_reason = "error"
            self.log.note(f"Stopped: the code runner could not be used: {error}", "runnerUnusable")
            reply, reason = "", runner_unusable(error)
        return await self.result(reply, reason)

    def how(self) -> str:
        return stopped(self.stop_reason, self.context.max_steps)
