"""Memory for a LangChain agent: its tools, and its part of the system prompt.

One per turn, with what the session recalled once as it began, so the system prompt stays the same while the session
works and a model's cache of it holds."""

from collections.abc import Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage

from computer_use.agent.handover import Handed
from computer_use.memory import Memory, MemoryStore
from computer_use.memory.tools import memory_tools
from computer_use.middleware.common import with_section
from computer_use.prompts.memory import REMEMBER, handed, recalled


class MemoryMiddleware(AgentMiddleware):
    """`user`'s memory in a run of conversation `thread` in `project` (None for none): with `learn`, the agent may
    remember and forget rules; it is `told` those the session recalled, if any."""

    def __init__(
        self, store: MemoryStore, user: str, project: str | None, thread: str, run: str, *, learn: bool,
        told: str,
    ):
        super().__init__()
        self.learn = learn
        self.tools = memory_tools(store, user, project, thread, run) if learn else []
        self.told = told

    async def awrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]
    ) -> ModelResponse | AIMessage:
        parts = (REMEMBER if self.learn else "", self.told)
        section = "\n".join(part for part in parts if part)
        return await handler(with_section(request, section) if section else request)


class UserMemory:
    """`user`'s memory in a session of conversation `thread` in `project` (None for none), as they let it: with `learn`,
    its main agent may remember and forget rules; with `use`, it is told those it has, recalled once as the session
    begins, and hands tasks over with them (agent.handover.SessionMemory)."""

    def __init__(self, store: MemoryStore, user: str, project: str | None, thread: str, *, learn: bool, use: bool):
        self.store, self.user, self.project, self.thread = store, user, project, thread
        self.learn, self.use = learn, use
        self.memories: tuple[Memory, ...] = ()  # its own and the project's, oldest first

    async def recall(self) -> bool:
        if self.use:
            listed = await self.store.list(self.user)
            self.memories = tuple(each for each in listed if each.project is None or each.project == self.project)
        return bool(self.memories)

    def middleware(self, run: str) -> list[AgentMiddleware]:
        return [MemoryMiddleware(self.store, self.user, self.project, self.thread, run, learn=self.learn,
                                 told=recalled(self.memories))]

    async def hand(self, ids: list[str]) -> Handed:
        taught = [memory for memory in self.memories if memory.id in ids]  # an id it was not told is passed over
        await self.store.used(self.user, [memory.id for memory in taught])
        return Handed(handed(taught), [{"id": memory.id, "text": memory.text} for memory in taught])
