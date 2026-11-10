"""The runtime emits the same v7 event contract the web projects, without reading prose: a turn's log, its task's
and the next turn's."""

import json
from pathlib import Path
from typing import get_args

from computer_use.tools.desktop import desktop_tools, reply
from computer_use.storage import FORMAT, TASK
from computer_use.computers import Frame
from computer_use.desktop.actions import ACTIONS, BATCHABLE, CLICKS, CONFIRMABLE, KEYBOARD, NO_CONFIRMATION
from computer_use.desktop.executor import ActionResult
from computer_use.events import ActionReason, NoteCode
from computer_use.storage import supported
from conftest import read_events, run_dir
from conftest import fixture_png, new_log


async def test_shared_web_fixture_matches_runtime_writers(settings):
    records = json.loads((Path(__file__).parents[1] / "fixtures/events-v7.json").read_text())["records"]
    for events in records:
        start = events[0]
        log = await new_log(settings.data_dir)
        if start["kind"] == TASK:
            log.start_task(start["thread"], start["session"], start["parent"], start["id"], start["agent"],
                           start["goal"], start["title"])
        else:
            log.start(start["goal"], start["thread"], settings.computer_model, settings.main_model, start["computer"],
                      session=start["session"])
        written = read_events(run_dir(settings, log.run))
        assert start["v"] == FORMAT and supported(written)
        for field in ("kind", "thread", "session", "goal", *(("parent", "id", "agent", "title") if start["kind"] == TASK else ())):
            assert written[0][field] == start[field], field
        await written_as_in(settings, log, events[1:])


async def written_as_in(settings, log, events: list[dict]) -> None:
    for event in events:
        if event["type"] == "note":
            assert event["code"] in get_args(NoteCode)
            log.note(event["text"], event["code"], **event.get("data", {}))
            written = read_events(run_dir(settings, log.run))[-1]
            assert written["code"] == event["code"]
            assert written["text"] == event["text"]
            assert written["data"] == event.get("data", {})
        elif event["type"] == "action":
            reason = event.get("reason")
            assert reason is None or reason in get_args(ActionReason)
            frame = Frame.of(fixture_png("EVENT-CONTRACT")) if event["screenshot"] else None
            result = reply(ActionResult(event["status"] == "success", event["result"], frame, reason=reason),
                           event["id"], event["tool"])
            call = {"id": event["id"], "name": event["tool"], "args": event["args"]}
            await log.action(call, result, event.get("agent"))
            written = read_events(run_dir(settings, log.run))[-1]
            for field in ("tool", "id", "args", "n", "status", "result", "reason", "screenshot"):
                assert written[field] == event[field], field
            assert written["message"]["data"]["artifact"]["reason"] == reason
        elif event["type"] == "task":
            log.task(event["id"], event["agent"], event["brief"], event["title"], event["record"])
            written = read_events(run_dir(settings, log.run))[-1]
            for field in ("state", "id", "agent", "brief", "title", "record"):
                assert written[field] == event[field], field
        elif event["type"] == "plan":
            log.plan({"version": event["version"], "steps": event["steps"]})
            written = read_events(run_dir(settings, log.run))[-1]
            for field in ("version", "steps"):
                assert written[field] == event[field], field
        elif event["type"] == "end":
            log.end(event["stop_reason"], event["summary"], event["computer"])
            written = read_events(run_dir(settings, log.run))[-1]
            for field in ("stop_reason", "summary", "computer"):
                assert written[field] == event[field], field


def test_action_classification_covers_the_actual_tools_and_dispatch(executor):
    executor.judge = object()  # press_while is offered only with a screen judge
    tools = {tool.name: tool for tool in desktop_tools(executor)}
    assert set(ACTIONS) == set(executor._actions)
    assert set(tools) == {*ACTIONS, "computer_batch"}
    assert set(BATCHABLE) <= set(ACTIONS)
    assert set(CLICKS) <= set(BATCHABLE) & set(CONFIRMABLE)
    assert set(KEYBOARD) <= set(BATCHABLE) & set(CONFIRMABLE)
    assert set(CONFIRMABLE) <= {*ACTIONS, "computer_batch"}
    assert set(CONFIRMABLE).isdisjoint(NO_CONFIRMATION)
    assert set(tools) == set(CONFIRMABLE) | set(NO_CONFIRMATION)
    for name, tool in tools.items():
        # The call id is injected by LangChain, never asked of the model or required in batch arguments.
        schema = tool.tool_call_schema.model_json_schema()
        assert "call_id" not in schema["properties"]
        assert ("needs_confirmation" in schema.get("required", [])) == (name in CONFIRMABLE)
        assert ("consequence" in schema["properties"]) == (name in CONFIRMABLE)


async def test_refusal_metadata_survives_tool_invocation_and_batch_stop(executor, settings, computer):
    from computer_use.desktop.control import ControlFile

    tools = {tool.name: tool for tool in desktop_tools(executor)}
    ControlFile(settings.control_path).write("user", "manual")
    call = {"type": "tool_call", "id": "blocked", "name": "computer_batch", "args": {
        "actions": [{"action": "left_click", "coordinate": [10, 10]}], "needs_confirmation": False,
    }}
    result = await tools["computer_batch"].ainvoke(call)
    assert result.tool_call_id == "blocked" and result.status == "error"
    assert result.artifact == {"reason": "userControl"}
    assert computer.calls == []


async def test_a_partially_executed_batch_is_not_reported_as_wholly_held_back(executor, settings, computer):
    from computer_use.desktop.control import ControlFile

    click = computer.click

    async def take_over_after_click(*args):
        await click(*args)
        ControlFile(settings.control_path).write("user", "manual")

    computer.click = take_over_after_click
    tools = {tool.name: tool for tool in desktop_tools(executor)}
    result = await tools["computer_batch"].ainvoke({"type": "tool_call", "id": "partial", "name": "computer_batch",
        "args": {"actions": [{"action": "left_click", "coordinate": [10, 10]},
                             {"action": "left_click", "coordinate": [20, 20]}], "needs_confirmation": False}})
    assert len(computer.calls) == 1
    assert result.status == "error" and result.artifact == {"reason": None}
    assert "Stopped at action 2 of 2" in str(result.content)
