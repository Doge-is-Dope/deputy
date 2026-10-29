"""What the agent remembers for each user: short rules it learned when the user corrected how it worked, or confirmed
an approach that was not obvious, each with why and when it applies.

A package of its own, which imports nothing else of computer_use: the runtime gives it a user's id and a project's,
both opaque. A memory is the user's own (personal), or a project's (`project`), which only that project's
conversations are told. MemoryMiddleware gives an agent the tools to write them as it works (tools) and tells
each run those it may follow (context); the page lists, edits and deletes them (routes). FileMemoryStore
(memory.files) keeps each as a Markdown file."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

# What taught it: a message the user sent while the agent worked, a step they declined with a reason, a takeover, or
# something they said in the conversation otherwise.
Kind = Literal["steer", "decline", "takeover", "said"]
KINDS: tuple[Kind, ...] = ("steer", "decline", "takeover", "said")
# A memory's fields that can be changed once it is written, by the user on the page or the agent replacing it.
EDITABLE = ("text", "why", "applies")
# A memory's text as written is cut to this many characters: a rule is a sentence or two, not a document.
MAX_TEXT = 500


@dataclass(frozen=True)
class Source:
    """Where a memory was learned: the conversation, the run, and what taught it."""

    thread: str
    run: str
    kind: Kind


@dataclass(frozen=True)
class Memory:
    id: str
    user: str
    project: str | None  # the project whose conversations it is told to; None: the user's, told everywhere
    text: str  # the rule itself
    why: str  # the user's reason: the correction as they gave it, or a declined step's note
    applies: str  # when it applies: the kind of task, app or site
    source: Source
    created: float
    updated: float
    uses: int = 0  # tasks it was handed over with
    last_used: float | None = None


class MemoryStore(Protocol):
    """Each user's memories, apart from everyone else's."""

    async def list(self, user: str) -> list[Memory]:
        """All of the user's memories, personal and every project's, oldest first."""

    async def get(self, user: str, id: str) -> Memory | None: ...

    async def save(self, memory: Memory) -> None:
        """Writes it whole: a new one, one put back after it was deleted, or one replaced."""

    async def update(self, user: str, id: str, **fields: str) -> Memory | None:
        """Changes EDITABLE fields; None when the user has no such memory."""

    async def delete(self, user: str, id: str) -> bool: ...

    async def reset(self, user: str) -> int:
        """Deletes every memory of the user's: how many there were."""

    async def used(self, user: str, ids: list[str]) -> None:
        """Counts a use of each, for the page to show and a later cleanup to weigh."""


def build_memory_store(data_dir: Path) -> MemoryStore:
    from computer_use.memory.files import FileMemoryStore

    return FileMemoryStore(data_dir)
