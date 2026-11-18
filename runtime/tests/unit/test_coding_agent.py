"""The coding agent and the code runner: offered when the runner can be reached, its commands run there in the
conversation's folder, and nothing it does needs the computer or the user's approval. The runner's own server
(code-runner/server.py) keeps each conversation in its folder, gives a command nothing of its environment, and stops a
command and everything it started after its time."""

import asyncio
import base64
import ctypes
import json
import socket
import importlib.util
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

import computer_use.agent.coding_agent as coding_agent
import computer_use.agent.main_agent as main_agent
from computer_use.prompts.computer import DESKTOP_HANDED
from computer_use.tools.coding import Attached, coding_tools
from computer_use.storage import MAIN
from computer_use.sandbox import CodeRunnerError, RunOutput
from computer_use.sandbox.http import HttpCodeRunner
from computer_use.desktop.control import RunLock
from computer_use.agent.history import tasks
from conftest import run_turn
from conftest import events_of, read_events, task_folder, task_states
from conftest import ScriptedModel, coding_script, image, logged, tool_call, use_script

pytestmark = pytest.mark.usefixtures("the_log_is_the_whole_record")


def handing_code(task="Add 2 and 2.", call_id="m1") -> AIMessage:
    return AIMessage(content="", tool_calls=[tool_call(call_id, "start_task", agent="coding", title="Task", task=task)])


async def test_file_tools_accept_the_conversations_absolute_path_only(code_runner):
    write = next(tool for tool in coding_tools(code_runner, "t1", "k1") if tool.name == "write_file")
    call = lambda path: write.ainvoke({"type": "tool_call", "id": "w1", "name": "write_file",
                                      "args": {"path": path, "content": "saved"}})
    assert (await call("/workspace/t1/result.txt")).status == "success"
    assert (await call("/workspace/t2/result.txt")).status == "error"
    assert code_runner.files == {"result.txt": "saved"}


async def test_the_coding_agent_is_offered_whenever_there_is_a_code_runner_even_one_that_is_down(
    settings, computer, code_runner, monkeypatch
):
    _, main_model = use_script(monkeypatch, [], main=[AIMessage("Hi."), AIMessage("Hi."), AIMessage("Hi.")])

    await run_turn(settings, "hi", max_steps=10, computer=computer)
    code_runner.connected = False
    await run_turn(settings, "hi", max_steps=10, computer=computer, code_runner=code_runner)
    code_runner.connected = True
    await run_turn(settings, "hi", max_steps=10, computer=computer, code_runner=code_runner)

    agents = [next(each for each in binding["tools"] if each.name == "start_task").description
              for binding in main_model.bindings]
    assert ["- coding:" in each for each in agents] == [False, True, True]
    assert not code_runner.closed  # the server's runner outlives a run


async def test_a_run_with_a_code_runner_offers_every_agent_the_settings_list(
    settings, computer, code_runner, monkeypatch
):
    _, main_model = use_script(monkeypatch, [], main=[AIMessage("Hi.")])

    await run_turn(settings, "hi", max_steps=10, computer=computer, code_runner=code_runner)

    start_task = next(each for each in main_model.bindings[0]["tools"] if each.name == "start_task")
    assert start_task.args["agent"]["enum"] == ["computer", "coding"]


async def test_a_coding_task_runs_in_the_conversations_folder_without_the_computer(
    settings, computer, code_runner, monkeypatch
):
    code_runner.answer = lambda script: RunOutput(0, "4\n", 0)
    use_script(monkeypatch, [], main=[handing_code("Add 2 and 2 with Python."), AIMessage("It is 4.")])
    coding = coding_script(monkeypatch, [
        AIMessage(content="", tool_calls=[tool_call("k1", "write_file", path="add.py", content="print(2 + 2)")]),
        AIMessage(content="", tool_calls=[tool_call("k2", "bash", script="python3 add.py")]),
        AIMessage("It printed 4."),
    ])
    lock = RunLock(settings.run_lock_path)

    async def held_while_running(script):
        assert lock.holder() is None
        return RunOutput(0, "4\n", 0)

    code_runner.answer = held_while_running

    result = await run_turn(
        settings, "what is 2 + 2", max_steps=10, computer=computer, code_runner=code_runner
    )

    assert result.reply == "It is 4." and computer.calls == []
    assert code_runner.files == {"add.py": "print(2 + 2)"}
    assert code_runner.commands == [(result.run, "python3 add.py")]
    # Under the task's own log, which stops only its command.
    assert code_runner.tasks == [task_folder(settings, result.run, "t1").name]
    task = coding.received[0][1].text
    assert task.startswith("Goal: Add 2 and 2 with Python.") and "word for word: what is 2 + 2" in task
    ended = tasks(events_of(settings, result.run))
    assert [(each["agent"], each["stop_reason"], each["reply"]) for each in ended] == [
        ("coding", "replied", "It printed 4.")
    ]
    assert ended[0]["actions"][-1] == 'bash {"script": "python3 add.py"} -> success: Exit code 0.'
    report = next(e for e in logged(result, "input", MAIN)
                  if e["message"]["data"].get("additional_kwargs", {}).get("runtime", {}).get("event") == "task_ended")
    text = "\n".join(b["text"] for b in report["message"]["data"]["content"] if b.get("type") == "text")
    assert "The coding agent stopped: it replied." in text and "screenshot" not in text


async def test_a_path_in_the_working_folders_name_is_a_file_in_the_conversations_folder(
    settings, computer, code_runner, monkeypatch
):
    use_script(monkeypatch, [], main=[AIMessage("Ready."), handing_code("Make out.xlsx."), AIMessage("Done.")])
    first = await run_turn(settings, "Hello", max_steps=10, computer=computer, code_runner=code_runner)
    path = f"/workspace/{first.run}"
    coding = coding_script(monkeypatch, [
        AIMessage(content="", tool_calls=[tool_call("k1", "write_file", path=f"{path}/make.py", content="...")]),
        AIMessage(content="", tool_calls=[tool_call("k2", "bash", script=f"python3 {path}/make.py")]),
        AIMessage(f"Made [out.xlsx](sandbox:{path}/out.xlsx)."),
    ])
    result = await run_turn(settings, "make out.xlsx", max_steps=10, computer=computer, code_runner=code_runner,
                           thread=first.run)

    assert code_runner.files == {"make.py": "..."}
    (ended,) = tasks(events_of(settings, result.run))
    assert ended["reply"] == f"Made [out.xlsx](sandbox:{path}/out.xlsx)."
    opening = next(message for message in coding.received[0] if isinstance(message, HumanMessage))
    assert f"Your working folder is {path}:" in opening.content


async def test_a_later_desktop_task_sees_the_coding_task_on_its_blackboard(
    settings, computer, code_runner, monkeypatch
):
    computer_model, _ = use_script(monkeypatch, [AIMessage("Looked.")], main=[
        handing_code("Sum the numbers.", "m1"),
        AIMessage(content="", tool_calls=[tool_call("m2", "start_task", agent="computer", title="Task", task="Type the sum.")]),
        AIMessage("Done."),
    ])
    coding_script(monkeypatch, [AIMessage("The sum is 10.")])

    await run_turn(settings, "sum and type", max_steps=10, computer=computer, code_runner=code_runner)

    board = computer_model.received[0][1].content[0]["text"]
    assert "An earlier task, handed to the coding agent: Sum the numbers." in board
    assert "Its final message: The sum is 10." in board


async def test_a_coding_task_handed_over_while_the_runner_is_down_fails_at_once_saying_so(
    settings, computer, code_runner, monkeypatch
):
    _, main_model = use_script(monkeypatch, [], main=[handing_code(), AIMessage("The code runner is down.")])
    coder = coding_script(monkeypatch, [AIMessage("Never asked.")])
    code_runner.connected = False

    result = await run_turn(settings, "add", max_steps=10, computer=computer, code_runner=code_runner)

    assert coder.received == []
    ended = main_model.received[1][-1]
    assert "the code runner could not be used" in ended.text and "not reachable" in ended.text
    assert tasks(events_of(settings, result.run))[0]["stop_reason"] == "error"


async def test_a_command_that_is_refused_or_too_slow_is_the_agents_to_hear(code_runner):
    tools = {each.name: each for each in coding_tools(code_runner, "thread", "task")}
    outside = await tools["write_file"].ainvoke(tool_call("w", "write_file", path="../x.py", content="nope"))
    code_runner.answer = lambda script: RunOutput(None, "started\n", 0)
    slow = await tools["bash"].ainvoke(tool_call("b", "bash", script="sleep 999"))

    assert outside.status == "error" and "Not executed: ../x.py is outside the working folder" in outside.text
    assert slow.status == "error" and "more than 120 seconds" in slow.text and "started" in slow.text
    assert code_runner.files == {}


async def test_a_code_runner_that_cannot_be_used_ends_the_task_and_the_main_agent_hears_why(
    settings, computer, code_runner, monkeypatch
):
    _, main_model = use_script(monkeypatch, [], main=[handing_code(), AIMessage("The code runner is down.")])
    coding_script(monkeypatch, [AIMessage(content="", tool_calls=[tool_call("k1", "bash", script="echo 4")])])

    async def gone(script):
        raise CodeRunnerError("ConnectError: gone")

    code_runner.answer = gone

    result = await run_turn(settings, "add", max_steps=10, computer=computer, code_runner=code_runner)

    assert result.reply == "The code runner is down."
    ended = main_model.received[1][-1]
    assert isinstance(ended, HumanMessage)
    assert "the code runner could not be used" in ended.text and "ConnectError: gone" in ended.text
    assert [e["code"] for e in logged(result, "note") if e["code"] == "runnerUnusable"] == ["runnerUnusable"]
    assert tasks(events_of(settings, result.run))[0]["stop_reason"] == "error"


# The runtime's client, against a fake transport.


async def test_what_the_user_attached_is_in_the_folder_and_only_what_a_model_reads_reaches_one(
    settings, computer, code_runner, monkeypatch
):
    def sheet(data: bytes, name="報表.xlsx") -> list[dict]:
        return [
            {"type": "file", "base64": base64.b64encode(data).decode(), "mime_type": "application/octet-stream",
             "filename": name},
            {"type": "text", "text": f"The user attached {name}. It is in the coding agent's working folder."},
        ]
    _, main_model = use_script(monkeypatch, [], main=[
        AIMessage("Got it."), handing_code("Sum it."), AIMessage("Summed."), AIMessage("A new one."),
        handing_code("Again."), handing_code("And once more.", "m2"), AIMessage("Summed."),
    ])
    coding_script(monkeypatch, [AIMessage("Done.") for _ in range(3)])
    turn = lambda message, **more: run_turn(settings, message, max_steps=10, computer=computer, code_runner=code_runner, **more)

    first = await turn("Keep this", media=sheet(b"PK old"))
    # What a message brings is there at once, and replaces a file of its name, with or without a coding task.
    assert code_runner.files == {"attachments/報表.xlsx": b"PK old"}
    code_runner.files["attachments/報表.xlsx"] = b"edited by the agent"
    await turn("Sum it", thread=first.run)
    assert code_runner.files["attachments/報表.xlsx"] == b"edited by the agent"
    await turn("I fixed it", thread=first.run, media=sheet(b"PK new") + sheet(b"notes", "notes.txt"))
    assert code_runner.files == {"attachments/報表.xlsx": b"PK new", "attachments/notes.txt": b"notes"}
    assert code_runner.asked == ["attachments/報表.xlsx"]  # an earlier file is looked for only as a coding task starts
    code_runner.files.clear()  # the runner restarted: its folders are gone
    code_runner.asked.clear()
    await turn("Again", thread=first.run)

    # Put back from the runs' files, once for the session: of the two named alike, the one attached last.
    assert code_runner.files == {"attachments/報表.xlsx": b"PK new", "attachments/notes.txt": b"notes"}
    assert sorted(code_runner.asked) == ["attachments/notes.txt", "attachments/報表.xlsx"]
    for received in main_model.received:  # the model reads the note, never the file
        sent = [block for message in received if isinstance(message.content, list) for block in message.content]
        assert not any(block.get("type") == "file" for block in sent)
        assert any("報表.xlsx" in block.get("text", "") for block in sent)


async def test_a_file_the_folder_turns_away_leaves_the_others_there(code_runner, monkeypatch):
    put = code_runner.put

    async def refusing(thread, path, data, source=None):
        if path.endswith("bad.txt"):
            raise ValueError("File name too long")
        return await put(thread, path, data, source)
    monkeypatch.setattr(code_runner, "put", refusing)
    files = [{"type": "file", "base64": "eA==", "mime_type": "text/plain", "filename": name} for name in ("bad.txt", "ok.txt")]

    await Attached(code_runner, None, "t1", [], files, "r2").place()

    assert code_runner.files == {"attachments/ok.txt": b"x"}


async def test_a_failed_replacement_is_recovered_by_the_next_session(settings, computer, code_runner, monkeypatch):
    use_script(monkeypatch, [], main=[AIMessage("Kept."), AIMessage("Kept."), handing_code(), AIMessage("Done.")])
    coding_script(monkeypatch, [AIMessage("Done.")])
    turn = lambda text, **more: run_turn(settings, text, max_steps=10, computer=computer, code_runner=code_runner, **more)
    first = await turn("Keep this", media=[attached_file("report.csv", b"old")])
    put = code_runner.put

    async def failed(*args, **kwargs):
        raise CodeRunnerError("connection lost")

    monkeypatch.setattr(code_runner, "put", failed)
    await turn("Use this revision", thread=first.run, media=[attached_file("report.csv", b"new")])
    monkeypatch.setattr(code_runner, "put", put)
    await turn("Read it", thread=first.run)

    assert code_runner.files["attachments/report.csv"] == b"new"


def attached_file(name: str, data: bytes) -> dict:
    return {"type": "file", "base64": base64.b64encode(data).decode(), "mime_type": "text/plain", "filename": name}


class Kept:
    """A run's files, and a log that names them as attached."""

    def __init__(self, **files: bytes):
        self.files = {name.replace("_", "."): data for name, data in files.items()}
        attachments = [{"file": name, "name": name} for name in self.files]
        self.logs = [SimpleNamespace(summary=SimpleNamespace(id="r1"), events=[{"type": "input", "attachments": attachments}])]

    async def get_file(self, run, name):
        return self.files[name]


async def test_a_file_the_runner_could_not_take_is_put_by_the_next_try_and_one_it_took_is_not_put_again(
    code_runner, monkeypatch
):
    put, failing = code_runner.put, ["attachments/report.csv"]

    async def failing_once(thread, path, data, source=None):
        if path in failing:
            failing.remove(path)
            raise CodeRunnerError("ConnectError: gone")
        return await put(thread, path, data, source)
    monkeypatch.setattr(code_runner, "put", failing_once)
    code_runner.files["attachments/report.csv"] = b"old"
    kept = Kept(earlier_txt=b"earlier")
    attached = Attached(code_runner, kept, "t1", kept.logs, [attached_file("notes.txt", b"notes"),
                                                             attached_file("report.csv", b"new")], "r2")

    with pytest.raises(CodeRunnerError):
        await attached.put_new()
    assert code_runner.files["attachments/report.csv"] == b"old"
    await attached.place()
    await attached.place()

    assert code_runner.files == {"attachments/notes.txt": b"notes", "attachments/report.csv": b"new",
                                 "attachments/earlier.txt": b"earlier"}
    assert code_runner.puts == [("attachments/notes.txt", "r2"), ("attachments/report.csv", "r2"),
                                ("attachments/earlier.txt", "r1")]


async def test_coding_tasks_that_start_together_put_each_file_once(code_runner):
    kept = Kept(earlier_txt=b"earlier")
    attached = Attached(code_runner, kept, "t1", kept.logs, [attached_file("notes.txt", b"notes")], "r2")

    await asyncio.gather(attached.place(), attached.place(), attached.put_new())

    assert sorted(code_runner.puts) == [("attachments/earlier.txt", "r1"), ("attachments/notes.txt", "r2")]


async def test_an_earlier_file_never_replaces_one_put_in_the_folder_meanwhile(code_runner):
    kept = Kept(report_csv=b"old")
    reading, read = asyncio.Event(), kept.get_file

    async def slow(run, name):
        reading.set()
        await asyncio.sleep(0)
        await code_runner.put("t1", "attachments/report.csv", b"new", "r2")
        return await read(run, name)
    kept.get_file = slow

    await Attached(code_runner, kept, "t1", kept.logs, [], "r2").place()

    assert reading.is_set() and code_runner.files == {"attachments/report.csv": b"new"}


async def test_the_coding_agent_looks_at_an_image_once_it_is_one_a_model_takes(code_runner):
    code_runner.files.update({
        "chart.png": image("PNG"), "frame.gif": image("GIF"), "huge.png": image("PNG", (3000, 10)),
    })
    view = next(each for each in coding_tools(code_runner, "t1", "k1") if each.name == "view_image")
    call = lambda path: view.ainvoke({"type": "tool_call", "id": "v1", "name": "view_image", "args": {"path": path}})

    seen = await call("chart.png")
    assert seen.content[1] == {
        "type": "image", "base64": base64.b64encode(code_runner.files["chart.png"]).decode(), "mime_type": "image/png",
    }
    for path, why in [("frame.gif", "save it as one first"), ("huge.png", "at most 2048 pixels"),
                      ("gone.png", "no gone.png")]:
        refused = await call(path)
        assert refused.status == "error" and why in refused.content


async def test_the_coding_agent_keeps_only_its_latest_images(settings, computer, code_runner, monkeypatch):
    code_runner.files["chart.png"] = image("PNG")
    looks = [AIMessage(content="", tool_calls=[tool_call(f"v{n}", "view_image", path="chart.png")]) for n in range(8)]
    coder = coding_script(monkeypatch, [*looks, AIMessage("It is a teal square.")])
    use_script(monkeypatch, [], main=[handing_code("Look at chart.png."), AIMessage("A teal square.")])

    result = await run_turn(settings, "What is in chart.png?", max_steps=20, computer=computer, code_runner=code_runner)

    images = [block for message in coder.received[-1] if isinstance(message.content, list)
              for block in message.content if block.get("type") == "image"]
    assert len(images) == 3  # as with screenshots: the oldest go five at a time, three at least stay
    opening = next(message for message in coder.received[0] if isinstance(message, HumanMessage))
    assert f"Your working folder is /workspace/{result.run}:" in opening.content  # so a file it made comes with its full path


@pytest.mark.skipif(sys.platform == "win32", reason="the runner is Linux")
def test_overlapping_restore_and_upload_leave_the_new_file(server, tmp_path, monkeypatch):
    target = (tmp_path / "t1/attachments/report.csv").resolve()
    checked, release, uploaded = threading.Event(), threading.Event(), threading.Event()
    is_file = Path.is_file

    def paused(path):
        result = is_file(path)
        if path == target and threading.current_thread().name == "restore":
            checked.set()
            assert release.wait(5)
        return result

    monkeypatch.setattr(Path, "is_file", paused)
    restore = threading.Thread(
        name="restore", target=lambda: server.put("t1", "attachments/report.csv", b"old", "r1"),
    )

    def upload():
        server.put("t1", "attachments/report.csv", b"new", "r2")
        uploaded.set()

    newer = threading.Thread(target=upload)
    restore.start()
    try:
        assert checked.wait(5)
        newer.start()
        uploaded.wait(0.2)  # a serialized upload waits for the restore to finish
    finally:
        release.set()
        restore.join(5)
        if newer.ident is not None:
            newer.join(5)
    assert not restore.is_alive() and not newer.is_alive()
    assert target.read_bytes() == b"new"


def test_the_server_keeps_edits_until_a_newer_attachment_arrives(server, tmp_path):
    data = bytes(range(256))
    assert server.put("t1", "attachments/a.bin", data, "r1") == {"path": "attachments/a.bin", "bytes": 256, "written": True}
    assert server.put("t1", "attachments/a.bin", b"new", "r1")["written"] is False
    assert (tmp_path / "t1" / "attachments" / "a.bin").read_bytes() == data
    server.write("t1", "attachments/a.bin", "edited")
    assert not server.put("t1", "attachments/a.bin", data, "r1")["written"]
    assert server.read("t1", "attachments/a.bin") == b"edited"
    assert server.put("t1", "attachments/a.bin", b"new", "r2")["written"]
    assert not server.put("t1", "attachments/a.bin", data, "r1")["written"]
    assert server.read("t1", "attachments/a.bin") == b"new"
    server.delete("t1")
    assert server.put("t1", "attachments/a.bin", data, "r1")["written"]
    with pytest.raises(server.Refused):
        server.put("t1", "../t2/a.bin", data)
    with pytest.raises(OSError):  # the handler says it in a 400
        server.put("t1", "attachments/" + "報" * 300 + ".txt", data)


def runner_with(handler) -> HttpCodeRunner:
    return HttpCodeRunner("http://code-runner:8080", transport=httpx.MockTransport(handler))


async def test_the_client_reads_status_seldom_and_tells_refusals_from_failures(tmp_path):
    asked = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.path)
        if request.url.path == "/write":
            return httpx.Response(400, json={"error": "../x is outside the working folder"})
        if request.url.path == "/run":
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json={"ok": True})

    runner = runner_with(handler)
    assert (await runner.status()).connected and (await runner.status()).connected
    with pytest.raises(ValueError, match="outside the working folder"):
        await runner.write("t", "../x", "")
    with pytest.raises(CodeRunnerError, match="HTTP 500"):
        await runner.run("t", "k", "true", 5)
    assert asked == ["/status", "/write", "/run"]

    def unreachable(request):
        raise httpx.ConnectError("no route")

    status = await runner_with(unreachable).status()
    assert not status.connected and "not reachable" in status.detail
    # As compose.yaml reaches it: over a socket in a shared volume, here one that is not there.
    missing = await HttpCodeRunner(f"unix://{tmp_path / 'runner.sock'}").status()
    assert not missing.connected and "unix://" in missing.detail


async def test_stopping_a_task_stops_its_command_on_the_runner():
    started, asked = asyncio.Event(), []

    async def handler(request: httpx.Request) -> httpx.Response:
        asked.append((request.url.path, json.loads(request.content).get("task")))
        if request.url.path == "/run":
            started.set()
            await asyncio.sleep(60)
        return httpx.Response(200, json={"stopped": True})

    runner = runner_with(handler)
    command = asyncio.create_task(runner.run("t", "k", "sleep 60", 120))
    await started.wait()
    command.cancel()
    with pytest.raises(asyncio.CancelledError):
        await command
    assert asked == [("/run", "k"), ("/stop", "k")]  # its own command, not the conversation's others


def landlocked() -> bool:
    """Whether this kernel confines commands as the runner does (Landlock); elsewhere, such as macOS, the tests run
    them unconfined."""
    return sys.platform == "linux" and ctypes.CDLL(None, use_errno=True).syscall(444, None, 0, 1) >= 0


@pytest.fixture
def server(tmp_path, tmp_path_factory, monkeypatch):
    path = Path(__file__).parents[3] / "code-runner" / "server.py"
    spec = importlib.util.spec_from_file_location("code_runner_server", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "WORKSPACE", tmp_path)
    if not landlocked():
        unconfined = tmp_path_factory.mktemp("sandbox") / "unconfined.py"
        # macOS adds this to a Python process's environment; the runner's Linux does not.
        unconfined.write_text(
            "import os, sys\nos.environ.pop('__CF_USER_TEXT_ENCODING', None)\nos.execvp(sys.argv[2], sys.argv[2:])\n"
        )
        monkeypatch.setattr(module, "SANDBOX", unconfined)
    return module


@pytest.mark.skipif(sys.platform == "win32", reason="the runner is Linux")
def test_the_server_keeps_each_conversation_in_its_folder(server, tmp_path):
    written = server.write("t1", "sub/a.txt", "hi")
    assert written == {"path": "sub/a.txt", "bytes": 2} and (tmp_path / "t1" / "sub" / "a.txt").read_text() == "hi"
    for bad in ("../escape.txt", "/etc/passwd", "sub/../../t2/x"):
        with pytest.raises(server.Refused):
            server.write("t1", bad, "no")
    for thread in ("../t2", "", ".hidden", "a/b"):
        with pytest.raises(server.Refused):
            server.run(thread, "k1", "true", 5)
    assert server.run("t1", "k1", "cat sub/a.txt; pwd", 5) == {"code": 0, "output": f"hi{tmp_path / 't1'}\n", "cut": 0}


def test_an_absolute_output_path_still_downloads_after_changing_directory(server, tmp_path):
    path = server.folder("t1") / "result.txt"
    result = server.run("t1", "k1", f"mkdir -p out; cd out; printf artifact > '{path}'", 5)
    assert result["code"] == 0
    assert server.read("t1", "result.txt") == b"artifact"
    assert not (tmp_path / "t1/out/result.txt").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="the runner is Linux")
def test_tasks_of_one_conversation_run_side_by_side_and_each_stops_only_its_own(server, tmp_path):
    results = {}

    def go(task, script):
        results[task] = server.run("t1", task, script, 30)

    first = threading.Thread(target=go, args=("k1", "sleep 30; echo one"))
    second = threading.Thread(target=go, args=("k2", "sleep 1; echo two > two.txt; echo two"))
    first.start(), second.start()
    for _ in range(100):  # both running at once, in the same folder
        if set(server.running) == {"k1", "k2"}:
            break
        time.sleep(0.02)
    assert set(server.running) == {"k1", "k2"}
    with pytest.raises(server.Refused, match="this task is still running"):
        server.run("t1", "k1", "true", 5)
    assert server.stop("k1") and not server.stop("k3")
    first.join(5), second.join(5)
    assert results["k1"]["code"] != 0 and results["k2"] == {"code": 0, "output": "two\n", "cut": 0}
    assert (tmp_path / "t1" / "two.txt").read_text() == "two\n" and server.running == {}
    for task in ("", "../k", None):
        with pytest.raises(server.Refused):
            server.run("t1", task, "true", 5)


@pytest.mark.skipif(sys.platform == "win32", reason="the runner is Linux")
def test_a_command_gets_nothing_of_the_servers_environment(server, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    output = server.run("t1", "k1", "env", 5)["output"]
    names = {line.split("=", 1)[0] for line in output.splitlines()}
    assert "OPENAI_API_KEY" not in names and names <= {"PATH", "HOME", "TMPDIR", "LANG", "PYTHONSAFEPATH", "PWD", "SHLVL", "_"}


def test_a_script_named_after_a_module_hides_none(server, tmp_path):
    (tmp_path / "t1").mkdir()
    (tmp_path / "t1" / "inspect.py").write_text("import json, inspect\nprint(inspect.isfunction(print))\n")
    assert server.run("t1", "k1", f"{sys.executable} inspect.py", 5)["output"] == "False\n"


@pytest.mark.skipif(sys.platform == "win32", reason="the runner is Linux")
def test_a_command_that_returns_leaves_nothing_it_started_running(server, tmp_path):
    result = server.run("t1", "k1", "(sleep 0.3; touch late) & echo started", 5)
    assert result == {"code": 0, "output": "started\n", "cut": 0}
    time.sleep(0.6)  # long enough for the background sleep to have touched the file, had it run on
    assert not (tmp_path / "t1" / "late").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="the runner is Linux")
def test_a_command_over_its_time_is_stopped_with_everything_it_started(server, tmp_path):
    result = server.run("t1", "k1", "(sleep 30; touch late) & echo started; wait", 1)
    assert result["code"] is None and result["output"] == "started\n"
    assert server.running == {}
    time.sleep(0.2)  # long enough for the background sleep to have touched the file, had it run on
    assert not (tmp_path / "t1" / "late").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="the runner is Linux")
def test_long_output_keeps_its_start_and_end(server, monkeypatch):
    monkeypatch.setattr(server, "KEEP", 10)
    result = server.run("t1", "k1", "printf 'a%.0s' $(seq 15); printf 'b%.0s' $(seq 15)", 5)
    assert result["cut"] == 10
    assert result["output"] == "aaaaaaaaaa\n[... 10 bytes cut ...]\nbbbbbbbbbb"


@pytest.mark.skipif(sys.platform == "win32", reason="the runner is Linux")
async def test_the_runtime_reaches_the_server_over_its_socket(server, monkeypatch):
    # As compose.yaml runs it, with no network: a Unix socket, which the no-network rule of these tests allows. In /tmp,
    # since a socket's path must be short. This client shares the server's processes, as only a command would in the
    # container, so the check for that is left out here.
    monkeypatch.setattr(server.UnixHTTPServer, "verify_request", lambda *args: True)
    path = Path(tempfile.mkdtemp(prefix="runner-", dir="/tmp")) / "runner.sock"
    httpd = server.UnixHTTPServer(str(path), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    runner = HttpCodeRunner(f"unix://{path}")
    try:
        assert (await runner.status()).connected
        folder = f"{server.WORKSPACE}/t1"
        assert await runner.write("t1", "a.txt", "hi") == "Wrote a.txt (2 bytes)."
        assert await runner.run("t1", "k1", "cat a.txt", 5) == RunOutput(0, "hi", 0)
        await runner.write("t1", f"{folder}/sub/absolute.txt", "absolute")
        assert await runner.read("t1", f"{folder}/sub/absolute.txt") == b"absolute"
        with pytest.raises(ValueError):
            await runner.read("t1", f"{server.WORKSPACE}/t2/a.txt")
        await runner.write("t1", "報表/年度 預算.csv", "方案,金額\nA,90720\n")
        assert await runner.read("t1", "報表/年度 預算.csv") == "方案,金額\nA,90720\n".encode()
        with pytest.raises(FileNotFoundError):
            await runner.read("t2", "a.txt")
        with pytest.raises(ValueError):
            await runner.read("t1", "../t2/a.txt")
        with pytest.raises(ValueError, match="outside the working folder"):
            await runner.write("t1", "../b.txt", "no")
        assert not await runner.has("t1", "attachments/報表.xlsx")
        assert await runner.put("t1", "attachments/報表.xlsx", bytes(range(256)), "r1")
        assert not await runner.put("t1", "attachments/報表.xlsx", b"new", "r1")
        assert await runner.has("t1", "attachments/報表.xlsx")
        assert await runner.has("t1", "attachments/報表.xlsx", "r1")
        assert not await runner.has("t1", "attachments/報表.xlsx", "r2")
        assert await runner.read("t1", "attachments/報表.xlsx") == bytes(range(256))
        assert await runner.put("t1", "attachments/報表.xlsx", b"new", "r2")
        assert not await runner.put("t1", "attachments/報表.xlsx", b"old", "r1")
        assert await runner.read("t1", "attachments/報表.xlsx") == b"new"
        with pytest.raises(ValueError, match="too long"):
            await runner.put("t1", "attachments/" + "報" * 300 + ".txt", b"x")
        await runner.delete("t1")
        with pytest.raises(FileNotFoundError):
            await runner.read("t1", "a.txt")
    finally:
        await runner.close()
        httpd.shutdown()
        httpd.server_close()
        path.unlink(missing_ok=True)


@pytest.mark.skipif(sys.platform == "win32", reason="the runner is Linux")
def test_deleting_a_conversation_removes_only_its_folder(server, tmp_path):
    server.write("t1", "sub/a.txt", "a")
    server.write("t2", "b.txt", "b")
    (tmp_path / "t3").symlink_to(tmp_path / "t2", target_is_directory=True)  # what a command could leave
    assert server.delete("t1") is True and not (tmp_path / "t1").exists()
    assert server.delete("t1") is False
    assert server.delete("t3") is True and not (tmp_path / "t3").exists() and (tmp_path / "t2" / "b.txt").exists()
    for thread in ("../t2", "", ".hidden", "a/b", None):
        with pytest.raises(server.Refused):
            server.delete(thread)
    assert (tmp_path / "t2" / "b.txt").read_text() == "b"


@pytest.mark.skipif(not landlocked(), reason="needs Landlock, as the runner's kernel has")
def test_a_command_reaches_only_its_own_conversations_folder(server, tmp_path):
    server.write("t2", "secret.txt", "t2's")
    script = "echo mine > a.txt; cat a.txt; cat ../t2/secret.txt; ls ..; ls /tmp; python3 -c 'print(6 * 7)'"
    output = server.run("t1", "k1", script, 10)["output"]
    assert "mine" in output and "42" in output and "t2's" not in output
    assert output.count("Permission denied") == 3  # the other folder, the list of folders and /tmp


@pytest.mark.skipif(not hasattr(socket, "SO_PEERCRED"), reason="peer credentials are Linux's")
def test_the_socket_turns_away_callers_in_its_own_container(server):
    path = Path(tempfile.mkdtemp(prefix="runner-", dir="/tmp")) / "runner.sock"
    httpd = server.UnixHTTPServer(str(path), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        with socket.socket(socket.AF_UNIX) as caller:
            caller.connect(str(path))
            caller.sendall(b"GET /status HTTP/1.0\r\n\r\n")
            try:
                answer = caller.recv(100)
            except ConnectionResetError:
                answer = b""
            assert answer == b""  # closed unanswered
    finally:
        httpd.shutdown()
        httpd.server_close()
        path.unlink(missing_ok=True)


def test_downloads_refuse_symlinks_folders_special_files_and_large_files(server, tmp_path, monkeypatch):
    server.write("t1", "a.csv", "a,b\n1,2\n")
    server.write("t1", "sub/b.csv", "b")
    server.write("t2", "private.csv", "private")
    (tmp_path / "t1" / "link").symlink_to(tmp_path / "t2", target_is_directory=True)
    (tmp_path / "t1" / "linked.csv").symlink_to(tmp_path / "t2" / "private.csv")
    (tmp_path / "t3").symlink_to(tmp_path / "t2", target_is_directory=True)
    os.mkfifo(tmp_path / "t1" / "pipe")
    open_before = len(os.listdir("/dev/fd"))
    for thread, path in [("t1", "link/private.csv"), ("t1", "linked.csv"), ("t3", "private.csv"), ("t1", "sub"),
                         ("t1", "pipe"), ("t1", "/etc/passwd"), ("t1", "../t2/private.csv")]:
        with pytest.raises(server.Refused):
            server.read(thread, path)
    assert len(os.listdir("/dev/fd")) == open_before  # a refused download leaves nothing open
    monkeypatch.setattr(server, "MAX_FILE", 3)
    with pytest.raises(server.Refused, match="over 3 bytes"):
        server.read("t1", "a.csv")


async def test_a_coding_task_runs_while_a_computer_task_does_each_logged_under_its_id(
    settings, computer, code_runner, monkeypatch
):
    use_script(monkeypatch, [
        AIMessage(content="", tool_calls=[tool_call("c1", "key", text="win")]), AIMessage("Opened Start."),
    ], main=[
        AIMessage(content="", tool_calls=[
            tool_call("m1", "start_task", agent="computer", title="Task", task="Open Start."),
            tool_call("m2", "start_task", agent="coding", title="Task", task="Add 2 and 2."),
        ]),
        AIMessage("Done."),
        AIMessage("Done."),
    ])
    coding_script(monkeypatch, [
        AIMessage(content="", tool_calls=[tool_call("k1", "bash", script="echo 4")]), AIMessage("It printed 4."),
    ])
    # Each waits for the other's action: done one after the other, neither would finish.
    pressed, ran = asyncio.Event(), asyncio.Event()
    press = computer.press

    async def pressing(combos):
        pressed.set()
        await asyncio.wait_for(ran.wait(), 5)
        await press(combos)

    async def running(script):
        ran.set()
        await asyncio.wait_for(pressed.wait(), 5)
        return RunOutput(0, "4\n", 0)

    computer.press, code_runner.answer = pressing, running

    result = await run_turn(
        settings, "open start and add 2 and 2", max_steps=10, computer=computer, code_runner=code_runner
    )

    assert result.reply == "Done."
    started = {event["agent"]: event["id"] for event in events_of(settings, result.run)
               if event["type"] == "task" and event["state"] == "started"}
    assert sorted(started.values()) == ["t1", "t2"]
    # Each task's action is in its own log.
    tools = {agent: [e["tool"] for e in read_events(task_folder(settings, result.run, id)) if e["type"] == "action"]
             for agent, id in started.items()}
    assert tools == {"computer": ["key"], "coding": ["bash"]}


async def test_work_handed_over_while_tasks_run_spreads_it_and_is_not_a_retry(
    settings, computer, code_runner, monkeypatch
):
    # One long file and three short ones: the short ones are handed over one at a time as the one before ends, while the
    # long one still runs. Counted as rounds, the fourth hand-over would be a second retry of the message and refused.
    finishing = asyncio.Event()

    class Coder(ScriptedModel):
        async def ainvoke(self, input, config=None, **kwargs):
            if any("Sum the long file." in message.text for message in input):  # the long file's
                await asyncio.wait_for(finishing.wait(), 5)
            return AIMessage("Summed it.")

    class Main(ScriptedModel):
        async def ainvoke(self, input, config=None, **kwargs):
            if len(self.received) == 3:  # every short file is done: the long one may end
                finishing.set()
            return await super().ainvoke(input, config, **kwargs)

    main = Main(messages=iter([
        AIMessage(content="", tool_calls=[
            tool_call("m1", "start_task", agent="coding", title="Long", task="Sum the long file."),
            tool_call("m2", "start_task", agent="coding", title="Two", task="Sum file 2."),
        ]),
        handing_code("Sum file 3.", "m3"),
        handing_code("Sum file 4.", "m4"),
        AIMessage("Three are summed; the long one is still going."),
        AIMessage("Done."),
    ]), received=[], bindings=[])
    monkeypatch.setattr(main_agent, "build_chat_model", lambda _spec, _settings, **_: main)
    monkeypatch.setattr(coding_agent, "build_chat_model",
                        lambda _spec, _settings: Coder(messages=iter([]), received=[], bindings=[]))

    result = await run_turn(
        settings, "sum each file", max_steps=10, computer=computer, code_runner=code_runner
    )

    assert result.reply == "Done."
    actions = logged(result, "action", MAIN)
    assert [event["status"] for event in actions] == ["success"] * 4
    ended = [id for id, state in task_states(settings, result.run) if state == "ended"]
    long = next(e["id"] for e in events_of(settings, result.run) if e["type"] == "task" and e["brief"] == "Sum the long file.")
    assert sorted(ended) == ["t1", "t2", "t3", "t4"] and ended[-1] == long


async def test_a_message_for_the_desktop_handed_only_to_code_goes_to_the_desktop_too(
    settings, computer, code_runner, monkeypatch
):
    computer_model, main_model = use_script(monkeypatch, [AIMessage("Opened Notepad.")], main=[
        handing_code("Count the days to New Year.", "m1"), AIMessage("Counting, and Notepad is opening."),
        AIMessage("Done."), AIMessage("Done."),
    ])
    coding_script(monkeypatch, [AIMessage("69 days.")])

    result = await run_turn(
        settings, "open notepad and count the days to New Year", max_steps=10, computer=computer,
        code_runner=code_runner, force_computer=True,
    )

    started = {e["agent"]: e["brief"] for e in events_of(settings, result.run)
               if e["type"] == "task" and e["state"] == "started"}
    assert started == {"coding": "Count the days to New Year.",
                       "computer": "open notepad and count the days to New Year"}
    # The runtime's word comes after the result of the call the reply made, as model APIs want it.
    second = main_model.received[1]
    assert isinstance(second[-2], ToolMessage) and second[-2].tool_call_id == "m1"
    assert second[-1].text.startswith("[From the runtime, not the user] " + DESKTOP_HANDED)
    assert len(computer_model.received) == 1
