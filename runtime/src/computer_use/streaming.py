"""Ordered, bounded delivery to each live viewer, independent of the active run's lifetime."""

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
