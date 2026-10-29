import json

import pytest
from langchain_core.messages import AIMessage

from computer_use.agent.history import can_continue
from conftest import run_turn
from conftest import run_dir, tool_call, use_script

pytestmark = pytest.mark.usefixtures("the_log_is_the_whole_record")


async def test_screenshots_are_files_and_messages_keep_only_their_names(settings, computer, monkeypatch):
    use_script(monkeypatch, [
        AIMessage(content="", tool_calls=[tool_call("c1", "key", text="win")]),
        AIMessage(content="Opened Start."),
    ])

    result = await run_turn(settings, "open start", max_steps=10, computer=computer)

    log = (run_dir(settings, result.run) / "steps.jsonl").read_text()
    assert "base64" not in log
    files = {block["file"] for event in map(json.loads, log.splitlines()) if "message" in event
             for block in (event["message"]["data"]["content"] if isinstance(event["message"]["data"]["content"], list) else [])
             if block.get("type") == "image"}
    assert files == {"000-observe.png", "001-key.png", "main-001-task-ended.png"}
    assert all((run_dir(settings, result.run) / name).exists() for name in files)


async def test_two_screens_at_the_same_point_get_files_of_their_own(settings, computer, monkeypatch):
    use_script(monkeypatch, [AIMessage("Looked."), AIMessage("Looked again.")], main=[
        AIMessage(content="", tool_calls=[tool_call("m1", "computer_use", title="Task", task="Look.")]),
        AIMessage(content="", tool_calls=[tool_call("m2", "computer_use", title="Task", task="Look again.")]),
        AIMessage("Done."),
    ])

    result = await run_turn(settings, "look twice", max_steps=10, computer=computer)

    # Both tasks began before any action: their first screens would have shared a name.
    assert {path.name for path in run_dir(settings, result.run).glob("000-observe*.png")} == {"000-observe.png", "000-observe_2.png"}


async def test_a_run_in_an_unsupported_format_cannot_be_continued(settings, store, computer):
    old = settings.data_dir / "runs" / "20261001-120000"
    old.mkdir(parents=True)
    start = {"type": "start", "run": old.name, "goal": "type a note", "history": [], "time": 0}
    (old / "steps.jsonl").write_text(json.dumps(start) + "\n")

    assert not await can_continue(store, old.name)
    with pytest.raises(ValueError, match="unsupported log format"):
        await run_turn(settings, "save it", max_steps=10, computer=computer, thread=old.name)
