"""The runtime's words are put together only by the functions in prompts/, from typed values: each, given sample values,
gives text with no slot left unfilled. A function added there later must be rendered here too."""

import importlib
import inspect
import pkgutil
import re
from typing import get_args

import pytest

from computer_use import prompts
from computer_use.agent.subagent import StopReason
from computer_use.prompts import coding, computer, main, notes, review

STEPS = ["clicked Start", "typed hello"]
EARLIER = [{"tool": "computer_use", "task": "open Notepad", "stop_reason": "replied", "reply": "", "actions": STEPS}]

RENDERS = [
    (main.main_prompt, (6, [computer.ABOUT, coding.ABOUT])),
    (computer.system_prompt, (None,)),
    (computer.system_prompt, ("zh-Hant",)),
    *[(computer.stopped, (reason, 40, 3)) for reason in get_args(StopReason)],
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
    (notes.computer_in_use, ("t1",)),
    (notes.step_rounds, (3,)),
    (notes.message_rounds, (3,)),
    (notes.desktop_offline, ("no RDP session",)),
    (notes.no_task, ("t9",)),
    (notes.since_heard, (["and save it"],)),
    (notes.task_ended, ("t1", "computer_use", "open Notepad")),
    (notes.missed, (["and save it", "as a.txt"],)),
    (notes.task_running, ("t1", "computer_use", 75, "open Notepad", STEPS)),
    (notes.task_stopped, ("t1", "computer_use", "open Notepad")),
    (notes.blackboard, (["open Notepad"], EARLIER)),
    (notes.opening, ("open Notepad", ["open notepad please"], "Earlier in this conversation")),
    (notes.told, (["and save it"],)),
    *[(notes.stopped, (reason, 40)) for reason in ("replied", "step_limit")],
    (notes.report, ("computer-use agent", "it replied", "Done.", STEPS, "The screen now.")),
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
