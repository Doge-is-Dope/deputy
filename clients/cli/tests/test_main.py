import pytest

from computer_use_cli import main as cli
from computer_use_cli.client import ApiError
from conftest import Interrupted, sse

START = {"type": "start", "run": "r1", "thread": "r1", "goal": "open start"}
NOTE = {"type": "note", "text": "Goal: open start\nRun: r1", "code": "goal"}
ACTION = {"type": "action", "n": 1, "tool": "key", "args": {"text": "win", "needs_confirmation": False},
          "status": "success", "result": "Pressed win."}


def quiet(api, run: str = "r1", thread: str = "r1", logs: list[dict] | None = None):
    """The session `run` began has ended: the runtime lists no session in progress, and its conversation's logs."""
    api.on("GET", "/api/status", json_body={"running": []})
    api.on("GET", f"/api/conversations/{thread}/runs", json_body=logs or [{"id": run, "session": run}])


def end(stop_reason: str = "replied") -> dict:
    return {"type": "end", "stop_reason": stop_reason, "summary": "Start is open."}


# A task the user stopped wakes no turn, so its turn ended before it did: how it ended is in its own log.
@pytest.mark.parametrize("computer, code", [("replied", 0), ("step_limit", 2), ("stopped", 2), (None, 2)])
def test_a_run_goes_to_the_desktop_shows_its_steps_and_says_how_its_task_ended(api, client, capsys, computer, code):
    api.on("POST", "/api/runs", 201, {"id": "r1", "thread": "r1"})
    api.on("GET", "/api/runs/r1/events", raw=sse(
        (0, START), (1, NOTE), ("delta", {"text": "Start"}), (2, end()), ("done", {})
    ))
    api.on("GET", "/api/runs/r2/events", raw=sse(
        (0, {"type": "start", "kind": "task", "thread": "r1", "agent": "computer", "goal": "Open Start."}), (1, ACTION),
        (2, {"type": "end", **({"stop_reason": "stopped"} if computer == "stopped" else
                                {"stop_reason": "ended", "computer": computer})}), ("done", {}),
    ))
    quiet(api, logs=[{"id": "r1", "session": "r1"}, *([{"id": "r2", "session": "r1"}] if computer else [])])

    assert cli.main(["run", "open start", "--project", "eval", "--max-steps", "9", "--computer", "openai:gpt-6-luna",
                     "high"], client) == code

    (sent,) = api.sent("POST", "/api/runs")
    assert sent["body"] == {"goal": "open start", "computer": True, "project_name": "eval", "max_steps": 9,
                            "agents": {"computer": {"model": "openai:gpt-6-luna", "effort": "high"}}}
    out = capsys.readouterr().out
    assert ('[  1] key {"text": "win"}' in out) == (computer is not None) and "Agent: Start is open." in out
    assert f"Desktop: {computer or 'not used'}" in out and out.rstrip().endswith("Run: r1")


def test_ctrl_c_stops_the_run_and_shows_how_it_ended(api, client, capsys):
    api.on("POST", "/api/runs", 201, {"id": "r1", "thread": "r1"})
    first = sse((0, START), (1, NOTE))
    api.on("GET", "/api/runs/r1/events", stream=lambda: Interrupted(first, 5))  # cut after the start
    api.on("GET", "/api/runs/r1/events", raw=sse((1, NOTE), (2, end("cancelled")), ("done", {})))
    api.on("POST", "/api/conversations/r1/stop", 200, {"stopped": True})
    quiet(api)

    assert cli.main(["run", "open start"], client) == 130

    assert len(api.sent("POST", "/api/conversations/r1/stop")) == 1
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
    api.on("GET", "/api/conversations?limit=1", json_body={"items": [{"id": "r1", "latest": {"id": "r3"}}], "next": None})
    api.on("GET", "/api/runs/r3/events", raw=sse((0, START | {"run": "r3", "goal": "and notepad"}), ("done", {})))
    api.on("POST", "/api/runs", 201, {"id": "r4", "thread": "r1"})
    api.on("GET", "/api/runs/r4/events", raw=sse((0, START), (1, end()), ("done", {})))
    quiet(api, "r4")

    assert cli.main(["resume"], client) == 2  # the desktop was not used

    assert api.sent("POST", "/api/runs")[0]["body"] | {} == {"goal": "and notepad", "thread": "r1", "computer": True,
                                                            "max_steps": 60}
    assert "Continuing r3 in its conversation r1." in capsys.readouterr().out


def test_resume_without_runs_or_with_an_unknown_one_says_so(api, client, capsys):
    api.on("GET", "/api/conversations?limit=1", json_body={"items": [], "next": None})
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


def test_status_idle_fails_while_a_run_is_going_or_the_user_has_control(api, client, capsys):
    def status(active=None, running=(), owner="agent", ready=True):
        return {"computer": {"detail": "RDP session: connected"}, "control": {"owner": owner, "ready": ready}, "active": active,
                "running": [{"run": run, "thread": run} for run in running], "approval": None}

    for answer in (status(), status(running=["r1"]), status(active="r2", running=["r2"]), status(owner="user"), status(ready=False)):
        api.on("GET", "/api/status", json_body=answer)

    assert [cli.main(["status", "--idle"], client) for _ in range(5)] == [0, 1, 1, 1, 1]
    assert "Running: r1 in conversation r1." in capsys.readouterr().out


def test_status_without_idle_only_reports(api, client):
    api.on("GET", "/api/status", json_body={"computer": {"detail": "x"}, "control": {"owner": "user"},
                                             "active": "r1", "running": [], "approval": None})
    assert cli.main(["status"], client) == 0


def test_takeover_and_return_hand_the_desktop_over(api, client):
    api.on("POST", "/api/control", json_body={"owner": "user"})
    assert cli.main(["takeover"], client) == 0 and cli.main(["return"], client) == 0
    assert [request["body"] for request in api.sent("POST", "/api/control")] == [
        {"owner": "user", "by": "cli"}, {"owner": "agent", "by": "cli"},
    ]


def test_a_runtime_that_cannot_be_reached_is_said(capsys):
    class Unreachable:
        def __call__(self, *args):
            raise ApiError(0, None, "cannot reach the runtime at http://127.0.0.1:8000: refused")

    from computer_use_cli.client import Client

    assert cli.main(["status"], Client("http://127.0.0.1:8000", send=Unreachable())) == 2
    assert "cannot reach the runtime" in capsys.readouterr().err


def test_a_run_shows_its_tasks_and_later_turns_and_ends_with_the_last_turns_reply(api, client, capsys):
    task = {"type": "task", "state": "started", "id": "t1", "agent": "computer", "brief": "Open Start.", "title": "Start",
            "record": "r2"}
    api.on("POST", "/api/runs", 201, {"id": "r1", "thread": "r1"})
    api.on("GET", "/api/runs/r1/events", raw=sse((0, START | {"kind": "turn"}), (1, task), (2, end() | {"summary": ""}),
                                                ("done", {})))
    api.on("GET", "/api/runs/r2/events", raw=sse(
        (0, {"type": "start", "kind": "task", "thread": "r1", "agent": "computer", "goal": "Open Start."}), (1, ACTION),
        (2, {"type": "end", "stop_reason": "ended", "computer": "replied"}), ("done", {}),
    ))
    api.on("GET", "/api/runs/r3/events", raw=sse((0, {"type": "start", "kind": "turn", "thread": "r1", "goal": ""}),
                                                (1, end()), ("done", {})))
    # In progress while its task works; quiet once its last turn has replied.
    api.on("GET", "/api/status", json_body={"running": [{"run": "r1"}]})
    api.on("GET", "/api/status", json_body={"running": []})
    logs = [{"id": "r1", "session": "r1"}, {"id": "r2", "session": "r1"}]
    api.on("GET", "/api/conversations/r1/runs", json_body=logs)
    api.on("GET", "/api/conversations/r1/runs", json_body=[*logs, {"id": "r3", "session": "r1"}])

    assert cli.main(["run", "open start"], client) == 0

    out = capsys.readouterr().out
    lines = [line.strip() for line in out.splitlines() if line.strip()]
    assert lines[:3] == ["computer started: Open Start.", '[  1] key {"text": "win"}', "computer ended: Open Start."]
    assert "Agent: Start is open." in out and "Desktop: replied" in out and out.rstrip().endswith("Run: r1")


def test_a_run_whose_stream_drops_carries_on_from_its_last_step(api, client, capsys):
    from conftest import Dropped

    api.on("POST", "/api/runs", 201, {"id": "r1", "thread": "r1"})
    api.on("GET", "/api/runs/r1/events", stream=lambda: Dropped(sse((0, START), (1, NOTE)), 5))
    api.on("GET", "/api/runs/r1/events", raw=sse((1, NOTE), (2, end()), ("done", {})))
    quiet(api)

    assert cli.main(["run", "open start"], client) == 2  # the desktop was not used
    assert api.sent("GET", "/api/runs/r1/events")[-1]["headers"]["Last-Event-ID"] == "0"
    assert capsys.readouterr().out.count("Goal: open start") == 1


def test_agents_lists_every_agent_at_work_by_the_id_stop_takes(api, client, capsys, monkeypatch):
    monkeypatch.setattr(cli.time, "time", lambda: 1000.0)
    api.on("GET", "/api/status", json_body={"running": [
        {"run": "s1", "thread": "s1", "turn": None, "tasks": ["k1", "k2"]},
        {"run": "s2", "thread": "s2", "turn": "s2", "tasks": []},
    ]})
    api.on("GET", "/api/runs/k1/events", raw=sse(
        (0, {"type": "start", "time": 935.0, "kind": "task", "agent": "coding", "title": "Count the files"})))
    api.on("GET", "/api/runs/k2/events", raw=sse(
        (0, {"type": "start", "time": 990.0, "kind": "task", "agent": "computer", "goal": "Open Notepad."})))

    assert cli.main(["agents"], client) == 0

    assert capsys.readouterr().out.splitlines() == [
        "k1  coding    1:05  Count the files",
        "k2  computer  0:10  Open Notepad.",
    ]


def test_agents_says_when_none_is_at_work(api, client, capsys):
    api.on("GET", "/api/status", json_body={"running": [{"run": "s1", "thread": "s1", "turn": "s1", "tasks": []}]})
    assert cli.main(["agents"], client) == 0 and capsys.readouterr().out == "No agent at work.\n"


def test_stop_stops_one_agent_and_says_when_it_is_not_at_work(api, client, capsys):
    api.on("POST", "/api/runs/k1/stop", json_body={"stopped": True})
    api.on("POST", "/api/runs/k2/stop", status=409, json_body={"error": "this run is not in progress"})

    assert cli.main(["stop", "k1"], client) == 0 and cli.main(["stop", "k2"], client) == 2

    out = capsys.readouterr()
    assert "Stopped k1." in out.out and "Not in progress: k2" in out.err


def test_the_main_agents_question_is_shown_with_its_recommendation():
    from computer_use_cli.render import line

    args = {"question": "Which one?", "options": [{"label": "A", "reason": "Newer."}, {"label": "B", "reason": "Older."}]}
    shown = line({"type": "action", "agent": "main", "n": 1, "tool": "ask_user", "args": args, "status": "success", "result": ""})

    assert shown == "The agent asks: Which one?\n  1. A (recommended): Newer.\n  2. B: Older."


def test_a_question_with_several_answers_marks_no_recommendation():
    from computer_use_cli.render import line

    args = {"question": "Which?", "multiple": True, "options": [{"label": "A", "reason": "One."}]}
    shown = line({"type": "action", "agent": "main", "n": 1, "tool": "ask_user", "args": args, "status": "success", "result": ""})

    assert shown == "The agent asks (choose any): Which?\n  1. A: One."
