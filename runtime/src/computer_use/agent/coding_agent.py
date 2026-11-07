"""Coding tasks in the conversation's folder on the isolated code runner; files persist across its tasks."""

from langchain_core.messages import HumanMessage

from computer_use.agent.inbox import Inbox
from computer_use.middleware.skills import SkillsMiddleware
from computer_use.middleware.subagent import SubagentMiddleware
from computer_use.agent.models import build_chat_model, chosen
from computer_use.agent.subagent import Result, Subagent
from computer_use.agent.trajectory import Trajectory
from computer_use.sandbox import CodeRunner, CodeRunnerError
from computer_use.tools.coding import coding_tools
from computer_use.config import RunChoices, Settings
from computer_use.prompts.coding import ABOUT, CODING_PROMPT, runner_unusable, stopped


class CodingAgent(Subagent):
    """The coding agent of one task, with fresh model context."""

    agent = "coding"
    name = "coding agent"
    about = ABOUT

    def __init__(
        self,
        settings: Settings,
        runner: CodeRunner,
        log: Trajectory,
        thread: str,
        session: str,
        request: str,
        max_steps: int,
        user: Inbox,
        choices: RunChoices,
        taught: str,
    ):
        super().__init__(settings, log, thread, session, request, max_steps, user, choices, taught)
        self.runner = runner

    async def run(self, task: str, told: Inbox) -> Result:
        reason = ""
        try:
            start = self._start = HumanMessage(content=await self.opening(task))
            await self.log.input(start, "task")
            choice = chosen(self.settings, self.agent, self.choices.agents)
            self.log.uses(choice.model, name=self.agent)
            reply = await self.invoke(
                build_chat_model(choice, self.settings), coding_tools(self.runner, self.thread, self.log.run),
                CODING_PROMPT, SubagentMiddleware(self.log, told), start, middleware=[SkillsMiddleware(self.agent)],
            )
        except CodeRunnerError as error:
            self.stop_reason = "error"
            self.log.note(f"Stopped: the code runner could not be used: {error}", "runnerUnusable")
            reply, reason = "", runner_unusable(error)
        actions = await self.steps()
        result = [{"type": "text", "text": self.report(reply, actions, reason)}]
        return result, {"stop_reason": self.stop_reason, "reply": reply, "actions": actions}

    def how(self) -> str:
        return stopped(self.stop_reason, self.max_steps)
