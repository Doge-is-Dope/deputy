"""Files under a folder, each key a path below it. Reads and writes stay on the event loop (well under a millisecond);
erasing a prefix runs in a worker thread."""

import asyncio
import shutil
from pathlib import Path, PurePosixPath


class LocalFileStore:
    def __init__(self, root: Path):
        self.root = root

    def _path(self, key: str) -> Path:
        parts = PurePosixPath(key).parts
        if not parts or key.startswith("/") or ".." in parts:
            raise ValueError(f"not a file key: {key!r}")
        return self.root.joinpath(*parts)

    async def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    async def get(self, key: str) -> bytes:
        try:
            return self._path(key).read_bytes()
        except (IsADirectoryError, NotADirectoryError):
            raise FileNotFoundError(key) from None

    async def delete_prefix(self, prefix: str) -> None:
        if not prefix.endswith("/"):
            raise ValueError(f"not a folder prefix: {prefix!r}")
        await asyncio.to_thread(shutil.rmtree, self._path(prefix.rstrip("/")), ignore_errors=True)
