"""The plan: what the main agent writes, what is done, and what a snapshot shows and restores."""

import asyncio
from types import SimpleNamespace as NS

import pytest

from computer_use.agent.blackboard import Blackboard
from computer_use.agent.history import latest_plan
from computer_use.agent.inbox import Inbox
from computer_use.agent.plan import MAX_STEPS, Plan, PlanError, Step
from computer_use.agent.session import Session
from computer_use.agent.trajectory import Trajectory
from computer_use.prompts import notes
from computer_use.storage import LOCAL_USER
from computer_use.tools.plan import plan_tool, task_tools
from conftest import file_runs

FIND = Step("find", "Find the reports")
SUM = Step("sum", "Add them up", "A total", ("find",))
SEND = Step("send", "Send it")


def statuses(snapshot) -> dict[str, str]:
    return {step["id"]: step["status"] for step in snapshot["steps"]}


def written(*steps: Step) -> Plan:
    plan = Plan()
    plan.write(steps)
    return plan


def test_writing_replaces_the_whole_list_and_a_step_that_stays_keeps_being_done():
    plan = written(FIND, SUM)
    plan.finish(["find"])

    plan.write([FIND, SEND])

    assert statuses(plan.snapshot({})) == {"find": "completed", "send": "pending"}


def test_the_main_agent_can_mark_a_step_done_or_open_it_again():
    plan = written(FIND, SUM)
    plan.write([FIND, SUM], finished=["find", "sum"])
    assert statuses(plan.snapshot({})) == {"find": "completed", "sum": "completed"}

    plan.write([FIND, SUM], reopened=["sum"])

    assert statuses(plan.snapshot({})) == {"find": "completed", "sum": "pending"}


def test_a_step_dropped_and_written_again_starts_undone():
    plan = written(FIND, SUM)
    plan.finish(["sum"])
    plan.write([FIND])
    plan.write([FIND, SUM])
    assert statuses(plan.snapshot({})) == {"find": "pending", "sum": "pending"}


@pytest.mark.parametrize("steps", [
    [],
    [Step(str(n), "A step") for n in range(MAX_STEPS + 1)],
    [FIND, Step("find", "The same id")],
    [Step("", "No id")],
    [Step("find", "")],
])
def test_a_list_that_is_not_a_plan_changes_nothing(steps):
    plan = written(FIND)
    with pytest.raises(PlanError):
        plan.write(steps)
    assert plan.steps == (FIND,)


def test_finishing_a_step_the_plan_does_not_have_is_answered_and_changes_nothing():
    plan = written(FIND, SUM)
    assert plan.finish(["sum", "gone"]) == ["gone"]
    assert statuses(plan.snapshot({})) == {"find": "pending", "sum": "completed"}


def test_a_snapshot_shows_the_tasks_at_work_and_needs_hold_nothing_back():
    plan = written(FIND, SUM)
    snapshot = plan.snapshot({"sum": ["t1", "t2"]})
    assert snapshot["steps"] == [
        {"id": "find", "title": "Find the reports", "done_when": "", "needs": [], "status": "pending", "tasks": []},
        {"id": "sum", "title": "Add them up", "done_when": "A total", "needs": ["find"], "status": "in_progress",
         "tasks": ["t1", "t2"]},
    ]


def test_a_task_on_a_step_that_is_done_does_not_make_it_in_progress():
    plan = written(FIND)
    plan.finish(["find"])
    assert statuses(plan.snapshot({"find": ["t1"]})) == {"find": "completed"}


def test_each_snapshot_is_newer_than_the_last():
    plan = written(FIND)
    assert [plan.snapshot({})["version"] for _ in range(3)] == [1, 2, 3]


def test_a_restored_plan_keeps_what_was_done_and_counts_on():
    plan = written(FIND, SUM, SEND)
    plan.finish(["find"])

    restored = Plan.restored(plan.snapshot({"sum": ["t1"]}))

    assert restored.steps == plan.steps
    next_one = restored.snapshot({})
    assert statuses(next_one) == {"find": "completed", "sum": "pending", "send": "pending"}
    assert next_one["version"] == 2


async def conversation(tmp_path, turns: int) -> tuple:
    store = file_runs(tmp_path).of(LOCAL_USER)
    logs, thread = [], None
    for _ in range(turns):
        log = Trajectory(store, await store.create())
        log.start("goal", thread, "m", "m", False, session="s")
        thread = thread or log.run
        logs.append(log)
    return store, thread, logs


async def test_the_latest_plan_is_the_highest_version_in_any_of_the_turns_logs(tmp_path):
    store, thread, (first, second) = await conversation(tmp_path, 2)
    plan = written(FIND)
    newer_in_the_first_log = [plan.snapshot({}), plan.snapshot({}), plan.snapshot({})]
    second.plan(newer_in_the_first_log[1])
    first.plan(newer_in_the_first_log[2])
    second.plan(newer_in_the_first_log[0])

    assert (await latest_plan(store, thread))["version"] == 3


async def test_a_plan_a_task_logged_counts_and_a_conversation_without_one_has_none(tmp_path):
    store, thread, (first,) = await conversation(tmp_path, 1)
    assert await latest_plan(store, thread) is None

    task = Trajectory(store, await store.create())
    task.start_task(thread, "s", first.run, "t1", "coding", "brief", "title")
    task.plan(written(FIND).snapshot({}))

    assert (await latest_plan(store, thread))["version"] == 1


class Running:
    def on_steps(self):
        return {"find": ["t1"]}

    def at_work(self):
        return [{"id": "t1", "agent": "computer", "title": "Finding", "steps": ["find"]},
                {"id": "t2", "agent": "coding", "title": "Adding", "steps": ["sum"]}]


async def test_a_task_reads_the_plan_who_is_on_it_and_the_others_at_work(tmp_path):
    store, thread, _ = await conversation(tmp_path, 1)
    board = await Blackboard(store, thread, "s", written(FIND, SUM), Running()).read("t1")

    assert "- find. [in progress: you] Find the reports" in board.text
    assert "- sum. [to do] Add them up (needs find) Done when: A total" in board.text
    assert "- t2 (coding agent): Adding (steps sum)" in board.text and "- t1 " not in board.text


async def test_a_conversation_with_nothing_on_it_reads_empty(tmp_path):
    class Idle:
        def on_steps(self):
            return {}

        def at_work(self):
            return []

    store, thread, _ = await conversation(tmp_path, 1)
    assert (await Blackboard(store, thread, "s", Plan(), Idle()).read("t1")).text == ""


async def test_a_finished_turns_log_is_read_once_however_often_the_board_is(tmp_path):
    store, thread, (first,) = await conversation(tmp_path, 1)
    first.end("replied", "", None)
    await store.flush(first.run)
    reads = []
    events = store.events
    store.events = lambda run, *a, **k: reads.append(run) or events(run, *a, **k)
    board = Blackboard(store, thread, "s", Plan(), Running())

    await board.read("t1")
    await board.read("t1")

    assert reads == [first.run]


async def test_writing_the_plan_and_reporting_a_step_log_on_the_event_loop(tmp_path):
    store, thread, (first,) = await conversation(tmp_path, 1)
    plan, loops = Plan(), []
    write = plan_tool(plan, lambda _: loops.append(asyncio.get_running_loop()))
    await write.ainvoke({"steps": [{"id": "A", "title": "Do A"}]})

    class OnLoop(Running):
        def on_steps(self):
            loops.append(asyncio.get_running_loop())
            return {}

    tools = {each.name: each for each in task_tools(Blackboard(store, thread, "s", plan, OnLoop()), "t1", Inbox(), first)}
    await tools["finish_step"].ainvoke({"steps": ["A"]})

    assert len(loops) == 2


async def test_done_false_on_a_finished_step_leaves_it_done_and_only_reopen_opens_it():
    plan = written(FIND)
    plan.finish(["find"])
    tool = plan_tool(plan, lambda _: None)

    await tool.ainvoke({"steps": [{"id": "find", "title": "Find the reports", "done": False}]})
    assert statuses(plan.snapshot({})) == {"find": "completed"}

    await tool.ainvoke({"steps": [{"id": "find", "title": "Find the reports", "done": False, "reopen": True}]})
    assert statuses(plan.snapshot({})) == {"find": "pending"}


def ended(plan: Plan, steps: tuple, outcome, tasks=None, planned=True) -> NS:
    """A task on `steps` that has ended with `outcome`, the plan being `plan`, and `tasks` still running."""
    job = NS(plan_steps=steps, plan_note="")
    running = NS(on_steps=lambda: tasks or {})
    session = NS(blackboard=NS(plan=plan), background=running, show_plan=lambda: None, planned=planned)
    Session.task_changed(session, job, outcome)
    return job


REPLIED = ([], {"stop_reason": "replied"})


def test_a_step_written_after_the_task_began_is_named_as_left():
    plan = written(Step("3", "Close the page"))

    job = ended(plan, ("1", "2"), REPLIED)

    assert job.plan_note == notes.plan_left(["3"])


def test_a_reply_marks_nothing_done_and_only_steps_nobody_is_on_are_named():
    plan = written(FIND, SUM, SEND)
    plan.finish(["find"])

    job = ended(plan, ("find", "sum"), REPLIED, tasks={"send": ["t2"]})

    assert job.plan_note == notes.plan_left(["sum"])
    assert statuses(plan.snapshot({})) == {"find": "completed", "sum": "pending", "send": "pending"}


def test_a_plan_restored_from_an_earlier_session_is_not_this_sessions_work_to_finish():
    assert ended(written(FIND), (), REPLIED, planned=False).plan_note == ""


def test_a_plan_with_every_step_done_or_none_at_all_says_nothing():
    plan = written(FIND)
    plan.finish(["find"])
    assert ended(plan, ("find",), REPLIED).plan_note == ""
    assert ended(Plan(), (), REPLIED).plan_note == ""


async def test_only_a_change_to_the_steps_of_a_written_plan_counts_as_revised():
    plan, heard = Plan(), []
    tool = plan_tool(plan, heard.append)
    one = [{"id": "A", "title": "Do A"}]

    await tool.ainvoke({"steps": one})
    await tool.ainvoke({"steps": [one[0] | {"done": True}]})
    await tool.ainvoke({"steps": [*one, {"id": "B", "title": "Do B"}]})

    assert heard == [False, False, True]
