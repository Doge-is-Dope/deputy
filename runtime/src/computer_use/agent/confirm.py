"""Hold flagged input actions until the user or auto reviewer approves them.

Approval covers one call; silence never approves. Flags are validated with the
tool schema, and actions needing approval must be sent outside batches.
Auto review settings are read for each step."""

import json
import time
from collections.abc import Awaitable, Callable

from langchain_core.messages import ToolMessage
from pydantic import ValidationError

from computer_use.agent.review import Verdict
from computer_use.agent.tools import not_executed
from computer_use.desktop.actions import CONFIRMABLE, KEYBOARD
from computer_use.agent.trajectory import Trajectory, shown_args
from computer_use.computers import ComputerError
from computer_use.desktop.control import Approval, ApprovalFile, Control
from computer_use.desktop.executor import Executor
from computer_use.desktop.screen import mark
from computer_use.prompts.computer import BATCHED, TOOK_CONTROL, UNEXPLAINED, declined

# Stop the task after three declined steps.
MAX_DECLINES = 3


class Confirmations:
    """The steps of one task that ask for the user's approval, each held until they answer, or until auto review lets
    it through (`review`: the step and its marked screen in, a verdict out) while the user has it on (`auto`, asked as
    each step comes up)."""

    def __init__(
        self,
        approvals: ApprovalFile,
        control: Control,
        executor: Executor,
        log: Trajectory,
        review: Callable[[str, bytes | None], Awaitable[Verdict]] | None = None,
        auto: Callable[[], bool] = lambda: True,
    ):
        self.approvals = approvals
        self.control = control
        self.executor = executor
        self.log = log
        self.review = review
        self.auto = auto
        self.declined = 0  # steps the user declined in this task

    @property
    def exhausted(self) -> bool:
        """The user declined MAX_DECLINES steps: the task ends, and the main agent hears why."""
        return self.declined >= MAX_DECLINES

    async def check(self, request) -> ToolMessage | None:
        """Why the call must not run, as its result for the agent; or None once it may: it needs no approval, the user
        approved it, or its arguments are wrong, which the tool itself reports without sending anything."""
        call = request.tool_call
        if call["name"] not in CONFIRMABLE or request.tool is None:
            return None
        try:
            args = request.tool.tool_call_schema.model_validate(call["args"]).model_dump()
        except ValidationError:
            return None
        if not args["needs_confirmation"]:
            return None
        if call["name"] == "computer_batch":
            return not_executed(call, BATCHED, "batched")
        consequence = " ".join((args["consequence"] or "").split())
        if not consequence:
            return not_executed(call, UNEXPLAINED, "unexplained")
        png = await self._marked(call["name"], args)
        auto = self.review is not None and self.auto()
        screenshot = self.log.confirm(call, consequence, png, auto)
        if auto and await self._reviewed(call, consequence, png):
            self.executor.approve_next()
            return None
        self.approvals.ask(Approval(call["id"], self.log.run, call["name"], consequence, screenshot, time.time()))
        try:
            answer = await self.approvals.wait(call["id"], self.control)
        finally:  # a run stopped while it waits leaves nothing to answer
            self.approvals.clear(call["id"])
        if answer is None:
            self.log.decision(call["id"], "took_control")
            return not_executed(call, TOOK_CONTROL, "tookControl")
        if answer.decision == "approve":
            self.log.decision(call["id"], "approved", by=answer.by)
            self.executor.approve_next()
            return None
        self.declined += 1
        self.log.decision(call["id"], "declined", answer.note, answer.by)
        return not_executed(call, declined(answer.note), "declined")

    async def _reviewed(self, call: dict, consequence: str, png: bytes | None) -> bool:
        """Whether auto review lets the step through."""
        step = (
            f"{call['name']} {json.dumps(shown_args(call['args']), ensure_ascii=False)}\n"
            f"The computer-use agent's description of it (its claim, to check against the screen): {consequence}"
        )
        verdict = await self.review(step, png)
        self.log.review(call["id"], verdict.allow, verdict.review)
        if verdict.allow:
            self.log.decision(call["id"], "approved", verdict.review.get("reason", ""), "auto")
        return verdict.allow

    async def _marked(self, name: str, args: dict) -> bytes | None:
        """The screen the agent decided from, where the step acts marked: its points, or the pointer for a click without
        one. Keys go wherever the focus is, so they mark nothing."""
        shown = self.executor.shown
        if shown is None:
            return None
        points = [tuple(args[key]) for key in ("start_coordinate", "coordinate") if args.get(key)]
        if not points and name not in KEYBOARD:
            try:
                points = [await self.executor.computer.cursor_position()]
            except ComputerError:  # the screen still shows what the step would act on
                points = []
        return mark(shown.png, points)
