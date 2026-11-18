"""Run Windows desktop tasks, grade them by hand, and compare code versions and models.

The harness copies runtime/src at a version into the container, serves it there on EVAL_PORT beside the web page's
server, and drives it through the CLI's API client; winsetup.py builds each task's starting state. Results live in
eval/results/<version>/<task>/<attempt>; grade.md holds the grades. See eval/README.md."""

import argparse
import contextlib
import hashlib
import io
import json
import re
import shutil
import statistics
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageChops

from computer_use.storage import MAIN
from computer_use.agent.history import action_lines, tasks

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "clients" / "cli" / "src"))  # the CLI's client: no packages needed
from computer_use_cli.client import ApiError, Client, Follow  # noqa: E402
from computer_use_cli.main import choices  # noqa: E402
from computer_use_cli.render import line as shown  # noqa: E402

from html_report import PROMPTS, end_screen, read_events, render, said, side, version_key, version_title
from winsetup import setup_script

EVAL = Path(__file__).resolve().parent
RESULTS = EVAL / "results"  # by version, task and attempt
CLEAN = EVAL / "clean-desktop.png"
WINSETUP = EVAL / "winsetup.py"  # sent to the container, which only sees runtime/data
TASKS_FILE = EVAL / "tasks.jsonl"
RUNTIME = EVAL.parent / "runtime"
# The eval's own server, running the version it tests beside the one the web page uses; compose.yaml publishes it.
EVAL_PORT = 8001
SERVER_PID = "/tmp/ev-server.pid"  # in the container
SERVER_LOG = "/tmp/ev-server.log"
SERVER_SECONDS = 60  # for it to answer once started

MAX_STEPS = 60
RUN_TIMEOUT = 1800
SETUP_TIMEOUT = 300
# How long a desktop that dropped may take to come back before the eval stops.
RECONNECT_SECONDS = 60
RESET_GOAL = (
    "Close every open window and dialog, and the Start menu. If asked whether to save, choose not to save. "
    "When you are done, only the desktop is showing."
)
RESET_STEPS = 15
CLUTTERED = "the desktop stayed cluttered"


@dataclass
class Task:
    id: str  # names its results folder
    source: str  # where the task comes from
    start: str  # the starting state, for the grader
    goal: str
    expect: str  # what the grader should find, shown on the sheet
    setup: list[dict] = field(default_factory=list)  # steps that build the starting state, see winsetup.step_script
    max_steps: int = MAX_STEPS
    feasible: bool = True  # infeasible tasks are scored apart: always giving up would win them


def load_tasks() -> dict[str, dict]:
    """The tasks by id. Every setup step and goal is checked here, so a mistake stops the eval before its first run."""
    rows = [json.loads(line) for line in TASKS_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]
    for row in rows:
        setup_script(row.get("setup", []), "check")
        if not isinstance(row["goal"], str) or not row["goal"]:
            raise SystemExit(f"{row['id']}: the goal needs to be text")
    if len({row["id"] for row in rows}) != len(rows):
        raise SystemExit("every task needs its own id")
    return {row["id"]: row for row in rows}


TASKS = load_tasks()
IDS = list(TASKS)


def task_ids(names: list[str]) -> list[str]:
    """Tasks named by id, in the order given; every task when none are named."""
    unknown = [name for name in names if name not in TASKS]
    if unknown:
        raise SystemExit(f"unknown tasks: {', '.join(unknown)} (see `eval/ev tasks`)")
    return names or IDS


def file_name(key: str, name: str, attempt: int) -> str:
    """What {name} becomes in a trial's goal and setup: its own on Windows, never an earlier run's. The task is a
    digest, not its id, which would tell the agent what the task tests (missing-file, notepad-distractor)."""
    return f"ev-{key}-{hashlib.sha256(name.encode()).hexdigest()[:4]}-{attempt}"


def task_for(name: str, file_name: str) -> Task:
    """The task with {name} replaced by the trial's own name (letters, digits and '-', so the JSON stays valid)."""
    return Task(**json.loads(json.dumps(TASKS[name], ensure_ascii=False).replace("{name}", file_name)))


# The runtime the eval drives: the web page's server, until `version_server` serves the version under test.
api = Client()


def compose(
    *args: str, timeout: float, stdin: str | None = None, env: dict[str, str] | None = None, detach: bool = False
) -> subprocess.CompletedProcess:
    """A command in the container, with `env` on top of the container's settings; `detach` leaves it running."""
    flags = [flag for key, value in (env or {}).items() for flag in ("-e", f"{key}={value}")]
    return subprocess.run(
        ["docker", "compose", "exec", "-T", *(["-d"] if detach else []), *flags, "runtime", *args],
        cwd=RUNTIME, capture_output=True, text=True, timeout=timeout, input=stdin,
    )


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=EVAL.parent, capture_output=True, text=True, check=True).stdout.strip()


def copy_source(ref: str, into: Path) -> Path:
    """runtime/src at a git ref, or as the working tree has it ("worktree"), copied to `into`/src: the one copy of what
    a version runs, which names it, goes into the container and is kept with its results."""
    source = into / "src"
    if ref == "worktree":  # the files git sees there, so no cache or .DS_Store tells two versions apart
        listed = git("ls-files", "--cached", "--others", "--exclude-standard", "--", "runtime/src").splitlines()
        for name in listed:
            if (EVAL.parent / name).is_file():  # not one deleted since the commit
                (source / name.removeprefix("runtime/src/")).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(EVAL.parent / name, source / name.removeprefix("runtime/src/"))
    else:
        archive = subprocess.run(["git", "archive", ref, "runtime/src"], cwd=EVAL.parent, capture_output=True,
                                 check=True).stdout
        tarfile.open(fileobj=io.BytesIO(archive)).extractall(into, filter="data")
        (into / "runtime" / "src").rename(source)
    return source


def tree_hash(root: Path, skip: str = "") -> str:
    """A digest of the files under `root`, but those in its folder `skip`, by their paths and contents: the same files
    always give the same one."""
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda path: path.relative_to(root).as_posix()):
        name = path.relative_to(root).as_posix()
        if path.is_file() and not (skip and name.startswith(f"{skip}/")):
            digest.update(f"{name}\0".encode() + path.read_bytes() + b"\0")
    return digest.hexdigest()[:12]


def version_of(ref: str, source: Path) -> dict:
    """The commit a git ref names, or "worktree" for the working tree as it is, whose runtime/src `copy_source` copied
    to `source`: its sha, subject and date; the files under runtime/src changed since, which only the working tree can
    have; and digests of the source, of its prompts and of the rest of its code, which tell versions apart."""
    commit = git("rev-parse", "--verify", f"{'HEAD' if ref == 'worktree' else ref}^{{commit}}")
    subject, date = git("show", "-s", "--format=%s%x00%cI", commit).split("\0")
    changed = [
        *git("diff", "--name-only", "HEAD", "--", "runtime/src").splitlines(),
        *git("ls-files", "--others", "--exclude-standard", "--", "runtime/src").splitlines(),
    ] if ref == "worktree" else []
    return {
        "commit": commit, "subject": subject, "date": date, "dirty": bool(changed),
        "changes": sorted(name.removeprefix("runtime/src/") for name in changed),
        "source": tree_hash(source), "prompts": tree_hash(source / PROMPTS), "code": tree_hash(source, PROMPTS),
    }


def install(version: dict, source: Path) -> str:
    """A version's source (`copy_source`), copied into the container for `version_server` to serve: its path there,
    /tmp/ev-<version_key>/src, replaced if an earlier eval left one."""
    target = f"/tmp/ev-{version_key(version)}"
    compose("rm", "-rf", target, timeout=60)
    compose("mkdir", "-p", target, timeout=60)
    subprocess.run(["docker", "compose", "cp", str(source), f"runtime:{target}/src"], cwd=RUNTIME, capture_output=True,
                   check=True, timeout=300)
    return f"{target}/src"


def keep(folder: Path, version: dict, source: Path) -> None:
    """A version's record in its results folder: version.json, keeping the note an earlier eval gave unless this one
    gives another, and the source it runs (src/), which the report shows the prompts' changes from and which keeps
    the wording of a prompt that did well, even one never committed."""
    saved = folder / "version.json"
    if saved.exists() and not version["note"]:
        version = version | {"note": json.loads(saved.read_text(encoding="utf-8")).get("note", "")}
    saved.write_text(json.dumps(version, ensure_ascii=False, indent=1), encoding="utf-8")
    if not (folder / "src").exists():
        shutil.copytree(source, folder / "src")


def stop_server() -> None:
    """Stop the eval's server, if one is running (this eval's, or one an earlier eval left behind), and wait until it
    has: it shuts down for a few seconds, and meanwhile it would keep the port and answer for a new one."""
    compose("sh", "-c", f"pid=$(cat {SERVER_PID} 2>/dev/null) || exit 0; kill $pid 2>/dev/null; "
            f"for i in $(seq 50); do kill -0 $pid 2>/dev/null || break; sleep 0.2; done; "
            f"kill -9 $pid 2>/dev/null; rm -f {SERVER_PID}; true", timeout=60)


@contextlib.contextmanager
def version_server(code: str):
    """The runtime at a version, served on EVAL_PORT with the copy of runtime/src `install` put at `code`: the version
    the tasks run with, apart from the server the web page uses. Both share the container's data and its desktop
    lock, so only one run uses the desktop at a time. `api` drives it until the block ends, which stops it."""
    global api
    served, before = Client(f"http://127.0.0.1:{EVAL_PORT}"), api
    with contextlib.suppress(ApiError):  # nothing answers there: nothing to stop
        if (status := served.status())["active"] or status["running"]:
            raise SystemExit(f"the server on port {EVAL_PORT} has a run going, perhaps another eval's; let it end first")
    stop_server()
    serve = f"echo $$ > {SERVER_PID}; exec python -m computer_use.serve --host 0.0.0.0 --port {EVAL_PORT} " \
            f">{SERVER_LOG} 2>&1"
    compose("sh", "-c", serve, timeout=60, env={"PYTHONPATH": code}, detach=True)
    try:  # from here on, however this ends, the server stops
        deadline = time.monotonic() + SERVER_SECONDS
        while True:
            try:
                served.status()
                break
            except ApiError as error:
                if time.monotonic() > deadline:
                    log = compose("tail", "-n", "40", SERVER_LOG, timeout=60).stdout
                    raise SystemExit(f"the eval's server did not answer on port {EVAL_PORT} ({error}); is it published "
                                     f"in runtime/compose.yaml? Its log:\n{log}")
                time.sleep(0.5)
        api = served
        yield served
    finally:
        api = before
        stop_server()


def approve_steps(stop: threading.Event) -> None:
    """Approve each step the run asks approval for, as the user would from the command line, logging it."""
    seen = set()
    while not stop.wait(1.0):
        try:
            approval = api.status().get("approval")
            if not approval or approval["id"] in seen:
                continue
            seen.add(approval["id"])
            api.answer(approval["id"], "approve")
        except ApiError:  # answered meanwhile, or the server is between runs: look again
            continue
        print(f"   approved: {approval.get('consequence')}", flush=True)


def run_agent(goal: str, max_steps: int, agents: dict | None = None) -> tuple[str | None, str, bool]:
    """Send the desktop a goal and follow its session to the end, every log of it: its first turn's id, the end of
    what it showed, as the command line shows it, and whether it was stopped. The steps it asks approval for are
    approved. `agents` chooses the agents' models (`choices`). A session past RUN_TIMEOUT is stopped, and so is one
    whose agent asks the user, since no one is here to answer."""
    stop = threading.Event()
    threading.Thread(target=approve_steps, args=(stop,), daemon=True).start()
    lines: list[str] = []
    try:
        try:
            # Under the eval project, so the web page lists these conversations apart from the user's own.
            run = api.start(goal, project="eval", max_steps=max_steps, computer=True, agents=agents)["id"]
        except ApiError as error:
            return None, f"Not started: {error}", False
        feed, reply, expired = Follow(api, run), None, threading.Event()
        threading.Thread(target=stop_at_timeout, args=(feed, run, stop, expired), daemon=True).start()
        kinds: dict[str, str] = {}
        for log, event in feed.lines():
            if event["type"] == "start":
                kinds[log] = event["kind"]
            if (text := shown(event)) is not None:
                lines.append(text)
            if event["type"] == "end" and kinds.get(log) == "turn":
                reply = event.get("summary", "")
            if event["type"] == "action" and event.get("tool") == "ask_user":
                end_session(feed, run)  # nobody is here to answer it, so the run ends on its question
        if expired.is_set():
            lines.append(f"Stopped after {RUN_TIMEOUT} s.")
        if reply is not None:
            lines.append(f"Agent: {reply}")
    finally:
        stop.set()
    return run, "\n".join(lines)[-1500:], expired.is_set()


def stop_at_timeout(feed: Follow, run: str, done: threading.Event, expired: threading.Event) -> None:
    """Stop the session once RUN_TIMEOUT has passed, unless it is `done`. On a clock: a session waiting for an answer
    logs nothing, so a check between its events would never come."""
    if not done.wait(RUN_TIMEOUT):
        expired.set()
        end_session(feed, run)


def end_session(feed: Follow, run: str) -> None:
    with contextlib.suppress(ApiError):  # it ended meanwhile
        api.stop(feed.thread or run)


def disconnected() -> str:
    """Why the desktop is not connected, once it has had RECONNECT_SECONDS to come back; empty when it is. Without it
    the runtime's screen is a blank display, which would pass for a cluttered desktop."""
    deadline = time.monotonic() + RECONNECT_SECONDS
    computer = api.status()["computer"]
    if not computer["connected"]:
        print(f"   waiting up to {RECONNECT_SECONDS}s for the desktop to reconnect ({computer['detail']})", flush=True)
    while not computer["connected"]:
        if time.monotonic() > deadline:
            return computer["detail"]
        time.sleep(10)
        computer = api.status()["computer"]
    return ""


def desktop_busy() -> str:
    """Why no eval run may start now: the desktop is not connected, the user has control, or another run holds the
    desktop; empty when it is free. Checked before each task: its setup and cleanup hold the lock while they type
    (run_setup), but do not wait for a reconnect or ask who has control."""
    try:
        if detail := disconnected():
            return f"the desktop is not connected ({detail})"
        status = api.status()
    except ApiError as error:
        raise SystemExit(f"could not read who has the desktop: {error}")
    control = status["control"]
    if control["owner"] != "agent":
        return f"the user has control of the desktop ({control.get('reason') or 'no reason given'})"
    return f"run {status['active']} has the desktop" if status["active"] else ""


def models(agents: dict | None) -> dict[str, dict[str, str]]:
    """The model and effort each agent runs with, as `run --main/--computer` choose them over the runtime's defaults;
    a model the runtime does not offer, or an effort its model does not take, stops the eval before it starts."""
    status = api.status()
    offered = {model["id"]: model["efforts"] for model in status["models"]}
    chosen: dict[str, dict[str, str]] = {}
    for agent in ("main", "computer"):
        given = (agents or {}).get(agent, {})
        model, effort = (given.get(key) or status["defaults"][agent][key] for key in ("model", "effort"))
        model, effort = (chosen["main"]["model"] if model == "follow" else model,
                         chosen["main"]["effort"] if effort == "follow" else effort)
        if model not in offered:
            raise SystemExit(f"the runtime does not offer {model} for the {agent} agent; it offers: "
                             f"{', '.join(offered)}")
        if effort not in offered[model]:
            raise SystemExit(f"{model} does not take {effort} effort, for the {agent} agent; give one of: "
                             f"{', '.join(offered[model])}")
        chosen[agent] = {"model": model, "effort": effort}
    return chosen


def model_names(agents: dict) -> str:
    return ", ".join(f"{agent} {choice['model']} {choice['effort']}" for agent, choice in agents.items())


SCREENS: list[Path] = []  # the folder this eval keeps the screens it takes in, once it takes one


def observe() -> Path:
    """The desktop's screen now, saved for this eval."""
    if not SCREENS:
        SCREENS.append(Path(tempfile.mkdtemp(prefix="cu-eval-screens-")))
    path = SCREENS[0] / f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}.png"
    path.write_bytes(api.screen())
    return path


def looks_clean(screen: Path) -> bool:
    """Whether the screen matches the clean desktop, above the taskbar (whose clock changes): in color, so a new
    wallpaper counts, and to under 1000 pixels, so one more desktop icon (~1750) counts but a cursor or a full
    recycle bin (683) does not."""
    if not CLEAN.exists():
        return False
    a, b = (Image.open(path).convert("RGB") for path in (screen, CLEAN))
    if a.size != b.size:
        return False
    box = (0, 0, a.width, a.height - 60)
    r, g, bl = ImageChops.difference(a.crop(box), b.crop(box)).point(lambda v: 255 if v > 32 else 0).split()
    return ImageChops.lighter(ImageChops.lighter(r, g), bl).histogram()[255] < 1000


def reset(after_run: bool) -> Path | None:
    """The clean desktop's screen, or None if the desktop is not clean.

    The cleanup run is told not to save, so it only runs after an eval run that started from the clean desktop
    (`after_run`): what is open then is the run's or its setup's, and the steps it asks approval for are approved. A desktop found
    cluttered before that may hold the user's unsaved work, and is left to them. Clean means like clean-desktop.png; after the wallpaper changes, a person checks the screen
    and makes it the new one with `eval.py reset --accept`."""
    screen = observe()
    if looks_clean(screen):
        return screen
    if not after_run:
        print("   reset: the desktop is not clean, and no eval run opened what is on it; close it yourself, or if only "
              "the wallpaper changed, run `eval/ev reset --accept`", flush=True)
        return None
    run_setup([{"type": "close-windows"}])  # a script first, fast and free; an agent for what it leaves
    screen = observe()
    if looks_clean(screen):
        return screen
    print("   reset: the script left the desktop cluttered; an agent run closes the rest", flush=True)
    for _ in range(3):
        run_agent(RESET_GOAL, RESET_STEPS)  # its goal already says not to save
        screen = observe()
        if looks_clean(screen):
            return screen
    return None


def run_setup(steps: list[dict]) -> dict:
    """Run the steps' script on Windows (winsetup.py), which holds the desktop's run lock while it types. Another run
    or tool holding it stops the eval, as desktop_busy does: typing now would land in what it drives."""
    marker = f"EVAL-SETUP-{uuid.uuid4().hex[:12]}"
    proc = compose("python", "-c", WINSETUP.read_text(), marker, timeout=SETUP_TIMEOUT, stdin=json.dumps(steps))
    try:
        result = json.loads(proc.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return {"ok": False, "detail": (proc.stdout + proc.stderr)[-500:]}
    if result.get("busy"):
        raise SystemExit(f"Stopped: the setup could not take the desktop ({result['detail']}).")
    return result


def prepare(task: Task, after_run: bool) -> tuple[Path | None, str]:
    """A clean desktop with the task's starting state built on it: the screen the agent starts from, or None.
    A failed setup is retried once: other Windows benchmarks lost 10-30% of tasks to setups that failed."""
    screen = reset(after_run)
    if screen is None:
        return None, CLUTTERED
    if not task.setup:
        return screen, "ok"
    result = run_setup(task.setup)
    if not result["ok"] and reset(True) is not None:  # what the setup opened on the clean desktop
        result = run_setup(task.setup)
    return (observe() if result["ok"] else None), result["detail"]


# Notes every run has: the goal it starts with.
ROUTINE_NOTES = {"goal"}


def summarize(events: list[dict]) -> dict:
    """What the run's logs say: how it ended (its last turn's end), the desktop tasks the main agent handed over, what
    else the runtime noted (notes such as gone or stuck, and why actions were held back, such as taskLimit), and what
    it cost, every log's and its title's; None when any of those is unknown."""
    kinds = {e.get("log"): e["kind"] for e in events if e["type"] == "start"}
    agents = {e.get("log"): e.get("agent") for e in events if e["type"] == "start" and e["kind"] == "task"}
    ends = [e for e in events if e["type"] == "end"]
    end = next((e for e in reversed(ends) if kinds.get(e.get("log")) == "turn"), {})
    last_desktop = next((e for e in reversed(ends) if agents.get(e.get("log")) == "computer"), None)
    desktop = [task for task in tasks(events) if task["agent"] == "computer"]
    codes = Counter(e["code"] for e in events if e["type"] == "note" and e.get("code") not in ROUTINE_NOTES | {None})
    codes.update(e["reason"] for e in events if e["type"] == "action" and e.get("reason"))
    shots = [e["screenshot"] for e in events if e.get("screenshot") and "zoom" not in e["screenshot"]]  # full screens
    costs = [*([e.get("cost") for e in ends] or [None]),
             *(e.get("cost") for e in events if e["type"] == "title" and e.get("model"))]

    def count(kind: str, main: bool) -> int:
        return sum(e["type"] == kind and (e.get("agent") == MAIN) == main for e in events)

    return {
        "stop_reason": end.get("stop_reason", "crashed"),  # the run's: replied, cancelled or error
        # How the last desktop task ended, as its agent says or else its log; None when the desktop was not used.
        "computer": last_desktop and (last_desktop.get("agent_stop_reason") or last_desktop["stop_reason"]),
        "summary": end.get("summary", ""),  # the main agent's reply
        "tasks": [{"brief": task["task"], "stop_reason": task.get("stop_reason")} for task in desktop],
        "codes": dict(codes),
        "end_screen": shots[-1] if shots else None,
        "calls": count("model", False),  # all subagents
        "main_calls": count("model", True),
        "actions": count("action", False),
        "seconds": round((end or events[-1])["time"] - events[0]["time"], 1) if events else None,
        "cost": round(sum(sum(cost.values()) for cost in costs), 5) if all(cost is not None for cost in costs) else None,
    }


def load_rows(version: Path) -> list[dict]:
    """A version's runs, in task order and by attempt, each result.json with its folder (`dir`), its grade line and
    verdict, and for a run that started, its actions (`steps`) and what its agents said (`words`)."""
    grades = read_grades(version)
    order = {name: index for index, name in enumerate(IDS)}
    rows = []
    for path in version.glob("*/*/result.json"):
        row = json.loads(path.read_text(encoding="utf-8")) | {"dir": path.parent}
        if row.get("run"):
            events = read_events(row["dir"] / "run")
            row |= {"steps": action_lines(events), "words": said(events)}
        grade = grades.get(row.get("run"), "")
        rows.append(row | {"grade": grade, "verdict": verdict(grade)})
    return sorted(rows, key=lambda row: (order.get(row["task"], len(order)), row["task"], row["attempt"]))


def cmd_run(args) -> None:
    names = task_ids(args.tasks)
    ref = args.version or "worktree"
    with tempfile.TemporaryDirectory() as tmp:
        source = copy_source(ref, Path(tmp))
        version = version_of(ref, source) | {"note": args.note or ""}
        code = install(version, source)
        agents = choices(args.main, args.computer)
        with version_server(code):
            run_tasks(args.trials, names, version, source, agents)


def cmd_serve(args) -> None:
    ref = args.version or "worktree"
    with tempfile.TemporaryDirectory() as tmp:
        source = copy_source(ref, Path(tmp))
        with version_server(install(version_of(ref, source), source)):
            print(f"Serving {ref} at http://127.0.0.1:{EVAL_PORT} until Ctrl-C. For the web page, run "
                  f"CU_API_URL=http://127.0.0.1:{EVAL_PORT} bun run dev in clients/web.", flush=True)
            with contextlib.suppress(KeyboardInterrupt):
                threading.Event().wait()


def run_tasks(trials: int, names: list[str], version: dict, source: Path, agents: dict | None) -> None:
    """Run the tasks on the version `api` serves, each from its starting state, then build the grading sheet."""
    model = model_names(models(agents))
    print(f"Agents: {model}", flush=True)
    key = version_key(version)
    folder = RESULTS / key
    changes = f"; changed since the commit: {', '.join(version['changes'])}" if version["changes"] else ""
    print(f"Version {key}: {version_title(version)}{changes}", flush=True)
    print(f"Results go to {folder}", flush=True)
    # The files a task makes on Windows are named after the version, task and attempt, so they never meet an earlier
    # run's. The values in the goals stay the same, and apps remember the last ones (Notepad's Replace panel kept a
    # previous run's words): the setup resets what it can, and the grader checks the start screen for the rest.
    plan = [name for _ in range(trials) for name in names]
    after_run = False  # no eval run has opened anything yet: a cluttered desktop is the user's to clear
    for index, name in enumerate(plan, 1):
        if reason := desktop_busy():
            raise SystemExit(f"Stopped before run {index} of {len(plan)}: {reason}.")
        task_dir = folder / name
        attempt = 1 + max((int(path.name) for path in task_dir.glob("[0-9]*") if path.name.isdigit()), default=0)
        task = task_for(name, file_name(key, name, attempt))
        start_screen, setup = prepare(task, after_run)
        if start_screen is None and not after_run and setup == CLUTTERED:
            raise SystemExit("The desktop is not clean before the first run; nothing was run.")
        out = task_dir / str(attempt)
        out.mkdir(parents=True)  # the version's folder with it, so an eval stopped before any task leaves none
        keep(folder, version, source)
        row = {
            "task": name, "attempt": attempt, "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "goal": task.goal, "expect": task.expect, "source": task.source, "start": task.start,
            "max_steps": task.max_steps, "feasible": task.feasible, "model": model, "setup": setup, "version": version,
            "run": None,
        }
        if start_screen is None:
            row["stop_reason"] = "setup_failed"
        else:
            run_id, output, timed_out = run_agent(task.goal, task.max_steps, agents)
            after_run = True
            shutil.copyfile(start_screen, out / "start.png")
            row |= {"run": run_id, "start_screen": "start.png"}
            if run_id:
                api.export_session(run_id, out / "run")  # every log of its session and their screenshots
                row |= summarize(read_events(out / "run"))
                if timed_out:  # the session the eval stopped, which may have ended no turn of its own
                    row["stop_reason"] = "cancelled"
            if not run_id or row["stop_reason"] != "replied":
                row["output"] = output
        (out / "result.json").write_text(json.dumps(row, ensure_ascii=False, indent=1), encoding="utf-8")
        desktop = " -> ".join(task["stop_reason"] or "?" for task in row.get("tasks", [])) or "not used"
        print(f"[{index}/{len(plan)}] {name} #{attempt}: {row.get('stop_reason')} ({setup}), desktop "
              f"{desktop}, {row.get('calls')} calls, {row.get('seconds')}s, ${row.get('cost')}", flush=True)
    reset(after_run)
    print(f"Grade the runs in {build_sheet(folder)}")


# The grading sheet: one section per run. The grader fills in the line that starts with GRADE; rebuilding keeps it.
GRADE = "Grade:"
SHEET_HEADER = """\
# Eval of {name}: {title}

For each run, look at the start and end screens, the actions and the agent's reply, then write `pass` or `fail` after
"Grade:", optionally followed by a reason. When done, run `eval/ev report {name}`.
"""


def read_grades(folder: Path) -> dict[str, str]:
    """The grader's line per run: {"run id": "pass ..."}."""
    path = folder / "grade.md"
    if not path.exists():
        return {}
    grades = {}
    for section in path.read_text(encoding="utf-8").split("\n## ")[1:]:
        match = re.search(r"`([^`]+)`", section.split("\n", 1)[0])
        line = re.search(rf"^{re.escape(GRADE)}(.*)$", section, re.M)
        if match and line and line.group(1).strip():
            grades[match.group(1)] = line.group(1).strip()
    return grades


def verdict(line: str | None) -> str | None:
    """pass or fail, from the first word of a grader's line; None when it is neither."""
    word = (line or "").split(" ", 1)[0].lower()
    return word if word in ("pass", "fail") else None


def image(path: str | None, caption: str) -> str:
    """A screen from the eval run's folder, where the sheet is too."""
    return f'<figure><img src="{path}" width="560"><figcaption>{caption}</figcaption></figure>' if path else ""


def section(folder: Path, row: dict) -> str:
    run = row.get("run") or "no-run"
    where = row["dir"].relative_to(folder).as_posix()  # task/attempt, where the sheet's screens are
    lines = [
        f"## {where} · `{run}`", "",
        f"- Source: {row['source']}", f"- Start: {row['start']}", f"- Goal: {row['goal']}", f"- Expect: {row['expect']}",
    ]
    if row.get("stop_reason") == "setup_failed":
        return "\n".join([*lines, f"- The setup did not finish ({row['setup']}), so the task was not run: nothing to grade"])
    lines.append(f"- Ended: {row.get('stop_reason')}")
    for number, task in enumerate(row.get("tasks", []), 1):
        lines.append(f"- Desktop task {number}: {task['stop_reason']}; brief: {' '.join(task['brief'].split())}")
    if not row.get("tasks"):
        lines.append("- Desktop tasks: none handed over")
    if row.get("codes"):
        lines.append("- Notes: " + ", ".join(f"{code} {count}" for code, count in row["codes"].items()))
    lines.append(f"- {row.get('calls')} desktop model calls ({row.get('main_calls')} more by the main agent), "
                 f"{row.get('actions')} actions, {row.get('seconds')} s, ${row.get('cost')}")
    # Quoted, so a heading in the reply cannot start a section of the sheet.
    reply = (row.get("summary") or "(none)").splitlines()
    lines += ["", "Agent reply:", "", *(f"> {line}".rstrip() for line in reply)]
    if row.get("output"):
        lines += ["", "```text", row["output"].strip()[-1200:], "```"]
    lines += ["", image(f"{where}/{row['start_screen']}" if row.get("start_screen") else None, "Start screen")]
    end = end_screen(row["dir"] / "run", row.get("end_screen"))
    if end:
        lines.append(image(end.relative_to(folder).as_posix(), "End screen"))
    if row.get("run"):
        listed = "\n".join(f"{i}. {line}" for i, line in enumerate(row["steps"], 1))
        lines += ["", f"<details><summary>Actions ({len(row['steps'])})</summary>", "", listed, "", "</details>"]
    lines += ["", f"{GRADE} {row['grade']}".rstrip()]
    return "\n".join(lines)


def build_sheet(folder: Path, rows: list[dict] | None = None) -> Path:
    """A version's grading sheet from its runs (`load_rows`), keeping the grades it has."""
    version = json.loads((folder / "version.json").read_text(encoding="utf-8"))
    header = SHEET_HEADER.format(name=folder.name, title=version_title(version))
    if version.get("changes"):
        header += f"\nChanged since {version['commit'][:7]}: {', '.join(f'`{name}`' for name in version['changes'])}\n"
    sections = [section(folder, row) for row in (load_rows(folder) if rows is None else rows)]
    path = folder / "grade.md"
    path.write_text("\n\n".join([header, *sections]) + "\n", encoding="utf-8")
    return path


def total(values, digits: int = 0) -> str:
    """A sum of recorded values; ? when any is unknown."""
    values = list(values)
    return "?" if any(value is None for value in values) else f"{sum(values):.{digits}f}"


def summary(folder: Path, rows: list[dict]) -> str:
    """All trials of a version (`load_rows`), by the agents' models: each task's passes of its graded runs, model
    calls, the median time of its passes and its cost. No transcripts are read here."""
    version = json.loads((folder / "version.json").read_text(encoding="utf-8"))
    lines = [f"== {folder.name}: {version_title(version)}", "   All trials; pass/graded; ? = unknown."]
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(side(row), []).append(row)
    for trials in groups.values():
        started = [row for row in trials if row.get("run")]
        ungraded = sum(row["verdict"] is None for row in started)
        not_run = Counter(row.get("stop_reason", "not_started") for row in trials if not row.get("run"))
        endings = Counter(row.get("computer") or row.get("stop_reason", "unknown") for row in started)
        lines += ["", f"   {trials[0]['model']}",
                  (f"   trials={len(trials)}, started={len(started)}, ungraded={ungraded}; "
                   f"not-run={dict(not_run)}; endings={dict(endings)}"),
                  f"   {'task':<26}{'pass':>7}{'n':>5}{'calls M/S':>14}{'pass p50':>9}{'USD':>10}"]
        by_task: dict[str, list[dict]] = {}
        for row in trials:
            by_task.setdefault(row["task"], []).append(row)
        for name, attempts in by_task.items():
            ran = [row for row in attempts if row.get("run")]
            judged = [row["verdict"] for row in ran if row["verdict"]]
            times = [row["seconds"] for row in ran if row["verdict"] == "pass" and row.get("seconds") is not None]
            calls = "/".join(total(row.get(key) for row in ran) for key in ("main_calls", "calls"))
            label = name + (" [infeasible]" if attempts[0].get("feasible") is False else "")
            passes = f"{judged.count('pass')}/{len(judged)}"
            p50 = f"{statistics.median(times):.1f}" if times else "?"
            lines.append(f"   {label:<26}{passes:>7}{len(attempts):>5}"
                         f"{calls:>14}{p50:>9}{total((row.get('cost') for row in ran), 3):>10}")
    return "\n".join(lines)


def cmd_report(args) -> None:
    """Rebuild the grading sheet of the versions named (or the one run last), keeping its grades, and print their
    numbers; then write every version's runs as one HTML page, where the reader picks two to compare."""
    datasets = {path.parent: load_rows(path.parent) for path in RESULTS.glob("*/version.json")}
    folders = sorted(datasets, key=lambda folder: max((row["started"] for row in datasets[folder]), default=""), reverse=True)
    selected = [RESULTS / name for name in args.versions] if args.versions else folders[:1]
    if not selected:
        raise SystemExit(f"no eval runs in {RESULTS}")
    missing = [folder.name for folder in selected if folder not in datasets]
    if missing:
        raise SystemExit(f"no such versions in {RESULTS}: {', '.join(missing)}")
    rows = []
    for folder in folders:
        if folder in selected:
            print(f"{summary(folder, datasets[folder])}\n   sheet: {build_sheet(folder, datasets[folder])}\n")
        rows += datasets[folder]
    print(f"HTML report: {render(rows, (RESULTS / 'report.html').resolve(), IDS)}")


def cmd_tasks(args) -> None:
    """Every task in brief; with one named, all of it, with the PowerShell that sets it up."""
    for name in task_ids([args.task]) if args.task else IDS:
        task = task_for(name, file_name("sample", name, 1))
        if not args.task:
            print(f"{name:<23}{task.source}")
            continue
        print(f"{name} ({task.source}), at most {task.max_steps} model calls"
              + ("" if task.feasible else ", infeasible")
              + f"\n  start: {task.start}\n  goal: {task.goal}\n  expect: {task.expect}\n\n"
              + (f"Setup:\n{setup_script(task.setup, 'EVAL-SETUP-sample')}" if task.setup else "No setup."))


def cmd_reset(args) -> None:
    if detail := disconnected():
        raise SystemExit(f"The desktop is not connected ({detail}), so there is no screen to check.")
    if args.accept:  # a person looked at the screen: only the wallpaper changed
        shutil.copyfile(observe(), CLEAN)
        print(f"{CLEAN} is the clean desktop now")
        return
    print("clean" if reset(after_run=args.close) else "NOT clean")


def main() -> None:
    parser = argparse.ArgumentParser(description="Windows desktop eval; see eval/README.md")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run tasks from their starting states, then build the grading sheet")
    run.add_argument("tasks", nargs="*", help="task ids (default: all)")
    run.add_argument("--trials", type=int, default=1, help="runs of each task")
    run.add_argument("--version", help='a git ref whose runtime/src the tasks run with (default: "worktree", the '
                     "working tree as it is)")
    for agent, example in (("main", "openai:gpt-6.1-sol low"), ("computer", "openai:gpt-6-luna high")):
        run.add_argument(f"--{agent}", nargs="+", metavar=("MODEL", "EFFORT"),
                         help=f'the {agent} agent\'s model and optionally effort, as "{example}" (default: the '
                         "container's settings)")
    run.add_argument("--note", help="what this version changes, as the report names it (kept until another is given)")
    serve = sub.add_parser("serve", help="serve a version on the eval's port until Ctrl-C, to try it by hand")
    serve.add_argument("--version", help='a git ref (default: "worktree", the working tree as it is)')
    report = sub.add_parser("report", help="rebuild grading sheets, print pass rates and write the HTML report")
    report.add_argument("versions", nargs="*", help="versions under eval/results (default: the one run last)")
    tasks_ = sub.add_parser("tasks", help="list the tasks; with one named, show it and its setup PowerShell")
    tasks_.add_argument("task", nargs="?", help="a task id")
    reset_ = sub.add_parser("reset", help="say whether the desktop is clean")
    what = reset_.add_mutually_exclusive_group()
    what.add_argument("--close", action="store_true", help="close what is open WITHOUT SAVING, by an agent run")
    what.add_argument("--accept", action="store_true", help="make the current screen the clean desktop")
    args = parser.parse_args()
    {"run": cmd_run, "serve": cmd_serve, "report": cmd_report, "tasks": cmd_tasks, "reset": cmd_reset}[args.command](args)


if __name__ == "__main__":
    main()
