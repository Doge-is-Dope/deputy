"""Screen judge contract: a fast yes or no about screens, for checks between inputs that do not call the agent's model.

DecisionsJudge (desktop.decisions) asks OpenAI's Decisions API; adapters.build_screen_judge picks it, or none. Without
a judge, press_while is not offered and a key on a screen that changed is refused as before."""

from typing import Protocol


class ScreenJudge(Protocol):
    """Answers are False when the judge is unsure or cannot be reached, so the caller keeps its cautious default."""

    async def holds(self, png: bytes, condition: str) -> bool: ...  # the condition, a statement about the screen
    async def same_screen(self, before: bytes, after: bytes) -> bool: ...  # after is before with only motion changed
