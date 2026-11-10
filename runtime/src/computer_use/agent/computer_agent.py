"""The Windows desktop agent."""

import re
from collections.abc import Callable, Iterable

from langchain_core.messages import HumanMessage

from computer_use.agent.inbox import SUBAGENT, Inbox
from computer_use.agent.models import MAIN_AGENT, build_chat_model, chosen
from computer_use.agent.review import Verdict, action_records, review_step
from computer_use.agent.subagent import Result, Subagent, TaskContext
from computer_use.agent.trajectory import Trajectory
from computer_use.computers import Computer, ComputerError
from computer_use.config import Approvals
from computer_use.desktop.control import ApprovalFile, Control
from computer_use.desktop.executor import ActionResult, Executor
from computer_use.desktop.judge import ScreenJudge
from computer_use.execution.approvals import MAX_DECLINES
from computer_use.execution.desktop import DesktopExecution
from computer_use.middleware.chat import Mention
from computer_use.middleware.skills import SkillsMiddleware
from computer_use.prompts import notes
from computer_use.prompts.computer import (
    ABOUT, DESKTOP_ASKED, DESKTOP_HANDED, FIRST_SCREEN, LAST_SCREEN, stopped, system_prompt, typed_on,
)
from computer_use.prompts.review import review_context
from computer_use.storage import MAIN
from computer_use.tools.common import image_block
from computer_use.tools.desktop import content


def text_entry_screens(events: Iterable[dict], limit: int = 2) -> list[tuple[int, str]]:
    """Recent full-screen observations before text entry, for the hand-over.

    Typing a filename and clicking Save in one batch otherwise hides the save dialog from the main agent. These are
    records, not proof of what happened afterward. Zooms are cropped and never replace the full screen. Action numbers
    count within the task, as its action summary does.
    """
    screen = None
    number = 0
    checkpoints: list[tuple[int, str]] = []
    for event in events:
        if event.get("agent") == MAIN:
            continue
        if event["type"] == "input":
            blocks = event.get("message", {}).get("data", {}).get("content", [])
            if isinstance(blocks, list):
                for block in blocks:
                    if isinstance(block, dict) and block.get("type") == "image" and block.get("file"):
                        screen = block["file"]
        elif event["type"] == "action":
            number += 1
            typing = event["tool"] == "type" or (
                event["tool"] == "computer_batch"
                and any(step.get("action") == "type" for step in event["args"].get("actions", []))
            )
            if typing and screen:
                checkpoints = [(n, name) for n, name in checkpoints if name != screen]
                checkpoints.append((number, screen))
            if event.get("screenshot") and event["tool"] != "zoom":
                screen = event["screenshot"]
    return checkpoints[-limit:] if limit > 0 else []


class ComputerAgent(Subagent):
    """Desktop agent for one task, with fresh context."""

    agent = "computer"
    name = "computer-use agent"
    about = ABOUT

    def __init__(
        self,
        context: TaskContext,
        log: Trajectory,
        taught: str,
        computer: Computer,
        control: Control,
        approvals: Callable[[], Approvals],
        judge: ScreenJudge | None = None,
    ):
        super().__init__(context, log, taught)
        self.computer = computer
        self.control = control
        self.judge = judge
        # Read per step, so a change the user makes mid-run applies.
        self.approvals = approvals

    async def run(self, task: str, told: Inbox) -> Result:
        """Run a task and capture a final screen for the main agent to check; a desktop failure ends the task with an
        explanation."""
        try:
            reply, after = await self._run(task, told)
        except ComputerError as error:
            self.stop_reason = "error"
            self.log.note(f"Stopped: the desktop could not be used: {error}", "unusable")
            reply, after = "", ActionResult(False, f"No screenshot: {error}")
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
        return stopped(self.stop_reason, self.context.max_steps, MAX_DECLINES)

    async def records(self) -> list[str]:
        """Every action whose input an agent sent in this conversation, this task's included."""
        runs = await self.log.store.runs(self.context.thread)
        return [
            record for each in runs
            for record in action_records(await self.log.store.events(each.id, messages=False))
        ]

    async def _run(self, task: str, told: Inbox) -> tuple[str, ActionResult]:
        def announce(reason: str) -> None:
            url = self.context.settings.web_url
            self.log.note(f"Agent requests a takeover: {reason}\nOpen {url}", "takeoverRequested")

        board = await self.context.blackboard.read(self.task_id)
        today = notes.today(self.context.choices.timezone)
        text = f"{self.opening(task, board)}\n\n{today}"

        async def review(step: str, png: bytes | None) -> Verdict:
            """Auto review by the main agent's model; a named delete or overwrite target must occur in the user's
            messages or the input the agent sent."""
            sent = [message.text for message in told.read(SUBAGENT)]
            context = review_context(text, sent, await self.steps())
            sources = [*self.words(), *sent, *board.requests, *await self.records()]
            settings = self.context.settings
            main = build_chat_model(chosen(settings, MAIN_AGENT, self.context.choices.agents), settings)
            return await review_step(main, context, step, png, sources)

        async with DesktopExecution(
            self.computer, self.control, ApprovalFile(self.context.settings.approval_path), self.log, review,
            lambda: self.approvals() == "auto", announce, self.context.settings.web_url, told, self.judge,
        ) as execution:
            executor = execution.executor
            start = self._start = HumanMessage(content=content(await executor.observe(f"{text}\n\n{FIRST_SCREEN}")))
            await self.log.input(start, "observe")
            choice = chosen(self.context.settings, self.agent, self.context.choices.agents)
            self.log.uses(choice.model, name=self.agent)
            reply = await self.invoke(
                build_chat_model(choice, self.context.settings),
                execution.tools,
                system_prompt(self.context.choices.locale), execution.middleware, start,
                middleware=[SkillsMiddleware(self.agent)],
            )
            return reply, await self._after(executor)

    async def _after(self, executor: Executor) -> ActionResult:
        try:
            return await executor.observe(LAST_SCREEN)
        except ComputerError as error:
            return ActionResult(False, f"No screenshot: {error}")


# "@Computer" anywhere in a message, in any case, as a word of its own: not part of a longer word or of an email
# address (me@computer.org). The page offers it in a list as the user types @.
MENTION = Mention(
    ComputerAgent.agent, re.compile(r"(?<![A-Za-z0-9_])@computer(?![A-Za-z0-9_])", re.IGNORECASE), DESKTOP_ASKED,
    DESKTOP_HANDED,
)
