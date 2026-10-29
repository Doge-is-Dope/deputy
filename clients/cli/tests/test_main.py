import pytest

from computer_use_cli import main as cli
from computer_use_cli.client import ApiError
from conftest import Interrupted, sse

START = {"type": "start", "run": "r1", "thread": "r1", "goal": "open start"}
NOTE = {"type": "note", "text": "Goal: open start\nRun: r1", "code": "goal"}
ACTION = {"type": "action", "n": 1, "tool": "key", "args": {"text": "win", "needs_confirmation": False},
          "status": "success", "result": "Pressed win."}


def end(computer: str | None, stop_reason: str = "replied") -> dict:
    return {"type": "end", "stop_reason": stop_reason, "computer": computer, "summary": "Start is open."}


@pytest.mark.parametrize("computer, code", [("replied", 0), ("step_limit", 2), ("stuck", 2), (None, 2)])
def test_a_run_goes_to_the_desktop_shows_its_steps_and_says_how_its_task_ended(api, client, capsys, computer, code):
    api.on("POST", "/api/runs", 201, {"id": "r1", "thread": "r1"})
    api.on("GET", "/api/runs/r1/events", raw=sse(
        (0, START), (1, NOTE), (2, ACTION), ("delta", {"text": "Start"}), (3, end(computer)), ("done", {})
    ))

    assert cli.main(["run", "open start", "--project", "eval", "--max-steps", "9", "--computer", "openai:gpt-6-luna",
                     "high"], client) == code

    (sent,) = api.sent("POST", "/api/runs")
    assert sent["body"] == {"goal": "open start", "computer": True, "project_name": "eval", "max_steps": 9,
                            "agents": {"computer": {"model": "openai:gpt-6-luna", "effort": "high"}}}
    out = capsys.readouterr().out
    assert '[  1] key {"text": "win"}' in out and "Agent: Start is open." in out
    assert f"Desktop: {computer or 'not used'}" in out and out.rstrip().endswith("Run: r1")


def test_ctrl_c_stops_the_run_and_shows_how_it_ended(api, client, capsys):
    api.on("POST", "/api/runs", 201, {"id": "r1", "thread": "r1"})
    first = sse((0, START), (1, NOTE))
    api.on("GET", "/api/runs/r1/events", stream=lambda: Interrupted(first, 5))  # cut after the start
    api.on("GET", "/api/runs/r1/events", raw=sse((1, NOTE), (2, end(None, "cancelled")), ("done", {})))
    api.on("POST", "/api/runs/r1/stop", 200, {"stopped": True})

    assert cli.main(["run", "open start"], client) == 130

    assert len(api.sent("POST", "/api/runs/r1/stop")) == 1
    again = api.sent("GET", "/api/runs/r1/events")[-1]
    assert again["headers"]["Last-Event-ID"] == "0"
    assert "Stopped." in capsys.readouterr().err


@pytest.mark.parametrize("answer, said", [
    ({"error": "another run is using the desktop", "reason": "desktop", "run": "r9"},
     "another run has the desktop: r9"),
    ({"error": "this conversation has a run in progress", "reason": "conversation", "run": "r8"},
     "this conversation has a run in progress: r8"),
])
def test_a_message_turned_away_says_why_and_starts_nothing(api, client, capsys, answer, said):
    api.on("POST", "/api/runs", 409, answer)
    assert cli.main(["run", "open start"], client) == 2
    assert said in capsys.readouterr().err and not api.sent("GET", "/api/runs/r9/events")


def test_a_conversation_that_cannot_be_continued_says_so(api, client, capsys):
    api.on("POST", "/api/runs", 404, {"error": "this conversation cannot be continued: no supported record"})
    assert cli.main(["run", "and notepad", "--thread", "old"], client) == 2
    assert "Conversation old cannot be continued" in capsys.readouterr().err


def test_resume_sends_the_latest_runs_message_again_in_its_conversation(api, client, capsys):
    api.on("GET", "/api/runs", json_body=[{"id": "r1"}, {"id": "r3"}, {"id": "r2"}])
    api.on("GET", "/api/runs/r3/events", raw=sse((0, START | {"run": "r3", "goal": "and notepad"}), ("done", {})))
    api.on("POST", "/api/runs", 201, {"id": "r4", "thread": "r1"})
    api.on("GET", "/api/runs/r4/events", raw=sse((0, START), (1, end("replied")), ("done", {})))

    assert cli.main(["resume"], client) == 0

    assert api.sent("POST", "/api/runs")[0]["body"] | {} == {"goal": "and notepad", "thread": "r1", "computer": True,
                                                            "max_steps": 60}
    assert "Continuing r3 in its conversation r1." in capsys.readouterr().out


def test_resume_without_runs_or_with_an_unknown_one_says_so(api, client, capsys):
    api.on("GET", "/api/runs", json_body=[])
    assert cli.main(["resume"], client) == 2
    api.on("GET", "/api/runs/gone/events", 404, {"error": "no such run"})
    assert cli.main(["resume", "gone"], client) == 2
    err = capsys.readouterr().err
    assert "No runs" in err and "gone cannot be continued" in err


def test_approve_and_reject_answer_the_waiting_step_from_the_command_line(api, client, capsys):
    waiting = {"approval": {"id": "c1", "consequence": "送出表單"}}
    api.on("GET", "/api/status", json_body=waiting)
    api.on("POST", "/api/approval", json_body={"id": "c1", "decision": "reject"})

    assert cli.main(["reject", "--message", "  not yet "], client) == 0

    assert api.sent("POST", "/api/approval")[0]["body"] == {
        "id": "c1", "decision": "reject", "message": "not yet", "by": "cli"
    }
    assert "Declined: 送出表單" in capsys.readouterr().out


def test_approving_when_nothing_waits_says_so(api, client, capsys):
    api.on("GET", "/api/status", json_body={"approval": None})
    assert cli.main(["approve"], client) == 2
    assert "No step is waiting" in capsys.readouterr().err


def test_observe_saves_the_screen_where_asked(api, client, capsys, tmp_path):
    png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (1280).to_bytes(4, "big") + (800).to_bytes(4, "big") + b"rest"
    api.on("GET", "/api/screen", raw=png)
    api.on("GET", "/api/status", json_body={"computer": {"connected": True, "detail": "RDP session: connected"}})

    assert cli.main(["observe", "--out", str(tmp_path / "shot.png")], client) == 0

    assert (tmp_path / "shot.png").read_bytes() == png
    assert "Screen 1280x800. RDP session: connected." in capsys.readouterr().out


def test_takeover_and_return_hand_the_desktop_over(api, client):
    api.on("POST", "/api/control", json_body={"owner": "user"})
    assert cli.main(["takeover"], client) == 0 and cli.main(["return"], client) == 0
    assert [request["body"]["owner"] for request in api.sent("POST", "/api/control")] == ["user", "agent"]


def test_a_runtime_that_cannot_be_reached_is_said(capsys):
    class Unreachable:
        def __call__(self, *args):
            raise ApiError(0, None, "cannot reach the runtime at http://127.0.0.1:8000: refused")

    from computer_use_cli.client import Client

    assert cli.main(["status"], Client("http://127.0.0.1:8000", send=Unreachable())) == 2
    assert "cannot reach the runtime" in capsys.readouterr().err


def test_a_run_whose_stream_drops_carries_on_from_its_last_step(api, client, capsys):
    from conftest import Dropped

    api.on("POST", "/api/runs", 201, {"id": "r1", "thread": "r1"})
    api.on("GET", "/api/runs/r1/events", stream=lambda: Dropped(sse((0, START), (1, NOTE)), 5))
    api.on("GET", "/api/runs/r1/events", raw=sse((1, NOTE), (2, end("replied")), ("done", {})))

    assert cli.main(["run", "open start"], client) == 0
    assert api.sent("GET", "/api/runs/r1/events")[-1]["headers"]["Last-Event-ID"] == "0"
    assert capsys.readouterr().out.count("Goal: open start") == 1
