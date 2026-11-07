"""Ordered, bounded delivery to each live viewer, and the reply being written, as a snapshot and updates."""

import asyncio
import json
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass(frozen=True)
class StreamEvent:
    kind: str
    data: dict
    index: int | None = None

    @property
    def size(self) -> int:
        return len(json.dumps(self.data, ensure_ascii=False).encode("utf-8"))


class Subscription:
    def __init__(self, limit: int):
        self.limit = limit
        self.pending: deque[tuple[StreamEvent, int]] = deque()
        self.bytes = 0
        self.ready = asyncio.Event()
        self.overflow = False

    def put(self, event: StreamEvent, size: int) -> None:
        if self.overflow:
            return
        if self.bytes + size > self.limit:
            # End this connection without "done": the client reconnects from its durable cursor and gets a snapshot.
            self.pending.clear()
            self.bytes = 0
            self.overflow = True
        else:
            self.pending.append((event, size))
            self.bytes += size
        self.ready.set()

    async def get(self) -> StreamEvent:
        await self.ready.wait()
        if self.overflow:
            return StreamEvent("resync", {})
        event, size = self.pending.popleft()
        self.bytes -= size
        if not self.pending:
            self.ready.clear()
        return event


class LiveStream:
    def __init__(self, limit: int = 2 * 1024 * 1024):
        self.limit = limit
        self.subscribers: set[Subscription] = set()
        self.index = 0
        self.closed = False

    def publish(self, kind: str, data: dict, index: int | None = None) -> None:
        if self.closed:
            return
        event = StreamEvent(kind, data, index)
        if self.subscribers:
            size = event.size
            for subscriber in tuple(self.subscribers):
                subscriber.put(event, size)
                if subscriber.overflow:
                    self.subscribers.discard(subscriber)

    def record(self, event: dict) -> None:
        self.publish("line", event, self.index)
        self.index += 1

    def close(self) -> None:
        self.publish("done", {})
        self.closed = True

    @contextmanager
    def subscribe(self):
        subscriber = Subscription(self.limit)
        if self.closed:
            subscriber.put(StreamEvent("done", {}), 0)
        else:
            self.subscribers.add(subscriber)
        try:
            yield subscriber
        finally:
            self.subscribers.discard(subscriber)


class Draft:
    """What the main agent has written so far in the model call under way, empty between calls. `call` is LangGraph's
    checkpoint namespace for it; `final` is whether its model said it writes the final reply. Viewers get it whole
    ("draft") when a call starts or restarts, then each piece ("delta")."""

    def __init__(self):
        self.call = ""
        self.text = ""
        self.final = False
        self.stream = LiveStream()

    def add(self, call: str, text: str) -> None:
        if call != self.call:
            self.call, self.text, self.final = call, text, False
            self._whole()
        else:
            self.text += text
            self.stream.publish("delta", {"text": text})

    def answer(self, call: str) -> None:
        if call != self.call:
            self.call, self.text = call, ""
        self.final = True
        self._whole()

    def restart(self) -> None:
        """Takes back what the call under way wrote, for viewers too, as it is tried again."""
        taken = self.text or self.final
        self.clear()
        if taken:
            self._whole()

    def clear(self) -> None:
        self.call, self.text, self.final = "", "", False

    def _whole(self) -> None:
        self.stream.publish("draft", {"text": self.text, "final": self.final})


@dataclass(frozen=True)
class View:
    """A viewer's hold on a run in progress."""

    updates: Subscription
    draft: str
    seen: int  # the lines before the updates, which the store has
    final: bool = False


class Live:
    """Streams the runs in progress in this process, each turn's and task's on its own.
    Other servers' runs are not here."""

    def __init__(self):
        self.streams: dict[str, LiveStream] = {}
        self.drafts: dict[str, Draft] = {}

    def open(self, run: str, draft: Draft | None = None) -> None:
        self.streams[run] = stream = LiveStream()
        if draft is not None:
            draft.stream = stream
            self.drafts[run] = draft

    def publish(self, run: str, event: dict) -> None:
        if (stream := self.streams.get(run)) is not None:
            stream.record(event)

    def close(self, run: str) -> None:
        self.drafts.pop(run, None)
        if (stream := self.streams.pop(run, None)) is not None:
            stream.close()

    @contextmanager
    def watch(self, run: str):
        """Subscribe and capture the draft and the lines so far without yielding to other tasks, so the lines before
        the updates are the ones the store has. Yields None if this process is not running the requested run."""
        stream = self.streams.get(run)
        if stream is None:
            yield None
            return
        draft = self.drafts.get(run)
        with stream.subscribe() as updates:
            yield View(updates, draft.text if draft is not None else "", stream.index, draft is not None and draft.final)
