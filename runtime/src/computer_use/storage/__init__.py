"""Where runs are kept: each run is a sequence of events (its record) and the files, screenshots, those events name.

The record's shape is the agents' (agent.trajectory writes it, history reads it); a store only keeps it. A run is
named by its id, never by a path. FileRunStore (storage.files) keeps runs as folders under data/runs; a database
plugs in here behind a setting. A ProjectStore keeps each user's projects, which runs name by id."""

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Protocol

from computer_use.config import Settings

# The supported event format: explicit note codes and action reasons, with background tasks and streamed drafts, each
# task under its id and title. A store lists only runs whose record is in this format.
FORMAT = 4
# The tag of the main agent's events; a subagent's are untagged.
MAIN = "main"
# Whose a run is when nobody signed in to start it (auth.LOCAL), and of a run from before runs recorded it.
LOCAL_USER = "local"
# A search finds this many conversations at most.
MAX_HITS = 50
# A hit's snippet: this many characters before the match and after it.
BEFORE, AFTER = 20, 80

RunId = str  # e.g. "20261023-131500" or "20261023-131500-2": sorts by when the run started
Thread = str  # a conversation: the id of its first run
Event = dict  # one record of a run, as a line of steps.jsonl; "time" is set by the store on append


@dataclass(frozen=True)
class RunSummary:
    """What the page lists a run by, without its events."""

    id: RunId
    thread: Thread
    goal: str
    project: str | None  # the one it was started in, or the user moved it to; the page lists by the first run's
    title: str | None  # the user's, else the runtime's (agent.title); None until it has one
    started: float
    actions: int  # on the desktop: not the main agent's handing work over
    ended: float | None  # None while it runs, and for a run that never ended (the runtime stopped under it)
    failed: bool  # it ended in an error, not a reply or the user's stop
    user: str  # whose it is: the id of who started its conversation (auth.Identity), the only one who sees it


@dataclass(frozen=True)
class Hit:
    """A conversation a search found, by the words around the first match in its latest run that has one."""

    thread: Thread
    snippet: str


@dataclass(frozen=True)
class Project:
    """A user's project, which the page lists conversations under; a run names it by its id, which a rename keeps."""

    id: str
    name: str
    created: float
    deleted: float | None = None  # when, until it is restored: kept, as a deleted conversation is


class ProjectStore(Protocol):
    """Each user's projects, apart from everyone else's."""

    async def list(self, user: str) -> list[Project]:
        """The user's projects, oldest first; not those deleted."""

    async def get(self, user: str, id: str) -> Project | None: ...

    async def create(self, user: str, name: str) -> Project:
        """A new project by this name, or the user's project that already has it: a name names one project."""

    async def rename(self, user: str, id: str, name: str) -> Project | None:
        """None when the user has no such project; ValueError when another of theirs has the name."""

    async def delete(self, user: str, id: str) -> bool:
        """The project only: its conversations stay, and list without one while it is deleted."""

    async def restore(self, user: str, id: str) -> Project | None:
        """A deleted project back, by its id, for its conversations brought back with it to list under."""


class RunStore(Protocol):
    # --- writing a run (agent.trajectory): synchronous, so an append and what follows it keep their order ---
    async def create(self) -> RunId:
        """A new, empty run, named by when it started."""

    def append(self, run: RunId, event: dict) -> tuple[int, Event]:
        """Adds one event to the run's record, with "time", and returns its index and the event as written. Appends
        are durable in order: index n is readable once this returns, and before n + 1 is."""

    def put_file(self, run: RunId, name: str, data: bytes) -> None:
        """Keeps a file of the run, e.g. a screenshot; a name given twice replaces."""

    def has_file(self, run: RunId, name: str) -> bool: ...

    # --- reading a run (history, server, agents) ---
    async def events(self, run: RunId, after: int = -1) -> list[Event]:
        """The run's events with an index above `after`: complete records only, so a line a crash cut off is not
        among them; none for a run that does not exist."""

    def count(self, run: RunId) -> int:
        """How many events the run has: at least one past the index of the last event this process appended, and as
        many as the store can see without waiting (another process may have appended). The events stream's durable
        boundary: an event appended here is always below it, so it is delivered before the text streamed after it."""

    async def get_file(self, run: RunId, name: str) -> bytes:
        """A file of the run; FileNotFoundError when it has none by this name."""

    # --- conversations (server, agents) ---
    async def summaries(self) -> list[RunSummary]:
        """Every run in the list, newest first; only records in the current format."""

    async def conversation(self, thread: Thread, deleted: bool = False, user: str | None = None) -> list[RunId]:
        """A conversation's runs, oldest first: those in the list, or those deleted; only if it is `user`'s, when
        given."""

    async def delete(self, thread: Thread) -> list[RunId]:
        """Takes a conversation's runs out of the list; nothing is erased (an eval's sheet still links its
        screenshots)."""

    async def restore(self, thread: Thread) -> list[RunId]: ...

    async def search(self, query: str, user: str, limit: int = MAX_HITS) -> list[Hit]:
        """`user`'s conversations in the list whose words (`said`) hold the query, ignoring case, most recently active
        first: one hit each, at most `limit`."""

    async def revision(self) -> int:
        """Changes whenever the list changes, by this process or another (LISTED events, create, delete, restore);
        0 before the first."""


# A name (a title, a project) is cut to this many characters: the sidebar shows a few dozen.
MAX_NAME = 80
# The events that change what the list shows.
LISTED = frozenset({"start", "end", "title", "project"})


def supported(events: list[Event]) -> bool:
    """A record that can be listed and continued: it starts with a start event in the current format."""
    return bool(events) and events[0].get("type") == "start" and events[0].get("v") == FORMAT


def title_of(events: list[Event]) -> str | None:
    """The last title the user gave, else the last the runtime made."""
    titles = [event for event in events if event["type"] == "title"]
    by_user = [event["text"] for event in titles if event.get("by") == "user"]
    return by_user[-1] if by_user else (titles[-1]["text"] if titles else None)


def project_name(name: object) -> str | None:
    """A project's name as it is kept, on one line and as long as a title at most; None for none."""
    return " ".join(name.split())[:MAX_NAME].rstrip() or None if isinstance(name, str) else None


def project_in(events: list[Event]) -> str | None:
    """The id of the last project the user moved the run to, else of the one it was started in."""
    moves = [event for event in events if event["type"] == "project"]
    return moves[-1].get("project") if moves else events[0].get("project")


def summarize(run: RunId, events: list[Event]) -> RunSummary:
    start = events[0]
    end = next((event for event in reversed(events) if event["type"] == "end"), None)
    return RunSummary(
        id=run,
        thread=start["thread"],
        goal=start["goal"],
        project=project_in(events),
        title=title_of(events),
        started=start["time"],
        actions=sum(event["type"] == "action" and event.get("agent") != MAIN for event in events),
        ended=end["time"] if end else None,
        failed=end is not None and end.get("stop_reason") == "error",
        user=start.get("user", LOCAL_USER),
    )


def said(events: list[Event]) -> Iterator[str]:
    """What a search reads of a run: the user's messages and the main agent's words, as the page shows them; not
    tools' results, subagents' words or reasoning."""
    for event in events:
        match event["type"]:
            case "start":
                yield event["goal"]
            case "message":
                yield event["text"]
            case "model" if event.get("agent") == MAIN:
                yield event["text"]


def snippet(texts: Iterable[str], query: str) -> str | None:
    """The words around the query's first match, on one line, "…" where they are cut; None without a match."""
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    for text in texts:
        if match := pattern.search(text):
            start, end = max(0, match.start() - BEFORE), match.end() + AFTER
            words = " ".join(text[start:end].split())
            return ("…" if start > 0 else "") + words + ("…" if end < len(text) else "")
    return None


def build_run_store(settings: Settings) -> RunStore:
    # Files only so far; a database plugs in here behind a setting.
    from computer_use.storage.files import FileRunStore

    return FileRunStore(settings.data_dir)


def build_project_store(settings: Settings) -> ProjectStore:
    from computer_use.storage.files import FileProjectStore

    return FileProjectStore(settings.data_dir)
