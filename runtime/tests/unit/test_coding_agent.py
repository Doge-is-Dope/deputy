"""The coding agent and the code runner: offered when the runner can be reached, its commands run there in the
conversation's folder, and nothing it does needs the computer or the user's approval. The runner's own server
(code-runner/server.py) keeps each conversation in its folder, gives a command nothing of its environment, and stops a
command and everything it started after its time."""

import asyncio
import importlib.util
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

import computer_use.agent.coding_agent as coding_agent
import computer_use.agent.main_agent as main_agent
from computer_use.prompts import notes
from computer_use.agent.coding_agent import coding_tools
from computer_use.agent.trajectory import TASK
from computer_use.storage import MAIN
from computer_use.sandbox import CodeRunnerError, RunOutput
from computer_use.sandbox.http import HttpCodeRunner
from computer_use.desktop.control import RunLock
from computer_use.agent.history import tasks
from conftest import run_turn
from conftest import read_events, run_dir
from conftest import ScriptedModel, logged, tool_call, use_script

pytestmark = pytest.mark.usefixtures("the_log_is_the_whole_record")


def coding_script(monkeypatch, replies) -> ScriptedModel:
    model = ScriptedModel(messages=iter(replies), received=[], bindings=[])
    monkeypatch.setattr(coding_agent, "build_chat_model", lambda _spec, _settings: model)
    return model


def handing_code(task="Add 2 and 2.", call_id="m1") -> AIMessage:
    return AIMessage(content="", tool_calls=[tool_call(call_id, "write_code", title="Task", task=task)])


async def test_the_coding_agent_is_offered_only_when_the_code_runner_can_be_reached(
    settings, computer, code_runner, monkeypatch
):
    _, main_model = use_script(monkeypatch, [], main=[AIMessage("Hi."), AIMessage("Hi."), AIMessage("Hi.")])

    await run_turn(settings, "hi", max_steps=10, computer=computer)
    code_runner.connected = False
    await run_turn(settings, "hi", max_steps=10, computer=computer, code_runner=code_runner)
    code_runner.connected = True
    await run_turn(settings, "hi", max_steps=10, computer=computer, code_runner=code_runner)

    prompts = [received[0].text for received in main_model.received]
    assert ["write_code" in prompt for prompt in prompts] == [False, False, True]
    assert not code_runner.closed  # the server's runner outlives a run


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
    task = coding.received[0][1].text
    assert task.startswith("Goal: Add 2 and 2 with Python.") and "word for word: what is 2 + 2" in task
    ended = tasks(read_events(run_dir(settings, result.run)))
    assert [(each["tool"], each["stop_reason"], each["reply"]) for each in ended] == [
        ("write_code", "replied", "It printed 4.")
    ]
    assert ended[0]["actions"][-1] == 'bash {"script": "python3 add.py"} -> success: Exit code 0.'
    report = next(e for e in logged(result, "input", MAIN)
                  if e["message"]["data"].get("additional_kwargs", {}).get("runtime", {}).get("event") == "task_ended")
    text = "\n".join(b["text"] for b in report["message"]["data"]["content"] if b.get("type") == "text")
    assert "The coding agent stopped: it replied." in text and "screenshot" not in text


async def test_a_later_desktop_task_sees_the_coding_task_on_its_blackboard(
    settings, computer, code_runner, monkeypatch
):
    computer_model, _ = use_script(monkeypatch, [AIMessage("Looked.")], main=[
        handing_code("Sum the numbers.", "m1"),
        AIMessage(content="", tool_calls=[tool_call("m2", "computer_use", title="Task", task="Type the sum.")]),
        AIMessage("Done."),
    ])
    coding_script(monkeypatch, [AIMessage("The sum is 10.")])

    await run_turn(settings, "sum and type", max_steps=10, computer=computer, code_runner=code_runner)

    board = computer_model.received[0][1].content[0]["text"]
    assert "An earlier task, handed over with write_code: Sum the numbers." in board
    assert "Its final message: The sum is 10." in board


async def test_a_command_that_is_refused_or_too_slow_is_the_agents_to_hear(code_runner):
    tools = {each.name: each for each in coding_tools(code_runner, "thread")}
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
    assert tasks(read_events(run_dir(settings, result.run)))[0]["stop_reason"] == "error"


# The runtime's client, against a fake transport.


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
        await runner.run("t", "true", 5)
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
        asked.append(request.url.path)
        if request.url.path == "/run":
            started.set()
            await asyncio.sleep(60)
        return httpx.Response(200, json={"stopped": True})

    runner = runner_with(handler)
    command = asyncio.create_task(runner.run("t", "sleep 60", 120))
    await started.wait()
    command.cancel()
    with pytest.raises(asyncio.CancelledError):
        await command
    assert asked == ["/run", "/stop"]


@pytest.fixture
def server(tmp_path, monkeypatch):
    path = Path(__file__).parents[3] / "code-runner" / "server.py"
    spec = importlib.util.spec_from_file_location("code_runner_server", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "WORKSPACE", tmp_path)
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
            server.run(thread, "true", 5)
    assert server.run("t1", "cat sub/a.txt; pwd", 5) == {"code": 0, "output": f"hi{tmp_path / 't1'}\n", "cut": 0}


@pytest.mark.skipif(sys.platform == "win32", reason="the runner is Linux")
def test_a_command_gets_nothing_of_the_servers_environment(server, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    output = server.run("t1", "env", 5)["output"]
    names = {line.split("=", 1)[0] for line in output.splitlines()}
    assert "OPENAI_API_KEY" not in names and names <= {"PATH", "HOME", "LANG", "PWD", "SHLVL", "_"}


@pytest.mark.skipif(sys.platform == "win32", reason="the runner is Linux")
def test_a_command_over_its_time_is_stopped_with_everything_it_started(server, tmp_path):
    result = server.run("t1", "(sleep 30; touch late) & echo started; wait", 1)
    assert result["code"] is None and result["output"] == "started\n"
    assert server.running == {}
    time.sleep(0.2)  # long enough for the background sleep to have touched the file, had it run on
    assert not (tmp_path / "t1" / "late").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="the runner is Linux")
def test_long_output_keeps_its_start_and_end(server, monkeypatch):
    monkeypatch.setattr(server, "KEEP", 10)
    result = server.run("t1", "printf 'a%.0s' $(seq 15); printf 'b%.0s' $(seq 15)", 5)
    assert result["cut"] == 10
    assert result["output"] == "aaaaaaaaaa\n[... 10 bytes cut ...]\nbbbbbbbbbb"


@pytest.mark.skipif(sys.platform == "win32", reason="the runner is Linux")
async def test_the_runtime_reaches_the_server_over_its_socket(server):
    # As compose.yaml runs it, with no network: a Unix socket, which the no-network rule of these tests allows. In /tmp,
    # since a socket's path must be short.
    path = Path(tempfile.mkdtemp(prefix="runner-", dir="/tmp")) / "runner.sock"
    httpd = server.UnixHTTPServer(str(path), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    runner = HttpCodeRunner(f"unix://{path}")
    try:
        assert (await runner.status()).connected
        assert await runner.write("t1", "a.txt", "hi") == "Wrote a.txt (2 bytes)."
        assert await runner.run("t1", "cat a.txt", 5) == RunOutput(0, "hi", 0)
        with pytest.raises(ValueError, match="outside the working folder"):
            await runner.write("t1", "../b.txt", "no")
    finally:
        await runner.close()
        httpd.shutdown()
        httpd.server_close()
        path.unlink(missing_ok=True)


async def test_a_coding_task_runs_while_a_computer_task_does_each_logged_under_its_id(
    settings, computer, code_runner, monkeypatch
):
    use_script(monkeypatch, [
        AIMessage(content="", tool_calls=[tool_call("c1", "key", text="win")]), AIMessage("Opened Start."),
    ], main=[
        AIMessage(content="", tool_calls=[
            tool_call("m1", "computer_use", title="Task", task="Open Start."), tool_call("m2", "write_code", title="Task", task="Add 2 and 2."),
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
    ids = {event["tool"]: event["task"] for event in logged(result, "action")}
    assert sorted(ids.values()) == ["t1", "t2"]
    started = {event["tool"]: event["id"] for event in read_events(run_dir(settings, result.run))
               if event["type"] == "task" and event["state"] == "started"}
    assert started == {"computer_use": ids["key"], "write_code": ids["bash"]}


async def test_work_handed_over_while_tasks_run_spreads_it_and_is_not_a_retry(
    settings, computer, code_runner, monkeypatch
):
    # One long file and three short ones: the short ones are handed over one at a time as the one before ends, while the
    # long one still runs. Counted as rounds, the fourth hand-over would be a second retry of the message and refused.
    finishing = asyncio.Event()

    class Coder(ScriptedModel):
        async def ainvoke(self, input, config=None, **kwargs):
            if TASK.get() == "t1":  # the long file's
                await asyncio.wait_for(finishing.wait(), 5)
            return AIMessage("Summed it.")

    class Main(ScriptedModel):
        async def ainvoke(self, input, config=None, **kwargs):
            if len(self.received) == 3:  # every short file is done: the long one may end
                finishing.set()
            return await super().ainvoke(input, config, **kwargs)

    main = Main(messages=iter([
        AIMessage(content="", tool_calls=[
            tool_call("m1", "write_code", title="Long", task="Sum the long file."),
            tool_call("m2", "write_code", title="Two", task="Sum file 2."),
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
    ended = [event["id"] for event in read_events(run_dir(settings, result.run))
             if event["type"] == "task" and event["state"] == "ended"]
    assert sorted(ended) == ["t1", "t2", "t3", "t4"] and ended[-1] == "t1"


async def test_a_message_for_the_desktop_handed_only_to_code_goes_to_the_desktop_too(
    settings, computer, code_runner, monkeypatch
):
    computer_model, main_model = use_script(monkeypatch, [AIMessage("Opened Notepad.")], main=[
        handing_code("Count the days to New Year.", "m1"), AIMessage("Counting, and Notepad is opening."),
        AIMessage("Done."), AIMessage("Done."),
    ])
    coding_script(monkeypatch, [AIMessage("69 days.")])

    result = await run_turn(
        settings, "@Computer open notepad and count the days to New Year", max_steps=10, computer=computer,
        code_runner=code_runner, force_computer=True,
    )

    started = {e["tool"]: e["brief"] for e in read_events(run_dir(settings, result.run))
               if e["type"] == "task" and e["state"] == "started"}
    assert started == {"write_code": "Count the days to New Year.",
                       "computer_use": "@Computer open notepad and count the days to New Year"}
    # The runtime's word comes after the result of the call the reply made, as model APIs want it.
    second = main_model.received[1]
    assert isinstance(second[-2], ToolMessage) and second[-2].tool_call_id == "m1"
    assert second[-1].text.startswith("[From the runtime, not the user] " + notes.DESKTOP_HANDED)
    assert len(computer_model.received) == 1
