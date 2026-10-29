"""Memory for a LangChain agent, as TodoListMiddleware gives it a plan: its tools, and its part of the system prompt.

One per run: what the user lets it remember is recalled once, the first time it is asked for, so the system prompt
stays the same while the run works and a model's cache of it holds."""

from collections.abc import Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, SystemMessage

from computer_use.memory import MemoryStore
from computer_use.memory.context import Recalled, recall
from computer_use.memory.prompts import REMEMBER
from computer_use.memory.tools import memory_tools


class MemoryMiddleware(AgentMiddleware):
    """`user`'s memory in a run of conversation `thread` in `project` (None for none): with `learn`, the agent may
    remember and forget rules; with `use`, it is told those it has."""

    def __init__(
        self, store: MemoryStore, user: str, project: str | None, thread: str, run: str, *, learn: bool, use: bool
    ):
        super().__init__()
        self.store, self.user, self.project, self.use = store, user, project, use
        self.learn = learn
        self.tools = memory_tools(store, user, project, thread, run) if learn else []
        self._recalled: Recalled | None = None

    async def recalled(self) -> Recalled | None:
        """What the run is told it remembers; None when it is not told."""
        if self.use and self._recalled is None:
            self._recalled = await recall(self.store, self.user, self.project)
        return self._recalled

    async def awrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]
    ) -> ModelResponse | AIMessage:
        recalled = await self.recalled()
        parts = (REMEMBER if self.learn else "", recalled.prompt() if recalled else "")
        section = "\n".join(part for part in parts if part)
        if not section:
            return await handler(request)
        blocks = [*request.system_message.content_blocks] if request.system_message is not None else []
        added = {"type": "text", "text": f"\n\n{section}" if blocks else section}
        return await handler(request.override(system_message=SystemMessage(content=[*blocks, added])))
