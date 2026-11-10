"""Where runs are kept: each run's events (its record) and the files they name.

The agents define the record (agent.trajectory writes it, history reads it); a store only keeps it. Everything goes
through one user's view (`Runs`), where another user's run does not exist. CU_DATABASE_URL picks the store:
FileRunStore (storage.files) or MongoRunStore (storage.mongo). What is the same for every store (titles, pages,
search hits) lives here. A ProjectStore keeps each user's projects."""

import base64
import binascii
import json
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Protocol

from computer_use.files import FileStore, run_key

FORMAT = 7
# The tag of the main agent's events; a subagent's are untagged.
MAIN = "main"
# The user when nobody signed in (auth.LOCAL).
LOCAL_USER = "local"
# A user id as auth makes it ("local" or 32 hex characters); stores key by it.
USER_ID = re.compile(r"[0-9a-z]{1,64}")
MAX_HITS = 50
# Snippet characters before and after the match.
BEFORE, AFTER = 20, 80
# Conversations per page: default and maximum.
PAGE, MAX_PAGE = 50, 100
# `conversations(project=ALL)`: any project or none.
ALL = "*"

RunId = str  # UUIDv7 hex: sorts by start time, unique across stores
Thread = str  # a conversation: its first run's id
# What a run records: a turn of the main agent, or a task it handed over.
TURN, TASK = "turn", "task"
Event = dict  # one steps.jsonl line; the store sets "time"
Cursor = str  # a page's `next`, opaque to clients


@dataclass(frozen=True)
class RunSummary:
    """A run without its events, as the page lists it: a turn of the main agent, or a task it handed over."""

    id: RunId
    thread: Thread
    kind: str  # TURN or TASK
    session: RunId  # the session it is part of: the id of the turn that began it (agent.session)
    parent: RunId | None  # a task's: the turn that handed it over
    goal: str  # a turn's user message ("" for one a task's result began), a task's brief
    project: str | None  # where it started, or where the user moved it
    title: str | None  # the user's, else the runtime's (agent.title)
    started: float
    actions: int  # desktop actions, not the main agent's
    ended: float | None  # None while running, or if the runtime died
    failed: bool  # ended in an error


@dataclass(frozen=True)
class Conversation:
    """A conversation as the page lists it: its runs folded into one."""

    id: Thread
    project: str | None  # its first turn's
    title: str | None  # the latest turn's that has one
    goal: str  # its first message, shown until it has a title
    last: float  # latest turn's start: the sort key
    latest: RunSummary  # its latest turn


@dataclass(frozen=True)
class Page[T]:
    items: list[T]
    next: Cursor | None  # None on the last page


@dataclass(frozen=True)
class Hit:
    """A search result; `snippet` is None when only the name matched."""

    conversation: Conversation
    snippet: str | None


@dataclass(frozen=True)
class Project:
    """A user's project; runs name it by id, which a rename keeps."""

    id: str
    name: str
    created: float


class ProjectStore(Protocol):
    """Each user's projects."""

    async def list(self, user: str) -> list[Project]:
        """The user's projects, oldest first."""

    async def get(self, user: str, id: str) -> Project | None: ...

    async def create(self, user: str, name: str) -> Project:
        """A new project, or the user's existing one by this name."""

    async def rename(self, user: str, id: str, name: str) -> Project | None:
        """None if there is no such project; ValueError if the name is taken."""

    async def delete(self, user: str, id: str) -> bool:
        """Delete only the project record. The caller handles its conversations."""

    async def close(self) -> None: ...


class RunStore(Protocol):
    def of(self, user: str) -> "Runs":
        """The store as `user` sees it: their runs only. ValueError for a malformed id."""

    async def close(self) -> None: ...


class Runs(Protocol):
    """One user's runs, their files, and the conversations they make up."""

    user: str

    # --- writing (agent.trajectory): append is sync, so events keep their order ---
    async def create(self) -> RunId:
        """A new, empty run."""

    def append(self, run: RunId, event: dict) -> Event:
        """Appends an event after the run's others, adding "time"; returns the event as it is stored. A store may
        write it later: this view's reads wait for it, other processes' once `flush` returns."""

    async def flush(self, run: RunId) -> None:
        """Waits until the run's events are stored; raises, once, the first error that kept one from being stored."""

    async def put_file(self, run: RunId, name: str, data: bytes) -> None:
        """Stores a file of the run (e.g. a screenshot), replacing one of the same name. Awaited before the event
        that names it is appended."""

    # --- reading ---
    async def events(self, run: RunId, after: int = -1, *, messages: bool = True) -> list[Event]:
        """Events with an index above `after`, complete ones only; none for a missing or foreign run. Without
        `messages`, a store may leave out the model messages, most of a record's bytes."""

    async def get_file(self, run: RunId, name: str) -> bytes:
        """A file of the run; FileNotFoundError if missing or foreign."""

    # --- conversations ---
    async def runs(self, thread: Thread) -> list[RunSummary]:
        """A conversation's runs in the current format, oldest first; none if foreign."""

    async def conversations(
        self, project: str | None = ALL, before: Cursor | None = None, limit: int = PAGE,
    ) -> Page[Conversation]:
        """A page of conversations, most recently active first, after cursor `before`. `project` filters: an id,
        None for none, ALL for any. ValueError for a bad cursor."""

    async def delete(self, thread: Thread) -> list[RunId]:
        """Erases a conversation's records and files for good."""

    async def search(self, query: str, limit: int = MAX_HITS) -> list[Hit]:
        """Conversations whose name or words contain the query, case-insensitive, most recent first."""

    async def revision(self) -> int:
        """Changes whenever the user's list does, in any process; 0 before the first change."""


class RunFiles:
    """A view's run files, in the files store under the user's prefix: the same for every store."""

    user: str
    files: FileStore

    async def put_file(self, run: RunId, name: str, data: bytes) -> None:
        await self.files.put(run_key(self.user, run, name), data)

    async def get_file(self, run: RunId, name: str) -> bytes:
        return await self.files.get(run_key(self.user, run, name))

    async def delete_files(self, run: RunId) -> None:
        await self.files.delete_prefix(run_key(self.user, run))


MAX_NAME = 80
# The events that change what the list shows.
LISTED = frozenset({"start", "end", "title", "project"})


def user_id(user: str) -> str:
    """ValueError if malformed."""
    if not USER_ID.fullmatch(user):
        raise ValueError(f"not a user id: {user!r}")
    return user


def supported(events: list[Event]) -> bool:
    return bool(events) and events[0].get("type") == "start" and events[0].get("v") == FORMAT


def project_name(name: object) -> str:
    """The name with spaces collapsed and cut; ValueError if empty."""
    kept = " ".join(name.split())[:MAX_NAME].rstrip() if isinstance(name, str) else ""
    if not kept:
        raise ValueError("a project needs a name")
    return kept


# A run's row: what every store keeps per run to list it. `run_change` holds the rules: the files store folds them over
# a record, a database applies each as its event is appended.
Row = dict  # v, thread, kind, session, parent, goal, project, user_title, runtime_title, started, ended, failed, actions
# The event fields `run_change` reads, for a store that reads events without the rest.
CHANGE_FIELDS = ("type", "v", "time", "thread", "kind", "session", "parent", "goal", "project", "text", "by", "agent", "stop_reason")


@dataclass(frozen=True)
class RunChange:
    """Changes to a run summary: field assignments and counter increments."""

    set: Row = field(default_factory=dict)
    add: dict[str, int] = field(default_factory=dict)
    starts: bool = False  # the row begins here
    refolds: bool = False  # the conversation must be folded again


def run_change(event: Event) -> RunChange | None:
    """None for an event the row does not show."""
    match event["type"]:
        case "start" if event.get("v") == FORMAT:
            return RunChange({
                "v": FORMAT, "thread": event["thread"], "kind": event["kind"], "session": event["session"],
                "parent": event.get("parent"), "goal": event["goal"], "project": event.get("project"),
                "user_title": None, "runtime_title": None, "started": event["time"], "ended": None, "failed": False,
                "actions": 0,
            }, starts=True, refolds=True)
        case "title":
            by = "user_title" if event.get("by") == "user" else "runtime_title"
            return RunChange({by: event["text"]}, refolds=True)
        case "project":
            return RunChange({"project": event.get("project")}, refolds=True)
        case "end":
            return RunChange({"ended": event["time"], "failed": event.get("stop_reason") == "error"})
        case "action" if event.get("agent") != MAIN:
            return RunChange(add={"actions": 1})
    return None


def row_of(events: Iterable[Event]) -> Row | None:
    """The row the events make; None for a record not in the current format."""
    row = None
    for event in events:
        change = run_change(event)
        if change is None or (row is None and not change.starts):
            continue
        row = {} if change.starts else row
        row |= change.set
        for name, count in change.add.items():
            row[name] += count
    return row


def summary_of(run: RunId, row: Row) -> RunSummary:
    return RunSummary(
        id=run, thread=row["thread"], kind=row["kind"], session=row["session"], parent=row["parent"],
        goal=row["goal"], project=row["project"],
        title=row["user_title"] if row["user_title"] is not None else row["runtime_title"],
        started=row["started"], actions=row["actions"], ended=row["ended"], failed=row["failed"],
    )


def summarize(run: RunId, events: list[Event]) -> RunSummary:
    return summary_of(run, row_of(events))


def conversations_of(summaries: Iterable[RunSummary]) -> list[Conversation]:
    """Turns folded into conversations, most recently active first; tasks are not listed."""
    by_thread: dict[Thread, list[RunSummary]] = {}
    for summary in summaries:
        if summary.kind == TURN:
            by_thread.setdefault(summary.thread, []).append(summary)
    found = []
    for thread, runs in by_thread.items():
        runs.sort(key=lambda run: (run.started, run.id))
        first, latest = runs[0], runs[-1]
        title = next((run.title for run in reversed(runs) if run.title), None)
        found.append(Conversation(thread, first.project, title, first.goal, latest.started, latest))
    found.sort(key=lambda each: (each.last, each.id), reverse=True)
    return found


def page_of(
    conversations: list[Conversation], project: str | None = ALL, before: Cursor | None = None, limit: int = PAGE,
) -> Page[Conversation]:
    """A page of `conversations_of`'s list, as `Runs.conversations` returns it."""
    limit = page_limit(limit)
    listed = [each for each in conversations if project == ALL or each.project == project]
    if before is not None:
        last, thread = decode_cursor(before)
        listed = [each for each in listed if (each.last, each.id) < (last, thread)]
    return paged(listed[:limit + 1], limit)


def page_limit(limit: int) -> int:
    return max(1, min(limit, MAX_PAGE))


def paged(listed: list[Conversation], limit: int) -> Page[Conversation]:
    """A page from `listed`, which holds one extra item when there is a next page."""
    items = listed[:limit]
    return Page(items, encode_cursor(items[-1].last, items[-1].id) if len(listed) > limit else None)


def encode_cursor(last: float, thread: Thread) -> Cursor:
    return base64.urlsafe_b64encode(json.dumps([last, thread]).encode()).decode()


def decode_cursor(cursor: Cursor) -> tuple[float, Thread]:
    """A cursor's (last, id); the next page lists what sorts strictly below. ValueError for a bad cursor."""
    try:
        last, thread = json.loads(base64.urlsafe_b64decode(cursor))
    except (ValueError, TypeError, binascii.Error) as error:
        raise ValueError("not a cursor") from error
    if not isinstance(last, int | float) or not isinstance(thread, str):
        raise ValueError("not a cursor")
    return last, thread


def named(conversation: Conversation, query: str) -> bool:
    """Whether the title, or the goal until there is one, contains the query."""
    return query.lower() in (conversation.title or conversation.goal).lower()


def said(events: list[Event]) -> Iterator[str]:
    """What search reads of a run: the user's messages and the main agent's words."""
    return (text for event in events if (text := said_of(event)) is not None)


def said_of(event: Event) -> str | None:
    """What a search or a read of the conversation takes from one event, or None: not a task's brief, which is the main
    agent's word."""
    match event["type"]:
        case "start" if event.get("kind") == TURN:
            return event["goal"] or None
        case "message":
            return event["text"]
        case "model" if event.get("agent") == MAIN:
            return event["text"]
    return None


def snippet(texts: Iterable[str], query: str) -> str | None:
    """The text around the first match on one line, with "…" at cuts; None without a match."""
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    for text in texts:
        if match := pattern.search(text):
            start, end = max(0, match.start() - BEFORE), match.end() + AFTER
            words = " ".join(text[start:end].split())
            return ("…" if start > 0 else "") + words + ("…" if end < len(text) else "")
    return None
