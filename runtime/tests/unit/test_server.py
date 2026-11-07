import asyncio
from dataclasses import asdict
import contextlib
import fractions
import io
import json
from typing import Any

import aioice.ice
import httpx
import pytest
from PIL import Image
from aiortc import RTCConfiguration, RTCPeerConnection, RTCRtpCodecParameters, RTCSessionDescription, rtcrtpsender
from av import VideoFrame
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import SecretStr
from pyee.asyncio import AsyncIOEventEmitter

import computer_use.agent.main_agent as main_agent
import computer_use.agent.title as title
import computer_use.server as server
from computer_use.prompts.computer import DESKTOP_ASKED, DESKTOP_BUSY
from computer_use.desktop import webrtc
from computer_use.desktop.control import ControlFile, RunLock
from computer_use.desktop.webrtc import ScreenShare, ScreenTrack
from computer_use.agent.history import has_title
from computer_use.storage.files import FileRuns
from computer_use.storage.mongo import MongoRuns
from computer_use.server import create_app
from computer_use.computers import ComputerError
from computer_use.config import Settings
from computer_use.adapters import build_stores
from computer_use.runner import Runner
from computer_use.storage import FORMAT, LOCAL_USER, summarize
from computer_use.streaming import LiveStream
from conftest import (
    runner_of,
    DATABASES, SCRIPTED_TITLE, ScriptedModel, StreamingModel, delegate, listed_runs, listed_sessions, settings_for, tool_call,
    use_script,
)


@pytest.fixture(params=DATABASES)
def settings(request, tmp_path) -> Settings:
    """The server on each store: files, then each database."""
    return settings_for(tmp_path, request.getfixturevalue("mongo_url") if request.param == "mongo" else "")


@pytest.fixture
async def client(settings, computer):
    app = create_app(settings, max_steps=10, computer=computer)
    async with app.router.lifespan_context(app), httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost",
    ) as client:
        yield client


@pytest.fixture
async def runs(settings):
    """The local user's runs in the server's store, as another process sees them."""
    store, _, _ = build_stores(settings)
    yield store.of(LOCAL_USER)
    await store.close()


async def logged(client, run: str) -> list[dict]:
    """The run's events, as the server reads them back."""
    return [data for kind, data in sse((await client.get(f"/api/runs/{run}/events?full=1")).text) if kind != "done"]


async def png(runs, run: str, name: str, size: tuple[int, int], color: str = "black") -> None:
    data = io.BytesIO()
    Image.new("RGB", size, color).save(data, format="PNG")
    await runs.put_file(run, name, data.getvalue())


async def until_idle(client) -> dict:
    for _ in range(200):
        status = (await client.get("/api/status")).json()
        if not status["running"] and status["active"] is None:
            return status
        await asyncio.sleep(0.01)
    raise AssertionError("the run did not end")


async def test_the_agent_uses_the_control_supplied_by_the_server(settings, computer, monkeypatch):
    control = ControlFile(settings.data_dir / "injected-control.json")
    control.write("user", "manual work")
    monkeypatch.setattr(server, "build_control", lambda _: control)
    monkeypatch.setattr(server, "build_code_runner", lambda _: None)
    use_script(monkeypatch, [AIMessage("Checked the screen.")])
    app = create_app(settings, max_steps=10, computer=computer)
    async with app.router.lifespan_context(app), httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost",
    ) as api:
        response = await api.post("/api/runs", json={"goal": "check the screen", "computer": True, "take_control": True})
        assert response.status_code == 201
        status = await until_idle(api)
        assert status["error"] is None
        assert control.read().allows_input("agent")
        assert not settings.control_path.exists()


async def test_generated_files_download_as_attachments(settings, computer, code_runner, monkeypatch):
    from unittest.mock import AsyncMock
    from computer_use.sandbox import CodeRunnerError

    data = "方案,金額\nA,90720\n".encode()
    code_runner.read = AsyncMock(return_value=data)
    monkeypatch.setattr("computer_use.server.build_code_runner", lambda _: code_runner)
    use_script(monkeypatch, [], main=[AIMessage("Done.")])
    app = create_app(settings, max_steps=10, computer=computer)
    async with app.router.lifespan_context(app), httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost",
    ) as api:
        thread = (await api.post("/api/runs", json={"goal": "make a budget"})).json()["thread"]
        await until_idle(api)
        url = f"/api/conversations/{thread}/files/報表/年度 預算.csv"
        response = await api.get(url)
        assert response.status_code == 200 and response.content == data
        assert response.headers["content-type"] == "application/octet-stream"
        assert response.headers["content-disposition"] == "attachment; filename*=UTF-8''%E5%B9%B4%E5%BA%A6%20%E9%A0%90%E7%AE%97.csv"
        assert response.headers["cache-control"] == "private, no-store"
        code_runner.read.assert_awaited_once_with(thread, "報表/年度 預算.csv")
        for error, status in [(FileNotFoundError(), 404), (ValueError("refused"), 400), (CodeRunnerError(), 503)]:
            code_runner.read.side_effect = error
            assert (await api.get(url)).status_code == status
        await api.delete(f"/api/conversations/{thread}")
        code_runner.read.reset_mock()
        assert (await api.get(url)).status_code == 404
        code_runner.read.assert_not_called()


def sse(text: str) -> list[tuple[str, dict]]:
    """(event name, data) for each server-sent event."""
    events = []
    for block in text.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if not line.startswith(":"))
        if "data" in fields:
            events.append((fields.get("event", "message"), json.loads(fields["data"])))
    return events


async def test_a_run_streams_its_events_and_shows_in_the_list(client, monkeypatch):
    use_script(monkeypatch, [
        AIMessage(content="Open Start.", tool_calls=[tool_call("c1", "key", text="win")]),
        AIMessage(content="Opened Start."),
    ])

    created = await client.post("/api/runs", json={"goal": "  open start  "})
    run = created.json()["id"]
    await until_idle(client)

    assert created.status_code == 201
    # The first turn's stream: the message, the hand-over, and its end once it handed the task over.
    events = sse((await client.get(f"/api/runs/{run}/events")).text)
    assert events[0][1] | {"time": 0} == {
        "type": "start", "v": FORMAT, "kind": "turn", "run": run, "thread": run, "session": run, "goal": "open start",
        "time": 0, "model": "openai:gpt-6.1-terra", "main_model": "openai:gpt-6.1-terra", "computer": False,
        "approvals": "ask", "project": None, "user": "local",
    }
    end = next(data for _, data in events if data.get("type") == "end")  # the title may come after it
    assert end | {"time": 0, "usage": {}, "cost": {}, "agents": []} == {
        "type": "end", "stop_reason": "replied", "computer": None, "summary": "", "time": 0, "usage": {},
        "cost": {}, "agents": [],
    }
    assert events[-1][0] == "done"
    assert not any("message" in data for _, data in events)
    full = sse((await client.get(f"/api/runs/{run}/events?full=1")).text)
    assert any("message" in data for _, data in full) and len(full) == len(events)
    resumed = sse((await client.get(f"/api/runs/{run}/events", headers={"Last-Event-ID": "2"})).text)
    assert len(resumed) == len(events) - 3
    # The task's own stream, which the turn names: its action on the desktop, with its screen.
    (task,) = [data["record"] for _, data in events if data.get("type") == "task"]
    worked = sse((await client.get(f"/api/runs/{task}/events")).text)
    assert worked[0][1]["kind"] == "task" and worked[0][1]["parent"] == run
    action = next(data for _, data in worked if data.get("type") == "action")
    image = await client.get(f"/api/runs/{task}/files/{action['screenshot']}")
    assert (image.status_code, image.headers["content-type"]) == (200, "image/png")
    listed = await listed_runs(client)
    # The conversation's logs, newest first: the turn the task's end woke, the task with its action, the first turn.
    assert [(each["kind"], each["actions"]) for each in listed] == [("turn", 0), ("task", 1), ("turn", 0)]
    first = listed[-1]
    assert first["ended"] >= first["started"]
    assert first | {"started": 0, "ended": 0} == {
        "id": run, "thread": run, "kind": "turn", "session": run, "parent": None, "goal": "open start",
        "title": SCRIPTED_TITLE, "started": 0,
        "actions": 0, "ended": 0, "failed": False, "project": None,
    }
    last = [data for _, data in sse((await client.get(f"/api/runs/{listed[0]['id']}/events")).text)]
    (ended,) = [data for data in last if data.get("type") == "end"]
    assert ended["summary"] == "Done." and ended["computer"] == "replied"


async def test_the_reply_being_written_follows_the_log_unnumbered_until_it_is_logged(client, monkeypatch):
    reply = "Paris is the capital of France, and its largest city."
    model = StreamingModel(messages=iter([AIMessage(reply)]), received=[], bindings=[], pause=0.02)
    monkeypatch.setattr(main_agent, "build_chat_model", lambda _spec, _settings, **_: model)
    run = (await client.post("/api/runs", json={"goal": "capital of France?"})).json()["id"]

    text = (await client.get(f"/api/runs/{run}/events")).text
    blocks = [
        dict(line.split(": ", 1) for line in block.splitlines() if not line.startswith(":"))
        for block in text.strip().split("\n\n")
    ]

    kinds = [block.get("event", "line") for block in blocks]
    written = "".join(json.loads(block["data"])["text"] for block in blocks if block.get("event") in ("draft", "delta"))
    lines = [json.loads(block["data"]) for block in blocks if "id" in block]
    replied = next(n for n, block in enumerate(blocks) if "id" in block and '"type": "model"' in block["data"])
    # All it had written so far once, then what it wrote since, a few words at a time, all before its logged reply.
    assert kinds.count("draft") == 1 and kinds.count("delta") > 1 and kinds.index("draft") < kinds.index("delta")
    assert max(n for n, kind in enumerate(kinds) if kind in ("draft", "delta")) < replied
    assert written and reply.startswith(written)
    assert [int(block["id"]) for block in blocks if "id" in block] == list(range(len(lines)))
    assert lines[-1]["type"] == "end" and lines[-1]["summary"] == reply and kinds[-1] == "done"


@pytest.mark.parametrize("pause", [0, 0.004])
async def test_fast_reply_reaches_an_active_viewer_before_completion_without_shortened_polls(
    client, monkeypatch, pause
):
    connected = asyncio.Event()
    subscribe = LiveStream.subscribe

    @contextlib.contextmanager
    def observed(stream):
        with subscribe(stream) as reader:
            connected.set()
            yield reader

    class AfterConnection(StreamingModel):
        async def _astream(self, *args, **kwargs):
            await connected.wait()
            async for chunk in super()._astream(*args, **kwargs):
                yield chunk

    reply = "A short answer with streamed tokens."
    model = AfterConnection(messages=iter([AIMessage(reply)]), received=[], bindings=[], pause=pause)
    monkeypatch.setattr(main_agent, "build_chat_model", lambda *a, **k: model)
    monkeypatch.setattr(LiveStream, "subscribe", observed)
    run = (await client.post("/api/runs", json={"goal": "reply"})).json()["id"]
    frames = sse((await client.get(f"/api/runs/{run}/events")).text)
    pieces = [data["text"] for kind, data in frames if kind in ("draft", "delta")]
    assert len(pieces) > 1 and "".join(pieces) == reply
    final = next(i for i, (_, data) in enumerate(frames) if data.get("type") == "model")
    assert all(i < final for i, (kind, _) in enumerate(frames) if kind in ("draft", "delta"))
    assert frames[-1][0] == "done"


async def test_a_screenshot_comes_as_a_small_webp_for_a_thumbnail(client, runs):
    run = await runs.create()
    runs.append(run, {"type": "start", "v": FORMAT, "kind": "turn", "session": "s", "thread": run, "goal": "go"})
    await runs.flush(run)
    await png(runs, run, "001-key.png", (1280, 800), "navy")

    small = await client.get(f"/api/runs/{run}/files/001-key.png?w=160")
    full = await client.get(f"/api/runs/{run}/files/001-key.png")

    assert (small.status_code, small.headers["content-type"]) == (200, "image/webp")
    assert "immutable" in small.headers["cache-control"]
    with Image.open(io.BytesIO(small.content)) as image:
        assert image.size == (160, 100)
    assert len(small.content) < len(full.content)
    assert (await client.get(f"/api/runs/{run}/files/001-key.png?w=10")).status_code == 400
    assert (await client.get(f"/api/runs/{run}/files/001-key.png?w=big")).status_code == 400


async def test_unsupported_logs_are_hidden_and_direct_access_is_rejected_without_changing_them(client, runs):
    logs = {}
    for first in (
        {"type": "note", "text": "Goal: old goal"},
        {"type": "start", "v": 1, "goal": "old goal"},
        {"type": "start", "v": 2, "goal": "old goal"},
        {"type": "start", "v": 3, "goal": "old goal"},
        {"type": "start", "v": FORMAT + 1, "goal": "future goal"},
    ):
        run = await runs.create()
        logs[run] = [runs.append(run, first)]
        await runs.flush(run)
        await png(runs, run, "001-key.png", (20, 20))

    assert await listed_sessions(client) == []
    for run, original in logs.items():
        assert (await client.get(f"/api/runs/{run}/events")).status_code == 404
        assert (await client.get(f"/api/runs/{run}/files/001-key.png")).status_code == 404
        assert (await client.post(f"/api/runs/{run}/stop")).status_code == 404
        assert (await client.post("/api/runs", json={"goal": "continue", "thread": run})).status_code == 404
        assert await runs.events(run) == original


def test_the_list_names_a_run_by_its_title_once_it_has_one(tmp_path):
    start = {"type": "start", "v": FORMAT, "kind": "turn", "session": "s", "thread": "t1", "goal": "open start", "time": 10}
    named = {"type": "title", "text": "Opening Start", "usage": {}, "seconds": 1.2, "time": 12}
    assert asdict(summarize("r1", [start]))["title"] is None
    assert asdict(summarize("r1", [start, named]))["title"] == "Opening Start"


async def test_a_conversation_begun_in_a_project_on_the_page_is_listed_under_it(client, monkeypatch):
    project = (await client.post("/api/projects", json={"name": "  客戶  報價 "})).json()
    assert project["name"] == "客戶 報價"
    use_script(monkeypatch, [AIMessage(content="Done.")])
    created = await client.post("/api/runs", json={"goal": "reply", "project": project["id"]})
    assert created.status_code == 201
    await until_idle(client)
    use_script(monkeypatch, [AIMessage(content="Again.")])
    # Its next message stays in the conversation's own project, whatever the page sends.
    thread = created.json()["thread"]
    assert (await client.post("/api/runs", json={"goal": "more", "thread": thread, "project": "x"})).status_code == 201
    await until_idle(client)
    listed = sorted(await listed_sessions(client), key=lambda item: item["started"])
    assert [item["project"] for item in listed] == [project["id"], None]
    assert (await client.post("/api/runs", json={"goal": "reply", "project": "nope"})).status_code == 404


async def test_the_command_line_names_a_project_which_is_made_once(client, monkeypatch):
    for goal in ("one", "two"):
        use_script(monkeypatch, [AIMessage(content="Done.")])
        assert (await client.post("/api/runs", json={"goal": goal, "project_name": "eval"})).status_code == 201
        await until_idle(client)
    (project,) = (await client.get("/api/projects")).json()
    assert project["name"] == "eval"
    assert [item["project"] for item in await listed_sessions(client)] == [project["id"]] * 2


async def test_deleting_a_project_erases_every_conversation_in_it(client, monkeypatch):
    for goal in ("one", "two", "three"):
        use_script(monkeypatch, [AIMessage(content="Done.")])
        assert (await client.post("/api/runs", json={"goal": goal, "project_name": "eval"})).status_code == 201
        await until_idle(client)
    use_script(monkeypatch, [AIMessage(content="Done.")])
    assert (await client.post("/api/runs", json={"goal": "kept"})).status_code == 201
    await until_idle(client)
    (project,) = (await client.get("/api/projects")).json()
    deleted = await client.delete(f"/api/projects/{project['id']}")
    assert deleted.status_code == 200 and len(deleted.json()["conversations"]) == 3
    assert [item["goal"] for item in await listed_sessions(client)] == ["kept"]
    assert (await client.get("/api/projects")).json() == []


async def test_a_project_keeps_its_id_when_renamed_and_names_are_one_each(client):
    made = (await client.post("/api/projects", json={"name": "客戶"})).json()
    other = (await client.post("/api/projects", json={"name": "報價"})).json()
    assert (await client.post("/api/projects", json={"name": "客戶"})).json() == made
    renamed = await client.patch(f"/api/projects/{made['id']}", json={"name": "大客戶"})
    assert renamed.status_code == 200 and renamed.json() == {**made, "name": "大客戶"}
    assert (await client.patch(f"/api/projects/{made['id']}", json={"name": "報價"})).status_code == 409
    assert (await client.patch("/api/projects/nope", json={"name": "x"})).status_code == 404
    assert (await client.post("/api/projects", json={"name": " "})).status_code == 400
    assert (await client.delete(f"/api/projects/{other['id']}")).status_code == 200
    assert (await client.delete(f"/api/projects/{other['id']}")).status_code == 404
    assert [each["name"] for each in (await client.get("/api/projects")).json()] == ["大客戶"]


def test_the_list_says_which_project_a_run_was_started_in(tmp_path):
    start = {"type": "start", "v": FORMAT, "kind": "turn", "session": "s", "thread": "t1", "goal": "open start", "time": 10}
    assert asdict(summarize("r1", [start]))["project"] is None
    assert asdict(summarize("r1", [start | {"project": "p1"}]))["project"] == "p1"


def test_the_list_says_when_a_run_ended_and_whether_it_failed(tmp_path):
    start = {"type": "start", "v": FORMAT, "kind": "turn", "session": "s", "thread": "t1", "goal": "open start", "time": 10}

    def ended(reason: str) -> dict:
        return {"type": "end", "stop_reason": reason, "time": 25}

    runs = [[start], [start, ended("replied")], [start, ended("cancelled")], [start, ended("error")]]
    assert [(each["ended"], each["failed"]) for each in (asdict(summarize("r1", events)) for events in runs)] == [
        (None, False), (25, False), (25, False), (25, True),
    ]


def blocking_press(computer) -> tuple[asyncio.Event, asyncio.Event, list]:
    """Every key press waits, like an action that never finishes, until `held` is set; `pressing` once one has begun."""
    held, pressing, presses = asyncio.Event(), asyncio.Event(), []

    async def press(combos):
        presses.append(combos)
        pressing.set()
        await held.wait()

    computer.press = press
    return held, pressing, presses


async def test_a_task_is_stopped_by_its_log_and_the_conversation_goes_on(client, computer, monkeypatch):
    held, pressing, _ = blocking_press(computer)
    use_script(monkeypatch, [AIMessage(content="", tool_calls=[tool_call("c1", "key", text="win")])], main=[
        delegate(), AIMessage("You stopped it."),
    ])
    run = (await client.post("/api/runs", json={"goal": "open start"})).json()["id"]
    await pressing.wait()
    (task,) = (await client.get("/api/status")).json()["running"][0]["tasks"]

    ended_turn = await client.post(f"/api/runs/{run}/stop")  # its first turn ended once it handed the task over
    stopped = await client.post(f"/api/runs/{task}/stop")
    await until_idle(client)
    held.set()

    assert (ended_turn.status_code, stopped.status_code) == (409, 200)
    worked = [data for _, data in sse((await client.get(f"/api/runs/{task}/events")).text)]
    assert [data["stop_reason"] for data in worked if data.get("type") == "end"] == ["stopped"]
    # The session ends without the main agent woken for it: it hears of the stop the next time it is asked.
    assert [each["kind"] for each in await listed_runs(client)] == ["task", "turn"]
    assert (await client.post(f"/api/conversations/{run}/stop")).status_code == 409


async def test_one_run_has_the_desktop_and_a_stopped_run_carries_on_in_its_conversation(client, computer, monkeypatch):
    held, pressing, presses = blocking_press(computer)
    use_script(monkeypatch, [
        AIMessage(content="", tool_calls=[tool_call("c1", "key", text="win")]),
        AIMessage(content="Done."),
    ])
    first, second = await asyncio.gather(  # sent together, both for the desktop: only one may start
        client.post("/api/runs", json={"goal": "@Computer open start"}),
        client.post("/api/runs", json={"goal": "@Computer other"}),
    )
    run = (first if first.status_code == 201 else second).json()["id"]

    await pressing.wait()
    busy = await client.post("/api/runs", json={"goal": "@Computer something else"})
    status = (await client.get("/api/status")).json()
    stopped = await client.post(f"/api/conversations/{run}/stop")
    events = sse((await client.get(f"/api/runs/{run}/events")).text)

    assert sorted([first.status_code, second.status_code]) == [201, 409]
    # The desktop is held by the task at work on it, by its log.
    (task,) = status["running"][0]["tasks"]
    assert busy.status_code == 409 and busy.json() | {"error": ""} == {"error": "", "reason": "desktop", "run": task}
    assert (status["active"], status["running"]) == (
        task, [{"run": run, "thread": run, "goal": "@Computer open start", "turn": None, "tasks": [task], "pending": [], "queued": [], "read": []}]
    )
    assert [item["id"] for item in await listed_sessions(client)] == [run]
    assert stopped.status_code == 200 and (await until_idle(client))["error"] is None
    # The turn that handed the task over had ended; stopping the run stops the task.
    ends = [data for _, data in events if data.get("type") == "end"]
    assert [end["stop_reason"] for end in ends] == ["replied"] and events[-1][0] == "done"
    worked = [data for _, data in sse((await client.get(f"/api/runs/{task}/events")).text)]
    assert [data["stop_reason"] for data in worked if data.get("type") == "end"] == ["stopped"]
    held.set()
    use_script(monkeypatch, [AIMessage(content="Done.")], main=[
        delegate(call_id="m2"), AIMessage("Done."),
    ])
    again = (await client.post("/api/runs", json={"goal": "open start", "thread": run})).json()["id"]
    await until_idle(client)
    events = [data for _, data in sse((await client.get(f"/api/runs/{again}/events")).text)]
    assert (events[0]["thread"], events[0]["goal"]) == (run, "open start")
    stopped_with_it = [
        event for _, event in sse((await client.get(f"/api/runs/{again}/events?full=1")).text)
        if event.get("message", {}).get("data", {}).get("additional_kwargs", {}).get("runtime", {}).get("event")
        == "task_stopped"
    ]
    assert len(stopped_with_it) == 1  # the next session hears, as it opens, that its task stopped with it
    assert len(presses) == 1


async def test_other_conversations_go_on_while_one_uses_the_desktop(client, settings, computer, monkeypatch):
    held, pressing, _ = blocking_press(computer)
    use_script(monkeypatch, [AIMessage(content="", tool_calls=[tool_call("c1", "key", text="win")])])
    desktop = (await client.post("/api/runs", json={"goal": "@Computer open start"})).json()["id"]
    await pressing.wait()

    use_script(monkeypatch, [], main=[AIMessage("Paris.")])
    question = (await client.post("/api/runs", json={"goal": "capital of France?"})).json()
    for _ in range(200):  # it ends while the desktop task is still going
        if all(item["run"] != question["id"] for item in (await client.get("/api/status")).json()["running"]):
            break
        await asyncio.sleep(0.01)
    use_script(monkeypatch, [AIMessage(content="never asked")], main=[
        delegate(), AIMessage("Another conversation is using the desktop."),
    ])
    refused = await client.post("/api/runs", json={"goal": "open notepad", "thread": question["thread"]})
    for _ in range(200):
        running = (await client.get("/api/status")).json()["running"]
        if running == [{"run": desktop, "thread": desktop, "pending": [], "queued": [], "read": []}]:
            break
        await asyncio.sleep(0.01)
    again = await client.post("/api/runs", json={"goal": "next", "thread": desktop})
    forced = await client.post("/api/runs", json={"goal": "@Computer open notepad", "thread": question["thread"]})

    answered = sse((await client.get(f"/api/runs/{question['id']}/events")).text)
    # The run's title is written as it comes, which may be after its end.
    assert next(data for _, data in answered if data.get("type") == "end")["summary"] == "Paris."
    events = [data for _, data in sse((await client.get(f"/api/runs/{refused.json()['id']}/events")).text)]
    handed = next(event for event in events if event.get("type") == "action")
    assert (handed["status"], handed["result"]) == ("error", "Not executed: " + DESKTOP_BUSY)
    end = next(event for event in events if event.get("type") == "end")
    assert (end["stop_reason"], end["computer"]) == ("replied", None)
    assert again.status_code == 202 and again.json()["id"] == desktop  # it goes to that run, stopped below
    assert forced.status_code == 409 and forced.json()["reason"] == "desktop"
    assert computer.calls == []  # only the first task's key press, which never finished
    held.set()
    await client.post(f"/api/conversations/{desktop}/stop")
    await until_idle(client)


async def test_a_conversation_takes_one_message_at_a_time(client, computer, monkeypatch):
    use_script(monkeypatch, [], main=[AIMessage("Hi.")])
    thread = (await client.post("/api/runs", json={"goal": "hello"})).json()["id"]
    await until_idle(client)
    held, pressing, _ = blocking_press(computer)
    use_script(monkeypatch, [AIMessage(content="", tool_calls=[tool_call("c1", "key", text="win")])])

    first, second = await asyncio.gather(  # sent together into one conversation: only one may start
        client.post("/api/runs", json={"goal": "open start", "thread": thread}),
        client.post("/api/runs", json={"goal": "open start", "thread": thread}),
    )
    await pressing.wait()

    assert sorted([first.status_code, second.status_code]) == [201, 409]
    refused = first if first.status_code == 409 else second
    assert refused.json()["reason"] == "conversation"
    assert (await client.delete(f"/api/conversations/{thread}")).json()["reason"] == "conversation"
    await client.post(f"/api/conversations/{thread}/stop")
    held.set()
    await until_idle(client)


async def test_a_message_sent_while_the_conversation_works_goes_to_its_run(
    client, computer, monkeypatch
):
    pressing, done = [asyncio.Event(), asyncio.Event()], [asyncio.Event(), asyncio.Event()]

    async def press(combos):  # each key press waits until the test lets it finish
        n = sum(event.is_set() for event in pressing)
        pressing[n].set()
        await done[n].wait()

    computer.press = press
    use_script(monkeypatch, [
        AIMessage(content="", tool_calls=[tool_call("c1", "key", text="win")]),
        AIMessage(content="", tool_calls=[tool_call("c2", "key", text="esc")]),
        AIMessage(content="Opened and closed Start."),
    ])
    run = (await client.post("/api/runs", json={"goal": "@Computer open start"})).json()["id"]
    await pressing[0].wait()

    sent = await client.post("/api/runs", json={"goal": "and close it", "thread": run})
    message = sent.json()["message"]
    waiting = (await client.get("/api/status")).json()["running"]
    done[0].set()
    await pressing[1].wait()  # the agent decided its next step, having read it
    read = (await client.get("/api/status")).json()["running"]
    done[1].set()
    await until_idle(client)

    assert sent.status_code == 202 and sent.json() | {"message": ""} == {"id": run, "thread": run, "message": ""}
    tasks = waiting[0]["tasks"]
    assert waiting == [{"run": run, "thread": run, "goal": "@Computer open start", "turn": None, "tasks": tasks, "pending": [{"id": message, "text": "and close it"}], "queued": [], "read": []}]
    assert read == [{"run": run, "thread": run, "goal": "@Computer open start", "turn": None, "tasks": tasks, "pending": [], "queued": [], "read": [message]}]
    events = await session_events(client, run)
    assert [(event["id"], event["text"]) for event in events if event.get("type") == "message"] == [
        (message, "and close it")
    ]
    assert [item["id"] for item in await listed_sessions(client)] == [run]  # the main agent read it in time


async def test_a_message_the_run_has_not_read_can_be_taken_back(client, monkeypatch):
    main = gated_main_agent(monkeypatch, "Paris.")
    run = (await client.post("/api/runs", json={"goal": "capital of France?"})).json()["id"]
    await main.asked.wait()  # its only model call has begun: it reads nothing until it replies
    message = (await client.post("/api/runs", json={"goal": "and Italy?", "thread": run})).json()["message"]

    withdrawn = await client.delete(f"/api/runs/{run}/messages/{message}")
    again = await client.delete(f"/api/runs/{run}/messages/{message}")
    waiting = (await client.get("/api/status")).json()["running"]
    main.gate.set()
    (only,) = await until_runs(client, 1)  # nothing was left over to start the next run with

    assert withdrawn.status_code == 200 and again.status_code == 409
    assert waiting == [{"run": run, "thread": run, "goal": "capital of France?", "turn": run, "tasks": [], "pending": [], "queued": [], "read": []}]
    events = [data for _, data in sse((await client.get(f"/api/runs/{run}/events")).text)]
    assert only["id"] == run and not [event for event in events if event.get("type") == "message"]
    assert (await client.delete(f"/api/runs/20991231-235959/messages/{message}")).status_code == 404


async def test_a_queued_message_waits_for_the_session_to_end_then_starts_the_next(client, monkeypatch):
    main = gated_main_agent(monkeypatch, "Paris.", "Rome.")
    run = (await client.post("/api/runs", json={"goal": "capital of France?"})).json()["id"]
    await main.asked.wait()
    first = (await client.post("/api/runs", json={"goal": "and Italy?", "thread": run, "queue": True})).json()
    second = (await client.post("/api/runs", json={"goal": "and Spain?", "thread": run, "queue": True})).json()
    waiting = (await client.get("/api/status")).json()["running"]
    withdrawn = await client.delete(f"/api/runs/{run}/messages/{second['message']}")
    main.gate.set()
    sessions = await until_runs(client, 2)

    # Read by no agent while the session worked, it starts the next one once that ends.
    assert waiting == [{"run": run, "thread": run, "goal": "capital of France?", "turn": run, "tasks": [], "pending": [],
                        "queued": [{"id": first["message"], "text": "and Italy?"},
                                   {"id": second["message"], "text": "and Spain?"}], "read": []}]
    assert withdrawn.status_code == 200
    assert not [event for event in await session_events(client, run) if event.get("type") == "message"]
    nxt = next(each for each in sessions if each["id"] != run)
    assert nxt["goal"] == "and Italy?" and len(main.received) == 2
    assert (await client.post("/api/runs", json={"goal": "x", "thread": run, "queue": "yes"})).status_code == 400


class GatedModel(ScriptedModel):
    """A main agent that, asked, waits to reply until `gate` is set; `asked` once it has been."""

    gate: Any = None
    asked: Any = None

    async def ainvoke(self, input, config=None, **kwargs):
        self.asked.set()
        await self.gate.wait()
        return await super().ainvoke(input, config, **kwargs)


def gated_main_agent(monkeypatch, *replies: str) -> GatedModel:
    model = GatedModel(
        messages=iter([AIMessage(reply) for reply in replies]), received=[], bindings=[],
        gate=asyncio.Event(), asked=asyncio.Event(),
    )
    monkeypatch.setattr(main_agent, "build_chat_model", lambda _spec, _settings, **_: model)
    return model


async def session_events(client, run: str) -> list[dict]:
    """Every event of the session `run` began, each of its logs in turn: its turns' and its tasks'."""
    logs = sorted(each["id"] for each in await listed_runs(client) if each["session"] == run)
    return [data for each in logs for _, data in sse((await client.get(f"/api/runs/{each}/events")).text)]


async def until_runs(client, count: int) -> list[dict]:
    for _ in range(200):
        runs = await listed_sessions(client)
        status = (await client.get("/api/status")).json()
        if len(runs) == count and not status["running"]:
            return runs
        await asyncio.sleep(0.01)
    raise AssertionError(f"there were not {count} runs")


async def test_the_status_says_once_a_run_in_progress_has_named_its_conversation(client, monkeypatch):
    main = gated_main_agent(monkeypatch, "Paris.")
    namer = GatedModel(
        messages=iter([AIMessage('{"title":"Capital of France"}')]), received=[], bindings=[],
        gate=asyncio.Event(), asked=asyncio.Event(),
    )
    monkeypatch.setattr(title, "build_chat_model", lambda _spec, _settings, **_: namer)
    run = (await client.post("/api/runs", json={"goal": "capital of France?"})).json()["id"]
    await namer.asked.wait()
    unnamed = (await client.get("/api/status")).json()
    namer.gate.set()
    for _ in range(200):  # the page lists the conversation again, by its name, once the status says so
        named = (await client.get("/api/status")).json()
        if named["titles_revision"] != unnamed["titles_revision"]:
            break
        await asyncio.sleep(0.01)
    listed = [item["title"] for item in await listed_sessions(client)]
    main.gate.set()
    await until_runs(client, 1)

    assert named["titles_revision"] != unnamed["titles_revision"]
    assert [item["run"] for item in named["running"]] == [run]
    assert listed == ["Capital of France"]


async def test_a_title_made_after_its_run_ended_reaches_the_list_but_not_the_runs_stream(client, monkeypatch):
    use_script(monkeypatch, [], main=[AIMessage("Paris.")])
    namer = GatedModel(
        messages=iter([AIMessage('{"title":"Capital of France"}')]), received=[], bindings=[],
        gate=asyncio.Event(), asked=asyncio.Event(),
    )
    monkeypatch.setattr(title, "build_chat_model", lambda *_, **__: namer)
    run = (await client.post("/api/runs", json={"goal": "capital of France?"})).json()["id"]
    await namer.asked.wait()
    try:
        before = await until_idle(client)
        stream = await asyncio.wait_for(client.get(f"/api/runs/{run}/events"), 2)  # done with its run
        untitled = (await listed_sessions(client))[0]["title"]
    finally:
        namer.gate.set()
    for _ in range(200):
        if (await client.get("/api/status")).json()["titles_revision"] != before["titles_revision"]:
            break
        await asyncio.sleep(0.01)
    else:
        pytest.fail("the title was not made")

    assert untitled is None and (await listed_sessions(client))[0]["title"] == "Capital of France"
    assert '"type": "title"' not in stream.text and stream.text.endswith("event: done\ndata: {}\n\n")


@pytest.mark.parametrize("action", ["rename", "delete"])
async def test_a_late_title_respects_conversation_changes(client, settings, monkeypatch, action):
    use_script(monkeypatch, [], main=[AIMessage("Paris.")])
    namer = GatedModel(
        messages=iter([AIMessage('{"title":"Capital of France"}')]), received=[], bindings=[],
        gate=asyncio.Event(), asked=asyncio.Event(),
    )
    monkeypatch.setattr(title, "build_chat_model", lambda *_, **__: namer)
    done, name = asyncio.Event(), title.name

    async def naming(*args):
        try:
            await name(*args)
        finally:
            done.set()

    monkeypatch.setattr(title, "name", naming)
    run = (await client.post("/api/runs", json={"goal": "capital of France?"})).json()["id"]
    await namer.asked.wait()
    try:
        await until_idle(client)
        if action == "rename":
            changed = await client.patch(f"/api/conversations/{run}", json={"title": "My title"})
        else:
            changed = await client.delete(f"/api/conversations/{run}")
    finally:
        namer.gate.set()
    await asyncio.wait_for(done.wait(), 2)

    assert changed.status_code == 200
    runs = await listed_sessions(client)
    if action == "rename":  # nothing named over it
        assert runs[0]["title"] == "My title"
        assert [e["text"] for e in await logged(client, run) if e["type"] == "title"] == ["My title"]
    else:
        assert runs == [] and (await client.get(f"/api/runs/{run}/events")).status_code == 404


async def test_a_message_the_run_had_not_read_as_its_main_agent_replied_is_answered_in_the_same_run(
    client, monkeypatch
):
    main = gated_main_agent(monkeypatch, "Paris.", "Rome.")
    run = (await client.post("/api/runs", json={"goal": "capital of France?"})).json()["id"]
    await main.asked.wait()  # its only model call has begun: it reads nothing more

    sent = await client.post("/api/runs", json={"goal": "and Italy?", "thread": run})
    main.gate.set()
    (only,) = await until_runs(client, 1)

    assert sent.status_code == 202 and only["id"] == run
    assert [m.text for m in main.received[1] if isinstance(m, HumanMessage)] == ["capital of France?", "and Italy?"]
    # It woke for the message it had not read, in a turn of the same session.
    events = await session_events(client, run)
    assert [e["text"] for e in events if e.get("type") == "model"] == ["Paris.", "Rome."]
    assert [e["summary"] for e in events if e.get("type") == "end"] == ["Paris.", "Rome."]


async def test_what_a_stopped_run_did_not_read_is_the_conversations_next_message_too(client, monkeypatch):
    main = gated_main_agent(monkeypatch, "Paris.", "Rome.")
    run = (await client.post("/api/runs", json={"goal": "capital of France?"})).json()["id"]
    await main.asked.wait()

    sent = await client.post("/api/runs", json={"goal": "and Italy?", "thread": run})
    stopped = await client.post(f"/api/conversations/{run}/stop")
    main.gate.set()
    runs = await until_runs(client, 2)

    assert (sent.status_code, stopped.status_code) == (202, 200)
    assert (runs[0]["thread"], runs[0]["goal"]) == (run, "and Italy?")
    # The stopped run's call never reached the model; the next run's did, with both messages.
    assert [m.text for m in main.received[-1] if isinstance(m, HumanMessage)] == ["capital of France?", "and Italy?"]


async def test_how_steps_are_approved_changes_for_a_run_in_progress_and_only_for_one(client, monkeypatch):
    main = gated_main_agent(monkeypatch, "Paris.")
    run = (await client.post("/api/runs", json={"goal": "capital of France?", "approvals": "auto"})).json()["id"]
    await main.asked.wait()

    changed = await client.post(f"/api/runs/{run}/approvals", json={"approvals": "ask"})
    wrong = await client.post(f"/api/runs/{run}/approvals", json={"approvals": "never"})
    main.gate.set()
    await until_idle(client)
    ended = await client.post(f"/api/runs/{run}/approvals", json={"approvals": "auto"})
    unknown = await client.post("/api/runs/20991231-000000/approvals", json={"approvals": "ask"})

    assert (changed.status_code, changed.json()) == (200, {"run": run, "approvals": "ask"})
    assert (wrong.status_code, ended.status_code, unknown.status_code) == (400, 409, 404)


async def test_what_runs_did_not_read_goes_nowhere_as_the_server_shuts_down(settings, computer, control, monkeypatch):
    main = gated_main_agent(monkeypatch, "Paris.")
    runner = runner_of(settings, computer, control)
    run = await runner.start("capital of France?", 10)
    await main.asked.wait()

    runner.send(run, "and Italy?")
    await runner.close()
    await asyncio.sleep(0.05)

    assert runner.running() == {} and not runner.following


async def test_stopping_with_no_runs_or_two(settings, computer, control, monkeypatch):
    await runner_of(settings, computer, control).stop()
    held, pressing, _ = blocking_press(computer)
    use_script(monkeypatch, [AIMessage(content="", tool_calls=[tool_call("c1", "key", text="win")])])
    runner = runner_of(settings, computer, control)
    desktop = await runner.start("@Computer open start", 10, force_computer=True)
    await pressing.wait()
    blocked, answering = asyncio.Event(), asyncio.Event()

    class Waiting(ScriptedModel):  # the main agent of a second conversation, mid-reply
        async def ainvoke(self, input, config=None, **kwargs):
            answering.set()
            await blocked.wait()

    monkeypatch.setattr(main_agent, "build_chat_model", lambda _spec, _settings, **_: Waiting(messages=iter([])))
    question = await runner.start("capital of France?", 10)
    await answering.wait()

    await runner.stop(question)
    assert runner.running() == {desktop: desktop}
    await runner.stop()
    assert runner.running() == {}
    held.set()


async def test_a_run_of_another_server_sharing_the_desktop_holds_it_and_shows_what_it_has_logged(
    client, settings, runs,
):
    run = await runs.create()
    start = runs.append(run, {"type": "start", "v": FORMAT, "kind": "turn", "session": run, "run": run, "thread": run, "goal": "save", "history": []})
    await runs.flush(run)

    with RunLock(settings.run_lock_path) as lock:  # as the eval's server holds it for its run
        lock.name(run)
        status = (await client.get("/api/status")).json()
        busy = await client.post("/api/runs", json={"goal": "@Computer something else"})
        events = sse((await client.get(f"/api/runs/{run}/events")).text)
        stopped = await client.post(f"/api/runs/{run}/stop")

    assert (status["active"], status["running"]) == (run, [])  # running: this server's runs
    assert (busy.status_code, busy.json()["reason"], busy.json()["run"]) == (409, "desktop", run)
    assert events == [("message", start), ("done", {})]
    assert stopped.status_code == 409  # its own server stops it
    assert [item["id"] for item in await listed_sessions(client)] == [run]


async def test_a_follow_up_continues_the_conversation(client, monkeypatch):
    use_script(monkeypatch, [AIMessage(content="Opened Notepad.")])
    first = (await client.post("/api/runs", json={"goal": "open notepad"})).json()["id"]
    await until_idle(client)
    use_script(monkeypatch, [AIMessage(content="Saved.")], main=[delegate(call_id="m2"), AIMessage("Saved it.")])

    created = (await client.post("/api/runs", json={"goal": "now save it", "thread": first})).json()
    second = created["id"]
    await until_idle(client)

    start = sse((await client.get(f"/api/runs/{second}/events")).text)[0][1]
    assert (created["thread"], start["thread"], start["goal"]) == (first, first, "now save it")
    assert {item["id"]: item["thread"] for item in await listed_sessions(client)} == {first: first, second: first}
    assert (await client.post("/api/runs", json={"goal": "x", "thread": "nope"})).status_code == 404


async def test_deleting_a_conversation_erases_its_runs_and_nothing_brings_them_back(
    client, settings, computer, monkeypatch
):
    done = AIMessage(content="Done.")
    use_script(monkeypatch, [done])
    first = (await client.post("/api/runs", json={"goal": "open notepad"})).json()["id"]
    await until_idle(client)
    use_script(monkeypatch, [done], main=[delegate(call_id="m2"), AIMessage("Done.")])
    second = (await client.post("/api/runs", json={"goal": "save it", "thread": first})).json()["id"]
    await until_idle(client)

    held, pressing = asyncio.Event(), asyncio.Event()

    async def press(combos):  # keeps a third conversation's run in progress
        pressing.set()
        await held.wait()

    computer.press = press
    use_script(monkeypatch, [AIMessage(content="", tool_calls=[tool_call("c1", "key", text="win")]), done])
    running = (await client.post("/api/runs", json={"goal": "open start"})).json()["id"]
    await pressing.wait()

    logs = [each["id"] for each in (await client.get(f"/api/conversations/{first}/runs")).json()]
    deleted = await client.delete(f"/api/conversations/{first}")
    assert deleted.status_code == 200 and sorted(deleted.json()["deleted"]) == sorted(logs)  # its turns' and tasks'
    assert {first, second} <= set(logs)
    assert [item["id"] for item in await listed_sessions(client)] == [running]
    assert [(await client.get(f"/api/runs/{each}/events")).status_code for each in (first, second)] == [404, 404]
    assert (await client.delete(f"/api/conversations/{running}")).status_code == 409
    assert (await client.delete(f"/api/conversations/{first}")).status_code == 404
    assert (await client.get(f"/api/runs/{first}/events")).status_code == 404
    assert (await client.post("/api/runs", json={"goal": "again", "thread": first})).status_code == 404
    await client.post(f"/api/conversations/{running}/stop")
    held.set()
    await until_idle(client)


async def test_a_message_cannot_start_a_run_while_its_conversation_is_being_deleted(client, monkeypatch):
    use_script(monkeypatch, [], main=[AIMessage("Hi.")])
    thread = (await client.post("/api/runs", json={"goal": "hello"})).json()["id"]
    await until_idle(client)
    main = gated_main_agent(monkeypatch, "Done.")
    entered, resume = asyncio.Event(), asyncio.Event()
    def paused(delete):
        async def paused_delete(store, thread):
            entered.set()
            await resume.wait()
            return await delete(store, thread)

        return paused_delete

    for kind in (FileRuns, MongoRuns):
        monkeypatch.setattr(kind, "delete", paused(kind.delete))
    deleting = asyncio.create_task(client.delete(f"/api/conversations/{thread}"))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        started = await client.post("/api/runs", json={"goal": "continue", "thread": thread})
    finally:
        resume.set()
        deleted = await deleting
        main.gate.set()
        await until_idle(client)

    assert (started.status_code, deleted.status_code) == (409, 200)
    assert started.json()["reason"] == "conversation"
    assert (await client.post("/api/runs", json={"goal": "continue", "thread": thread})).status_code == 404


async def test_renaming_a_conversation_lists_it_by_the_users_title_over_the_runtimes(client, runs, monkeypatch):
    use_script(monkeypatch, [AIMessage(content="Done.")])
    first = (await client.post("/api/runs", json={"goal": "open notepad"})).json()["id"]
    await until_idle(client)
    runs.append(first, {"time": 1, "type": "title", "text": "Opening Notepad", "usage": {}, "seconds": 1})  # as agent.title
    await runs.flush(first)
    assert (await client.get("/api/conversations")).json()["items"][0]["title"] == "Opening Notepad"

    renamed = await client.patch(f"/api/conversations/{first}", json={"title": "  Notepad   notes \n"})
    assert renamed.status_code == 200 and renamed.json() == {"thread": first, "title": "Notepad notes"}
    assert (await client.get("/api/conversations")).json()["items"][0]["title"] == "Notepad notes"
    turns = [each["id"] for each in (await client.get(f"/api/conversations/{first}/runs")).json() if each["kind"] == "turn"]
    last = (await logged(client, turns[-1]))[-1]  # in its latest turn
    assert (last["type"], last["text"], last["by"]) == ("title", "Notepad notes", "user")
    assert await has_title(runs, first)
    assert (await client.patch(f"/api/conversations/{first}", json={"title": " "})).status_code == 400
    assert (await client.patch("/api/conversations/nope", json={"title": "x"})).status_code == 404


async def test_a_deleted_runs_events_and_screenshots_are_gone(client, monkeypatch):
    use_script(monkeypatch, [AIMessage(content="Done.")])
    run = (await client.post("/api/runs", json={"goal": "open notepad"})).json()["id"]
    await until_idle(client)
    (task,) = [each["id"] for each in await listed_runs(client) if each["kind"] == "task"]
    shot = next(name for name in (await client.get(f"/api/runs/{task}/events?full=1")).text.split('"') if name.endswith(".png"))
    assert (await client.get(f"/api/runs/{task}/files/{shot}")).status_code == 200
    assert (await client.delete(f"/api/conversations/{run}")).status_code == 200
    assert (await client.get(f"/api/runs/{run}/events")).status_code == 404
    assert (await client.get(f"/api/runs/{run}/files/{shot}")).status_code == 404


async def test_moving_a_conversation_lists_it_under_another_project_or_none(client, monkeypatch):
    use_script(monkeypatch, [AIMessage(content="Done.")])
    client_project = (await client.post("/api/projects", json={"name": "客戶"})).json()["id"]
    quote = (await client.post("/api/projects", json={"name": "報價 單"})).json()["id"]
    first = (await client.post("/api/runs", json={"goal": "quote", "project": client_project})).json()["id"]
    await until_idle(client)
    use_script(monkeypatch, [AIMessage(content="Again.")])
    await client.post("/api/runs", json={"goal": "more", "thread": first})
    await until_idle(client)

    moved = await client.patch(f"/api/conversations/{first}", json={"project": quote})
    assert moved.status_code == 200 and moved.json() == {"thread": first, "project": quote}
    # Its first run carries the move, which the page lists the conversation by.
    listed = sorted(await listed_sessions(client), key=lambda item: item["started"])
    assert listed[0]["project"] == quote
    last = (await logged(client, first))[-1]
    assert (last["type"], last["project"], last["by"]) == ("project", quote, "user")

    out = await client.patch(f"/api/conversations/{first}", json={"project": None})
    assert out.json() == {"thread": first, "project": None}
    assert sorted(await listed_sessions(client), key=lambda item: item["started"])[0]["project"] is None
    assert (await client.patch(f"/api/conversations/{first}", json={"project": 3})).status_code == 404
    assert (await client.patch(f"/api/conversations/{first}", json={})).status_code == 400


def test_a_runs_project_is_the_last_it_was_moved_to(tmp_path):
    start = {"type": "start", "v": FORMAT, "kind": "turn", "session": "s", "thread": "t1", "goal": "open start", "time": 10, "project": "p1"}
    moved = {"type": "project", "project": "p2", "by": "user", "time": 11}
    assert asdict(summarize("r1", [start, moved]))["project"] == "p2"
    assert asdict(summarize("r1", [start, moved, {**moved, "project": None}]))["project"] is None


def test_the_users_title_stands_over_the_runtimes_whichever_came_last(tmp_path):
    start = {"type": "start", "v": FORMAT, "kind": "turn", "session": "s", "thread": "t1", "goal": "open start", "time": 10}
    made = {"type": "title", "text": "Opening Start", "usage": {}, "seconds": 1.2, "time": 12}
    given = {"type": "title", "text": "Start menu", "by": "user", "time": 11}
    assert asdict(summarize("r1", [start, given, made]))["title"] == "Start menu"
    assert asdict(summarize("r1", [start, made, {**given, "text": "Start again"}]))["title"] == "Start again"


async def test_a_message_for_the_desktop_is_recorded_as_one(client, monkeypatch):
    _, main_model = use_script(monkeypatch, [AIMessage(content="Opened Start.")])
    run = (await client.post("/api/runs", json={"goal": "@Computer open start"})).json()["id"]
    await until_idle(client)

    first = sse((await client.get(f"/api/runs/{run}/events")).text)[0][1]
    assert (first["goal"], first["computer"]) == ("@Computer open start", True)
    assert DESKTOP_ASKED in main_model.received[0][-1].text


async def test_a_message_sent_for_the_desktop_goes_to_it_without_mentioning_it(client, monkeypatch):
    _, main_model = use_script(monkeypatch, [AIMessage(content="Opened Start.")])
    assert (await client.post("/api/runs", json={"goal": "open start", "computer": "yes"})).status_code == 400
    run = (await client.post("/api/runs", json={"goal": "open start", "computer": True})).json()["id"]
    await until_idle(client)

    first = sse((await client.get(f"/api/runs/{run}/events")).text)[0][1]
    assert (first["goal"], first["computer"]) == ("open start", True)
    assert DESKTOP_ASKED in main_model.received[0][-1].text


async def test_the_screen_now_comes_as_a_png_or_says_why_it_cannot(client, computer):
    shown = await client.get("/api/screen")
    assert (shown.status_code, shown.headers["content-type"]) == (200, "image/png")
    assert shown.content == computer.screen() and shown.headers["cache-control"] == "no-store"

    def gone():
        raise ComputerError("no display")

    computer.screen = gone
    failed = await client.get("/api/screen")
    assert failed.status_code == 503 and "no display" in failed.json()["error"]


async def test_a_failed_return_of_control_refuses_the_run_as_the_control_route_does(client, computer):
    await client.post("/api/control", json={"owner": "user"})
    computer.connected = False

    refused = await client.post("/api/runs", json={"goal": "open start", "computer": True, "take_control": True})

    assert refused.status_code == 503 and "Reconnect" in refused.json()["error"]
    assert (await client.get("/api/status")).json()["control"]["owner"] == "user"


async def test_a_run_that_fails_to_start_says_why(client, monkeypatch):
    async def fail(*_, **__):
        raise RuntimeError("no model")

    monkeypatch.setattr(Runner, "start", fail)

    failed = await client.post("/api/runs", json={"goal": "hello"})

    assert failed.status_code == 500 and failed.json()["error"] == "RuntimeError: no model"


async def test_a_message_for_a_conversation_deleted_as_it_starts_finds_nothing(client, runs, monkeypatch):
    use_script(monkeypatch, [], main=[AIMessage("Done.")])
    thread = (await client.post("/api/runs", json={"goal": "hello"})).json()["thread"]
    await until_idle(client)

    async def deleted_meanwhile(*_, **__):
        await runs.delete(thread)
        raise RuntimeError("its log is gone")

    monkeypatch.setattr(Runner, "start", deleted_meanwhile)

    gone = await client.post("/api/runs", json={"goal": "and now", "thread": thread})

    assert gone.status_code == 404


async def test_control_says_where_it_was_taken_and_returned(client):
    for body, reason in (
        ({"owner": "user"}, "taken over from web"), ({"owner": "agent"}, "returned from web"),
        ({"owner": "user", "by": "cli"}, "taken over from cli"), ({"owner": "agent", "by": "cli"}, "returned from cli"),
    ):
        await client.post("/api/control", json=body)
        assert (await client.get("/api/status")).json()["control"]["reason"] == reason


async def test_control_and_bad_requests(client, computer):
    taken = await client.post("/api/control", json={"owner": "user"})

    assert taken.json()["owner"] == "user" and computer.releases == 1
    status = (await client.get("/api/status")).json()
    assert status["control"]["owner"] == "user"
    assert (await client.post("/api/runs", json={"goal": " "})).status_code == 400
    assert (await client.post("/api/runs", json={"goal": "x", "max_steps": 0})).status_code == 400
    assert (await client.get("/api/runs/a.b/events")).status_code == 404
    assert (await client.get("/api/runs/nope/files/x.png")).status_code == 404


async def test_a_step_awaiting_approval_shows_in_the_status_and_is_answered_from_the_page(
    client, monkeypatch, fast_polls
):
    use_script(monkeypatch, [
        AIMessage(content="", tool_calls=[
            tool_call("c1", "key", text="ctrl+enter", needs_confirmation=True, consequence="送出表單"),
        ]),
        AIMessage(content="Submitted."),
    ])
    await client.post("/api/runs", json={"goal": "@Computer submit the form"})
    for _ in range(500):
        if approval := (await client.get("/api/status")).json()["approval"]:
            break
        await asyncio.sleep(0.01)

    (task,) = (await client.get("/api/status")).json()["running"][0]["tasks"]  # it asks from the task's log
    assert (approval["id"], approval["run"], approval["tool"], approval["consequence"]) == ("c1", task, "key", "送出表單")
    assert approval["decision"] is None and approval["screenshot"].endswith("-confirm.png")
    bad = await client.post("/api/approval", json={"id": "c1", "decision": "maybe"})
    other = await client.post("/api/approval", json={"id": "c9", "decision": "approve"})
    assert (bad.status_code, other.status_code) == (400, 409)
    nowhere = await client.post("/api/approval", json={"id": "c1", "decision": "approve", "by": "phone"})
    assert nowhere.status_code == 400
    answered = await client.post("/api/approval", json={"id": "c1", "decision": "approve", "by": "cli"})
    again = await client.post("/api/approval", json={"id": "c1", "decision": "reject"})
    assert (answered.status_code, again.status_code) == (200, 409)

    assert (await until_idle(client))["approval"] is None
    events = [data for _, data in sse((await client.get(f"/api/runs/{task}/events")).text)]
    decision = next(event for event in events if event.get("type") == "decision")
    assert (decision["outcome"], decision["by"]) == ("approved", "cli")


async def test_the_status_keeps_no_users_choices_and_says_how_the_settings_start_them(client):
    status = (await client.get("/api/status")).json()

    assert "agents" not in status and "approvals" not in status
    assert status["title_model"] == {"model": "openai:gpt-6-luna", "effort": "low"}
    assert status["defaults"] == {
        "main": {"model": "openai:gpt-6.1-terra", "effort": "medium"},
        "computer": {"model": "openai:gpt-6.1-terra", "effort": "medium"},
        "coding": {"model": "follow", "effort": "follow"},
    }
    models = {each["id"]: each["efforts"] for each in status["models"]}
    assert models["openai:gpt-6.1-sol"] == ["low", "medium", "high", "xhigh", "max"]
    assert models["openai:gpt-6-luna"][0] == "none"


async def test_a_run_works_with_the_choices_sent_with_its_message_and_the_runtime_keeps_none(
    client, settings, monkeypatch
):
    use_script(monkeypatch, [], main=[AIMessage("Hello."), AIMessage("Hello again.")])

    async def started(**sent) -> dict:
        run = (await client.post("/api/runs", json={"goal": "hi", **sent})).json()["id"]
        await until_idle(client)
        return sse((await client.get(f"/api/runs/{run}/events")).text)[0][1]

    chose = await started(approvals="auto", agents={
        "main": {"model": "openai:gpt-6-luna"}, "computer": {"model": "openai:gpt-6.1-sol"},
        "designer": {"model": "openai:gpt-6-luna"},  # an agent the runtime does not have: not refused
    })
    assert (chose["main_model"], chose["model"], chose["approvals"]) == ("openai:gpt-6-luna", "openai:gpt-6.1-sol", "auto")
    plain = await started(thread=chose["thread"])
    assert (plain["main_model"], plain["model"], plain["approvals"]) == ("openai:gpt-6.1-terra", "openai:gpt-6.1-terra", "ask")
    assert [path for path in settings.data_dir.iterdir() if path.is_file()] == []

    for bad in ({"approvals": "always"}, {"agents": ["main"]}, {"agents": {"main": {"temperature": "1"}}},
                {"agents": {"main": {"model": 4}}}, {"locale": 4}, {"locale": "zh Hant"}):
        assert (await client.post("/api/runs", json={"goal": "hi", **bad})).status_code == 400


async def test_the_computer_agent_writes_to_the_user_in_the_language_of_the_page_that_sent_the_message(
    client, monkeypatch
):
    computer_model, _ = use_script(
        monkeypatch, [AIMessage("Done."), AIMessage("Done.")], main=[delegate(), AIMessage("Done.")] * 2
    )

    async def prompt(**sent) -> str:
        await client.post("/api/runs", json={"goal": "check the screen", **sent})
        await until_idle(client)
        return computer_model.received[-1][0].text

    assert tells_language(await prompt(locale="zh-Hant"), "Traditional Chinese")
    # Without it, as from a page that does not send it, the agent goes by the user's message.
    assert "The user reads" not in await prompt()


def tells_language(prompt: str, language: str) -> bool:
    return f"\n\nThe user reads {language}: write anything you say to them in {language}.\n" in f"{prompt}\n"


@pytest.fixture
def no_candidates(monkeypatch):
    """Peers gather no candidates, so they agree on a session but never open a socket or connect: the page's side
    is played by a stand-in channel instead."""
    monkeypatch.setattr(aioice.ice, "get_host_addresses", lambda use_ipv4, use_ipv6: [])


async def offer() -> RTCPeerConnection:
    page = RTCPeerConnection(RTCConfiguration(iceServers=[]))
    page.addTransceiver("video", direction="recvonly")
    page.createDataChannel("input")
    await page.setLocalDescription(await page.createOffer())
    return page


class PageChannel(AsyncIOEventEmitter):
    """The page's data channel with no connection under it: the test emits what the page sends and reads what the
    runtime sent."""

    readyState = "open"

    def __init__(self):
        super().__init__()
        self.received: asyncio.Queue[dict] = asyncio.Queue()

    def send(self, message: str) -> None:
        self.received.put_nowait(json.loads(message))


async def test_the_live_view_answers_the_pages_offer_with_the_screen(client, no_candidates):
    page = await offer()

    answer = (await client.post("/api/live", json={"type": "offer", "sdp": page.localDescription.sdp})).json()
    await page.setRemoteDescription(RTCSessionDescription(**answer))
    directions = [transceiver.currentDirection for transceiver in page.getTransceivers()]
    await page.close()

    assert directions == ["recvonly"]


async def test_the_live_view_tells_the_page_the_agents_pointer_and_takes_the_users_input(computer, control, no_candidates):
    page, share, channel = await offer(), ScreenShare(computer, control), PageChannel()
    await share.answer(page.localDescription.sdp)
    (peer,) = share.peers
    tracks = [type(sender.track) for sender in peer.getSenders()]

    peer.emit("datachannel", channel)
    agents_pointer = await asyncio.wait_for(channel.received.get(), 10)
    control.write("user")
    users_turn = await asyncio.wait_for(channel.received.get(), 10)
    for event in [
        {"type": "move", "x": 10, "y": 20},
        {"type": "button", "button": "left", "down": True},
        {"type": "button", "button": "left", "down": False},
        {"type": "wheel", "direction": "down", "x": 10, "y": 20},
        {"type": "key", "key": "Control", "down": True},
        {"type": "text", "text": "會議"},
    ]:
        channel.emit("message", json.dumps(event))
    for _ in range(100):
        if len(computer.calls) == 6:
            break
        await asyncio.sleep(0.01)
    channel.emit("close")  # with Control still down
    for _ in range(100):
        if computer.releases:
            break
        await asyncio.sleep(0.01)
    await asyncio.gather(share.close(), page.close())

    assert computer.releases == 1

    assert tracks == [ScreenTrack]
    assert agents_pointer == {"type": "pointer", "point": [640, 400]}  # screen captures leave it out: the page draws it
    assert users_turn == {"type": "pointer", "point": None}  # the page draws the user's at their mouse
    assert computer.calls == [
        ("move", (10, 20), "unsettled"), ("mouse_button", True), ("mouse_button", False),
        ("scroll", (10, 20), "down", 1, []), ("key_state", "ctrl", True), ("type_text", "會議"),
    ]


async def test_live_view_input_is_dropped_while_the_agent_has_control(computer, control):
    share = ScreenShare(computer, control)
    control.write("agent")

    await share.apply({"type": "key", "key": "a", "down": True})
    control.write("user")
    await share.apply({"type": "key", "key": "nonsense", "down": True})
    await share.apply({"type": "move", "x": "1", "y": 2})

    assert computer.calls == []


async def test_live_text_bursts_are_merged_without_crossing_a_key_or_pointer_event(computer, control):
    share, channel = ScreenShare(computer, control), PageChannel()
    control.write("user")
    share._take_input(channel)
    for event in [
        *({"type": "text", "text": ch} for ch in "abcdefghij"),
        {"type": "key", "key": "Left", "down": True},
        {"type": "key", "key": "Left", "down": False},
        {"type": "text", "text": "中文"},
        {"type": "text", "text": "🙂"},
        {"type": "button", "button": "left", "down": True},
        {"type": "button", "button": "left", "down": False},
        {"type": "text", "text": "最後"},
    ]:
        channel.emit("message", json.dumps(event))
    for _ in range(100):
        if len(computer.calls) == 7:
            break
        await asyncio.sleep(0.01)
    channel.emit("close")
    for _ in range(100):
        if computer.releases:
            break
        await asyncio.sleep(0.01)

    assert computer.calls == [
        ("type_text", "abcdefghij"), ("key_state", "left", True), ("key_state", "left", False),
        ("type_text", "中文🙂"), ("mouse_button", True), ("mouse_button", False), ("type_text", "最後"),
    ]
    assert computer.releases == 1


async def test_live_text_waits_for_the_end_of_a_continuous_burst(computer, control, monkeypatch):
    import computer_use.desktop.webrtc as live

    monkeypatch.setattr(live, "TEXT_BATCH_SECONDS", 0.03)
    share, channel = ScreenShare(computer, control), PageChannel()
    control.write("user")
    share._take_input(channel)
    # The whole burst lasts longer than the batching interval; the interval restarts with each character.
    for char in "逐字中文輸入":
        channel.emit("message", json.dumps({"type": "text", "text": char}))
        await asyncio.sleep(0.01)
    assert computer.calls == []
    for _ in range(100):
        if computer.calls:
            break
        await asyncio.sleep(0.01)
    channel.emit("close")
    for _ in range(100):
        if computer.releases:
            break
        await asyncio.sleep(0.01)
    assert computer.calls == [("type_text", "逐字中文輸入")]


async def test_status_hands_the_page_the_turn_server_with_its_password(settings, computer):
    settings = settings.model_copy(update={"turn_url": "turn:localhost:3478?transport=tcp", "turn_password": SecretStr("pw")})
    app = create_app(settings, max_steps=10, computer=computer)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as client:
        status = (await client.get("/api/status")).json()

    assert status["ice_servers"] == [{"urls": "turn:localhost:3478?transport=tcp", "username": "live", "credential": "pw"}]


class Clock:
    """Stands in for `time` and `asyncio` in the video track: time passes only when the track sleeps or waits for
    the screen, so frames are paced exactly however busy the machine is."""

    def __init__(self):
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += max(0.0, seconds)


@pytest.fixture
def clock(monkeypatch) -> Clock:
    clock = Clock()
    monkeypatch.setattr(webrtc, "time", clock)
    monkeypatch.setattr(webrtc, "asyncio", clock)
    return clock


async def test_the_video_runs_faster_while_the_user_has_control(computer, control, clock):
    track = ScreenTrack(computer, control)
    control.write("agent")
    watched = [(await track.recv()).pts for _ in range(3)]
    control.write("user")
    worked = [(await track.recv()).pts for _ in range(3)]

    # pts count 90 kHz: 3000 a frame at 30 fps, 1500 at 60 fps (the fake screen always changes).
    assert watched + worked == [0, 3000, 6000, 7500, 9000, 10500]


@pytest.mark.parametrize("owner", ["user", "agent"])
async def test_a_frame_waits_for_the_screen_to_change(owner, computer, control, clock):
    changes = iter([None, 0.05])  # how far into each wait the screen changes: not before the keepalive, then 50 ms

    async def next_change(seen, timeout):
        change = next(changes)
        clock.now += timeout if change is None else change
        return seen if change is None else seen + 1

    computer.next_change = next_change
    control.write(owner)
    track = ScreenTrack(computer, control)
    first, still, changed = [(await track.recv()).pts / webrtc.CLOCK_RATE for _ in range(3)]

    # A frame comes no sooner than the frame rate allows, then as soon as the screen changes or the keepalive is due.
    interval = 1 / (webrtc.CONTROL_FPS if owner == "user" else webrtc.WATCH_FPS)
    assert still - first == pytest.approx(interval + webrtc.KEEPALIVE_SECONDS, abs=1e-4)
    assert changed - still == pytest.approx(interval + 0.05, abs=1e-4)


def test_vp8_video_is_encoded_with_screen_settings_that_aiortc_keeps():
    encoder = rtcrtpsender.get_encoder(RTCRtpCodecParameters(mimeType="video/VP8", clockRate=90_000, payloadType=96))
    frame = VideoFrame.from_image(Image.new("RGB", (320, 200), "white"))
    frame.pts, frame.time_base = 0, fractions.Fraction(1, 90_000)

    first, _ = encoder.encode(frame)
    codec = encoder.codec
    encoder.encode(frame)

    assert first
    assert encoder.codec is codec  # not replaced by one with aiortc's own settings
    assert codec.bit_rate == webrtc.BITRATE
    assert codec.options == {}  # once open, PyAV keeps only the options libvpx did not take


async def test_a_search_finds_a_conversation_by_what_was_said_in_it(client, monkeypatch):
    use_script(monkeypatch, [AIMessage(content="記事本已經存好了。")])  # the computer agent's words: not searched
    created = await client.post("/api/runs", json={"goal": "寫一份會議紀錄"})
    await until_idle(client)
    thread = created.json()["thread"]
    hits = (await client.get("/api/search", params={"q": " 會議 "})).json()
    assert [(hit["conversation"]["id"], hit["snippet"]) for hit in hits] == [(thread, "寫一份會議紀錄")]
    assert (await client.get("/api/search", params={"q": "記事本"})).json() == []
    assert (await client.get("/api/search", params={"q": "  "})).json() == []


async def test_a_message_says_the_users_time_zone_and_whether_memory_learns_and_is_used(client):
    for wrong in ({"timezone": "Mars/Base"}, {"memory": {"learn": "yes"}}, {"memory": {"forget": True}}):
        assert (await client.post("/api/runs", json={"goal": "reply"} | wrong)).status_code == 400
