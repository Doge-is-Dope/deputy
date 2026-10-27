"""The runtime emits the same v4 event contract the web projects, without reading prose."""

import json
from pathlib import Path
from typing import get_args

from computer_use.agent.tools import desktop_tools, reply
from computer_use.storage import FORMAT
from computer_use.computers import Frame
from computer_use.desktop.actions import ACTIONS, BATCHABLE, CLICKS, CONFIRMABLE, KEYBOARD, NO_CONFIRMATION
from computer_use.desktop.executor import ActionResult
from computer_use.events import ActionReason, NoteCode
from computer_use.storage import supported
from conftest import read_events, run_dir
from conftest import fixture_png, new_log


def test_shared_web_fixture_matches_runtime_writers(settings):
    events = json.loads((Path(__file__).parents[1] / "fixtures/events-v4.json").read_text())
    start = events[0]
    log = new_log(settings.data_dir)
    log.start(start["goal"], None, settings.computer_model, settings.main_model, start["computer"])
    assert start["v"] == FORMAT and supported(read_events(run_dir(settings, log.run)))

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
            log.action(call, result, event.get("agent"))
            written = read_events(run_dir(settings, log.run))[-1]
            for field in ("tool", "id", "args", "n", "status", "result", "reason", "screenshot"):
                assert written[field] == event[field], field
            assert written["message"]["data"]["artifact"]["reason"] == reason


def test_action_classification_covers_the_actual_tools_and_dispatch(executor):
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
