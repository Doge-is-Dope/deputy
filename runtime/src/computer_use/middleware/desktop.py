"""A desktop task's guard: it holds steps that need approval, stops a task that is stuck, declined or disconnected,
waits while the user has control, re-observes after either, and prunes old screenshots."""

from typing import Literal

from langchain.agents.middleware import hook_config
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from computer_use.agent.inbox import SUBAGENT, Inbox
from computer_use.agent.trajectory import Trajectory
from computer_use.desktop.control import Control
from computer_use.desktop.executor import Disconnected, Executor
from computer_use.events import NoteCode
from computer_use.execution.approvals import Confirmations
from computer_use.middleware.common import prune_screenshots
from computer_use.middleware.subagent import SubagentMiddleware
from computer_use.prompts import notes
from computer_use.prompts.computer import DECIDE_AGAIN, disconnected_for, user_had_control
from computer_use.tools.desktop import content

# Why this guard ended a task: its actions kept leaving the screen as it was, the desktop did not reconnect, or the user
# declined MAX_DECLINES of its steps (execution.approvals).
Stop = Literal["stuck", "disconnected", "declined"]


class DesktopMiddleware(SubagentMiddleware):
    """A desktop task's guard. It extends the guard rather than running beside it: what the main agent told it is
    folded into a fresh screen before plain steering would read it, and a held step's refusal is logged by the guard
    like any result. Hooks before the model run in stack order but tool wrappers nest first-outermost, so no order of
    two separate middleware keeps both."""

    def __init__(
        self,
        executor: Executor,
        control: Control,
        log: Trajectory,
        web_url: str,  # where the user watches and takes over
        confirm: Confirmations,
        inbox: Inbox,
    ):
        super().__init__(log, inbox)
        self.executor = executor
        self.control = control
        self.web_url = web_url
        self.confirm = confirm

    @hook_config(can_jump_to=["end"])
    async def abefore_model(self, state, runtime) -> dict | None:
        """End a task that is stuck or whose steps the user keeps declining. Wait for the desktop, then while the user
        has control; after either, hand the model a fresh screen with what the main agent told it meanwhile. The
        desktop comes first: one that does not reconnect ends the task whoever has control. Once the user hands
        control back, wait for the desktop again: it may have gone meanwhile."""
        if self.executor.stuck:
            return await self.stop(f"Stopped: the last {self.executor.repeats} actions did not change the screen.", "stuck",
                             count=self.executor.repeats)
        if self.confirm.exhausted:
            return await self.stop(f"Stopped: the user declined {self.confirm.declined} of its steps.", "declined",
                             count=self.confirm.declined)
        changes: list[str] = []
        try:
            lost = await self.reconnect(changes)
            if self.control.read().owner == "user":
                self.log.note(
                    f"The user has control. Return it on {self.web_url} or run `computer-use return`.",
                    "userControl",
                )
            held = await self.control.wait_for_agent()
            if held is not None:
                self.log.note(f"Control returned after {held:.0f}s; re-observing.", "controlReturned", seconds=held)
                changes.append(user_had_control(held))
                lost = await self.reconnect(changes) or lost
        except Disconnected as gone:
            return await self.stop(f"Stopped: {gone}.", "disconnected", seconds=gone.seconds)
        if not changes:
            return await super().abefore_model(state, runtime)
        sent = self.inbox.take(SUBAGENT)
        self.executor.clear_unchanged()
        note = " ".join([*changes, DECIDE_AGAIN])
        if sent:
            note = f"{notes.told([each.text for each in sent])}\n\n{note}"
        message = HumanMessage(content=content(await self.executor.observe(note)))
        await self.log.input(message, "reconnected" if lost else "returned")
        return {"messages": [message]}

    async def reconnect(self, changes: list[str]) -> bool:
        """Wait for a disconnected desktop to come back, saying so in the log and in `changes`; whether it was gone.
        Disconnected if it is not back in time."""
        if (await self.executor.computer.status()).connected:
            return False
        self.log.note("The desktop is disconnected; waiting for it to reconnect.", "disconnected")
        # Back already between the two looks: gone for no time, but the line the log opened still closes.
        lost = await self.executor.wait_for_connection() or 0.0
        self.log.note(f"The desktop reconnected after {lost:.0f}s; re-observing.", "reconnected", seconds=lost)
        changes.append(disconnected_for(lost))
        return True

    async def stop(self, summary: str, reason: Stop, **data) -> dict:
        """End the task, its transcript closed by the runtime's message.
        The message is the runtime's, not the agent's: the task has no reply."""
        self.stopped = reason
        codes: dict[Stop, NoteCode] = {"stuck": "stuck", "disconnected": "gone", "declined": "declined"}
        self.log.note(summary, codes[reason], **data)
        message = AIMessage(content=summary)
        await self.log.input(message, reason)
        return {"messages": [message], "jump_to": "end"}

    async def awrap_model_call(self, request, handler):
        pruned = request.override(messages=prune_screenshots(request.messages))
        return await super().awrap_model_call(pruned, handler)

    async def held(self, request) -> ToolMessage | None:
        """A step that needs the user's approval runs only once they give it; a refusal is its result, logged in its
        place like any other."""
        return await self.confirm.check(request)
