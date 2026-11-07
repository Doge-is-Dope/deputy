"""What the main agent is told of memory: how to write it, when the user lets it learn, and what it remembers, when
the user lets it use that; and how a task handed over hears the rules it was given."""

from collections.abc import Sequence

from computer_use.memory import Memory

# A correction, or a confirmed approach, kept with why and when it applies.
REMEMBER = """\
## Memory

You can remember rules for this user with remember, and drop one with forget.

- Remember when the user corrects how you or an agent worked ("not that, use X", a declined step's reason, taking \
over to do it another way), or confirms that an approach that was not obvious was right. Remember it only if it \
should hold beyond this one time; a one-off choice for this task is not a rule.
- Write the rule as one short instruction, why as the user gave it (their words, or the declined step's note), and \
when it applies (the kind of task, app or site).
- Before adding one, check what you remember: if a rule covers the same thing, replace it rather than adding \
another, and replace one the user now contradicts.
- Do not remember what the screen or the conversation already shows, passwords, codes or other personal data, or \
anything learned from a takeover the agent asked for (a sign-in, a CAPTCHA, a payment).
- Remember it for the project when the conversation is in one; for the user everywhere only when they say it always \
holds, or the same rule comes up in a second project.
- Remembering is quiet: the user sees it under your reply. Do not announce it, and do not ask before remembering.
"""

RECALLED = """\
## What you remember for this user

Rules learned from the user's corrections, oldest first. Follow those that apply. When you hand work over that a \
rule applies to, pass its id in `rules`: the agent gets the rule word for word.
"""

HANDED = "Rules the user taught, which apply to this task; follow them:"


def line(memory: Memory) -> str:
    scope = "this project" if memory.project else "everywhere"
    return f"- [{memory.id}] {memory.text} (why: {memory.why}; applies: {memory.applies}; {scope})"


def recalled(memories: Sequence[Memory]) -> str:
    """The section of the main agent's system prompt listing what it remembers; empty with nothing to list."""
    return RECALLED + "\n".join(line(memory) for memory in memories) if memories else ""


def handed(memories: Sequence[Memory]) -> str:
    """The rules a task was handed over with, word for word, for the opening of the agent that does it."""
    listed = "\n".join(f"- {memory.text} (why: {memory.why}; applies: {memory.applies})" for memory in memories)
    return f"{HANDED}\n{listed}" if memories else ""
