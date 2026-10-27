"""Run Windows desktop tasks, grade them by hand, and compare code versions and models.

The harness copies runtime/src at a version into the container, serves it there on EVAL_PORT beside the web page's
server, and drives it through the CLI's API client; winsetup.py builds each task's starting state. Results live in
eval/results/<version>/<task>/<attempt>; grade.md holds the grades. See eval/README.md."""

import argparse
import ast
import contextlib
import hashlib
import io
import json
import os
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
from computer_use_cli.client import ApiError, Client  # noqa: E402
from computer_use_cli.main import choices  # noqa: E402
from computer_use_cli.render import line as shown  # noqa: E402

from html_report import PROMPTS, read_events, render, said, version_key, version_title
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
LANGS = ("zh", "en")  # each task's goal is asked in either
ENV = {**os.environ, "DOCKER_CONTEXT": "colima"}

MAX_STEPS = 60
RUN_TIMEOUT = 1800
SETUP_TIMEOUT = 300
# How long a desktop that dropped may take to come back before the eval stops, as long as a run waits for one.
RECONNECT_SECONDS = 60
RESET_GOAL = (
    "Close every open window and dialog, and the Start menu. If asked whether to save, choose not to save. "
    "When you are done, only the desktop is showing."
)
RESET_STEPS = 15
CLUTTERED = "the desktop stayed cluttered"


@dataclass
class Task:
    no: int  # the task's number, which names its results folder
    id: str
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
        if set(row["goal"]) != set(LANGS):
            raise SystemExit(f"{row['id']}: the goal needs each of {', '.join(LANGS)}")
    if len({row["no"] for row in rows}) != len(rows):
        raise SystemExit("every task needs its own number (no)")
    return {row["id"]: row for row in rows}


TASKS = load_tasks()
IDS = list(TASKS)
NUMBERS = {name: row["no"] for name, row in TASKS.items()}


def task_folder(name: str) -> str:
    """A task's results folder in a version's: its number and id, such as 03-paint-canvas; a task dropped since has
    no number, and keeps its id alone."""
    return f"{NUMBERS[name]:02d}-{name}" if name in NUMBERS else name


def task_ids(names: list[str]) -> list[str]:
    """Tasks named by id or number (11, or 011), in the order given; every task when none are named."""
    by_number = {str(no): name for name, no in NUMBERS.items()}
    found = [name if name in TASKS else by_number.get(name.lstrip("0")) for name in names]
    unknown = [name for name, task in zip(names, found) if task is None]
    if unknown:
        raise SystemExit(f"unknown tasks: {', '.join(unknown)} (see `eval/ev tasks`)")
    return found or IDS


def task_for(name: str, lang: str, file_name: str) -> Task:
    """The task asked in `lang`, with {name} replaced by the trial's own name (letters, digits and '-', so the JSON
    stays valid)."""
    row = json.loads(json.dumps(TASKS[name], ensure_ascii=False).replace("{name}", file_name))
    return Task(**row | {"goal": row["goal"][lang]})


# The runtime the eval drives: the web page's server, until `version_server` serves the version under test.
api = Client()


def compose(
    *args: str, timeout: float, stdin: str | None = None, env: dict[str, str] | None = None, detach: bool = False
) -> subprocess.CompletedProcess:
    """A command in the container, with `env` on top of the container's settings; `detach` leaves it running."""
    flags = [flag for key, value in (env or {}).items() for flag in ("-e", f"{key}={value}")]
    return subprocess.run(
        ["docker", "compose", "exec", "-T", *(["-d"] if detach else []), *flags, "runtime", *args],
        cwd=RUNTIME, env=ENV, capture_output=True, text=True, timeout=timeout, input=stdin,
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
    prompts = source / PROMPTS
    return {
        "commit": commit, "subject": subject, "date": date, "dirty": bool(changed),
        "changes": sorted(name.removeprefix("runtime/src/") for name in changed),
        "source": tree_hash(source), "prompts": tree_hash(prompts) if prompts.is_dir() else None,
        "code": tree_hash(source, PROMPTS),
    }


def install(version: dict, source: Path) -> str:
    """A version's source (`copy_source`), copied into the container for `version_server` to serve: its path there,
    /tmp/ev-<version_key>/src, replaced if an earlier eval left one."""
    target = f"/tmp/ev-{version_key(version)}"
    compose("rm", "-rf", target, timeout=60)
    compose("mkdir", "-p", target, timeout=60)
    subprocess.run(["docker", "compose", "cp", str(source), f"runtime:{target}/src"], cwd=RUNTIME, env=ENV,
                   capture_output=True, check=True, timeout=300)
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
    stop_server()
    serve = f"echo $$ > {SERVER_PID}; exec python -m computer_use.serve --host 0.0.0.0 --port {EVAL_PORT} " \
            f">{SERVER_LOG} 2>&1"
    compose("sh", "-c", serve, timeout=60, env={"PYTHONPATH": code}, detach=True)
    served, before = Client(f"http://127.0.0.1:{EVAL_PORT}"), api
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


def run_agent(goal: str, max_steps: int, approve: bool = True, agents: dict | None = None) -> tuple[str | None, str]:
    """Send the desktop a goal and follow its run to the end: its id, and the end of what it showed, as the command
    line shows it. With `approve`, the steps it asks approval for are approved; without, they wait for a person, as
    in any run. `agents` chooses the agents' models (`choices`). A run past RUN_TIMEOUT is stopped."""
    stop = threading.Event()
    if approve:
        threading.Thread(target=approve_steps, args=(stop,), daemon=True).start()
    lines: list[str] = []
    try:
        try:
            # Under the eval project, so the web page lists these conversations apart from the user's own.
            run = api.start(goal, project="eval", max_steps=max_steps, computer=True, agents=agents)["id"]
        except ApiError as error:
            return None, f"Not started: {error}"
        deadline, last, done = time.monotonic() + RUN_TIMEOUT, -1, False
        while not done:  # a stream cut off goes on from the last line it had
            for event in api.events(run, last):
                if event.kind == "line":
                    last = event.index
                    if (text := shown(event.data)) is not None:
                        lines.append(text)
                    if event.data["type"] == "end":
                        lines.append(f"Agent: {event.data.get('summary', '')}")
                done = done or event.kind == "done"
                if not done and time.monotonic() > deadline:
                    lines.append(f"Stopped after {RUN_TIMEOUT} s.")
                    with contextlib.suppress(ApiError):  # it ended meanwhile
                        api.stop(run)
                    deadline = float("inf")  # and wait for it to end
    finally:
        stop.set()
    return run, "\n".join(lines)[-1500:]


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
    desktop; empty when it is free. Checked before each task, since its setup and cleanup type on the desktop before
    the run takes the lock."""
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


def screenshot_settings(source: Path) -> dict | None:
    """Read literal pruning constants from the tested snapshot, never import or execute that version's code.
    An older/different implementation is unknown, rather than silently assigned the evaluator's defaults."""
    path = source / "computer_use/agent/middleware.py"
    if not path.is_file():
        return None
    found = {}
    names = {"KEEP_SCREENSHOTS": "keep", "PRUNE_EVERY": "every"}
    try:
        nodes = ast.parse(path.read_text(encoding="utf-8")).body
    except SyntaxError:
        return None
    for node in nodes:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in names:
                    try:
                        value = ast.literal_eval(node.value)
                    except (ValueError, TypeError):
                        return None
                    if type(value) is not int or value <= 0:
                        return None
                    found[names[target.id]] = value
    return found if len(found) == len(names) else None


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
    marker = f"EVAL-SETUP-{uuid.uuid4().hex[:12]}"
    proc = compose("python", "-c", WINSETUP.read_text(), marker, timeout=SETUP_TIMEOUT, stdin=json.dumps(steps))
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return {"ok": False, "detail": (proc.stdout + proc.stderr)[-500:]}


def prepare(task: Task, after_run: bool) -> tuple[Path | None, str]:
    """A clean desktop with the task's starting state built on it: the screen the agent starts from, or None.
    A failed setup is retried once: WAA lost 10-30% of tasks to setups that failed, WAA-V2 retries them."""
    screen = reset(after_run)
    if screen is None:
        return None, CLUTTERED
    if not task.setup:
        return screen, "ok"
    result = run_setup(task.setup)
    if not result["ok"] and reset(True) is not None:  # what the setup opened on the clean desktop
        result = run_setup(task.setup)
    return (observe() if result["ok"] else None), result["detail"]


# Notes every run has: the goal it starts with, and how it finished.
ROUTINE_NOTES = {"goal", "runFinished"}


def summarize(events: list[dict]) -> dict:
    """What the run's log says: how it ended, the desktop tasks the main agent handed over, what else the runtime
    noted (notes such as gone or stuck, and why actions were held back, such as taskLimit), and what it cost."""
    end = next((e for e in reversed(events) if e["type"] == "end"), {})
    desktop = [task for task in tasks(events) if task["tool"] == "computer_use"]
    codes = Counter(e["code"] for e in events if e["type"] == "note" and e.get("code") not in ROUTINE_NOTES | {None})
    codes.update(e["reason"] for e in events if e["type"] == "action" and e.get("reason"))
    shots = [e["screenshot"] for e in events if e.get("screenshot")]
    titles = [e.get("cost") for e in events if e["type"] == "title" and e.get("model")]
    costs = [end.get("cost"), *titles]

    def count(kind: str, main: bool) -> int:
        return sum(e["type"] == kind and (e.get("agent") == MAIN) == main for e in events)

    return {
        "stop_reason": end.get("stop_reason", "crashed"),  # the run's: replied, cancelled or error
        "computer": end.get("computer"),  # how the last desktop task ended; None when the desktop was not used
        "summary": end.get("summary", ""),  # the main agent's reply
        "tasks": [{"brief": task["task"], "stop_reason": task.get("stop_reason")} for task in desktop],
        "codes": dict(codes),
        "end_screen": shots[-1] if shots else None,
        "calls": count("model", False),  # all subagents
        "main_calls": count("model", True),
        "actions": count("action", False),
        "seconds": round((end or events[-1])["time"] - events[0]["time"], 1) if events else None,
        "cost": round(sum(sum(cost.values()) for cost in costs), 5) if all(cost is not None for cost in costs) else None,
        "agent_cost": sum(end["cost"].values()) if end.get("cost") is not None else None,
        "title_cost": sum(sum(cost.values()) for cost in titles) if titles and all(cost is not None for cost in titles) else None,
        "usage": end.get("usage"), "agents": end.get("agents"),
        "unknown_calls": sum(e["type"] == "model" and e.get("usage") is None for e in events),
    }


def load_rows(version: Path) -> list[dict]:
    """A version's runs, by task number and attempt: each result.json with its folder (`dir`)."""
    found = [json.loads(path.read_text(encoding="utf-8")) | {"dir": path.parent} for path in version.glob("*/*/result.json")]
    return sorted(found, key=lambda row: (row.get("no") or 99, row["task"], row["attempt"]))


def cmd_run(args) -> None:
    names = task_ids(args.tasks)
    ref = args.version or "worktree"
    with tempfile.TemporaryDirectory() as tmp:
        source = copy_source(ref, Path(tmp))
        version = version_of(ref, source) | {"note": args.note or ""}
        code = install(version, source)
        agents = choices(args.main, args.computer)
        with version_server(code):
            run_tasks(args, names, version, source, agents)


def run_tasks(args, names: list[str], version: dict, source: Path, agents: dict | None) -> None:
    """Run the tasks on the version `api` serves, each from its starting state, then build the grading sheet."""
    resolved = models(agents)
    model = model_names(resolved)
    settings = {"requested_agents": agents or {}, "agents": resolved, "screenshots": screenshot_settings(source)}
    print(f"Agents: {model}", flush=True)
    key = version_key(version)
    folder = RESULTS / key
    changes = f"; changed since the commit: {', '.join(version['changes'])}" if version["changes"] else ""
    print(f"Version {key}: {version_title(version)}{changes}", flush=True)
    print(f"Results go to {folder}", flush=True)
    # The files a task makes on Windows are named after the version, task and attempt, so they never meet an earlier
    # run's. The values in the goals stay the same, and apps remember the last ones (Notepad's Replace panel kept a
    # previous run's words): the setup resets what it can, and the grader checks the start screen for the rest.
    plan = [name for _ in range(args.trials) for name in names]
    after_run = False  # no eval run has opened anything yet: a cluttered desktop is the user's to clear
    for index, name in enumerate(plan, 1):
        if reason := desktop_busy():
            raise SystemExit(f"Stopped before run {index} of {len(plan)}: {reason}.")
        task_dir = folder / task_folder(name)
        attempt = 1 + max((int(path.name) for path in task_dir.glob("[0-9]*") if path.name.isdigit()), default=0)
        task = task_for(name, args.lang, f"ev-{key}-{NUMBERS[name]:02d}-{attempt}")
        start_screen, setup = prepare(task, after_run)
        if start_screen is None and not after_run and setup == CLUTTERED:
            raise SystemExit("The desktop is not clean before the first run; nothing was run.")
        out = task_dir / str(attempt)
        out.mkdir(parents=True)  # the version's folder with it, so an eval stopped before any task leaves none
        keep(folder, version, source)
        row = {
            "no": task.no, "task": name, "attempt": attempt, "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "lang": args.lang, "goal": task.goal, "expect": task.expect, "source": task.source, "start": task.start,
            "max_steps": task.max_steps, "feasible": task.feasible, "model": model, "setup": setup, "version": version,
            "settings": settings,
            "approve": not args.ask, "run": None,
        }
        if start_screen is None:
            row["stop_reason"] = "setup_failed"
        else:
            started = time.time()
            run_id, output = run_agent(task.goal, task.max_steps, not args.ask, agents)
            after_run = True
            shutil.copyfile(start_screen, out / "start.png")
            row |= {"run": run_id, "start_screen": "start.png", "wall": round(time.time() - started, 1)}
            if run_id:
                api.export(run_id, out / "run")  # the log and its screenshots
                row |= summarize(read_events(out / "run"))
            if not run_id or row["stop_reason"] != "replied":
                row["output"] = output
        (out / "result.json").write_text(json.dumps(row, ensure_ascii=False, indent=1), encoding="utf-8")
        desktop = " -> ".join(task["stop_reason"] or "?" for task in row.get("tasks", [])) or "not used"
        print(f"[{index}/{len(plan)}] {task_folder(name)} #{attempt}: {row.get('stop_reason')} ({setup}), desktop "
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


def section(folder: Path, row: dict, grade: str) -> str:
    run = row.get("run") or "no-run"
    where = row["dir"].relative_to(folder).as_posix()  # NN-task/attempt, where the sheet's screens are
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
    if row.get("end_screen"):
        lines.append(image(f"{where}/run/{row['end_screen']}", "End screen"))
    if row.get("run"):
        history = row["steps"] if "steps" in row else action_lines(read_events(row["dir"] / "run"))
        listed = "\n".join(f"{i}. {line}" for i, line in enumerate(history, 1))
        lines += ["", f"<details><summary>Actions ({len(history)})</summary>", "", listed, "", "</details>"]
    lines += ["", f"{GRADE} {grade}".rstrip()]
    return "\n".join(lines)


def build_sheet(folder: Path, grades: dict[str, str] | None = None, rows: list[dict] | None = None) -> Path:
    """A version's grading sheet, keeping the grades it has (and any given)."""
    if grades is None or rows is None:
        grades = read_grades(folder) | (grades or {})
    version = json.loads((folder / "version.json").read_text(encoding="utf-8"))
    header = SHEET_HEADER.format(name=folder.name, title=version_title(version))
    if version.get("changes"):
        header += f"\nChanged since {version['commit'][:7]}: {', '.join(f'`{name}`' for name in version['changes'])}\n"
    sections = [section(folder, row, grades.get(row.get("run"), "")) for row in (load_rows(folder) if rows is None else rows)]
    path = folder / "grade.md"
    path.write_text("\n\n".join([header, *sections]) + "\n", encoding="utf-8")
    return path


def experiment(row: dict) -> tuple:
    """Effective settings identify a cohort; equivalent requested overrides do not split it.
    Missing legacy metadata stays unknown, never inferred from today's runtime defaults."""
    settings, version = row.get("settings") or {}, row.get("version") or {}
    return (
        version.get("source") or version.get("commit") or "unknown",
        json.dumps(settings.get("agents", row.get("model")), sort_keys=True),
        json.dumps(settings.get("screenshots"), sort_keys=True),
        row.get("lang"), row.get("max_steps"), row.get("approve"),
    )


def known_total(values, digits: int = 0) -> str:
    """A sum of recorded values, with an explicit count of missing values (including an entirely unknown sum)."""
    values = list(values)
    known = [value for value in values if value is not None]
    if not known:
        return "?"
    total = f"{sum(known):.{digits}f}"
    return total + (f"+?{len(values) - len(known)}" if len(known) != len(values) else "")


def percentile(values: list[float], fraction: float) -> str:
    """Linear interpolation over sorted observations; a small sample's p95 is descriptive only."""
    if not values:
        return "?"
    point = (len(values) - 1) * fraction
    lower = int(point)
    return f"{values[lower] + (values[min(lower + 1, len(values) - 1)] - values[lower]) * (point - lower):.1f}"


def summary(folder: Path, rows: list[dict], grades: dict[str, str]) -> str:
    """All trials, grouped by effective settings. No screenshots or transcripts are read here."""
    groups: dict[tuple, list[dict]] = {}
    for row in rows:
        groups.setdefault(experiment(row), []).append(row)
    version = json.loads((folder / "version.json").read_text(encoding="utf-8"))
    lines = [f"== {folder.name}: {version_title(version)}", "   All trials; pass/graded; ? = unknown; p95 is descriptive for small samples."]
    for key, trials in groups.items():
        first = trials[0]
        settings = first.get("settings") or {}
        screenshots = settings.get("screenshots")
        pruning = f"{screenshots['keep']}/{screenshots['every']}" if screenshots else "unknown"
        approval = {True: "auto-approve", False: "ask", None: "unknown"}[key[-1]]
        lines += ["", f"   {first.get('model') or 'models unknown'}",
                  f"   source={key[0]}; lang={key[3] or '?'}; max_steps={key[4]}; approval={approval}; "
                  f"screenshots={pruning}; settings={'recorded' if settings else 'legacy'}"]
        started = [row for row in trials if row.get("run")]
        ungraded = sum(verdict(grades.get(row["run"])) is None for row in started)
        not_run = Counter(row.get("stop_reason", "not_started") for row in trials if not row.get("run"))
        endings = Counter(row.get("computer") or row.get("stop_reason", "unknown") for row in started)
        lines.append(f"   trials={len(trials)}, started={len(started)}, ungraded={ungraded}; "
                     f"not-run={dict(not_run)}; endings={dict(endings)}")
        lines.append(f"   {'task':<26}{'pass':>7}{'n':>5}{'calls M/S':>14}{'pass p50':>9}{'pass p95':>9}{'agent USD':>18}")
        by_task: dict[str, list[dict]] = {}
        for row in trials:
            by_task.setdefault(row["task"], []).append(row)
        for name, attempts in by_task.items():
            ran = [row for row in attempts if row.get("run")]
            judged = [verdict(grades.get(row["run"])) for row in ran]
            times = sorted(row["seconds"] for row in ran
                           if verdict(grades.get(row["run"])) == "pass" and row.get("seconds") is not None)
            calls = "/".join(known_total(row.get(field) for row in ran) for field in ("main_calls", "calls"))
            label = task_folder(name) + (" [infeasible]" if attempts[0].get("feasible") is False else "")
            passes = f"{judged.count('pass')}/{len(judged) - judged.count(None)}"
            lines.append(f"   {label:<26}{passes:>7}{len(attempts):>5}{calls:>14}"
                         f"{percentile(times, .5):>9}{percentile(times, .95):>9}"
                         f"{known_total((row.get('agent_cost') for row in ran), 5):>18}")
        agents: dict[tuple, list[dict]] = {}
        for row in started:
            for agent in row.get("agents") or []:
                agents.setdefault((agent["agent"], agent["model"]), []).append(agent.get("usage") or {})
        for (agent, model), usages in agents.items():
            totals = {field: known_total(usage.get(field) for usage in usages)
                      for field in ("input", "cached", "cache_write", "output", "reasoning")}
            inputs = sum(usage.get("input") or 0 for usage in usages)
            ratio = (f"{sum(usage['cached'] for usage in usages) / inputs:.1%}"
                     if inputs and all(usage.get("cached") is not None and usage.get("input") is not None for usage in usages)
                     else "?")
            lines.append(f"   {agent or 'unnamed'} ({model}) known tokens: in={totals['input']}, "
                         f"cached={totals['cached']} ({ratio}), write={totals['cache_write']}, "
                         f"out={totals['output']}, reasoning={totals['reasoning']}")
        lines.append(f"   usage unavailable in {sum(row.get('agents') is None for row in started)} trial(s); "
                     f"unknown calls={known_total(row.get('unknown_calls') for row in started)}; "
                     f"title USD={known_total((row.get('title_cost') for row in started), 5)}")
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
    selected = set(selected)
    rows = []
    for folder in folders:
        grades = read_grades(folder)
        trials = []
        for row in datasets[folder]:
            if row.get("run"):
                events = read_events(row["dir"] / "run")
                if events and not all(key in row for key in ("usage", "agents", "agent_cost", "title_cost", "unknown_calls")):
                    row = summarize(events) | row
                row = row | {"steps": action_lines(events), "words": said(events)}
            trials.append(row | {"grade": grades.get(row.get("run"), ""), "verdict": verdict(grades.get(row.get("run")))})
        if folder in selected:
            print(f"{summary(folder, trials, grades)}\n   sheet: {build_sheet(folder, grades, trials)}\n")
        rows += trials
    print(f"HTML report: {render(rows, (RESULTS / 'report.html').resolve(), IDS, NUMBERS)}")


def cmd_tasks(args) -> None:
    """Every task in brief; with one named, all of it, with the PowerShell that sets it up."""
    for name in task_ids([args.task]) if args.task else IDS:
        task = task_for(name, args.lang, f"ev-sample-{NUMBERS[name]:02d}-1")
        if not args.task:
            print(f"{task_folder(name):<23}{task.source}")
            continue
        print(f"{task_folder(name)} ({task.source}), at most {task.max_steps} model calls"
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
    run.add_argument("tasks", nargs="*", help="task numbers or ids (default: all)")
    run.add_argument("--trials", type=int, default=1, help="runs of each task")
    run.add_argument("--lang", choices=LANGS, default=LANGS[0], help="the language the goals are asked in")
    run.add_argument("--version", help='a git ref whose runtime/src the tasks run with (default: "worktree", the '
                     "working tree as it is)")
    for agent, example in (("main", "openai:gpt-6.1-sol low"), ("computer", "openai:gpt-6-luna high")):
        run.add_argument(f"--{agent}", nargs="+", metavar=("MODEL", "EFFORT"),
                         help=f'the {agent} agent\'s model and optionally effort, as "{example}" (default: the '
                         "container's settings)")
    run.add_argument("--note", help="what this version changes, as the report names it (kept until another is given)")
    run.add_argument("--ask", action="store_true",
                     help="wait for a person to answer the steps a run asks approval for (default: approve them all)")
    report = sub.add_parser("report", help="rebuild grading sheets, print pass rates and write the HTML report")
    report.add_argument("versions", nargs="*", help="versions under eval/results (default: the one run last)")
    tasks_ = sub.add_parser("tasks", help="list the tasks; with one named, show it and its setup PowerShell")
    tasks_.add_argument("task", nargs="?", help="a task number or id")
    tasks_.add_argument("--lang", choices=LANGS, default=LANGS[0])
    reset_ = sub.add_parser("reset", help="say whether the desktop is clean")
    what = reset_.add_mutually_exclusive_group()
    what.add_argument("--close", action="store_true", help="close what is open WITHOUT SAVING, by an agent run")
    what.add_argument("--accept", action="store_true", help="make the current screen the clean desktop")
    args = parser.parse_args()
    {"run": cmd_run, "report": cmd_report, "tasks": cmd_tasks, "reset": cmd_reset}[args.command](args)


if __name__ == "__main__":
    main()
