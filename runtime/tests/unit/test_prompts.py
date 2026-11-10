"""The runtime's words are put together only by the functions in prompts/, from typed values: each, given sample values,
gives text with no slot left unfilled. A function added there later must be rendered here too."""

import importlib
import inspect
import pkgutil
import re
from typing import get_args

import pytest

from computer_use import prompts
from computer_use.middleware.desktop import Stop
from computer_use.memory import Memory, Source
from computer_use.prompts import coding, computer, main, memory, notes, review, skills

STEPS = ["clicked Start", "typed hello"]
EARLIER = [{"agent": "computer", "task": "open Notepad", "stop_reason": "replied", "reply": "", "actions": STEPS}]
RULES = [
    Memory("m1", "local", project, "Save to Documents", "they said so", "saving files", Source("t1", "r1", "said"), 0, 0)
    for project in (None, "p1")
]

RENDERS = [
    (main.start_task, (6, [("computer", computer.ABOUT), ("coding", coding.ABOUT)])),
    (computer.system_prompt, (None,)),
    (computer.system_prompt, ("zh-Hant",)),
    *[(computer.stopped, (reason, 40, 3)) for reason in ("replied", "step_limit", "error", *get_args(Stop))],
    (computer.typed_on, (4,)),
    (computer.user_had_control, (12.6,)),
    (computer.disconnected_for, (3.2,)),
    (computer.declined, (None,)),
    (computer.declined, ("not now",)),
    *[(coding.stopped, (reason, 40)) for reason in ("replied", "step_limit", "error")],
    (coding.runner_unusable, (RuntimeError("no runner"),)),
    (review.review_context, ("Goal: open Notepad", ["stop after"], STEPS)),
    (review.review_request, ("Goal: open Notepad", "press Delete")),
    (notes.started, ("t1",)),
    (notes.full, (6,)),
    (computer.computer_in_use, ("t1",)),
    (notes.message_rounds, (3,)),
    (computer.desktop_offline, ("no RDP session",)),
    (notes.no_task, ("t9",)),
    (notes.no_conversation, ("0a1b",)),
    (notes.conversation, ("User: write the notes", 0)),
    (notes.conversation, ("You: Done.", 23)),
    (notes.since_heard, (["and save it"],)),
    (notes.task_ended, ("t1", "computer", "open Notepad")),
    (notes.task_failed, ("t1", "computer", "open Notepad", "APIError: overloaded")),
    (notes.missed, (["and save it", "as a.txt"],)),
    (notes.task_running, ("t1", "computer", 75, "open Notepad", STEPS)),
    (notes.task_stopped, ("t1", "computer", "open Notepad")),
    (notes.stopped_by_user, ("t2", "coding", "add 2 and 2")),
    (notes.bad_plan, (12,)),
    (notes.plan_left, (["2"],)),
    (notes.steps_finished, (["9"],)),
    (notes.task_asks, ("t1", "computer", "Which file?")),
    (notes.plan_on_board, ([{"id": "1", "title": "Find it", "done_when": "Found", "needs": ["0"], "status": "in_progress",
                             "tasks": ["t1", "t2"]}], "t1")),
    (notes.others_at_work, ([{"id": "t2", "agent": "coding", "title": "Add", "steps": ["2"]}], "t1")),
    (notes.blackboard, (["open Notepad"], EARLIER)),
    (notes.opening, ("open Notepad", ["open notepad please"], "Earlier in this conversation")),
    (notes.opening, ("open Notepad", ["open notepad please"], "", "Rules the user taught")),
    (notes.told, (["and save it"],)),
    (notes.today, ("Asia/Taipei",)),
    (notes.today, (None,)),
    *[(notes.following, (count,)) for count in (1, 2)],
    *[(notes.stopped, (reason, 40)) for reason in ("replied", "step_limit")],
    (notes.report, ("computer-use agent", "it replied", "Done.", STEPS, "The screen now.")),
    *[(memory.line, (rule,)) for rule in RULES],
    (memory.recalled, (RULES,)),
    (memory.handed, (RULES,)),
    (skills.section, ([("windows", "Starting apps on Windows.")],)),
]


@pytest.mark.parametrize(
    ("build", "values"), RENDERS, ids=[f"{build.__module__.rsplit('.', 1)[1]}.{build.__name__}" for build, _ in RENDERS]
)
def test_each_function_fills_every_slot(build, values):
    text = build(*values)
    assert isinstance(text, str) and text
    assert not re.search(r"\{\w+(?:[:!][^}]*)?\}", text)


def test_every_function_in_prompts_is_rendered():
    names = [each.name for each in pkgutil.iter_modules(prompts.__path__)]
    modules = [importlib.import_module(f"{prompts.__name__}.{name}") for name in names]
    functions = {
        function for module in modules for function in vars(module).values()
        if inspect.isfunction(function) and function.__module__ == module.__name__
    }
    assert functions == {build for build, _ in RENDERS}
