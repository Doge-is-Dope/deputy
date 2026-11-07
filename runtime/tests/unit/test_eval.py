"""Eval metadata and all-trial statistics, with fake API/export data and no desktop, subprocesses or model calls."""

import copy
import importlib.util
import json
import re
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image


MODEL = "openai:offline-model"


def usage(input=100, cached=20, write=10, output=8, reasoning=3):
    return {"input": input, "cached": cached, "cache_write": write, "output": output, "reasoning": reasoning}


def events(cost=None):
    tokens = usage()
    return [
        {"type": "start", "time": 0, "goal": "Draw a box"},
        {"type": "model", "time": 1, "model": MODEL, "text": "Draw.", "tool_calls": [{"name": "left_click"}],
         "usage": tokens},
        {"type": "end", "time": 10, "stop_reason": "replied", "computer": "replied", "summary": "Done.",
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
    return {"commit": commit, "source": source, "dirty": False, "subject": "Offline fixture", "date": "2026-10-27",
            "changes": [], "note": ""}


def trial(evaluator, attempt=1, effort="medium", **changes):
    agents = {"main": {"model": MODEL, "effort": "medium"}, "computer": {"model": MODEL, "effort": effort}}
    return {
        "no": 3, "task": "paint-canvas", "attempt": attempt, "started": f"2026-10-27T12:{attempt:02d}:00",
        "lang": "zh", "goal": "Draw a box", "expect": "A box", "source": "offline fixture", "start": "Empty canvas",
        "max_steps": 60, "feasible": True, "model": evaluator.model_names(agents), "setup": "ok",
        "version": version(), "approve": True, "run": f"run-{attempt}", "stop_reason": "replied", "computer": "replied",
        "calls": 2, "main_calls": 1, "seconds": 10, "agent_cost": .01, "title_cost": .003, "unknown_calls": 0,
        "usage": usage(), "agents": [{"agent": "computer", "model": MODEL, "usage": usage()}],
        "settings": {"requested_agents": {}, "agents": agents, "screenshots": {"keep": 3, "every": 5}},
        **changes,
    }


def save_version(evaluator, record=None):
    record = record or version()
    folder = evaluator.RESULTS / evaluator.version_key(record)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "version.json").write_text(json.dumps(record))
    return folder


def save_trial(folder, row, log=None):
    where = folder / "03-paint-canvas" / str(row["attempt"])
    where.mkdir(parents=True)
    (where / "result.json").write_text(json.dumps(row))
    if row.get("run"):
        run = where / "run"
        run.mkdir()
        (run / "steps.jsonl").write_text("".join(json.dumps(event) + "\n" for event in (log or events())))
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


def test_pruning_metadata_comes_from_the_snapshot_without_executing_it(evaluator, tmp_path):
    source = tmp_path / "src"
    file = source / "computer_use/agent/middleware.py"
    file.parent.mkdir(parents=True)
    file.write_text("raise RuntimeError('must never execute')\nKEEP_SCREENSHOTS = 7\nPRUNE_EVERY = 25\n")
    assert evaluator.screenshot_settings(source) == {"keep": 7, "every": 25}
    for text in ("KEEP_SCREENSHOTS = 7\n", "KEEP_SCREENSHOTS = 3\nPRUNE_EVERY = get_setting()\n",
                 "KEEP_SCREENSHOTS = True\nPRUNE_EVERY = 5\n", "not valid python!"):
        file.write_text(text)
        assert evaluator.screenshot_settings(source) is None
    assert evaluator.screenshot_settings(tmp_path / "absent") is None


def test_run_records_requested_and_resolved_settings_and_exported_usage(evaluator, monkeypatch, tmp_path):
    folder = save_version(evaluator)
    source = tmp_path / "src"
    file = source / "computer_use/agent/middleware.py"
    file.parent.mkdir(parents=True)
    file.write_text("KEEP_SCREENSHOTS = 3\nPRUNE_EVERY = 5\n")
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
        into.mkdir()
        (into / "steps.jsonl").write_text("".join(json.dumps(event) + "\n" for event in events({"input": .01})))

    monkeypatch.setattr(evaluator.api, "export_session", exported)
    evaluator.run_tasks(SimpleNamespace(trials=1, ask=True, lang="zh"), ["paint-canvas"], version(), source, requested)
    row = json.loads((folder / "03-paint-canvas/1/result.json").read_text())
    assert sent[0][-1] == requested and sent[0][-2] is False
    assert row["settings"]["requested_agents"] == requested
    assert row["settings"]["agents"]["computer"] == {"model": MODEL, "effort": "low"}
    assert row["settings"]["screenshots"] == {"keep": 3, "every": 5}
    assert row["usage"] == usage() and row["agent_cost"] == .01 and row["title_cost"] == .003
    assert row["version"]["source"] == "snapshot1234"


def test_summarize_keeps_authoritative_totals_title_and_unknown_calls_separate(evaluator):
    log = events({"input": .01, "output": .02})
    # A duplicated model usage must not be added again to the end event's authoritative total.
    log.insert(2, copy.deepcopy(log[1]))
    result = evaluator.summarize(log)
    assert result["usage"] == usage() and result["agents"][0]["usage"] == usage()
    assert result["agent_cost"] == pytest.approx(.03)
    assert result["title_cost"] == pytest.approx(.003) and result["cost"] == pytest.approx(.033)
    log[1]["usage"] = None
    log[-2]["cost"] = None
    result = evaluator.summarize(log)
    assert result["unknown_calls"] == 1 and result["agent_cost"] is None and result["cost"] is None
    assert evaluator.summarize([])["usage"] is None


def test_grouping_uses_effective_settings_not_the_requested_spelling(evaluator):
    a = trial(evaluator)
    b = copy.deepcopy(a)
    b["settings"]["requested_agents"] = {"main": {"model": "follow"}, "computer": {"effort": "medium"}}
    b["settings"]["agents"] = dict(reversed(list(b["settings"]["agents"].items())))
    assert evaluator.experiment(a) == evaluator.experiment(b)
    for field, value in (("lang", "en"), ("max_steps", 20), ("approve", False)):
        assert evaluator.experiment(a) != evaluator.experiment(a | {field: value})
    for change in (trial(evaluator, effort="low"), a | {"version": version(source="other-source")},
                   a | {"settings": a["settings"] | {"screenshots": {"keep": 3, "every": 25}}}):
        assert evaluator.experiment(a) != evaluator.experiment(change)
    legacy = a.copy()
    legacy.pop("settings")
    assert evaluator.experiment(a) != evaluator.experiment(legacy)


def test_summary_includes_all_trials_and_unknown_cost_without_reading_logs(evaluator, monkeypatch):
    folder = save_version(evaluator)
    a = trial(evaluator, seconds=10, agent_cost=.01)
    b = trial(evaluator, attempt=2, seconds=1, agent_cost=None, stop_reason="cancelled", computer="step_limit",
              unknown_calls=1)
    rows = [a, b, trial(evaluator, attempt=3),
            trial(evaluator, attempt=4, run=None, stop_reason="setup_failed"), trial(evaluator, attempt=5, effort="low")]
    monkeypatch.setattr(evaluator, "read_events", lambda *args: pytest.fail("summary must not read transcripts"))
    text = evaluator.summary(folder, rows, {"run-1": "pass", "run-2": "fail", "run-5": "pass"})
    medium, low = text.split(f"   main {MODEL} medium, computer {MODEL} low")
    assert "trials=4, started=3, ungraded=1" in medium
    assert "'setup_failed': 1" in medium and "'step_limit': 1" in medium
    assert "1/2" in medium and "0.02000+?1" in medium
    task = next(line for line in medium.splitlines() if line.strip().startswith("03-paint-canvas"))
    assert task.split()[4:6] == ["10.0", "10.0"]  # a quick failure must not improve successful-run latency
    assert "trials=1, started=1" in low and "1/1" in low
    # A token-weighted ratio, not the average of 20% and 90% (55%).
    rows[1]["agents"] = [{"agent": "computer", "model": MODEL, "usage": usage(input=900, cached=810)}]
    text = evaluator.summary(folder, rows[:2], {"run-1": "pass", "run-2": "fail"})
    assert "cached=830 (83.0%)" in text and "write=20" in text
    assert evaluator.percentile([10, 30], .5) == "20.0"
    assert evaluator.percentile([10, 30], .95) == "29.0"
    assert evaluator.known_total([None, None], 5) == "?"


def test_legacy_missing_data_and_infeasible_results_are_explicit(evaluator):
    folder = save_version(evaluator)
    row = trial(evaluator, feasible=False)
    for key in ("settings", "agent_cost", "agents", "title_cost", "unknown_calls"):
        row.pop(key)
    text = evaluator.summary(folder, [row], {row["run"]: "pass"})
    assert "screenshots=unknown; settings=legacy" in text
    assert "[infeasible]" in text and "usage unavailable in 1 trial(s)" in text
    assert "0.00000" not in text


@pytest.mark.parametrize("legacy", [False, True])
def test_report_loads_each_result_and_trajectory_once_and_preserves_grades(evaluator, monkeypatch, capsys, legacy):
    folder = save_version(evaluator)
    originals = {}
    grades = {}
    for n in range(1, 31):
        row = trial(evaluator, attempt=n, effort="low" if n % 2 else "medium")
        # Legacy records get usage from their export once, without modifying result.json.
        if legacy:
            row.pop("agent_cost")
            row.pop("agents")
        path = save_trial(folder, row, events({"input": .01}))
        originals[path / "result.json"] = (path / "result.json").read_text()
        grades[row["run"]] = "pass retained reason" if n % 2 else "fail retained reason"
    (folder / "grade.md").write_text("# Grades\n\n" + "\n\n".join(
        f"## trial · `{run}`\n\nGrade: {grade}" for run, grade in grades.items()))
    reads = Counter()
    read_text = Path.read_text
    calculated = []
    summarize = evaluator.summarize

    def metrics(log):
        calculated.append(True)
        return summarize(log)

    def counted(path, *args, **kwargs):
        if path.name in ("result.json", "steps.jsonl"):
            reads[path] += 1
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counted)
    monkeypatch.setattr(evaluator, "summarize", metrics)
    evaluator.cmd_report(SimpleNamespace(versions=[]))
    assert len(reads) == 60 and set(reads.values()) == {1}
    assert evaluator.read_grades(folder) == grades
    output = capsys.readouterr().out
    assert "trials=15" in output and "0/15" in output and "15/15" in output
    assert (evaluator.RESULTS / "report.html").is_file()
    assert all(read_text(path) == text for path, text in originals.items())
    sheet = folder / "grade.md"
    sheet.write_text(read_text(sheet).replace("Grade: pass retained reason", "Grade: fail revised", 1))
    evaluator.cmd_report(SimpleNamespace(versions=[]))
    assert set(reads.values()) == {2}  # cache lifetime is one report, so a regrade is visible on the next call
    assert len(calculated) == (60 if legacy else 0)  # new records reuse their saved metrics
    assert evaluator.read_grades(folder)["run-1"] == "fail revised"


def test_build_sheet_merges_new_grades_without_losing_existing_ones(evaluator):
    folder = save_version(evaluator)
    save_trial(folder, trial(evaluator))
    save_trial(folder, trial(evaluator, attempt=2))
    (folder / "grade.md").write_text("# Grades\n\n## one · `run-1`\n\nGrade: pass original reason\n")
    evaluator.build_sheet(folder, {"run-2": "fail another reason"})
    assert evaluator.read_grades(folder) == {"run-1": "pass original reason", "run-2": "fail another reason"}


def save_session(where, logs):
    """A run as `computer-use export` writes it: {log: {name: colour}}, each log in its folder, or in `where` for ""."""
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
    ({"": {"000-observe.png": "red", "001-key.png": "blue", "main-001-task-ended.png": "red"}}, "001-key.png"),  # one log
], ids=["a log per folder", "one log"])
def test_a_rebuilt_sheet_and_the_report_show_the_runs_end_screen_and_keep_its_grade(evaluator, logs, end):
    folder = save_version(evaluator)
    row = trial(evaluator, start_screen="start.png")
    where = save_trial(folder, row)
    (where / "run" / "steps.jsonl").unlink()
    Image.new("RGB", (8, 8), "white").save(where / "start.png")
    save_session(where / "run", logs)
    row |= evaluator.summarize(evaluator.read_events(where / "run"))
    (where / "result.json").write_text(json.dumps(row))
    (folder / "grade.md").write_text("# Grades\n\n## one · `run-1`\n\nGrade: pass kept reason\n")

    evaluator.cmd_report(SimpleNamespace(versions=[]))

    sheet = (folder / "grade.md").read_text()
    links = re.findall(r'src="([^"]+)"', sheet)
    assert links == ["03-paint-canvas/1/start.png", f"03-paint-canvas/1/run/{end}"]
    assert all((folder / link).is_file() for link in links)
    assert evaluator.read_grades(folder) == {"run-1": "pass kept reason"}
    assert f"{folder.name}/03-paint-canvas/1/run/{end}" in (evaluator.RESULTS / "report.html").read_text()


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
    assert result["agent_cost"] == pytest.approx(.06) and result["seconds"] == 6
