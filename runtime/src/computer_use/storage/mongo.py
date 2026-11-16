"""Runs in MongoDB. Every document carries its user and every unique key starts with it, so one user's view can
neither reach nor collide with another's documents.

events          {user, run, seq, said?, event}: `event` is the steps.jsonl line; `said` is what search reads (said_of)
runs            {user, run, **row}: the run's row (storage.Row)
conversations   {user, thread, v, project, title, goal, last, latest}: the sidebar pages over these
revisions       {user, n}
projects        {user, id, name, created}

Rows and conversations carry the event format (`v`) they were made in, and only the current one's are read: an
older format's are left unlisted until `rebuild` erases them with their runs.

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
    ALL, CHANGE_FIELDS, FORMAT, HITS, LISTED, PAGE, Conversation, Cursor, Event, Hit, Page, Project, RunChange, RunFiles,
    RunId, RunSummary, Thread, conversations_of, decode_cursor, encode_cursor, named, page_limit, project_name, row_of,
    run_change, said_of, snippet, summary_of, user_id,
)

logger = logging.getLogger(__name__)

# What search reads, and nothing else: an index of the events that have words, with the words in it, so a search
# neither reads the other events (most of them) nor fetches a document.
SAID = {"partialFilterExpression": {"said": {"$exists": True}}}
# What a search reads of them, from that index.
WORDS = {"run": 1, "said": 1, "_id": 0}
# Up to this many matching events, a search looks its conversations up from them; past it, it walks the
# conversations: this many at a time, a few to begin with and more while it finds little.
FEW = 2000
WALK, MAX_WALK = 50, 2000
# Each index's keys and options, unique keys first.
UNIQUE = {"unique": True}
INDEXES = {
    "events": [(["user", "run", "seq"], UNIQUE), (["user", "run", "seq", "said"], SAID)],
    "runs": [(["user", "run"], UNIQUE), (["user", "thread", "started"], {})],
    "conversations": [(["user", "thread"], UNIQUE), (["user", "last", "thread"], {}),
                      (["user", "project", "last", "thread"], {})],
    "revisions": [(["user"], UNIQUE)],
    "projects": [(["user", "id"], UNIQUE), (["user", "name"], UNIQUE)],
}
NO_ID = {"_id": 0}
# What the row is made from: not the model messages, most of the bytes.
CHANGES = {"_id": 0, "run": 1, **{f"event.{name}": 1 for name in CHANGE_FIELDS}}


def connect(url: str, indexes: dict) -> AsyncDatabase:
    """The URL's database, on one client every store of the runtime shares, with `indexes` made first (idempotent)."""
    with MongoClient(url) as client:
        database = client.get_default_database()
        for collection, wanted in indexes.items():
            for keys, options in wanted:
                database[collection].create_index([(key, ASCENDING) for key in keys], **options)
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

    async def rebuild(self, user: str) -> tuple[int, int, int]:
        """Remakes the user's rows and conversations from events and erases the runs of an older format, which are
        never listed and so could never be deleted; returns the counts of rows, conversations and erased runs. Stop all
        writers first: concurrent appends could be omitted or counted twice."""
        records: dict[RunId, list[Event]] = {}
        async for doc in self.db.events.find(_of(user), CHANGES).sort([("run", ASCENDING), ("seq", ASCENDING)]):
            records.setdefault(doc["run"], []).append(doc["event"])
        rows = {run: row for run, events in records.items() if (row := row_of(events)) is not None}
        old = [run for run in records if run not in rows]
        await self.db.events.delete_many(_of(user, run={"$in": old}))
        for run in old:
            await self.of(user).delete_files(run)
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
        return len(rows), len(conversations), len(old)


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

    async def thread(self, run: RunId) -> Thread | None:
        await self._settled(run)
        found = await self.db.runs.find_one(self._current(run=run), {"thread": 1})
        return found and found["thread"]

    async def runs(self, thread: Thread) -> list[RunSummary]:
        await self._settled()
        found = self.db.runs.find(self._current(thread=thread), NO_ID).sort([("started", ASCENDING), ("run", ASCENDING)])
        return [summary_of(doc["run"], doc) async for doc in found]

    async def conversations(
        self, project: str | None = ALL, before: Cursor | None = None, limit: int = PAGE,
    ) -> Page[Conversation]:
        limit = page_limit(limit)
        await self._settled()
        docs = await self._page(before, limit + 1, **({} if project == ALL else {"project": project}))
        # The next page goes on from the documents, which may name a run a crash left them without.
        after = encode_cursor(docs[limit - 1]["last"], docs[limit - 1]["thread"]) if len(docs) > limit else None
        return Page(await self._conversations(docs[:limit]), after)

    async def _page(self, before: Cursor | None, limit: int, **fields) -> list[dict]:
        """Up to `limit` conversation documents, most recently active first, after cursor `before`."""
        query = self._current(**fields)
        if before is not None:
            last, thread = decode_cursor(before)
            # The bound starts the index scan at the cursor: the $or alone may be planned as a scan from the top.
            query["last"] = {"$lte": last}
            query["$or"] = [{"last": {"$lt": last}}, {"last": last, "thread": {"$lt": thread}}]
        found = self.db.conversations.find(query, NO_ID).sort([("last", DESCENDING), ("thread", DESCENDING)])
        return await found.limit(limit).to_list()

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

    async def search(self, query: str, limit: int = HITS, before: Cursor | None = None) -> list[Hit]:
        """Snippets come from the first matching message in each conversation's latest matching run. Words few runs
        have are looked up from those runs; words many have are found by walking the conversations, newest first,
        which soon has a page of them. Either way a page costs far less than reading the store."""
        await self._settled()
        pattern = {"$regex": re.escape(query), "$options": "i"}
        said = self.db.events.find(self._of(said=pattern), WORDS).sort([("run", ASCENDING), ("seq", ASCENDING)])
        rows = await said.limit(FEW + 1).to_list()
        if len(rows) > FEW:
            return await self._walk(query, pattern, limit, before)
        words = await self._words(rows)
        found = {"$or": [{"thread": {"$in": list(words)}}, {"title": pattern}, {"title": None, "goal": pattern}]}
        return await self._hits(await self._page(before, limit, **{"$and": [found]}), words, query)  # the cursor's $or beside it

    async def _walk(self, query: str, pattern: dict, limit: int, before: Cursor | None) -> list[Hit]:
        """The conversations a batch at a time, a few to begin with and more while it finds little, until it has
        `limit` of them."""
        hits: list[Hit] = []
        batch = WALK
        while len(hits) < limit:
            docs = await self._page(before, batch)
            runs = self.db.runs.find(self._current(thread={"$in": [doc["thread"] for doc in docs]}), {"run": 1})
            said = self.db.events.find(self._of(run={"$in": await runs.distinct("run")}, said=pattern), WORDS)
            words = await self._words(await said.sort([("run", ASCENDING), ("seq", ASCENDING)]).to_list())
            found = [doc for doc in docs if doc["thread"] in words or named(doc["title"], doc["goal"], query)]
            hits += await self._hits(found[:limit - len(hits)], words, query)
            if len(docs) < batch:
                break
            before, batch = encode_cursor(docs[-1]["last"], docs[-1]["thread"]), min(batch * 4, MAX_WALK)
        return hits

    async def _words(self, rows: list[dict]) -> dict[Thread, str]:
        """Each conversation's matching words from `rows` (a run's in order): its latest matching run's first."""
        first: dict[RunId, str] = {}
        for row in rows:
            first.setdefault(row["run"], row["said"])
        found = self.db.runs.find(self._current(run={"$in": list(first)}), {"run": 1, "thread": 1})
        return {run["thread"]: first[run["run"]] async for run in found.sort([("started", ASCENDING), ("run", ASCENDING)])}

    async def _hits(self, docs: list[dict], words: dict[Thread, str], query: str) -> list[Hit]:
        return [
            Hit(conversation, (text := words.get(conversation.id)) and snippet([text], query))
            for conversation in await self._conversations(docs)
        ]

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
