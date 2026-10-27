"""Subagent turn handling: steering and message logging.

Desktop tasks also handle approvals, takeover, reconnection and screenshot
pruning. Input validation and dispatch belong to desktop.executor."""

import asyncio
from typing import Literal

from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from computer_use.agent.confirm import Confirmations
from computer_use.agent.inbox import SUBAGENT, Inbox
from computer_use.agent.tools import content, image_blocks
from computer_use.agent.trajectory import Trajectory, is_image
from computer_use.desktop.control import Control
from computer_use.desktop.executor import Disconnected, Executor
from computer_use.events import NoteCode
from computer_use.prompts import notes
from computer_use.prompts.computer import DECIDE_AGAIN, disconnected_for, user_had_control


# Why this middleware ended a task: its actions kept leaving the screen as it was, the desktop did not reconnect, or
# the user declined MAX_DECLINES of its steps.
Stop = Literal["stuck", "disconnected", "declined"]

# Prune old screenshots in batches to preserve prompt-cache reuse between prunes.
# Keep between KEEP_SCREENSHOTS and KEEP_SCREENSHOTS + PRUNE_EVERY - 1 images.
KEEP_SCREENSHOTS = 3
PRUNE_EVERY = 5
REMOVED_SCREENSHOT = {"type": "text", "text": "[earlier screenshot removed]"}


def pruned(carrying: int, keep: int, every: int = 1) -> int:
    """How many of the oldest `carrying` messages with images lose them: `every` at a time, keeping at least `keep`."""
    return (carrying - keep) // every * every if carrying > keep else 0


def without_screenshots(message):
    """The message with each of its images replaced by a note that it was removed."""
    blocks = [REMOVED_SCREENSHOT if is_image(block) else block for block in message.content]
    return message.model_copy(update={"content": blocks})


def prune_screenshots(messages: list, keep: int, every: int = 1) -> list:
    """Remove images from the oldest messages that carry them, `every` messages at a time, keeping at least `keep`."""
    result = list(messages)
    carrying = [index for index, message in enumerate(result) if image_blocks(message)]
    for index in carrying[:pruned(len(carrying), keep, every)]:
        result[index] = without_screenshots(result[index])
    return result


def read_before_ending(message: AIMessage, inbox: Inbox) -> dict | None:
    """Send an ending reply back to the model if steering messages remain unread."""
    if not message.tool_calls and inbox.unread(SUBAGENT):
        return {"jump_to": "model"}
    return None


class SubagentMiddleware(AgentMiddleware):
    """An agent's turns on a task: what the main agent tells it, read before its next model call and before it ends;
    and every message logged as it arrives."""

    def __init__(self, log: Trajectory, inbox: Inbox | None = None):
        super().__init__()
        self.log = log
        self.inbox = inbox if inbox is not None else Inbox()
        self.last: AIMessage | None = None  # the agent's own latest turn; the closing messages below are not its own
        self.stopped: Stop | None = None  # why this middleware ended the task, if it did

    async def abefore_model(self, state, runtime) -> dict | None:
        sent = self.inbox.take(SUBAGENT)
        if not sent:
            return None
        message = HumanMessage(content=notes.told([each.text for each in sent]))
        self.log.input(message, "message")
        return {"messages": [message]}

    @hook_config(can_jump_to=["model"])
    async def aafter_model(self, state, runtime) -> dict | None:
        message = state["messages"][-1]
        if isinstance(message, AIMessage):
            self.last = message
            self.log.model(message)
            return read_before_ending(message, self.inbox)
        return None

    async def awrap_model_call(self, request, handler):
        try:
            return await handler(request)
        except asyncio.CancelledError:
            self.log.cut()
            raise

    async def awrap_tool_call(self, request, handler):
        result = await self.held(request) or await handler(request)
        self.log.action(request.tool_call, result)
        return result

    async def held(self, request) -> ToolMessage | None:
        """Why the call must not run yet, as its result, or None once it may: no call is held here."""
        return None


class ComputerAgentMiddleware(SubagentMiddleware):
    def __init__(
        self,
        executor: Executor,
        control: Control,
        log: Trajectory,
        web_url: str,  # where the user watches and takes over
        confirm: Confirmations,
        inbox: Inbox | None = None,
    ):
        super().__init__(log, inbox)
        self.executor = executor
        self.control = control
        self.web_url = web_url
        self.confirm = confirm

    @hook_config(can_jump_to=["end"])
    async def abefore_model(self, state, runtime) -> dict | None:
        """End a task whose actions keep leaving the screen as it was, or whose steps the user keeps declining. Wait
        for the desktop, then while the user has control; after either, hand the model a fresh screen. The desktop
        comes first: one that does not reconnect ends the task whoever has control, and the user can't use one that
        is gone either. Once they hand it back, wait for it again: it may have gone meanwhile. Then hand the model
        what the main agent told it meanwhile."""
        if self.executor.stuck:
            return self.stop(f"Stopped: the last {self.executor.repeats} actions did not change the screen.", "stuck",
                             count=self.executor.repeats)
        if self.confirm.exhausted:
            return self.stop(f"Stopped: the user declined {self.confirm.declined} of its steps.", "declined",
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
            return self.stop(f"Stopped: {gone}.", "disconnected", seconds=gone.seconds)
        if not changes:
            return await super().abefore_model(state, runtime)
        sent = self.inbox.take(SUBAGENT)
        self.executor.clear_unchanged()
        note = " ".join([*changes, DECIDE_AGAIN])
        if sent:
            note = f"{notes.told([each.text for each in sent])}\n\n{note}"
        message = HumanMessage(content=content(await self.executor.observe(note)))
        self.log.input(message, "reconnected" if lost else "returned")
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

    def stop(self, summary: str, reason: Stop, **data) -> dict:
        """End the task, its transcript closed by the runtime's message, as LangChain's model call limit closes one.
        The message is the runtime's, not the agent's: the task has no reply."""
        self.stopped = reason
        codes: dict[Stop, NoteCode] = {"stuck": "stuck", "disconnected": "gone", "declined": "declined"}
        self.log.note(summary, codes[reason], **data)
        message = AIMessage(content=summary)
        self.log.input(message, reason)
        return {"messages": [message], "jump_to": "end"}

    async def awrap_model_call(self, request, handler):
        pruned = request.override(messages=prune_screenshots(request.messages, KEEP_SCREENSHOTS, PRUNE_EVERY))
        return await super().awrap_model_call(pruned, handler)

    async def held(self, request) -> ToolMessage | None:
        """A step that needs the user's approval runs only once they give it; a refusal is its result, logged in its
        place like any other."""
        return await self.confirm.check(request)
