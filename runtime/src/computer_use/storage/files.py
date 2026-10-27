"""Runs as folders: data/runs/<id>/steps.jsonl, one event per line, with the run's files beside it.

Deleted conversations' folders move to data/trash. The list's revision is the modification time of data/revision,
touched by whichever process changes the list, so servers sharing the data see each other's changes."""

import json
import os
import time
from datetime import datetime
from pathlib import Path

from computer_use.storage import (
    LISTED, LOCAL_USER, MAX_HITS, Event, Hit, RunId, RunSummary, Thread, said, snippet, summarize, supported,
)


class FileRunStore:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.runs = data_dir / "runs"
        self.trash = data_dir / "trash"
        self.revision_path = data_dir / "revision"
        # Each run's event count at the record's size last seen, so an append need not count the lines every time.
        self._counts: dict[RunId, tuple[int, int]] = {}
        # Each run's summary, keyed on its record's modification time and size, so listing reads only what changed.
        self._summaries: dict[RunId, tuple[tuple[int, int], RunSummary]] = {}

    def _folder(self, run: RunId, deleted: bool = False) -> Path:
        return (self.trash if deleted else self.runs) / run

    def _record(self, run: RunId) -> Path:
        return self._folder(run) / "steps.jsonl"

    async def create(self) -> RunId:
        base = self.runs / datetime.now().strftime("%Y%m%d-%H%M%S")
        folder, n = base, 1
        while True:  # a resume can start within the same second as the run it continues
            try:
                folder.mkdir(parents=True)
                break
            except FileExistsError:
                n += 1
                folder = base.with_name(f"{base.name}-{n}")
        self._touch()
        return folder.name

    def append(self, run: RunId, event: dict) -> tuple[int, Event]:
        event = {"time": time.time(), **event}
        path = self._record(run)
        index = self._count(path, run)
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, ensure_ascii=False) + "\n")
        self._counts[run] = (path.stat().st_size, index + 1)
        if event["type"] in LISTED:
            self._touch()
        return index, event

    def _count(self, path: Path, run: RunId) -> int:
        """Counted once, then kept while the record's size is as last seen: another process may append, e.g. the
        web page's server naming a conversation the eval's server runs."""
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            return 0
        known = self._counts.get(run)
        if known is not None and known[0] == size:
            return known[1]
        count = path.read_bytes().count(b"\n")
        self._counts[run] = (size, count)
        return count

    def put_file(self, run: RunId, name: str, data: bytes) -> None:
        (self._folder(run) / name).write_bytes(data)

    def has_file(self, run: RunId, name: str) -> bool:
        return (self._folder(run) / name).exists()

    async def events(self, run: RunId, after: int = -1) -> list[Event]:
        return self._events(self._record(run), after)

    @staticmethod
    def _events(path: Path, after: int = -1) -> list[Event]:
        return FileRunStore._parse(FileRunStore._read(path), after)

    @staticmethod
    def _read(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except (FileNotFoundError, NotADirectoryError):
            return ""

    @staticmethod
    def _parse(text: str, after: int = -1) -> list[Event]:
        lines = text.split("\n")[:-1]  # a line still being written, or cut off by a crash, has no newline yet
        return [json.loads(line) for line in lines[after + 1:] if line]

    def count(self, run: RunId) -> int:
        return self._count(self._record(run), run)

    async def get_file(self, run: RunId, name: str) -> bytes:
        return (self._folder(run) / name).read_bytes()

    async def summaries(self) -> list[RunSummary]:
        items = []
        for path in self.runs.glob("*/steps.jsonl") if self.runs.is_dir() else ():
            run = path.parent.name
            stat = path.stat()
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

    async def conversation(self, thread: Thread, deleted: bool = False, user: str | None = None) -> list[RunId]:
        if not deleted:  # from the summaries, which read only the records that changed
            return sorted(
                summary.id for summary in await self.summaries()
                if summary.thread == thread and user in (None, summary.user)
            )
        found = []
        for path in sorted(self.trash.glob("*/steps.jsonl")) if self.trash.is_dir() else ():
            start = self._start(path)
            if start is not None and start["thread"] == thread and user in (None, start.get("user", LOCAL_USER)):
                found.append(path.parent.name)
        return found

    @staticmethod
    def _start(path: Path) -> Event | None:
        try:
            with path.open(encoding="utf-8") as file:
                line = file.readline()
        except (FileNotFoundError, NotADirectoryError):
            return None
        if not line.endswith("\n"):
            return None
        event = json.loads(line)
        return event if supported([event]) else None

    async def delete(self, thread: Thread) -> list[RunId]:
        runs = await self.conversation(thread)
        self.trash.mkdir(exist_ok=True)
        for run in runs:
            self._folder(run).rename(self._folder(run, deleted=True))
            self._summaries.pop(run, None)
        if runs:
            self._touch()
        return runs

    async def restore(self, thread: Thread) -> list[RunId]:
        runs = await self.conversation(thread, deleted=True)
        self.runs.mkdir(parents=True, exist_ok=True)
        for run in runs:
            self._folder(run, deleted=True).rename(self._folder(run))
        if runs:
            self._touch()
        return runs

    async def search(self, query: str, user: str, limit: int = MAX_HITS) -> list[Hit]:
        """Reads the records newest first, as Codex greps its rollouts: one without the query anywhere in its text,
        as written to the file, is passed over unparsed."""
        written = json.dumps(query, ensure_ascii=False)[1:-1].lower()
        hits: list[Hit] = []
        threads: set[Thread] = set()
        for summary in await self.summaries():
            if len(hits) == limit:
                break
            if summary.user != user or summary.thread in threads:
                continue
            text = self._read(self._record(summary.id))
            if written in text.lower() and (found := snippet(said(self._parse(text)), query)):
                hits.append(Hit(summary.thread, found))
                threads.add(summary.thread)
        return hits

    async def revision(self) -> int:
        try:
            return self.revision_path.stat().st_mtime_ns
        except FileNotFoundError:
            return 0

    def _touch(self) -> None:
        """Moves the revision forward, even within one clock tick."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.revision_path.touch()
        now = time.time_ns()
        try:
            last = self._last_revision
        except AttributeError:
            last = 0
        self._last_revision = max(now, last + 1)
        os.utime(self.revision_path, ns=(self._last_revision, self._last_revision))
