"""Commands on Windows through the Windows Tools host: the transport, the lease and what the model is told."""

import hashlib

import pytest
from langchain_core.messages import AIMessage

from computer_use.adapters import build_windows_tools
from computer_use.computers import Status
from computer_use.config import RunChoices, Settings
from computer_use.native import HostError
from computer_use.native.execution import MAX_OUTPUT_CHARACTERS, Commands, report
from computer_use.native import lease as leases
from computer_use.native.lease import Lease
from computer_use.native.mcp import Connection, McpChannel, check_certificate
from computer_use.tools.native import command_tools

from conftest import run_turn, use_script

TARGET = {"environmentGeneration": "g", "hostInstance": "h", "sessionId": 1, "controlEpoch": 1}
RAN = {"state": "succeeded", "exitCode": 0, "error": None, "durationMs": 340, "output": "22\r\n", "outputTruncated": False}


class Host:
    """A host that answers calls as the real one does, and remembers them."""

    def __init__(self):
        self.calls: list[tuple[str, dict | None, dict | None]] = []
        self.fail: HostError | None = None
        self.result = RAN

    async def call(self, method, target=None, args=None, *, timeout=5):
        self.calls.append((method, target, args))
        if self.fail:
            raise self.fail
        if method == "exec.run":
            return self.result
        return {"target": TARGET, "controlOwner": "human" if method == "control.takeover" else "agent"}

    def sent(self) -> list[str]:
        return [method for method, _, _ in self.calls]


TOKEN, FINGERPRINT = "ab" * 32, hashlib.sha256(b"the host's certificate").hexdigest()
URL = f"https://{TOKEN}@127.0.0.1:8767/{FINGERPRINT.upper()}"


def test_one_url_says_where_the_host_is_its_token_and_its_certificate():
    assert Connection.from_url(URL) == Connection("127.0.0.1", 8767, TOKEN, FINGERPRINT)
    assert Connection.from_url(f"https://{TOKEN}@windows.example/{FINGERPRINT}").port == 8767
    for wrong in (f"https://127.0.0.1/{FINGERPRINT}", f"https://{TOKEN}@127.0.0.1", f"http://{TOKEN}@127.0.0.1/{FINGERPRINT}"):
        with pytest.raises(ValueError, match="WINDOWS_TOOLS_URL"):
            Connection.from_url(wrong)


def test_only_the_certificate_the_url_names_is_trusted():
    connection = Connection.from_url(URL)
    check_certificate(connection, b"the host's certificate")
    with pytest.raises(HostError) as refused:
        check_certificate(connection, b"another certificate")
    assert refused.value.code == "certificate_changed" and not refused.value.sent


def test_windows_tools_are_on_with_a_url_in_env_and_write_nothing(settings, control, tmp_path):
    env = tmp_path / ".env"
    env.write_text(f"WINDOWS_TOOLS_URL={URL}\n")
    on = Settings(_env_file=env, data_dir=settings.data_dir)
    assert Connection.from_url(on.windows_tools_url.get_secret_value()).fingerprint == FINGERPRINT  # the whole line
    assert build_windows_tools(on, control) is not None
    for off in (None, ""):
        assert build_windows_tools(Settings(_env_file=None, data_dir=settings.data_dir, windows_tools_url=off), control) is None
    assert not list(settings.data_dir.glob("windows-tools*"))


async def test_a_tool_call_names_the_session_it_is_for_and_the_lease_goes_beside_mcp():
    posted = []

    def post(path, body, timeout):
        posted.append((path, body))
        if path == "/connector/control":
            return {"id": body["id"], "result": {"target": TARGET}, "error": None}
        if body["method"] == "tools/call":
            return {"id": body["id"], "result": {"structuredContent": {"id": "x", "result": RAN, "error": None}}}
        return {"id": body.get("id"), "result": {"protocolVersion": "2025-11-25"}}

    channel = McpChannel(post)
    assert await channel.call("control.resume", TARGET) == {"target": TARGET}
    assert await channel.call("exec.run", TARGET, {"command": "hostname"}) == RAN
    await channel.call("exec.run", TARGET, {"command": "hostname"})
    paths = [path for path, _ in posted]
    assert paths == ["/connector/control", "/mcp", "/mcp", "/mcp", "/mcp"]  # one handshake, then the calls
    control, _, _, call, _ = (body for _, body in posted)
    assert control["method"] == "control.resume" and control["target"] == TARGET and control["args"] == {}
    assert call["params"] == {
        "name": "windows_exec_run", "arguments": {"command": "hostname"}, "_meta": {"windows-tools/target": TARGET},
    }


async def test_a_refusal_says_whether_the_call_could_have_run():
    def post(path, body, timeout):
        if body.get("method") != "tools/call":
            return {"id": body.get("id"), "result": {}}
        return {"id": body["id"], "result": {"structuredContent": {"id": "x", "result": None, "error": error}}}

    channel = McpChannel(post)
    error = {"code": "control_required", "message": "Acquire the lease.", "delivery": "not_sent"}
    with pytest.raises(HostError) as refused:
        await channel.call("exec.run", TARGET, {"command": "x"})
    assert refused.value.code == "control_required" and not refused.value.sent
    error = {"code": "internal_error", "message": "Unknown.", "delivery": "unknown"}
    with pytest.raises(HostError) as unknown:
        await channel.call("exec.run", TARGET, {"command": "x"})
    assert unknown.value.sent


async def test_a_failed_handshake_ran_nothing():
    def post(path, body, timeout):
        raise HostError("no_reply", "The host did not reply.")

    with pytest.raises(HostError) as failed:
        await McpChannel(post).call("exec.run", TARGET, {"command": "x"})
    assert not failed.value.sent


async def test_the_lease_is_held_while_the_agent_has_the_desktop_and_only_then(control):
    host = Host()
    lease = Lease(host, control)
    control.write("user", "took over")
    await lease.step()
    assert host.calls == [] and lease.target is None and "user has control" in lease.problem

    control.write("agent", "returned")
    await lease.step()
    await lease.step()
    assert host.sent() == ["describe", "control.resume", "control.heartbeat"] and lease.target == TARGET

    control.write("user", "took over")
    await lease.step()
    assert host.sent()[-1] == "control.takeover" and lease.target is None


async def test_a_fault_keeps_who_has_the_desktop_and_the_lease_is_taken_again(control):
    host = Host()
    lease = Lease(host, control)
    control.write("agent", "returned")
    before = control.read()
    await lease.step()
    host.fail = HostError("unreachable", "The host did not answer.", sent=False)
    await lease.step()
    assert lease.target is None and lease.problem == "The host did not answer." and control.read() == before
    host.fail = None
    await lease.step()
    assert lease.target == TARGET and lease.problem == "" and control.read() == before
    await lease.close()
    assert host.sent()[-1] == "control.takeover"


async def test_the_status_says_whether_the_host_answers_checked_again_after_a_while(control, monkeypatch):
    host = Host()
    lease = Lease(host, control)
    host.fail = HostError("unreachable", "The host did not answer.", sent=False)
    assert await lease.status() == Status(False, "The host did not answer.")
    host.fail = None
    assert not (await lease.status()).connected and host.sent() == ["describe"]  # the last check holds a while
    monkeypatch.setattr(leases, "STATUS_SECONDS", 0)
    assert await lease.status() == Status(True)
    control.write("agent", "returned")
    await lease.step()
    host.calls.clear()
    assert await lease.status() == Status(True) and not host.calls  # a lease held says so itself


def commands(host, control, executor) -> tuple[Commands, Lease]:
    lease = Lease(host, control)
    return Commands(lease, executor), lease


async def test_a_command_returns_how_it_ended_what_it_printed_and_the_screen(executor, control):
    host = Host()
    run, lease = commands(host, control, executor)
    await lease.step()
    result = await run.run("(Get-Content a.txt | Select-String example).Count", 30)
    assert result.ok and result.text.startswith("Exit code 0 after 0.3 s.\n22\n") and result.frame is not None
    assert host.calls[-1] == ("exec.run", TARGET, {"command": "(Get-Content a.txt | Select-String example).Count", "timeoutMs": 30000})


async def test_no_command_is_sent_without_the_lease_or_while_the_user_has_the_desktop(executor, control):
    host = Host()
    run, lease = commands(host, control, executor)
    waiting = await run.run("hostname", 30)
    assert not waiting.ok and "unavailable right now (not started yet)" in waiting.text
    await lease.step()
    control.write("user", "took over")
    held = await run.run("hostname", 30)
    assert not held.ok and "the user has control" in held.text
    assert "exec.run" not in host.sent()


async def test_a_lost_reply_is_told_as_unknown_and_a_refusal_as_not_executed(executor, control):
    host = Host()
    run, lease = commands(host, control, executor)
    await lease.step()
    host.fail = HostError("no_reply", "The host did not reply.")
    unknown = await run.run("Remove-Item a.txt", 30)
    assert unknown.ok and unknown.text.startswith("Outcome unknown: the command may have run") and unknown.frame is not None
    host.fail = HostError("desktop_busy", "An exec job owns this session.", sent=False)
    refused = await run.run("Remove-Item a.txt", 30)
    assert not refused.ok and refused.text == "Not executed: An exec job owns this session."
    assert host.sent().count("exec.run") == 2  # neither was sent again


async def test_an_approval_covers_one_command(executor, control):
    host = Host()
    run, lease = commands(host, control, executor)
    await lease.step()
    executor.approve_next()
    await run.run("hostname", 30)
    assert not executor.approved


def test_a_report_says_how_the_command_ended():
    assert report(RAN) == "Exit code 0 after 0.3 s.\n22"
    assert report(RAN | {"output": ""}) == "Exit code 0 after 0.3 s.\n(no output)"
    assert report(RAN | {"state": "failed", "exitCode": 7}).startswith("Exit code 7 after")
    assert report(RAN | {"state": "timed_out", "exitCode": 1, "durationMs": 30012}).startswith(
        "Stopped after 30.0 s: the command did not finish in time.")
    assert report(RAN | {"state": "cancelled", "exitCode": 1}).startswith("Stopped after 0.3 s: the desktop changed hands.")
    assert report(RAN | {"state": "failed", "exitCode": None, "error": "no such program"}).startswith(
        "The command could not be started: no such program")
    long = report(RAN | {"output": "x" * (MAX_OUTPUT_CHARACTERS + 5) + "end"})
    assert "Only the end of its output is shown." in long and long.endswith("end")
    assert len(long.split("\n", 1)[1]) == MAX_OUTPUT_CHARACTERS


def test_a_command_can_be_held_for_approval_like_other_input(executor, control):
    [tool] = command_tools(commands(Host(), control, executor)[0])
    schema = tool.tool_call_schema.model_json_schema()
    assert tool.name == "run_command" and "needs_confirmation" in schema["required"] and "consequence" in schema["properties"]
    assert schema["properties"]["timeout"]["maximum"] == 600 and schema["properties"]["command"]["maxLength"] == 32000


async def test_a_task_has_commands_unless_the_user_turned_them_off(settings, computer, control, monkeypatch):
    host = Host()
    windows = Lease(host, control)

    async def offered(**choices) -> set[str]:
        model, _ = use_script(monkeypatch, [AIMessage(content="Done.")])
        await run_turn(settings, "tidy the folder", max_steps=5, computer=computer, windows=windows, **choices)
        return {tool.name for tool in model.bindings[0]["tools"]}

    assert "run_command" in await offered()
    assert host.sent() == ["describe", "control.resume", "control.takeover"]
    host.calls.clear()
    assert "run_command" not in await offered(choices=RunChoices(commands=False))
    assert not host.calls
