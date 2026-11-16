"""Commands on the Windows machine itself, run by the Windows Tools host there. Optional: without it the agent has
the screen, mouse and keyboard alone."""

from typing import Protocol


class HostError(Exception):
    """A call the host refused or that did not come back. `sent` is False when it surely never ran; otherwise it
    may have, and nothing sends it again."""

    def __init__(self, code: str, message: str, *, sent: bool = True):
        super().__init__(message)
        self.code, self.sent = code, sent


class Channel(Protocol):
    """How calls reach the host. `target` is the session and lease a call is meant for, as the host described it:
    a call for another is refused there rather than run."""

    async def call(self, method: str, target: dict | None = None, args: dict | None = None, *, timeout: float = 5) -> dict: ...
