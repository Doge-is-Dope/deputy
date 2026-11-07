"""Runs in MongoDB. Every document carries its user and every unique key starts with it, so one user's view can
neither reach nor collide with another's documents.

events          {user, run, seq, said?, event}: `event` is the steps.jsonl line; `said` is what search reads (said_of)
runs            {user, run, **row}: the run's row (storage.Row)
conversations   {user, thread, v, project, title, goal, last, latest}: the sidebar pages over these

Rows and conversations carry the event format (`v`) they were made in, and only the current one's are read: an
older format's are left as they are, unlisted, as the files store leaves its records.
revisions       {user, n}
projects        {user, id, name, created}

An append returns at once; each run's writes follow one another in the background: the event, then its `run_change`,
without a transaction. A crash in between leaves the rows behind the events, which `rebuild` repairs with the runtime
stopped."""

import asyncio
import logging
import re
import time
import uuid
from dataclasses import asdict
from functools import partial

from pymongo import ASCENDING, DESCENDING, AsyncMongoClient, MongoClient, ReplaceOne, ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError

from computer_use.files import FileStore
from computer_use.storage import (
    ALL, CHANGE_FIELDS, FORMAT, LISTED, MAX_HITS, PAGE, Conversation, Cursor, Event, Hit, Page, Project, RunChange, RunFiles,
    RunId, RunSummary, Thread, conversations_of, decode_cursor, encode_cursor, named, page_limit, project_name, row_of,
    run_change, said_of, snippet, summary_of, user_id,
)

logger = logging.getLogger(__name__)

# Unique keys first.
INDEXES = {
    "events": [(["user", "run", "seq"], True)],
    "runs": [(["user", "run"], True), (["user", "thread", "started"], False)],
    "conversations": [(["user", "thread"], True), (["user", "last", "thread"], False),
                      (["user", "project", "last", "thread"], False)],
    "revisions": [(["user"], True)],
    "projects": [(["user", "id"], True), (["user", "name"], True)],
}
NO_ID = {"_id": 0}
# What the row is made from: not the model messages, most of the bytes.
CHANGES = {"_id": 0, "run": 1, **{f"event.{name}": 1 for name in CHANGE_FIELDS}}


def connect(url: str, indexes: dict) -> AsyncDatabase:
    """The URL's database, on one client every store of the runtime shares, with `indexes` made first (idempotent)."""
    with MongoClient(url) as client:
        database = client.get_default_database()
        for collection, wanted in indexes.items():
            for keys, unique in wanted:
                database[collection].create_index([(key, ASCENDING) for key in keys], unique=unique)
    return AsyncMongoClient(url, maxPoolSize=8).get_default_database()


def _of(user: str, **fields) -> dict:
    """A query for a user's documents; ValueError for a malformed id."""
    return {"user": user_id(user), **fields}


class MongoRunStore:
    def __init__(self, database: AsyncDatabase, files: FileStore):
        self.db = database
        self.files = files
        self._views: dict[str, MongoRuns] = {}  # one view per user

    def of(self, user: str) -> "MongoRuns":
        if user not in self._views:
            self._views[user] = MongoRuns(self, user_id(user))
        return self._views[user]

    async def close(self) -> None:
        writes = [write for view in self._views.values() for write in view._writes.values()]
        if writes:
            await asyncio.wait(writes)
        await self.db.client.close()

    async def users(self) -> list[str]:
        """Everyone with events, runs or conversations."""
        found = set()
        for collection in ("events", "runs", "conversations"):
            found.update(await self.db[collection].distinct("user"))
        return sorted(found)

    async def rebuild(self, user: str) -> tuple[int, int]:
        """Remakes the user's rows and conversations from events; returns their counts. Stop all writers first:
        concurrent appends could be omitted or counted twice."""
        records: dict[RunId, list[Event]] = {}
        async for doc in self.db.events.find(_of(user), CHANGES).sort([("run", ASCENDING), ("seq", ASCENDING)]):
            records.setdefault(doc["run"], []).append(doc["event"])
        rows = {run: row for run, events in records.items() if (row := row_of(events)) is not None}
        conversations = conversations_of(summary_of(run, row) for run, row in rows.items())
        if rows:
            await self.db.runs.bulk_write([
                ReplaceOne(_of(user, run=run), _of(user, run=run, **row), upsert=True) for run, row in rows.items()
            ], ordered=False)
            await self.db.conversations.bulk_write([
                ReplaceOne(_of(user, thread=each.id), conversation_doc(user, each), upsert=True)
                for each in conversations
            ], ordered=False)
        await self.db.runs.delete_many(_of(user, run={"$nin": list(rows)}))
        await self.db.conversations.delete_many(_of(user, thread={"$nin": [each.id for each in conversations]}))
        await self.of(user).bump()
        return len(rows), len(conversations)


class MongoRuns(RunFiles):
    def __init__(self, store: MongoRunStore, user: str):
        self.user = user
        self.db, self.files = store.db, store.files
        self._next: dict[RunId, int] = {}  # next seq per run this view writes
        self._writes: dict[RunId, asyncio.Task] = {}  # each run's last write until it is done
        self._errors: dict[RunId, Exception] = {}  # each run's first write that failed, until `flush` raises it
        self._folding = asyncio.Lock()  # runs of one conversation write apart; its summary is folded once at a time

    def _of(self, **fields) -> dict:
        return {"user": self.user, **fields}

    def _current(self, **fields) -> dict:
        """A query of the user's rows or conversations made in the current event format."""
        return self._of(v=FORMAT, **fields)

    async def bump(self) -> None:
        await self.db.revisions.update_one(self._of(), {"$inc": {"n": 1}}, upsert=True)

    async def create(self) -> RunId:
        run = uuid.uuid7().hex
        self._next[run] = 0
        await self.bump()
        return run

    def append(self, run: RunId, event: dict) -> Event:
        event = {"time": time.time(), **event}
        write = asyncio.create_task(self._write(run, event, self._writes.get(run)))
        self._writes[run] = write
        write.add_done_callback(partial(self._written, run))
        return event

    def _written(self, run: RunId, write: asyncio.Task) -> None:
        if self._writes.get(run) is write:
            del self._writes[run]

    async def _write(self, run: RunId, event: Event, previous: asyncio.Task | None) -> None:
        if previous is not None:
            await asyncio.wait([previous])  # after the run's earlier events, stored or not
        try:
            said = {"said": text} if (text := said_of(event)) else {}
            index = self._next[run] if run in self._next else await self._count(run)
            while True:
                try:
                    await self.db.events.insert_one(self._of(run=run, seq=index, event=event, **said))
                    break
                except DuplicateKeyError:  # another process appended first
                    index = await self._count(run)
            self._next[run] = index + 1
            if (change := run_change(event)) is not None:
                await self._apply(run, change)
            if event["type"] in LISTED:
                await self.bump()
        except Exception as error:
            if run not in self._errors:
                logger.exception("could not store an event of run %s", run)
                self._errors[run] = error

    async def flush(self, run: RunId) -> None:
        if (write := self._writes.get(run)) is not None:
            await asyncio.wait([write])
        if (error := self._errors.pop(run, None)) is not None:
            raise error

    async def _settled(self, *runs: RunId) -> None:
        """Waits for this view's writes, to `runs` or to any, so it reads what it appended; `flush` reports a failure."""
        writes = [write for run, write in self._writes.items() if not runs or run in runs]
        if writes:
            await asyncio.wait(writes)

    async def _apply(self, run: RunId, change: RunChange) -> None:
        update = {op: fields for op, fields in (("$set", change.set), ("$inc", change.add)) if fields}
        if change.starts:
            await self.db.runs.update_one(self._of(run=run), update, upsert=True)
            thread = change.set["thread"]
        else:
            found = await self.db.runs.find_one_and_update(self._of(run=run), update, {"thread": 1})
            thread = found and found["thread"]
        if change.refolds and thread:
            async with self._folding:
                await self._refold(thread)

    async def _refold(self, thread: Thread) -> None:
        rows = await self.db.runs.find(self._current(thread=thread), NO_ID).to_list()
        (conversation,) = conversations_of(summary_of(doc["run"], doc) for doc in rows)
        await self.db.conversations.replace_one(
            self._of(thread=thread), conversation_doc(self.user, conversation), upsert=True,
        )

    async def events(self, run: RunId, after: int = -1, *, messages: bool = True) -> list[Event]:
        await self._settled(run)
        shown = {"event": 1, "_id": 0} if messages else {"event.message": 0, "said": 0, "_id": 0}
        found = self.db.events.find(self._of(run=run, seq={"$gt": after}), shown).sort("seq")
        return [doc["event"] async for doc in found]

    async def _count(self, run: RunId) -> int:
        """Not cached: another process may have appended."""
        last = await self.db.events.find_one(self._of(run=run), {"seq": 1}, sort=[("seq", DESCENDING)])
        return last["seq"] + 1 if last else 0

    async def runs(self, thread: Thread) -> list[RunSummary]:
        await self._settled()
        found = self.db.runs.find(self._current(thread=thread), NO_ID).sort([("started", ASCENDING), ("run", ASCENDING)])
        return [summary_of(doc["run"], doc) async for doc in found]

    async def conversations(
        self, project: str | None = ALL, before: Cursor | None = None, limit: int = PAGE,
    ) -> Page[Conversation]:
        limit = page_limit(limit)
        await self._settled()
        query = self._current()
        if project != ALL:
            query["project"] = project
        if before is not None:
            last, thread = decode_cursor(before)
            query["$or"] = [{"last": {"$lt": last}}, {"last": last, "thread": {"$lt": thread}}]
        found = self.db.conversations.find(query, NO_ID).sort([("last", DESCENDING), ("thread", DESCENDING)])
        docs = await found.limit(limit + 1).to_list()
        # The next page goes on from the documents, which may name a run a crash left them without.
        after = encode_cursor(docs[limit - 1]["last"], docs[limit - 1]["thread"]) if len(docs) > limit else None
        return Page(await self._conversations(docs[:limit]), after)

    async def _conversations(self, docs: list[dict]) -> list[Conversation]:
        found = self.db.runs.find(self._current(run={"$in": [doc["latest"] for doc in docs]}), NO_ID)
        latest = {doc["run"]: summary_of(doc["run"], doc) async for doc in found}
        return [
            Conversation(doc["thread"], doc["project"], doc["title"], doc["goal"], doc["last"], latest[doc["latest"]])
            for doc in docs if doc["latest"] in latest
        ]

    async def delete(self, thread: Thread) -> list[RunId]:
        runs = [each.id for each in await self.runs(thread)]
        if not runs:
            return []
        # Events, rows, the conversation, then files: a crash leaves no record naming missing files, and a conversation
        # whose runs are gone is not listed (rebuild drops it).
        await self.db.events.delete_many(self._of(run={"$in": runs}))
        await self.db.runs.delete_many(self._of(run={"$in": runs}))
        await self.db.conversations.delete_one(self._of(thread=thread))
        for run in runs:
            await self.delete_files(run)
            self._next.pop(run, None)
            self._writes.pop(run, None)
            self._errors.pop(run, None)
        await self.bump()
        return runs

    async def search(self, query: str, limit: int = MAX_HITS) -> list[Hit]:
        """Snippets come from the first matching message in each conversation's latest matching run."""
        await self._settled()
        pattern = {"$regex": re.escape(query), "$options": "i"}
        matching = await self.db.events.distinct("run", self._of(said=pattern))
        latest: dict[Thread, RunId] = {}  # thread -> its latest matching run
        found = self.db.runs.find(self._current(run={"$in": matching}), {"run": 1, "thread": 1})
        async for run in found.sort([("started", ASCENDING), ("run", ASCENDING)]):
            latest[run["thread"]] = run["run"]
        named_or_matched = [{"thread": {"$in": list(latest)}}, {"title": pattern}, {"title": None, "goal": pattern}]
        candidates = self._current(**{"$or": named_or_matched})
        hits: list[Hit] = []
        skip = 0
        while len(hits) < limit:
            docs = await self.db.conversations.find(candidates, NO_ID).sort(
                [("last", DESCENDING), ("thread", DESCENDING)],
            ).skip(skip).limit(limit).to_list()
            for conversation in await self._conversations(docs):
                text = None
                if conversation.id in latest:
                    first = await self.db.events.find_one(
                        self._of(run=latest[conversation.id], said=pattern), {"said": 1}, sort=[("seq", ASCENDING)],
                    )
                    text = first and snippet([first["said"]], query)
                if (text or named(conversation, query)) and len(hits) < limit:
                    hits.append(Hit(conversation, text))
            if len(docs) < limit:
                break
            skip += limit
        return hits

    async def revision(self) -> int:
        await self._settled()
        found = await self.db.revisions.find_one(self._of())
        return found["n"] if found else 0


def conversation_doc(user: str, conversation: Conversation) -> dict:
    return {
        "user": user, "thread": conversation.id, "v": FORMAT, "project": conversation.project, "title": conversation.title,
        "goal": conversation.goal, "last": conversation.last, "latest": conversation.latest.id,
    }


# A project document as a Project: without its user.
PROJECT = {"_id": 0, "user": 0}


class MongoProjectStore:
    def __init__(self, database: AsyncDatabase):
        self.projects = database.projects

    async def close(self) -> None:
        await self.projects.database.client.close()

    async def list(self, user: str) -> list[Project]:
        return [Project(**doc) async for doc in self.projects.find(_of(user), PROJECT).sort("created")]

    async def get(self, user: str, id: str) -> Project | None:
        found = await self.projects.find_one(_of(user, id=id), PROJECT)
        return Project(**found) if found else None

    async def create(self, user: str, name: str) -> Project:
        name = project_name(name)
        if found := await self.projects.find_one(_of(user, name=name), PROJECT):
            return Project(**found)
        project = Project(uuid.uuid4().hex, name, time.time())
        try:
            await self.projects.insert_one(_of(user, **asdict(project)))
        except DuplicateKeyError:  # created concurrently
            return await self.create(user, name)
        return project

    async def rename(self, user: str, id: str, name: str) -> Project | None:
        name = project_name(name)
        try:
            found = await self.projects.find_one_and_update(
                _of(user, id=id), {"$set": {"name": name}}, PROJECT, return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError:
            raise ValueError(f"another project is named {name}") from None
        return Project(**found) if found else None

    async def delete(self, user: str, id: str) -> bool:
        return (await self.projects.delete_one(_of(user, id=id))).deleted_count == 1
