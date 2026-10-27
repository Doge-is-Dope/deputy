"""Coding tasks in a conversation-specific folder on the isolated code runner.

Each task starts with fresh model context; files persist for later tasks in the
conversation. The main agent checks results from commands and their output."""

from typing import Annotated

from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool, ToolException, tool
from pydantic import Field

from computer_use.agent.inbox import Inbox
from computer_use.agent.middleware import SubagentMiddleware
from computer_use.agent.models import build_chat_model, chosen
from computer_use.agent.subagent import Result, Subagent
from computer_use.agent.trajectory import Trajectory
from computer_use.sandbox import CodeRunner, CodeRunnerError
from computer_use.config import RunChoices, Settings
from computer_use.prompts.coding import (
    ABOUT, BRIEF, CODING_PROMPT, DESCRIPTION, runner_unusable, stopped,
)

# How long one command may run, as Claude Code and Anthropic's computer use demo give a shell command.
RUN_SECONDS = 120



def coding_tools(runner: CodeRunner, thread: str) -> list[BaseTool]:
    """bash and write_file, in the conversation's folder on the code runner."""

    @tool
    async def bash(
        script: Annotated[str, Field(description="The commands, run with bash in your working folder.")],
    ) -> str:
        """Run commands with bash in your working folder; returns the exit code and what they printed, stdout and
        stderr together, cut in the middle when long."""
        try:
            output = await runner.run(thread, script, RUN_SECONDS)
        except ValueError as refused:
            raise ToolException(f"Not executed: {refused}.")
        if output.code is None:
            raise ToolException(f"Stopped: it ran for more than {RUN_SECONDS} seconds. What it printed:\n{output.text}")
        return f"Exit code {output.code}.\n{output.text}"

    @tool
    async def write_file(
        path: Annotated[str, Field(description="A path in your working folder.")],
        content: Annotated[str, Field(description="The file's whole text.")],
    ) -> str:
        """Write a text file in your working folder, replacing any there."""
        try:
            return await runner.write(thread, path, content)
        except ValueError as refused:
            raise ToolException(f"Not executed: {refused}.")

    tools = [bash, write_file]
    for each in tools:  # a refused or failed command is the agent's to hear and work around
        each.handle_tool_error = True
    return tools


class CodingAgent(Subagent):
    """The coding agent of one run: each task starts afresh, in the conversation's folder on the code runner."""

    tool = "write_code"
    agent = "coding"
    name = "coding agent"
    description = DESCRIPTION
    brief = BRIEF
    prompt = ABOUT

    def __init__(
        self,
        settings: Settings,
        runner: CodeRunner,
        log: Trajectory,
        thread: str,
        request: str,
        max_steps: int,
        user: Inbox | None = None,
        choices: RunChoices = RunChoices(),
    ):
        super().__init__(settings, log, thread, request, max_steps, user, choices)
        self.runner = runner

    async def run(self, task: str, told: Inbox) -> Result:
        """Carry out a task. A runner that cannot be reached ends it, and the main agent hears why."""
        self._start = None
        reason = ""
        try:
            start = self._start = HumanMessage(content=await self.opening(task))
            self.log.input(start, "task")
            choice = chosen(self.settings, self.agent, self.choices.agents)
            self.log.uses(choice.model, name=self.agent)
            reply = await self.invoke(
                build_chat_model(choice, self.settings), coding_tools(self.runner, self.thread),
                CODING_PROMPT, SubagentMiddleware(self.log, told), start,
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
