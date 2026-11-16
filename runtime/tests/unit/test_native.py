"""Commands on Windows through the Windows Tools host: the transport, the lease and what the model is told."""

import pytest
from langchain_core.messages import AIMessage

from computer_use.config import RunChoices
from computer_use.native import HostError
from computer_use.native.execution import MAX_OUTPUT_CHARACTERS, Commands, report
from computer_use.native import launcher
from computer_use.native.launcher import FINGERPRINT_PREFIX, TOKEN_PREFIX, RdpLauncher
from computer_use.native.lease import Lease, WindowsTools
from computer_use.native.mcp import CredentialFile, Credentials, McpChannel, check_certificate
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


def test_a_host_started_by_hand_has_its_first_certificate_remembered_and_another_refused(tmp_path):
    store = CredentialFile(tmp_path / "data" / "windows-tools.json", token="set by hand")
    assert store.read() == Credentials("set by hand")
    check_certificate(store, store.read(), b"first certificate")
    known = store.read()
    assert known.token == "set by hand" and known.fingerprint is not None
    check_certificate(store, known, b"first certificate")
    with pytest.raises(HostError) as refused:
        check_certificate(store, known, b"another certificate")
    assert not refused.value.sent and str(store.path) in str(refused.value)
    # Another token set by hand is another host: nothing known of its certificate.
    assert CredentialFile(store.path, token="a new one").read() == Credentials("a new one")


def test_a_host_the_runtime_starts_is_reached_with_what_was_kept_for_its_desktop(tmp_path):
    store = CredentialFile(tmp_path / "windows-tools.json")
    assert store.read() is None  # not started yet
    store.write(Credentials("made for this run", "ab" * 32))
    assert CredentialFile(store.path).read() == Credentials("made for this run", "ab" * 32)  # another server's view
    assert store.path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(HostError):
        check_certificate(store, store.read(), b"not the certificate it announced")


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


def commands(host, control, executor) -> tuple[Commands, Lease]:
    lease = Lease(host, control)
    return Commands(WindowsTools(host, lease, CredentialFile(executor.control.path.with_name("windows-tools.json"))), executor), lease


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
    windows = WindowsTools(Host(), Lease(Host(), control), CredentialFile(settings.data_dir / "windows-tools.json"))

    async def offered(**choices) -> set[str]:
        model, _ = use_script(monkeypatch, [AIMessage(content="Done.")])
        await run_turn(settings, "tidy the folder", max_steps=5, computer=computer, windows=windows, **choices)
        return {tool.name for tool in model.bindings[0]["tools"]}

    assert "run_command" in await offered()
    assert "run_command" not in await offered(choices=RunChoices(commands=False))


class FakeClipboard:
    """A clipboard a host answers on: once it holds a token, the next look finds the fingerprint."""

    def __init__(self, answers: bool = True):
        self.text, self.answers, self.puts = "", answers, []

    async def put(self, text: str) -> None:
        self.puts.append(text)
        self.text = text

    async def get(self) -> str:
        if self.answers and self.text.startswith(TOKEN_PREFIX):
            self.text = FINGERPRINT_PREFIX + "cd" * 32
        return self.text


PATH = r"C:\tools\windows-tools-host.exe"


async def test_the_host_is_started_from_the_run_dialog_and_the_token_goes_by_the_clipboard(computer, monkeypatch):
    monkeypatch.setattr(launcher, "RUN_OPENS_SECONDS", 0)
    clipboard = FakeClipboard()
    fingerprint = await RdpLauncher(computer, clipboard, PATH, "127.0.0.1", 8767).start("secret token")
    assert fingerprint == "cd" * 32
    command = f'conhost.exe --headless "{PATH}" --attach 127.0.0.1 8767'
    assert computer.calls == [("press", [["win", "r"]]), ("type_text", command), ("press", [["enter"]])]
    assert "secret token" not in command
    assert clipboard.puts == [TOKEN_PREFIX + "secret token", ""]  # nothing of the exchange stays there


async def test_a_host_that_does_not_answer_is_not_started(computer, monkeypatch):
    for name in ("RUN_OPENS_SECONDS", "ANSWER_POLL_SECONDS"):
        monkeypatch.setattr(launcher, name, 0)
    monkeypatch.setattr(launcher, "ANSWER_SECONDS", 0.05)
    clipboard = FakeClipboard(answers=False)
    with pytest.raises(HostError) as failed:
        await RdpLauncher(computer, clipboard, PATH, "127.0.0.1", 8767).start("secret token")
    assert not failed.value.sent and clipboard.text == ""


def test_a_launcher_needs_the_hosts_own_address_and_a_path_the_run_dialog_takes(computer):
    for path, address in ((PATH, "windows.example"), ('C:\\a"b.exe', "127.0.0.1"), ("C:\\" + "x" * 260, "127.0.0.1")):
        with pytest.raises(ValueError):
            RdpLauncher(computer, FakeClipboard(), path, address, 8767)


class Starts:
    """A launcher that starts the fake host, or fails."""

    def __init__(self, host: Host, fails: bool = False):
        self.host, self.fails, self.tokens = host, fails, []

    async def start(self, token: str) -> str:
        self.tokens.append(token)
        if self.fails:
            raise HostError("not_started", "The host did not answer after it was started.", sent=False)
        self.host.fail = None
        return "ef" * 32


def started_by_runtime(control, tmp_path, fails=False) -> tuple[WindowsTools, Host, Starts]:
    host = Host()
    host.fail = HostError("unreachable", "The host did not answer.", sent=False)  # nothing runs there yet
    starts = Starts(host, fails)
    return WindowsTools(host, Lease(host, control), CredentialFile(tmp_path / "windows-tools.json"), starts), host, starts


async def test_a_task_starts_the_host_when_it_does_not_answer_and_keeps_what_reaches_it(control, tmp_path):
    windows, host, starts = started_by_runtime(control, tmp_path)
    control.write("agent", "returned")
    await windows.ensure()
    [token] = starts.tokens
    assert len(token) == 64 and windows.store.read() == Credentials(token, "ef" * 32)
    assert windows.lease.target == TARGET and windows.lease.problem == ""
    await windows.ensure()  # it answers now: not started again
    assert len(starts.tokens) == 1


async def test_the_host_is_not_started_while_the_user_has_the_desktop_or_when_started_by_hand(control, tmp_path):
    windows, host, starts = started_by_runtime(control, tmp_path)
    control.write("user", "took over")
    await windows.ensure()
    by_hand = WindowsTools(host, Lease(host, control), CredentialFile(tmp_path / "by-hand.json", "set by hand"))
    control.write("agent", "returned")
    await by_hand.ensure()
    assert starts.tokens == [] and host.calls == []


async def test_a_host_that_cannot_be_started_leaves_the_task_without_commands_and_says_why(control, tmp_path):
    windows, _, _ = started_by_runtime(control, tmp_path, fails=True)
    control.write("agent", "returned")
    await windows.ensure()
    assert windows.lease.target is None and "did not answer after it was started" in windows.lease.problem
    assert windows.store.read() is None
