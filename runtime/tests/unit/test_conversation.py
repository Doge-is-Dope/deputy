import json

import pytest
from langchain_core.messages import AIMessage

from computer_use.agent.history import can_continue
from conftest import run_turn, runs_dir
from conftest import events_of, run_file, task_folder, tool_call, use_script

pytestmark = pytest.mark.usefixtures("the_log_is_the_whole_record")


async def test_screenshots_are_files_and_messages_keep_only_their_names(settings, computer, monkeypatch):
    use_script(monkeypatch, [
        AIMessage(content="", tool_calls=[tool_call("c1", "key", text="win")]),
        AIMessage(content="Opened Start."),
    ])

    result = await run_turn(settings, "open start", max_steps=10, computer=computer)

    events = events_of(settings, result.run)
    assert "base64" not in json.dumps(events)
    files = {block["file"] for event in events if "message" in event
             for block in (event["message"]["data"]["content"] if isinstance(event["message"]["data"]["content"], list) else [])
             if block.get("type") == "image"}
    # The task's screens in its log's folder, the screen the main agent checks in its next turn's.
    assert files == {"000-observe.png", "001-key.png", "main-000-task-ended.png"}
    assert all(run_file(settings, result.run, name).exists() for name in files)


async def test_two_screens_at_the_same_point_get_files_of_their_own(settings, computer, monkeypatch):
    use_script(monkeypatch, [AIMessage("Looked."), AIMessage("Looked again.")], main=[
        AIMessage(content="", tool_calls=[tool_call("m1", "start_task", agent="computer", title="Task", task="Look.")]),
        AIMessage(content="", tool_calls=[tool_call("m2", "start_task", agent="computer", title="Task", task="Look again.")]),
        AIMessage("Done."),
    ])

    result = await run_turn(settings, "look twice", max_steps=10, computer=computer)

    # Both tasks began before any action: each first screen is in its own task's folder.
    assert [(task_folder(settings, result.run, id) / "000-observe.png").exists() for id in ("t1", "t2")] == [True, True]


async def test_a_run_in_an_unsupported_format_cannot_be_continued(settings, store, computer):
    old = runs_dir(settings.data_dir) / "20261001-120000"
    old.mkdir(parents=True)
    start = {"type": "start", "run": old.name, "goal": "type a note", "history": [], "time": 0}
    (old / "steps.jsonl").write_text(json.dumps(start) + "\n")

    assert not await can_continue(store, old.name)
    with pytest.raises(ValueError, match="unsupported log format"):
        await run_turn(settings, "save it", max_steps=10, computer=computer, thread=old.name)
