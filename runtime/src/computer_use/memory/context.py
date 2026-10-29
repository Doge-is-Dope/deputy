"""What a run is told it remembers: taken once as it starts, so its system prompt stays the same while it works and
a model's cache of it holds. A rule remembered during the run is told from the next."""

from dataclasses import dataclass

from computer_use.memory import Memory, MemoryStore
from computer_use.memory.prompts import recalled


@dataclass(frozen=True)
class Recalled:
    store: MemoryStore
    user: str
    memories: tuple[Memory, ...]  # the user's own and the project's, oldest first

    def prompt(self) -> str:
        """The main agent's system prompt section; empty with nothing remembered."""
        return recalled(self.memories)

    def chosen(self, ids: list[str]) -> list[Memory]:
        """The rules a task is handed over with, of those the run was told: an id it was not told is passed over."""
        return [memory for memory in self.memories if memory.id in ids]

    async def use(self, ids: list[str]) -> list[Memory]:
        """Those rules, each counted as used once more (memory.prompts.handed words them for the agent)."""
        chosen = self.chosen(ids)
        await self.store.used(self.user, [memory.id for memory in chosen])
        return chosen


async def recall(store: MemoryStore, user: str, project: str | None) -> Recalled:
    """What `user` lets a run in `project` (None for none) follow: their own rules, and that project's."""
    memories = await store.list(user)
    return Recalled(store, user, tuple(each for each in memories if each.project is None or each.project == project))
