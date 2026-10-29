"""Memories as files: data/users/<user>/memory/<id>.md, the rule as the body under a header of its other fields, one
JSON value a line, so a person can read and fix one by hand."""

import json
import os
import re
import time
from dataclasses import asdict, fields, replace
from pathlib import Path

from computer_use.memory import EDITABLE, Memory, Source

# A user's id, a memory's id: each names a folder or a file, so nothing else may.
NAME = re.compile(r"[0-9a-z]{1,64}")
HEADER = [each.name for each in fields(Memory) if each.name != "text"]


def write(memory: Memory) -> str:
    head = "\n".join(f"{name}: {json.dumps(asdict(memory)[name], ensure_ascii=False)}" for name in HEADER)
    return f"---\n{head}\n---\n{memory.text}\n"


def read(text: str) -> Memory:
    _, head, body = text.split("---\n", 2)
    values = {}
    for line in head.splitlines():
        name, value = line.split(": ", 1)
        values[name] = json.loads(value)
    values["source"] = Source(**values["source"])
    return Memory(text=body.rstrip("\n"), **values)


class FileMemoryStore:
    def __init__(self, data_dir: Path):
        self.users = data_dir / "users"

    def _folder(self, user: str) -> Path:
        if not NAME.fullmatch(user):
            raise ValueError(f"not a user id: {user!r}")
        return self.users / user / "memory"

    def _path(self, user: str, id: str) -> Path | None:
        return self._folder(user) / f"{id}.md" if NAME.fullmatch(id) else None

    async def list(self, user: str) -> list[Memory]:
        folder = self._folder(user)
        memories = [read(path.read_text(encoding="utf-8")) for path in folder.glob("*.md")] if folder.exists() else []
        return sorted(memories, key=lambda memory: memory.created)

    async def get(self, user: str, id: str) -> Memory | None:
        path = self._path(user, id)
        try:
            return read(path.read_text(encoding="utf-8")) if path else None
        except FileNotFoundError:
            return None

    async def save(self, memory: Memory) -> None:
        path = self._path(memory.user, memory.id)
        if path is None:
            raise ValueError(f"not a memory id: {memory.id!r}")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(write(memory), encoding="utf-8")
        os.replace(temporary, path)

    async def update(self, user: str, id: str, **changes: str) -> Memory | None:
        memory = await self.get(user, id)
        if memory is None:
            return None
        changed = replace(memory, **{name: changes[name] for name in EDITABLE if name in changes}, updated=time.time())
        await self.save(changed)
        return changed

    async def delete(self, user: str, id: str) -> bool:
        path = self._path(user, id)
        if path is None or not path.exists():
            return False
        path.unlink()
        return True

    async def reset(self, user: str) -> int:
        paths = list(self._folder(user).glob("*.md")) if self._folder(user).exists() else []
        for path in paths:
            path.unlink()
        return len(paths)

    async def used(self, user: str, ids: list[str]) -> None:
        now = time.time()
        for id in ids:
            if (memory := await self.get(user, id)) is not None:
                await self.save(replace(memory, uses=memory.uses + 1, last_used=now))
