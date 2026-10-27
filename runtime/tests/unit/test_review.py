"""Auto review: a reviewer answers a step flagged for approval before the user is asked. It lets a step through only
on its own "allow" for a step neither high risk nor beyond what the user's words cover; a review that fails, takes too
long or cannot be read leaves the step to the user."""

import asyncio

import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError

import computer_use.agent.review as review
from computer_use.agent.review import Review, review_step
from computer_use.prompts.review import REVIEW_PROMPT
from computer_use.agent.history import action_lines, action_records
from conftest import fixture_png


class ReviewerModel:
    """A model that answers every review the same way, or fails, and keeps what it was asked. An answer given as its
    fields is read as LangChain's structured output reads one with include_raw: one it cannot read parses to None."""

    def __init__(self, answer: Review | dict | None = None, error: Exception | None = None, delay: float = 0):
        self.answer, self.error, self.delay = answer, error, delay
        self.asked: list = []

    def with_structured_output(self, schema, include_raw=False):
        assert schema is Review and include_raw
        return self

    async def ainvoke(self, messages):
        self.asked.append(messages)
        await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        raw = AIMessage(content="", usage_metadata={"input_tokens": 900, "output_tokens": 40, "total_tokens": 940})
        parsed, error = self.answer, None if self.answer else "no JSON"
        if isinstance(self.answer, dict):
            try:
                parsed = Review.model_validate(self.answer)
            except ValidationError as invalid:
                parsed, error = None, invalid
        return {"raw": raw, "parsed": parsed, "parsing_error": error}


def answer(decision="allow", risk="low", authorization="high", target="", evidence="") -> Review:
    return Review(risk=risk, authorization=authorization, decision=decision, reason="使用者要刪除自己剛建立的檔案",
                  target=target, evidence=evidence)


async def test_a_step_goes_ahead_on_the_reviewers_allow_with_its_reason():
    model = ReviewerModel(answer())

    verdict = await review_step(model, "Goal: 建立再刪掉 a.txt", 'key {"text": "Delete"}', fixture_png("shot"))

    assert verdict.allow
    assert verdict.review["reason"] == "使用者要刪除自己剛建立的檔案"
    assert verdict.review["usage"]["input"] == 900
    (system, question), = model.asked
    assert system.content == REVIEW_PROMPT
    text, image = question.content
    assert "Goal: 建立再刪掉 a.txt" in text["text"] and 'key {"text": "Delete"}' in text["text"]
    assert image["type"] == "image"


@pytest.mark.parametrize("decision, risk, authorization", [
    ("ask", "low", "high"),
    ("allow", "high", "high"),  # its allow is not enough for what is hard to undo
    ("allow", "low", "low"),  # nor for what the user's words do not cover
    ("allow", "medium", "unknown"),
])
async def test_anything_else_is_left_to_the_user(decision, risk, authorization):
    verdict = await review_step(ReviewerModel(answer(decision, risk, authorization)), "", "step", None)

    assert not verdict.allow


async def test_a_review_that_fails_or_takes_too_long_or_makes_no_sense_leaves_it_to_the_user(monkeypatch):
    monkeypatch.setattr(review, "REVIEW_SECONDS", 0.05)

    down = await review_step(ReviewerModel(error=ConnectionError("model service down")), "", "step", None)
    slow = await review_step(ReviewerModel(answer(), delay=1), "", "step", None)
    unreadable = await review_step(ReviewerModel(None), "", "step", None)

    assert not (down.allow or slow.allow or unreadable.allow)
    assert "model service down" in down.review["error"]
    assert "within" in slow.review["error"] and "unreadable" in unreadable.review["error"]


async def test_an_answer_that_leaves_out_the_target_cannot_be_read_so_the_user_is_asked():
    fields = {"risk": "low", "authorization": "high", "decision": "allow", "reason": "這一步沒有刪除任何東西"}

    left_out = await review_step(ReviewerModel(fields), "", "step", None)
    empty = await review_step(ReviewerModel(fields | {"target": ""}), "", "step", None)

    assert not left_out.allow and "unreadable" in left_out.review["error"]
    # An empty target is an answer: the reviewer's own call that the step deletes nothing, which no check confirms.
    assert empty.allow


# Where what a step deletes must be named: the user's messages and the arguments of the recorded actions.
SOURCES = ["把桌面上的 txt 檔都刪掉", "建立 b.txt 再刪掉", 'type {"text": "a.txt"}']


@pytest.mark.parametrize("target, evidence", [
    ("a.txt", 'type {"text": "a.txt"}'),  # the recorded action that created it
    ("b.txt", "建立 b.txt 再刪掉"),  # the user's words naming it
    ("a.txt", '{"text": "a.txt"}'),  # a quote of the record reworded, as it came back live (2026-10-08)
])
async def test_a_deletion_goes_ahead_when_the_user_or_a_recorded_action_names_its_target(target, evidence):
    verdict = await review_step(ReviewerModel(answer(target=target, evidence=evidence)), "", "step", None, SOURCES)

    assert verdict.allow


@pytest.mark.parametrize("target, evidence", [
    # Live (2026-10-08): "the txt files on the desktop" let through a file the user never named.
    ("internet.txt", "把桌面上的 txt 檔都刪掉"),
    ("report.txt", "請刪除 report.txt"),  # words no user or record said: the main agent's, say
    ("report.txt", ""),
])
async def test_a_deletion_neither_names_is_left_to_the_user(target, evidence):
    verdict = await review_step(ReviewerModel(answer(target=target, evidence=evidence)), "", "step", None, SOURCES)

    assert not verdict.allow


@pytest.mark.parametrize("target, source", [
    ("B.TXT", "建立 b.txt 再刪掉"),  # Windows would take it for the same file; asking once more is the safe side
    ("a  b.txt", "建立 a b.txt 再刪掉"),  # two spaces are another name than one
    ("a b.txt", "建立 a  b.txt 再刪掉"),
    ("Straße.txt", "建立 Strasse.txt 再刪掉"),
    ("a.txt ", 'type {"text": "a.txt"}'),  # spaces around a name are part of it, not trimmed
    (" a.txt", 'type {"text": "a.txt"}'),
])
async def test_a_name_counts_only_as_written(target, source):
    verdict = await review_step(ReviewerModel(answer(target=target)), "", "step", None, [source])

    assert not verdict.allow


@pytest.mark.parametrize("target", ["", "  "])
async def test_a_step_the_reviewer_says_deletes_nothing_skips_the_name_check(target):
    # Only the reviewer judges that it deletes nothing; a blank target is no name to look for.
    verdict = await review_step(ReviewerModel(answer(target=target)), "", "step", None, SOURCES)

    assert verdict.allow


def test_the_records_hold_what_the_agent_did_not_what_it_said():
    events = [
        {"type": "model", "text": "I'll delete internet.txt now.", "tool_calls": []},
        {"type": "action", "id": "c1", "tool": "key", "args": {"text": "Delete", "needs_confirmation": True,
                                                               "consequence": "刪除 internet.txt"},
         "status": "success", "result": "Pressed delete. internet.txt is gone."},
        {"type": "action", "agent": "main", "id": "m1", "tool": "computer_use", "args": {"task": "刪除 internet.txt"},
         "status": "success", "result": ""},
    ]

    assert action_records(events) == ['key {"text": "Delete"}']


async def test_only_input_that_was_sent_counts_as_a_record():
    def action(tool: str, args: dict, status: str | None, result: str = "", **extra) -> dict:
        event = {"type": "action", "id": tool, "tool": tool, "args": args, "result": result, **extra}
        return event | ({"status": status} if status is not None else {})

    saved = [{"action": "type", "text": "b.txt"}, {"action": "key", "text": "enter"}]
    stopped = [{"action": "type", "text": "partial.txt"}, {"action": "key", "text": "enter"}]
    events = [
        action("type", {"text": "sent.txt"}, "success", "Typed."),
        action("type", {"text": "failed.txt"}, "error", "Not executed: the screen changed since your last screenshot."),
        action("type", {"text": "declined.txt"}, "error", "Not executed: the user declined this step."),
        action("type", {"text": "unknown.txt"}, None),  # no status: whether it went out is not known
        action("computer_batch", {"actions": stopped}, "error", "Stopped at action 2 of 2: the screen changed"),
        action("computer_batch", {"actions": saved}, "success", "1. Typed.\n2. Pressed enter."),
        action("computer_use", {"task": "建立 main.txt"}, "success", agent="main"),
    ]

    records = action_records(events)

    assert records == [
        'type {"text": "sent.txt"}',
        'computer_batch {"actions": [{"action": "type", "text": "b.txt"}, {"action": "key", "text": "enter"}]}',
    ]
    # A name typed only where the input never went out is asked of the user.
    for target, allowed in [("sent.txt", True), ("b.txt", True), ("failed.txt", False), ("declined.txt", False),
                            ("unknown.txt", False), ("partial.txt", False), ("main.txt", False)]:
        verdict = await review_step(ReviewerModel(answer(target=target)), "", "step", None, records)
        assert verdict.allow is allowed, target


def test_a_batchs_record_keeps_the_name_it_typed():
    # Live (2026-10-08): the empty fields of a batch's actions filled its line, cut at 200 characters before the file
    # name it typed, so auto review found no record that this conversation made the file.
    empty = dict.fromkeys(("coordinate", "start_coordinate", "scroll_direction", "scroll_amount", "repeat", "duration"))
    steps = [{"action": "key", **empty, "text": "ctrl+a"}, {"action": "type", **empty, "text": "cu-auto-d.txt"},
             {"action": "key", **empty, "text": "enter"}]
    event = {"type": "action", "id": "c1", "tool": "computer_batch", "args": {"actions": steps}, "status": "success",
             "result": "1. Pressed ctrl+a."}

    (line,) = action_lines([event])

    assert "cu-auto-d.txt" in line and "null" not in line


def test_the_policy_always_asks_before_sending_or_paying():
    always = REVIEW_PROMPT.split("Always ask:")[1]

    assert "Sending, posting, submitting" in always and "even when the user asked for it" in always
    assert "Buying or paying" in always

