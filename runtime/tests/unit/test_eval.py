"""Eval metadata and all-trial statistics, with fake API/export data and no desktop, subprocesses or model calls."""

import copy
import importlib.util
import json
import re
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from computer_use.desktop.control import RunLock


MODEL = "openai:offline-model"


def events(cost=None):
    tokens = {"input": 100, "cached": 20, "cache_write": 10, "output": 8, "reasoning": 3}
    return [
        {"type": "start", "kind": "turn", "time": 0, "goal": "Draw a box"},
        {"type": "model", "time": 1, "model": MODEL, "text": "Draw.", "tool_calls": [{"name": "left_click"}],
         "usage": tokens},
        {"type": "end", "time": 10, "stop_reason": "replied", "summary": "Done.",
         "usage": tokens, "cost": cost,
         "agents": [{"agent": "computer", "model": MODEL, "usage": tokens, "cost": cost}]},
        {"type": "title", "time": 11, "model": MODEL, "cost": {"input": .001, "output": .002}},
    ]


@pytest.fixture
def evaluator(monkeypatch, tmp_path):
    root = Path(__file__).resolve().parents[3]
    monkeypatch.syspath_prepend(str(root / "eval"))
    spec = importlib.util.spec_from_file_location("desktop_eval", root / "eval/eval.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)

    def forbidden(*args, **kwargs):
        raise AssertionError("offline eval tests must not start a server, subprocess or network request")

    monkeypatch.setattr(module, "compose", forbidden)
    monkeypatch.setattr(module.subprocess, "run", forbidden)
    monkeypatch.setattr(module.api, "_send", forbidden)
    monkeypatch.setattr(module, "RESULTS", tmp_path / "results")
    return module


def status():
    return {
        "defaults": {"main": {"model": MODEL, "effort": "medium"},
                     "computer": {"model": "follow", "effort": "follow"}},
        "models": [{"id": MODEL, "efforts": ["low", "medium"]}],
    }


def version(commit="abcdef123456", source="snapshot1234"):
    return {"commit": commit, "source": source, "prompts": "prompts1234", "code": "code12345678", "dirty": False,
            "subject": "Offline fixture", "date": "2026-10-27", "changes": [], "note": ""}


def trial(evaluator, attempt=1, effort="medium", **changes):
    """A run's result.json; with `verdict`, as `load_rows` reads it back."""
    agents = {"main": {"model": MODEL, "effort": "medium"}, "computer": {"model": MODEL, "effort": effort}}
    return {
        "task": "paint-canvas", "attempt": attempt, "started": f"2026-10-27T12:{attempt:02d}:00",
        "goal": "Draw a box", "expect": "A box", "source": "offline fixture", "start": "Empty canvas",
        "max_steps": 60, "feasible": True, "model": evaluator.model_names(agents), "setup": "ok",
        "version": version(), "run": f"run-{attempt}", "stop_reason": "replied", "computer": "replied",
        "calls": 2, "main_calls": 1, "seconds": 10, "cost": .013, **changes,
    }


def save_version(evaluator, record=None):
    record = record or version()
    folder = evaluator.RESULTS / evaluator.version_key(record)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "version.json").write_text(json.dumps(record))
    return folder


def save_trial(folder, row, log=None):
    where = folder / "paint-canvas" / str(row["attempt"])
    where.mkdir(parents=True)
    (where / "result.json").write_text(json.dumps(row))
    if row.get("run"):
        turn = where / "run" / "turn-1"
        turn.mkdir(parents=True)
        (turn / "steps.jsonl").write_text("".join(json.dumps(event) + "\n" for event in (log or events())))
    return where


def test_models_record_effective_choices_without_reimplementing_the_runtime(evaluator, monkeypatch):
    replies = []
    monkeypatch.setattr(evaluator.api, "status", lambda: replies.append(True) or status())
    requested = {"computer": {"effort": "low"}}
    original = copy.deepcopy(requested)
    resolved = evaluator.models(requested)
    assert resolved == {"main": {"model": MODEL, "effort": "medium"},
                        "computer": {"model": MODEL, "effort": "low"}}
    assert evaluator.model_names(resolved) == f"main {MODEL} medium, computer {MODEL} low"
    assert requested == original and replies == [True]


@pytest.mark.parametrize("choice, message", [
    ({"model": "openai:not-offered"}, "does not offer"),
    ({"effort": "high"}, "does not take high"),
])
def test_unsupported_choices_still_stop_before_a_run(evaluator, monkeypatch, choice, message):
    monkeypatch.setattr(evaluator.api, "status", status)
    with pytest.raises(SystemExit, match=message):
        evaluator.models({"computer": choice})


def test_a_version_server_never_replaces_one_with_a_run_going(evaluator, monkeypatch):
    busy = {"active": None, "running": [{"run": "r1", "thread": "r1"}]}
    monkeypatch.setattr(evaluator.Client, "status", lambda self: busy)
    with pytest.raises(SystemExit, match="has a run going"):  # before compose, which the fixture forbids
        with evaluator.version_server("/tmp/ev-x/src"):
            pass


class SetupDesktop:
    """The Windows desktop as winsetup sees it: each screen differs, and each key pressed or text typed records who
    held the run lock then."""

    def __init__(self, lock_path, fail: bool = False):
        self.lock_path, self.fail, self.shots, self.input = lock_path, fail, 0, []

    async def screenshot(self):
        self.shots += 1
        return SimpleNamespace(png=b"%d" % self.shots)

    async def press(self, combos):
        self.input.append((combos, RunLock(self.lock_path).holder()))

    async def type_text(self, text):
        if self.fail:
            raise RuntimeError("the display went away")
        self.input.append((text, RunLock(self.lock_path).holder()))


@pytest.fixture
def winsetup(evaluator, monkeypatch):
    module = sys.modules["winsetup"]  # as eval.py imported it

    async def no_wait(*args):
        pass

    monkeypatch.setattr(module.asyncio, "sleep", no_wait)
    monkeypatch.setattr(module, "settle", no_wait)
    monkeypatch.setattr(module, "set_clipboard", lambda display, text: None)
    monkeypatch.setattr(module, "clipboard", lambda display: "EVAL-SETUP-x ok")
    return module


async def test_a_setup_types_only_while_it_holds_the_run_lock(winsetup, tmp_path):
    lock = RunLock(tmp_path / "run.lock")
    desktop = SetupDesktop(lock.path)

    result = await winsetup.setup(desktop, ":0", lock, "EVAL-SETUP-x", [{"type": "close-windows"}])

    assert result == {"ok": True, "detail": "ok"}
    assert [what for what, _ in desktop.input] == [[["win", "r"]], winsetup.BOOTSTRAP, [["enter"]]]
    assert all(holder["run"] == "eval setup" for _, holder in desktop.input)
    assert not lock.held and lock.holder() is None


async def test_a_setup_lets_go_of_the_lock_when_typing_fails(winsetup, tmp_path):
    lock = RunLock(tmp_path / "run.lock")
    with pytest.raises(RuntimeError, match="display went away"):
        await winsetup.setup(SetupDesktop(lock.path, fail=True), ":0", lock, "EVAL-SETUP-x", [])
    assert not lock.held and lock.holder() is None


async def test_a_setup_presses_nothing_while_another_holder_has_the_desktop(winsetup, monkeypatch, tmp_path):
    def forbidden(*args):
        raise AssertionError("a setup that does not hold the desktop must not touch its clipboard")

    monkeypatch.setattr(winsetup, "set_clipboard", forbidden)
    desktop = SetupDesktop(tmp_path / "run.lock")
    with RunLock(tmp_path / "run.lock") as other:
        other.name("20261107-120000")
        result = await winsetup.setup(desktop, ":0", RunLock(other.path), "EVAL-SETUP-x", [])
        assert other.holder()["run"] == "20261107-120000"
    assert result == {"ok": False, "busy": True, "detail": "another run has the desktop: 20261107-120000"}
    assert desktop.input == [] and desktop.shots == 0


def test_a_busy_desktop_stops_the_eval_instead_of_failing_the_setup(evaluator, monkeypatch):
    reply = {"ok": False, "busy": True, "detail": "another run has the desktop: eval setup"}
    monkeypatch.setattr(evaluator, "compose", lambda *args, **kwargs: SimpleNamespace(stdout=json.dumps(reply), stderr=""))
    with pytest.raises(SystemExit, match=r"could not take the desktop \(another run has the desktop: eval setup\)"):
        evaluator.run_setup([{"type": "close-windows"}])


def test_run_records_the_effective_models_and_what_the_run_cost(evaluator, monkeypatch, tmp_path):
    folder = save_version(evaluator)
    source = tmp_path / "src"
    source.mkdir()
    screen = tmp_path / "start.png"
    screen.write_bytes(b"fake screen; no image processing in this test")
    requested = {"computer": {"effort": "low"}}
    sent = []
    monkeypatch.setattr(evaluator.api, "status", status)
    monkeypatch.setattr(evaluator, "desktop_busy", lambda: "")
    monkeypatch.setattr(evaluator, "prepare", lambda *args: (screen, "ok"))
    monkeypatch.setattr(evaluator, "run_agent", lambda *args: sent.append(args) or ("offline-run", "", False))
    monkeypatch.setattr(evaluator, "reset", lambda *args: None)
    monkeypatch.setattr(evaluator, "build_sheet", lambda folder: folder / "grade.md")

    def exported(run, into):
        assert run == "offline-run"
        (into / "turn-1").mkdir(parents=True)
        (into / "turn-1" / "steps.jsonl").write_text("".join(json.dumps(event) + "\n" for event in events({"input": .01})))

    monkeypatch.setattr(evaluator.api, "export_session", exported)
    evaluator.run_tasks(1, ["paint-canvas"], version(), source, requested)
    row = json.loads((folder / "paint-canvas/1/result.json").read_text())
    assert sent[0][-1] == requested
    assert row["model"] == f"main {MODEL} medium, computer {MODEL} low"
    assert row["cost"] == pytest.approx(.013) and row["version"]["source"] == "snapshot1234"
    assert evaluator.file_name("abcdef1", "paint-canvas", 1) in row["goal"]  # the attempt's own files
    assert "paint-canvas" not in evaluator.file_name("abcdef1", "paint-canvas", 1)  # the id would hint at the task


def test_summarize_counts_every_logs_cost_and_the_titles_once(evaluator):
    log = events({"input": .01, "output": .02})
    log.insert(2, copy.deepcopy(log[1]))  # a model call's usage is not a cost of its own
    assert evaluator.summarize(log)["cost"] == pytest.approx(.033)
    log[-2]["cost"] = None
    assert evaluator.summarize(log)["cost"] is None


def test_summary_includes_all_trials_by_models_and_shows_unknown_cost(evaluator, monkeypatch):
    folder = save_version(evaluator)
    rows = [trial(evaluator, verdict="pass"),
            trial(evaluator, attempt=2, seconds=1, cost=None, stop_reason="cancelled", computer="step_limit",
                  verdict="fail"),
            trial(evaluator, attempt=3, verdict=None),
            trial(evaluator, attempt=4, run=None, stop_reason="setup_failed", verdict=None),
            trial(evaluator, attempt=5, effort="low", verdict="pass", feasible=False)]
    monkeypatch.setattr(evaluator, "read_events", lambda *args: pytest.fail("summary must not read transcripts"))
    text = evaluator.summary(folder, rows)
    medium, low = text.split(f"   main {MODEL} medium, computer {MODEL} low")
    assert "trials=4, started=3, ungraded=1" in medium
    assert "'setup_failed': 1" in medium and "'step_limit': 1" in medium
    task = next(line for line in medium.splitlines() if line.strip().startswith("paint-canvas"))
    # 1/2 graded passed, 4 trials, calls of the 3 started, the passes' median time (a quick failure must not
    # improve it), and a cost one trial left unknown.
    assert task.split()[1:] == ["1/2", "4", "3/6", "10.0", "?"]
    assert "paint-canvas [infeasible]" in low and "1/1" in low and "0.013" in low


def test_the_report_keeps_the_grades_and_never_rewrites_results(evaluator, capsys):
    folder = save_version(evaluator)
    originals, grades = {}, {}
    for n in range(1, 5):
        row = trial(evaluator, attempt=n, effort="low" if n % 2 else "medium")
        path = save_trial(folder, row, events({"input": .01}))
        originals[path / "result.json"] = (path / "result.json").read_text()
        grades[row["run"]] = "pass retained reason" if n % 2 else "fail retained reason"
    (folder / "grade.md").write_text("# Grades\n\n" + "\n\n".join(
        f"## trial · `{run}`\n\nGrade: {grade}" for run, grade in grades.items()))
    evaluator.cmd_report(SimpleNamespace(versions=[]))
    assert evaluator.read_grades(folder) == grades
    output = capsys.readouterr().out
    assert "trials=2" in output and "0/2" in output and "2/2" in output
    assert (evaluator.RESULTS / "report.html").is_file()
    assert all(path.read_text() == text for path, text in originals.items())
    sheet = folder / "grade.md"
    sheet.write_text(sheet.read_text().replace("Grade: pass retained reason", "Grade: fail revised", 1))
    evaluator.cmd_report(SimpleNamespace(versions=[]))
    assert evaluator.read_grades(folder)["run-1"] == "fail revised"


def test_a_rebuilt_sheet_keeps_its_grades_and_adds_new_runs_ungraded(evaluator):
    folder = save_version(evaluator)
    save_trial(folder, trial(evaluator))
    save_trial(folder, trial(evaluator, attempt=2))
    (folder / "grade.md").write_text("# Grades\n\n## one · `run-1`\n\nGrade: pass original reason\n")
    evaluator.build_sheet(folder)
    assert evaluator.read_grades(folder) == {"run-1": "pass original reason"}
    assert "`run-2`" in (folder / "grade.md").read_text()


def save_session(where, logs):
    """A run as `computer-use export` writes it: {log: {name: colour}}, each log in its folder."""
    clock = 0
    for log, screens in logs.items():
        folder = where / log
        folder.mkdir(parents=True, exist_ok=True)
        lines = []
        for name, colour in screens.items():
            Image.new("RGB", (8, 8), colour).save(folder / name)
            clock += 1
            if not name.startswith("main-"):  # an image in a message, not a screen an action took
                lines.append({"type": "action", "tool": "key", "args": {}, "status": "success", "result": "",
                              "time": clock, "screenshot": name})
        lines.append({"type": "end", "time": clock + .5, "stop_reason": "replied", "summary": "Done."})
        (folder / "steps.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines))


@pytest.mark.parametrize("logs, end", [
    # The last task's last screen: not the same name in an earlier task, nor the earlier screens the main agent was sent.
    ({"a-turn": {}, "b-task": {"000-observe.png": "red", "001-key.png": "red"},
      "c-task": {"000-observe.png": "red", "001-key.png": "blue"},
      "d-turn": {"main-000-task-ended.png": "red", "main-000-task-ended-2.png": "red"}}, "c-task/001-key.png"),
])
def test_a_rebuilt_sheet_and_the_report_show_the_runs_end_screen_and_keep_its_grade(evaluator, logs, end):
    folder = save_version(evaluator)
    row = trial(evaluator, start_screen="start.png")
    where = save_trial(folder, row)
    (where / "run" / "turn-1" / "steps.jsonl").unlink()
    (where / "run" / "turn-1").rmdir()
    Image.new("RGB", (8, 8), "white").save(where / "start.png")
    save_session(where / "run", logs)
    row |= evaluator.summarize(evaluator.read_events(where / "run"))
    (where / "result.json").write_text(json.dumps(row))
    (folder / "grade.md").write_text("# Grades\n\n## one · `run-1`\n\nGrade: pass kept reason\n")

    evaluator.cmd_report(SimpleNamespace(versions=[]))

    sheet = (folder / "grade.md").read_text()
    links = re.findall(r'src="([^"]+)"', sheet)
    assert links == ["paint-canvas/1/start.png", f"paint-canvas/1/run/{end}"]
    assert all((folder / link).is_file() for link in links)
    assert evaluator.read_grades(folder) == {"run-1": "pass kept reason"}
    assert f"{folder.name}/paint-canvas/1/run/{end}" in (evaluator.RESULTS / "report.html").read_text()


def test_a_run_without_a_screen_on_disk_has_no_end_screen_on_its_sheet(evaluator):
    folder = save_version(evaluator)
    save_trial(folder, trial(evaluator, end_screen="001-key.png"))  # named by the log, but the export has no such file
    assert "End screen" not in evaluator.build_sheet(folder).read_text()


def test_the_end_screen_is_never_a_zoomed_in_crop(evaluator):
    log = [{"type": "action", "tool": "key", "time": 1, "screenshot": "001-key.png"},
           {"type": "action", "tool": "zoom", "time": 2, "screenshot": "002-zoom.png"}]
    assert evaluator.summarize(log)["end_screen"] == "001-key.png"


def test_empty_report_and_missing_version_fail_offline(evaluator):
    with pytest.raises(SystemExit, match="no eval runs"):
        evaluator.cmd_report(SimpleNamespace(versions=[]))
    save_version(evaluator)
    with pytest.raises(SystemExit, match="no such versions"):
        evaluator.cmd_report(SimpleNamespace(versions=["missing"]))


def test_a_sessions_logs_read_back_in_order_and_summed(evaluator, tmp_path):
    run = tmp_path / "run"
    logs = {
        "a-turn": [{"type": "start", "kind": "turn", "time": 1}, {"type": "model", "agent": "main", "text": "On it.", "time": 2},
                   {"type": "end", "stop_reason": "replied", "summary": "On it.", "cost": {"input": .01}, "time": 3}],
        "b-task": [{"type": "start", "kind": "task", "time": 2.5}, {"type": "action", "tool": "key", "time": 4},
                   {"type": "end", "stop_reason": "ended", "summary": "Opened.", "cost": {"input": .02}, "time": 5}],
        "c-turn": [{"type": "start", "kind": "turn", "time": 6},
                   {"type": "end", "stop_reason": "replied", "summary": "Start is open.", "cost": {"input": .03}, "time": 7}],
    }
    for name, events_of_log in logs.items():
        (run / name).mkdir(parents=True)
        (run / name / "steps.jsonl").write_text("".join(json.dumps(event) + "\n" for event in events_of_log))

    events = evaluator.read_events(run)
    result = evaluator.summarize(events)

    assert [event["time"] for event in events] == [1, 2, 2.5, 3, 4, 5, 6, 7]
    assert (result["stop_reason"], result["summary"], result["actions"]) == ("replied", "Start is open.", 1)
    assert result["cost"] == pytest.approx(.06) and result["seconds"] == 6


class WaitingSession:
    """A session whose task waits for an answer: after `logged`, nothing more comes until it is stopped."""

    def __init__(self, logged):
        self.logged, self.stopped, self.thread = logged, threading.Event(), "thread"

    def follow(self, api, run):
        return self

    def lines(self):
        yield from (("turn", event) for event in self.logged)
        assert self.stopped.wait(5), "the eval kept waiting on a session nobody will answer"
        yield "task", {"type": "end", "stop_reason": "cancelled", "summary": "Stopped."}


def waiting(evaluator, monkeypatch, logged):
    session = WaitingSession(logged)
    monkeypatch.setattr(evaluator, "Follow", session.follow)
    monkeypatch.setattr(evaluator, "approve_steps", lambda stop: None)
    monkeypatch.setattr(evaluator.api, "start", lambda *args, **kwargs: {"id": "run"})
    monkeypatch.setattr(evaluator.api, "stop", lambda thread: session.stopped.set())
    return session


def test_an_unattended_run_ends_the_session_when_the_agent_asks_the_user(evaluator, monkeypatch):
    question = {"type": "action", "agent": "main", "n": 1, "tool": "ask_user", "status": "success", "reason": None,
                "args": {"question": "Which account?", "options": [], "multiple": False},
                "result": "Shown to the user. Their next message answers it."}
    session = waiting(evaluator, monkeypatch, [{"type": "start", "kind": "turn"}, question])

    run, output, stopped = evaluator.run_agent("Book the receipts", 60)

    assert session.stopped.is_set() and (run, stopped) == ("run", False) and "Which account?" in output


def test_a_quiet_session_is_stopped_at_the_run_timeout(evaluator, monkeypatch):
    session = waiting(evaluator, monkeypatch, [{"type": "start", "kind": "turn"}])
    monkeypatch.setattr(evaluator, "RUN_TIMEOUT", 0.05)

    run, output, stopped = evaluator.run_agent("Book the receipts", 60)

    assert session.stopped.is_set() and stopped and "Stopped after 0.05 s." in output
