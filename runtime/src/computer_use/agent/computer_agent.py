"""Windows desktop agent with per-task context, approvals and result screenshots."""

from collections.abc import Callable

from langchain_core.messages import HumanMessage

from computer_use.agent.confirm import MAX_DECLINES, Confirmations
from computer_use.agent.inbox import SUBAGENT, Inbox
from computer_use.agent.middleware import ComputerAgentMiddleware
from computer_use.agent.models import MAIN_AGENT, build_chat_model, chosen
from computer_use.agent.review import Verdict, review_step
from computer_use.agent.subagent import Result, Subagent
from computer_use.agent.tools import content, desktop_tools, image_block, takeover_tool
from computer_use.agent.trajectory import Trajectory
from computer_use.computers import Computer, ComputerError
from computer_use.config import Approvals, RunChoices, Settings
from computer_use.desktop.control import ApprovalFile, Control, release_input
from computer_use.desktop.executor import ActionResult, Executor
from computer_use.agent.history import text_entry_screens
from computer_use.prompts import notes
from computer_use.prompts.computer import (
    ABOUT, BRIEF, DESCRIPTION, FIRST_SCREEN, LAST_SCREEN, stopped, system_prompt, typed_on,
)
from computer_use.prompts.review import review_context

class ComputerAgent(Subagent):
    """Desktop agent for one run, initialized lazily; each task gets fresh context."""

    tool = "computer_use"
    agent = "computer"
    name = "computer-use agent"
    uses_computer = True
    description = DESCRIPTION
    brief = BRIEF
    prompt = ABOUT

    def __init__(
        self,
        settings: Settings,
        computer: Computer,
        control: Control,
        log: Trajectory,
        thread: str,
        request: str,
        max_steps: int,
        user: Inbox | None = None,
        choices: RunChoices = RunChoices(),
        approvals: Callable[[], Approvals] | None = None,
    ):
        super().__init__(settings, log, thread, request, max_steps, user, choices)
        self.computer = computer
        self.control = control
        # How a step that needs approval is answered as it comes up: as the user chose last, while the run works.
        self.approvals = approvals or (lambda: choices.approvals)
        self.executor: Executor | None = None  # made with the first task

    async def run(self, task: str, told: Inbox) -> Result:
        """Run a task and capture a final screen for the main agent to check.

        Desktop failures end the task with an explanation. Always release held input
        when the task ends or is cancelled."""
        self._start = None
        try:
            try:
                reply = await self._run(task, told)
                after = await self._after()
            except ComputerError as error:
                self.stop_reason = "error"
                self.log.note(f"Stopped: the desktop could not be used: {error}", "unusable")
                reply, after = "", ActionResult(False, f"No screenshot: {error}")
        finally:
            if self.executor is not None:
                await release_input(self.control, self.computer, "agent")
        actions = await self.steps()
        result = [{"type": "text", "text": self.report(reply, actions)}]
        if self._start is not None:
            for number, filename in text_entry_screens(await self.events_since(self._start)):
                try:
                    png = await self.log.store.get_file(self.log.run, filename)
                except FileNotFoundError:
                    continue
                result.extend([{"type": "text", "text": typed_on(number)}, image_block(png)])
        result.append({"type": "text", "text": after.text})
        if after.frame is not None:
            result.append(image_block(after.frame.png))
        # The artifact, which the model does not see, keeps the task's parts for the blackboard of later tasks.
        return result, {"stop_reason": self.stop_reason, "reply": reply, "actions": actions}

    def how(self) -> str:
        return stopped(self.stop_reason, self.max_steps, MAX_DECLINES)

    async def _run(self, task: str, told: Inbox) -> str:
        if self.executor is None:
            self.executor = Executor(self.computer, self.control, self.settings)
        executor = self.executor
        executor.clear_unchanged()  # an earlier task's actions that changed nothing do not count against this one

        def announce(reason: str) -> None:
            self.log.note(f"Agent requests a takeover: {reason}\nOpen {self.settings.web_url}", "takeoverRequested")

        requests, earlier = await self.earlier()
        board = notes.blackboard(requests, earlier)
        text = f"{notes.opening(task, self.words(), board, self.taught)}\n\n{notes.today(self.choices.timezone)}"

        async def review(step: str, png: bytes | None) -> Verdict:
            """Auto review of a step, by the main agent's model, given what this agent was given and did since, and
            what the user sent meanwhile; the name it gives for what the step deletes or overwrites must be written in
            the user's messages or the input the agent sent."""
            sent = [message.text for message in told.read(SUBAGENT)]
            context = review_context(text, sent, await self.steps())
            sources = [*self.words(), *sent, *requests, *await self.records()]
            main = build_chat_model(chosen(self.settings, MAIN_AGENT, self.choices.agents), self.settings)
            return await review_step(main, context, step, png, sources)

        confirm = Confirmations(
            ApprovalFile(self.settings.approval_path), self.control, executor, self.log,
            review, lambda: self.approvals() == "auto",
        )
        guard = ComputerAgentMiddleware(executor, self.control, self.log, self.settings.web_url, confirm, told)
        start = self._start = HumanMessage(content=content(await executor.observe(f"{text}\n\n{FIRST_SCREEN}")))
        self.log.input(start, "observe")
        choice = chosen(self.settings, self.agent, self.choices.agents)
        self.log.uses(choice.model, name=self.agent)
        return await self.invoke(
            build_chat_model(choice, self.settings),
            [*desktop_tools(executor), takeover_tool(self.control, announce)],
            system_prompt(self.choices.locale), guard, start,
        )

    async def _after(self) -> ActionResult:
        try:
            return await self.executor.observe(LAST_SCREEN)
        except ComputerError as error:
            return ActionResult(False, f"No screenshot: {error}")
