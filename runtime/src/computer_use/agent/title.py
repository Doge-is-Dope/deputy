"""Name conversations from their first message in a background model call.

Title jobs belong to the runtime and survive run completion or cancellation.
A later run may retry a failed title."""

import asyncio
import re
import time
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field

from computer_use.agent.models import build_chat_model, clamp, efforts
from computer_use.agent.trajectory import usage_of
from computer_use.config import Choice, Settings
from computer_use.prompts.title import TITLE_PROMPT
from computer_use.agent.history import has_title
from computer_use.storage import RunStore

if TYPE_CHECKING:
    from computer_use.agent.trajectory import Trajectory

# The title model when the settings name none, and its effort (or the lowest the model takes), whatever the agents'
# are: a title needs little reasoning.
MODEL = "openai:gpt-6-luna"
EFFORT = "low"
# As much of a long first message as the model reads.
MESSAGE_CHARS = 2000
# A title longer than this is cut: the sidebar shows a few dozen characters.
MAX_CHARS = 80
# The title call's own timeout, independent of the main agent's lifetime.
CALL_SECONDS = 30

QUOTES = "\"'“”‘’「」『』«»"
TRAILING = ".。!！?？…"


class Title(BaseModel):
    """A short conversation title for the sidebar."""

    model_config = ConfigDict(extra="forbid")
    # Not limited in length: `clean` cuts a long title to MAX_CHARS rather than losing it.
    title: str = Field(description="The conversation's name")


def clean(text: str) -> str | None:
    """The title in a model's reply: its first line without quotes, markdown marks or final punctuation, cut to
    MAX_CHARS; None when nothing is left."""
    line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    line = re.sub(r"^(?:title\s*[:：]\s*)", "", line, flags=re.IGNORECASE)
    line = line.strip().strip(QUOTES).strip().lstrip("#*- ").rstrip("*").strip().rstrip(TRAILING).strip(QUOTES).strip()
    line = " ".join(line.split())
    if len(line) > MAX_CHARS:
        line = line[:MAX_CHARS].rstrip()
    return line or None


def title_model(settings: Settings) -> Choice:
    """The model that names conversations, whatever the user chose for the agents: the settings' title model, else
    MODEL; at EFFORT, or the lowest effort it takes."""
    model = settings.title_model or MODEL
    return Choice(model, clamp(EFFORT, efforts(model)))


async def generate_title(
    settings: Settings, message: str, choice: Choice | None = None
) -> tuple[str, dict[str, int]] | None:
    """A title for a conversation that opens with `message`, by `choice` (by default `title_model`), and the tokens it
    took; None when the model's reply held none, or the call failed or took too long, which is said on the terminal
    and is otherwise no error."""
    prompt = [SystemMessage(TITLE_PROMPT), HumanMessage(message[:MESSAGE_CHARS])]
    try:
        model = build_chat_model(choice or title_model(settings), settings)
        reply = await asyncio.wait_for(
            model.with_structured_output(Title, method="json_schema", strict=True, include_raw=True).ainvoke(prompt),
            CALL_SECONDS,
        )
        parsed = reply.get("parsed")
        if reply.get("parsing_error") or not isinstance(parsed, Title):
            raise ValueError(f"unreadable title: {reply.get('parsing_error')}")
        title = clean(parsed.title)
        return (title, usage_of(reply["raw"])) if title else None
    except asyncio.CancelledError:
        raise
    except Exception as error:
        print(f"      (no title: {type(error).__name__}: {error})", flush=True)
        return None


async def name(settings: Settings, store: RunStore, log: "Trajectory", thread: str) -> None:
    """Title the conversation `thread` from its first message, in this run's log, by the independent `title_model`,
    unless it is named already. A new conversation, whose first run this is, has no name to look for."""
    if thread != log.run and await has_title(store, thread):
        return
    events = await store.events(thread)
    message = events[0]["goal"]
    started, choice = time.monotonic(), title_model(settings)
    named = await generate_title(settings, message, choice)
    # Not one deleted meanwhile, whose runs went to the trash together, nor one the user named meanwhile.
    if named is not None and log.run in await store.conversation(thread) and not await has_title(store, thread):
        title, usage = named
        log.title(title, usage, time.monotonic() - started, choice.model)


class Titles:
    """Runtime-owned title jobs, at most one per conversation, independent of agent runs."""

    def __init__(self, settings: Settings, store: RunStore):
        self.settings = settings
        self.store = store
        self.tasks: dict[str, asyncio.Task] = {}

    def start(self, log: "Trajectory", thread: str) -> None:
        """Name the conversation in the background, into this run's log, unless it is named or being named. A title
        that cannot be made is no error for the run."""
        if thread in self.tasks:
            return
        task = asyncio.create_task(name(self.settings, self.store, log, thread))
        self.tasks[thread] = task

        def finished(done: asyncio.Task) -> None:
            self.tasks.pop(thread, None)
            if not done.cancelled() and (error := done.exception()) is not None:
                print(f"      (no title: {type(error).__name__}: {error})", flush=True)

        task.add_done_callback(finished)

    async def close(self, *, cancel: bool = True) -> None:
        """At process shutdown only: cancel jobs, or wait until they finish."""
        tasks = list(self.tasks.values())
        if cancel:
            for task in tasks:
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
