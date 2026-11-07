"""The structured part of the run log the web interface reads; text never identifies a state or a refusal."""

from typing import Literal, TypedDict

NoteCode = Literal[
    "userControl", "controlReturned", "disconnected", "reconnected", "interrupted", "stuck", "declined", "gone",
    "unusable", "runnerUnusable", "takeoverRequested", "runFinished", "runStopped", "runFailed", "goal", "memoryUsed",
]
ActionReason = Literal[
    "userControl", "userActed", "screenChanged", "disconnected", "declined", "tookControl", "batched",
    "unexplained", "desktopBusy", "taskLimit", "computerInUse", "tooManyTasks", "noTask",
]

CONFIRM_FIELDS = ("needs_confirmation", "consequence")


class NoteData(TypedDict, total=False):
    seconds: float
    count: int
    tool: str
    rules: list[dict[str, str]]


class NoteEvent(TypedDict):
    type: Literal["note"]
    text: str
    code: NoteCode | None
    data: NoteData


def shown_args(args: dict) -> dict:
    """An action's arguments as people read them: without the approval fields or those left empty, which in a
    batch's actions are most of them and once cut the text it typed out of an action's line (2026-10-08)."""
    shown = {key: value for key, value in args.items() if key not in CONFIRM_FIELDS and value is not None}
    if isinstance(shown.get("actions"), list):
        shown["actions"] = [
            {key: value for key, value in step.items() if value is not None} if isinstance(step, dict) else step
            for step in shown["actions"]
        ]
    return shown
