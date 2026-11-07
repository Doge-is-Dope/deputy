"""Memories in MongoDB, one document each, unique by (user, id) so users never collide."""

import time
from dataclasses import asdict

from pymongo import ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase

from computer_use.memory import EDITABLE, NAME, Memory, Source

NO_ID = {"_id": 0}
# Unique keys first; storage.mongo.connect makes them.
INDEXES = {"memories": [(["user", "id"], True), (["user", "created"], False)]}


class MongoMemoryStore:
    def __init__(self, database: AsyncDatabase):
        self.memories = database.memories

    async def close(self) -> None:
        await self.memories.database.client.close()

    async def list(self, user: str) -> list[Memory]:
        return [read(doc) async for doc in self.memories.find(_of(user), NO_ID).sort("created")]

    async def get(self, user: str, id: str) -> Memory | None:
        found = await self.memories.find_one(_of(user, id=id), NO_ID)
        return read(found) if found else None

    async def save(self, memory: Memory) -> None:
        if not NAME.fullmatch(memory.id):
            raise ValueError(f"not a memory id: {memory.id!r}")
        await self.memories.replace_one(_of(memory.user, id=memory.id), asdict(memory), upsert=True)

    async def update(self, user: str, id: str, **changes: str) -> Memory | None:
        found = await self.memories.find_one_and_update(
            _of(user, id=id),
            {"$set": {**{name: changes[name] for name in EDITABLE if name in changes}, "updated": time.time()}},
            NO_ID, return_document=ReturnDocument.AFTER,
        )
        return read(found) if found else None

    async def delete(self, user: str, id: str) -> bool:
        return (await self.memories.delete_one(_of(user, id=id))).deleted_count == 1

    async def reset(self, user: str) -> int:
        return (await self.memories.delete_many(_of(user))).deleted_count

    async def used(self, user: str, ids: list[str]) -> None:
        await self.memories.update_many(
            _of(user, id={"$in": ids}), {"$inc": {"uses": 1}, "$set": {"last_used": time.time()}},
        )


def read(doc: dict) -> Memory:
    return Memory(**doc | {"source": Source(**doc["source"])})


def _of(user: str, **fields) -> dict:
    """A query for a user's memories; ValueError for a malformed id."""
    if not NAME.fullmatch(user):
        raise ValueError(f"not a user id: {user!r}")
    return {"user": user, **fields}
