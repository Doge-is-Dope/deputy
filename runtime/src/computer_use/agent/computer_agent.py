"""The Windows desktop agent."""

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass

from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool

from computer_use.agent.background import Refusal
from computer_use.agent.inbox import SUBAGENT, Inbox
from computer_use.agent.models import MAIN_AGENT, build_chat_model, chosen
from computer_use.agent.review import Verdict, action_records, review_step
from computer_use.agent.subagent import Result, Subagent, TaskContext
from computer_use.agent.trajectory import Trajectory
from computer_use.computers import Computer, ComputerError
from computer_use.config import Approvals
from computer_use.desktop.control import ApprovalFile, Control, DesktopBusy, RunLock, release_input
from computer_use.desktop.executor import ActionResult, Executor
from computer_use.desktop.judge import ScreenJudge
from computer_use.middleware.approvals import MAX_DECLINES, Confirmations
from computer_use.middleware.chat import Mention
from computer_use.middleware.desktop import DesktopMiddleware
from computer_use.middleware.skills import SkillsMiddleware
from computer_use.native.execution import Commands
from computer_use.native.lease import WindowsTools
from computer_use.prompts import notes
from computer_use.prompts.computer import (
    ABOUT, DESKTOP_ASKED, DESKTOP_BUSY, DESKTOP_HANDED, FIRST_SCREEN, LAST_SCREEN, computer_in_use, desktop_offline,
    SYSTEM_PROMPT, stopped, typed_on,
)
from computer_use.prompts.review import review_context
from computer_use.storage import MAIN
from computer_use.tools.common import image_block
from computer_use.tools.desktop import content, desktop_tools, takeover_tool
from computer_use.tools.native import command_tools


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
        windows: WindowsTools | None = None,
    ):
        super().__init__(context, log, taught)
        self.computer = computer
        self.control = control
        self.judge = judge
        self.windows = windows if context.choices.commands else None
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
        screens = []
        if self._start is not None:
            for number, filename in text_entry_screens(await self.events_since(self._start)):
                try:
                    png = await self.log.store.get_file(self.log.run, filename)
                except FileNotFoundError:
                    continue
                screens += [{"type": "text", "text": typed_on(number)}, image_block(png)]
        screens.append({"type": "text", "text": after.text})
        if after.frame is not None:
            screens.append(image_block(after.frame.png))
        return await self.result(reply, content=screens)

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

        executor = Executor(self.computer, self.control, self.judge)  # fresh for each task, so nothing carries over
        tools, guard = self._equipped(executor, told, review)
        try:
            if self.windows is not None:
                await self.windows.ensure()
            start = self._start = HumanMessage(content=content(await executor.observe(f"{text}\n\n{FIRST_SCREEN}")))
            await self.log.input(start, "observe")
            choice = chosen(self.context.settings, self.agent, self.context.choices.agents)
            self.log.uses(choice.model, name=self.agent)
            reply = await self.invoke(
                build_chat_model(choice, self.context.settings),
                tools,
                SYSTEM_PROMPT, guard, start,
                middleware=[SkillsMiddleware(self.agent)],
            )
            return reply, await self._after(executor)
        finally:  # let go of whatever the task left held down, after its last screen
            await release_input(self.control, self.computer, "agent")

    def _equipped(
        self, executor: Executor, told: Inbox, review: Callable[[str, bytes | None], Awaitable[Verdict]],
    ) -> tuple[list[BaseTool], DesktopMiddleware]:
        """A task's tools, and the guard that holds, stops and re-observes around them."""
        settings = self.context.settings
        confirm = Confirmations(ApprovalFile(settings.approval_path), self.control, executor, self.log, review,
                                lambda: self.approvals() == "auto")
        commands = command_tools(Commands(self.windows, executor)) if self.windows else []

        def announce(reason: str) -> None:
            self.log.note(f"Agent requests a takeover: {reason}\nOpen {settings.web_url}", "takeoverRequested")

        tools = [*desktop_tools(executor), *commands, takeover_tool(self.control, self.computer, announce)]
        return tools, DesktopMiddleware(executor, self.control, self.log, settings.web_url, confirm, told)

    async def _after(self, executor: Executor) -> ActionResult:
        try:
            return await executor.observe(LAST_SCREEN)
        except ComputerError as error:
            return ActionResult(False, f"No screenshot: {error}")


@dataclass(frozen=True)
class DesktopResource:
    """The desktop a task holds while it runs: a hand-over starts it only while the computer is free and connected,
    and the task keeps the run lock until it ends."""

    computer: Computer
    lock: RunLock

    def in_use(self, task: str) -> Refusal:
        return computer_in_use(task), "computerInUse"

    async def unavailable(self) -> Refusal | None:
        status = await self.computer.status()
        return None if status.connected else (desktop_offline(status.detail), "disconnected")

    def acquire(self, run: str) -> Refusal | None:
        if self.lock.held:  # a message for the desktop took it as its run began
            return None
        try:
            self.lock.acquire(run)
        except DesktopBusy:
            return DESKTOP_BUSY, "desktopBusy"
        return None

    def taken_by(self, run: str) -> None:
        self.lock.name(run)

    def release(self) -> None:
        if self.lock.held:
            self.lock.release()


# A message sent to the desktop (the API's `computer`, as the CLI's run sends it) goes to the computer agent.
MENTION = Mention(ComputerAgent.agent, DESKTOP_ASKED, DESKTOP_HANDED)
