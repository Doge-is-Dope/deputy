"""Subagent turn handling: steering and message logging.

Desktop tasks also handle approvals, takeover, reconnection and screenshot
pruning (middleware.desktop). Input validation and dispatch belong to desktop.executor."""

import asyncio

from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from computer_use.agent.inbox import SUBAGENT, Inbox
from computer_use.agent.trajectory import Trajectory
from computer_use.prompts import notes


def read_before_ending(message: AIMessage, inbox: Inbox) -> dict | None:
    """Send an ending reply back to the model if steering messages remain unread."""
    if not message.tool_calls and inbox.unread(SUBAGENT):
        return {"jump_to": "model"}
    return None


class SubagentMiddleware(AgentMiddleware):
    """An agent's turns on a task: what the main agent tells it, read before its next model call and before it ends;
    and every message logged as it arrives."""

    def __init__(self, log: Trajectory, inbox: Inbox):
        super().__init__()
        self.log = log
        self.inbox = inbox
        self.last: AIMessage | None = None  # the agent's own latest turn; the closing messages below are not its own
        self.stopped: str | None = None  # why a guard ended the task, if it did

    async def abefore_model(self, state, runtime) -> dict | None:
        sent = self.inbox.take(SUBAGENT)
        if not sent:
            return None
        message = HumanMessage(content=notes.told([each.text for each in sent]))
        await self.log.input(message, "message")
        return {"messages": [message]}

    @hook_config(can_jump_to=["model"])
    async def aafter_model(self, state, runtime) -> dict | None:
        message = state["messages"][-1]
        if isinstance(message, AIMessage):
            self.last = message
            await self.log.model(message)
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
        await self.log.action(request.tool_call, result)
        return result

    async def held(self, request) -> ToolMessage | None:
        """Why the call must not run yet, as its result, or None once it may: no call is held here."""
        return None
