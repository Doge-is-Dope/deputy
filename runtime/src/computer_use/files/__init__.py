"""Where runs' files (screenshots, thumbnails) are kept, apart from their records. Keys are
users/<user>/runs/<run>/<name>, so a user's or a run's files share a prefix. LocalFileStore (files.local) keeps them
under the data folder; adapters.build_file_store picks it."""

from typing import Protocol



class FileStore(Protocol):
    async def put(self, key: str, data: bytes) -> None:
        """Stores a file, replacing any with the same key."""

    async def get(self, key: str) -> bytes:
        """A file; FileNotFoundError if missing."""

    async def delete_prefix(self, prefix: str) -> None:
        """Erases every file under `prefix`, a folder ending in "/" (as `run_key` makes); none is no error."""


def run_key(user: str, run: str, name: str = "") -> str:
    """A run file's key, or without a name the run's prefix."""
    return f"users/{user}/runs/{run}/{name}"
