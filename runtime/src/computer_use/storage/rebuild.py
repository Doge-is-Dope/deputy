"""`python -m computer_use.storage.rebuild [--user ID]`: remakes a database store's runs and conversations from the
events, using the runtime's settings. Stop every runtime writing to the database first. A store without `rebuild`, as
the files store, has nothing to remake."""

import argparse
import asyncio
from typing import Protocol

from computer_use.config import Settings, get_settings
from computer_use.adapters import build_stores
from computer_use.storage import user_id


class Rebuilds(Protocol):
    async def users(self) -> list[str]: ...

    async def rebuild(self, user: str) -> tuple[int, int]:
        """How many runs and conversations the user has."""

    async def close(self) -> None: ...


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m computer_use.storage.rebuild",
        description="Make the runs and conversations again from the events in the database.",
    )
    parser.add_argument("--user", type=user_id, help="only this user's (their id); everyone's when left out")
    return parser


def main(argv: list[str] | None = None, settings: Settings | None = None) -> int:
    args = build_parser().parse_args(argv)
    store, _, _ = build_stores(settings or get_settings())
    if not hasattr(store, "rebuild"):
        print("This store reads its runs off the records each time: nothing to rebuild.")
        return 0
    asyncio.run(rebuild(store, args.user))
    return 0


async def rebuild(store: Rebuilds, user: str | None) -> None:
    try:
        for each in [user] if user else await store.users():
            runs, conversations = await store.rebuild(each)
            print(f"{each}: {runs} runs, {conversations} conversations")
    finally:
        await store.close()


if __name__ == "__main__":
    raise SystemExit(main())
