"""Runs as folders: data/users/<user>/runs/<id>/steps.jsonl, one event per line; a user's folder is their whole view.
Files go to a files store, by default beside the record. The list revision is the mtime of data/users/<user>/revision,
so processes sharing the data see each other's changes. Projects are data/users/<user>/projects.json, rewritten
under a lock. Records are parsed in a worker thread; appends stay on the event loop to keep their order."""

import asyncio
import contextlib
import fcntl
import json
import os
import shutil
import time
import uuid
from dataclasses import asdict, replace
from pathlib import Path

from computer_use.files import FileStore
from computer_use.storage import (
    ALL, LISTED, MAX_HITS, PAGE, Conversation, Cursor, Event, Hit, Page, Project, RunFiles, RunId, RunSummary, Thread,
    conversations_of, named, page_of, project_name, said, snippet, summarize, supported, user_id,
)


class FileRunStore:
    def __init__(self, data_dir: Path, files: FileStore):
        self.users = data_dir / "users"
        self.files = files
        self._views: dict[str, FileRuns] = {}  # one view per user, with its caches

    def of(self, user: str) -> "FileRuns":
        if user not in self._views:
            self._views[user] = FileRuns(self.users / user_id(user), user, self.files)
        return self._views[user]

    async def close(self) -> None:
        pass


class FileRuns(RunFiles):
    def __init__(self, folder: Path, user: str, files: FileStore):
        self.user = user
        self.folder = folder
        self.files = files
        self.root = folder / "runs"
        self.revision_path = folder / "revision"
        # Each run's summary, keyed on its record's mtime and size.
        self._summaries: dict[RunId, tuple[tuple[int, int], RunSummary]] = {}
        # The scan in progress and the revision it began at: lists asked for meanwhile share it.
        self._scan: tuple[int, asyncio.Future[list[RunSummary]]] | None = None

    def _folder(self, run: RunId) -> Path:
        return self.root / run

    def _record(self, run: RunId) -> Path:
        return self._folder(run) / "steps.jsonl"

    async def create(self) -> RunId:
        run = uuid.uuid7().hex
        self._folder(run).mkdir(parents=True)
        self._touch()
        return run

    def append(self, run: RunId, event: dict) -> Event:
        event = {"time": time.time(), **event}
        with self._record(run).open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, ensure_ascii=False) + "\n")
        if event["type"] in LISTED:
            self._touch()
        return event

    async def flush(self, run: RunId) -> None:
        """Appends are written as they are made."""

    async def events(self, run: RunId, after: int = -1, *, messages: bool = True) -> list[Event]:
        return await asyncio.to_thread(self._events, self._record(run), after)

    @staticmethod
    def _events(path: Path, after: int = -1) -> list[Event]:
        return FileRuns._parse(FileRuns._read(path), after)

    @staticmethod
    def _read(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except (FileNotFoundError, NotADirectoryError):
            return ""

    @staticmethod
    def _parse(text: str, after: int = -1) -> list[Event]:
        lines = text.split("\n")[:-1]  # drop a partial last line
        return [json.loads(line) for line in lines[after + 1:] if line]

    async def runs(self, thread: Thread) -> list[RunSummary]:
        summaries = await self._scanned()
        return sorted((each for each in summaries if each.thread == thread), key=lambda each: (each.started, each.id))

    async def conversations(
        self, project: str | None = ALL, before: Cursor | None = None, limit: int = PAGE,
    ) -> Page[Conversation]:
        return page_of(conversations_of(await self._scanned()), project, before, limit)

    async def _scanned(self) -> list[RunSummary]:
        """Every run's summary, from one scan for every list the page asks for at once, unless the list changed since
        it began."""
        revision = await self.revision()
        if self._scan is None or self._scan[0] != revision or self._scan[1].done():
            self._scan = (revision, asyncio.ensure_future(asyncio.to_thread(self._summarize)))
        return await asyncio.shield(self._scan[1])

    def _summarize(self) -> list[RunSummary]:
        items = []
        for path in self.root.glob("*/steps.jsonl") if self.root.is_dir() else ():
            run = path.parent.name
            try:
                stat = path.stat()
            except (FileNotFoundError, NotADirectoryError):
                continue  # deleted meanwhile
            key = (stat.st_mtime_ns, stat.st_size)
            cached = self._summaries.get(run)
            if cached is None or cached[0] != key:
                events = self._events(path)
                if not supported(events):
                    continue
                cached = self._summaries[run] = (key, summarize(run, events))
            items.append(cached[1])
        items.sort(key=lambda item: item.started, reverse=True)
        return items

    async def delete(self, thread: Thread) -> list[RunId]:
        runs = [each.id for each in await self.runs(thread)]
        for run in runs:
            # Record first, then files: a crash leaves stray files, never a record naming missing ones.
            await asyncio.to_thread(shutil.rmtree, self._folder(run), ignore_errors=True)
            await self.delete_files(run)
            self._summaries.pop(run, None)
        if runs:
            self._touch()
        return runs

    async def search(self, query: str, limit: int = MAX_HITS) -> list[Hit]:
        return await asyncio.to_thread(self._search, query, limit)

    def _search(self, query: str, limit: int) -> list[Hit]:
        """Newest first; a record whose raw text lacks the query is skipped unparsed."""
        written = json.dumps(query, ensure_ascii=False)[1:-1].lower()
        summaries = self._summarize()
        runs_of: dict[Thread, list[RunId]] = {}
        for each in sorted(summaries, key=lambda each: (each.started, each.id)):
            runs_of.setdefault(each.thread, []).append(each.id)
        hits: list[Hit] = []
        for conversation in conversations_of(summaries):
            if len(hits) == limit:
                break
            found = None
            for run in reversed(runs_of[conversation.id]):  # latest match first
                text = self._read(self._record(run))
                if written in text.lower() and (found := snippet(said(self._parse(text)), query)):
                    break
            if found or named(conversation, query):
                hits.append(Hit(conversation, found))
        return hits

    async def revision(self) -> int:
        try:
            return self.revision_path.stat().st_mtime_ns
        except FileNotFoundError:
            return 0

    def _touch(self) -> None:
        """Moves the revision forward, even within one clock tick."""
        self.folder.mkdir(parents=True, exist_ok=True)
        self.revision_path.touch()
        now = time.time_ns()
        try:
            last = self._last_revision
        except AttributeError:
            last = 0
        self._last_revision = max(now, last + 1)
        os.utime(self.revision_path, ns=(self._last_revision, self._last_revision))


class FileProjectStore:
    def __init__(self, data_dir: Path):
        self.users = data_dir / "users"

    async def close(self) -> None:
        pass

    def _path(self, user: str) -> Path:
        return self.users / user_id(user) / "projects.json"

    def _read(self, user: str) -> list[Project]:
        try:
            return [Project(**each) for each in json.loads(self._path(user).read_text(encoding="utf-8"))]
        except FileNotFoundError:
            return []

    @contextlib.contextmanager
    def _changing(self, user: str):
        """The user's projects to edit in place, written back under a lock."""
        path = self._path(user)
        path.parent.mkdir(parents=True, exist_ok=True)
        with (path.parent / "projects.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            projects = self._read(user)
            yield projects
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps([asdict(each) for each in projects], ensure_ascii=False), encoding="utf-8")
            os.replace(temporary, path)

    async def list(self, user: str) -> list[Project]:
        return self._read(user)

    async def get(self, user: str, id: str) -> Project | None:
        return next((each for each in await self.list(user) if each.id == id), None)

    async def create(self, user: str, name: str) -> Project:
        name = project_name(name)
        with self._changing(user) as projects:
            if found := next((each for each in projects if each.name == name), None):
                return found
            projects.append(project := Project(uuid.uuid4().hex, name, time.time()))
        return project

    async def rename(self, user: str, id: str, name: str) -> Project | None:
        name = project_name(name)
        with self._changing(user) as projects:
            index = next((n for n, each in enumerate(projects) if each.id == id), None)
            if index is None:
                return None
            if any(each.name == name and each.id != id for each in projects):
                raise ValueError(f"another project is named {name}")
            projects[index] = renamed = replace(projects[index], name=name)
        return renamed

    async def delete(self, user: str, id: str) -> bool:
        with self._changing(user) as projects:
            index = next((n for n, each in enumerate(projects) if each.id == id), None)
            if index is not None:
                del projects[index]
        return index is not None
