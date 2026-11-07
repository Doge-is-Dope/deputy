"""What an agent is told of its skills: one line each, and when to read one."""

from collections.abc import Iterable

SKILLS = "Skills: when your work matches a skill's description, read it with read_skill before acting, and follow it."


def section(skills: Iterable[tuple[str, str]]) -> str:
    """The system prompt's list of skills, by name and description."""
    return "\n".join([SKILLS, *(f"- {name}: {description}" for name, description in skills)])
