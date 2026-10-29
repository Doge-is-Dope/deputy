"""The main agent's tools for memory: remember a rule, or forget one."""

import time
import uuid
from dataclasses import replace
from typing import Annotated, Literal

from langchain_core.tools import BaseTool, tool
from pydantic import Field

from computer_use.memory import KINDS, MAX_TEXT, Kind, Memory, MemoryStore, Source

REMEMBER = "remember"
FORGET = "forget"


def memory_tools(store: MemoryStore, user: str, project: str | None, thread: str, run: str) -> list[BaseTool]:
    """The tools for `user`'s memories, in a run of conversation `thread` in `project` (None for none)."""

    @tool(REMEMBER)
    async def remember(
        rule: Annotated[str, Field(description="The rule, as one short instruction in the user's language.")],
        why: Annotated[str, Field(description="Why, as the user gave it: their words, or the declined step's note.")],
        applies: Annotated[str, Field(description="When it applies: the kind of task, app or site.")],
        scope: Annotated[Literal["project", "personal"], Field(
            description="project: only this project's conversations; personal: everywhere."
        )],
        learned_from: Annotated[Kind, Field(
            description="steer: a message sent while work ran; decline: a declined step's reason; takeover: the user "
                        "took over and did it another way; said: anything else the user said."
        )],
        replaces: Annotated[str | None, Field(description="The id of a rule this one replaces, if any.")] = None,
    ) -> str:
        """Remember a rule the user taught by correcting how the work was done, for this and later conversations."""
        if scope == "project" and project is None:
            return "Not remembered: this conversation is in no project. Remember it as personal, or not at all."
        if learned_from not in KINDS:
            return f"Not remembered: learned_from is one of {', '.join(KINDS)}."
        now = time.time()
        fields = {
            "text": " ".join(rule.split())[:MAX_TEXT],
            "why": " ".join(why.split())[:MAX_TEXT],
            "applies": " ".join(applies.split())[:MAX_TEXT],
            "project": project if scope == "project" else None,
            "source": Source(thread, run, learned_from),
            "updated": now,
        }
        if not fields["text"]:
            return "Not remembered: the rule is empty."
        old = await store.get(user, replaces) if replaces else None
        if replaces and old is None:
            return f"Not remembered: there is no rule {replaces} to replace."
        memory = replace(old, **fields) if old else Memory(id=uuid.uuid4().hex, user=user, created=now, **fields)
        await store.save(memory)
        return f"Remembered as {memory.id}."

    @tool(FORGET)
    async def forget(id: Annotated[str, Field(description="The id of the rule to drop.")]) -> str:
        """Forget a rule, when the user asks you to or it no longer holds."""
        return f"Forgot {id}." if await store.delete(user, id) else f"There is no rule {id}."

    return [remember, forget]
