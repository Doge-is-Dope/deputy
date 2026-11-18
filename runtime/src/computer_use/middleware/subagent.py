"""Subagent turn handling: steering, message logging, and the hand-over at the model call limit.

Desktop tasks also handle approvals, takeover and reconnection
(middleware.desktop). Input validation and dispatch belong to desktop.executor."""

import asyncio

from langchain.agents.middleware import AgentMiddleware, ModelResponse, hook_config
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from computer_use.agent.inbox import SUBAGENT, Inbox
from computer_use.agent.trajectory import Trajectory
from computer_use.middleware.common import prune_screenshots
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
            # What a call pruned stays pruned, so the state lets go of those images too; the log keeps them.
            kept = prune_screenshots(state["messages"])
            dropped = [new for old, new in zip(state["messages"], kept) if new is not old]
            return ({"messages": dropped} if dropped else {}) | (read_before_ending(message, self.inbox) or {}) or None
        return None

    async def awrap_model_call(self, request, handler):
        # An agent keeps only its latest images, as with screenshots: one it looked at is in its folder still.
        request = request.override(messages=prune_screenshots(request.messages))
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


def in_words(message: BaseMessage) -> BaseMessage:
    """An agent's turn with its tool calls dropped: only what it wrote."""
    if not isinstance(message, AIMessage):
        return message
    return message.model_copy(update={"content": message.text, "tool_calls": [], "invalid_tool_calls": []})


class HandOverAtLimit(AgentMiddleware):
    """Once a task has used its `limit` of model calls, one more asks the agent for a hand-over: what whoever continues
    needs that the screen will not show. The model call limit then ends the task. That call's reply is words only, so
    no step runs past the limit."""

    def __init__(self, limit: int, log: Trajectory):
        super().__init__()
        self.limit = limit
        self.log = log
        self.calls = 0
        self.asked = False  # whether the task reached its hand-over

    async def abefore_model(self, state, runtime) -> dict | None:
        if self.calls < self.limit or self.asked:
            return None
        self.asked = True
        message = HumanMessage(content=notes.HAND_OVER)
        await self.log.input(message, "handover")
        return {"messages": [message]}

    async def awrap_model_call(self, request, handler):
        self.calls += 1
        response = await handler(request)
        if not self.asked:
            return response
        if isinstance(response, ModelResponse):
            return ModelResponse([in_words(each) for each in response.result], response.structured_response)
        return in_words(response)
