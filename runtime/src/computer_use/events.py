"""The small structured part of the run log consumed by the web interface.

Text remains useful to people and models, but never identifies a state or a refusal.
"""

from typing import Literal, TypedDict

NoteCode = Literal[
    "userControl", "controlReturned", "disconnected", "reconnected", "interrupted", "stuck", "declined", "gone",
    "unusable", "runnerUnusable", "takeoverRequested", "runFinished", "runStopped", "runFailed", "goal",
]
ActionReason = Literal[
    "userControl", "userActed", "screenChanged", "disconnected", "declined", "tookControl", "batched",
    "unexplained", "desktopBusy", "taskLimit", "computerInUse", "tooManyTasks", "noTask",
]


class NoteData(TypedDict, total=False):
    seconds: float
    count: int
    tool: str


class NoteEvent(TypedDict):
    type: Literal["note"]
    text: str
    code: NoteCode | None
    data: NoteData
