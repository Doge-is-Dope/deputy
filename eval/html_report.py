"""Render eval results as a single HTML comparison of code versions and models.

Pass rates exclude ungraded runs. Each task uses its latest attempt that passed
setup. Embedded thumbnails link to full screenshots relative to eval/results,
so keep the report there. Two versions are compared by their results, saying
whether their prompts or the rest of their code differ; when only the prompts
do, the page shows how they changed, from the source kept with each version."""

import base64
import difflib
import io
import itertools
import json
from pathlib import Path

from PIL import Image


def read_events(run: Path) -> list[dict]:
    """A copied run folder's complete events, off its steps.jsonl (as `computer-use export` writes it)."""
    try:
        text = (run / "steps.jsonl").read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    return [json.loads(line) for line in text.split("\n")[:-1] if line]

THUMB_WIDTH = 480
MODEL = "model"
# Where in runtime/src the runtime keeps everything its agents are told, apart from its tools: a version's prompts are
# named by this folder's contents, and the rest of its code by everything else (eval.py).
PROMPTS = "computer_use/prompts"


def version_key(version: dict) -> str:
    """A version's name, the folder in eval/results its runs go to (eval.py): its short commit, and for changes not
    committed, a digest of the source it ran, so each set of changes is a version of its own."""
    return version["commit"][:7] + (f"-{version['source'][:6]}" if version["dirty"] else "")


def version_title(version: dict) -> str:
    """What a version is called: the note the eval was given for it, else its commit's subject, saying when it has
    changes not committed."""
    return version.get("note") or version["subject"] + (" + changes not committed" if version["dirty"] else "")


def version_of(row: dict) -> str:
    """The version a run used, by its name; "unknown" for a run that recorded none."""
    version = row.get("version")
    return version_key(version) if version else "unknown"


def side(row: dict) -> str:
    """What a run is compared as: its version with its agents' models, so two models on one version are two sides."""
    return f"{version_of(row)} {row.get('model') or ''}".strip()


def versions(rows: list[dict], results: Path) -> dict:
    """Each version's record, by the name `version_of` gives it: its version.json in `results`, else what its runs
    recorded; with its title."""
    found = {}
    for row in rows:
        name = version_of(row)
        if name not in found:
            saved = results / name / "version.json"
            version = json.loads(saved.read_text(encoding="utf-8")) if saved.is_file() else row.get("version") or {
                "commit": "", "subject": "version not recorded", "date": "", "dirty": False}
            found[name] = version | {"title": version_title(version)}
    return found


def lines_of(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.is_file() else []


def changes(old: Path, new: Path) -> list[dict]:
    """The files that differ between two folders, each with its diff, old as - and new as +, and how many lines it adds
    and removes."""
    names = {path.relative_to(root).as_posix() for root in (old, new) for path in root.rglob("*") if path.is_file()}
    found = []
    for name in sorted(names):
        before, after = lines_of(old / name), lines_of(new / name)
        if before != after:
            lines = list(difflib.unified_diff(before, after, lineterm="", n=2))[2:]  # without the ---/+++ header
            found.append({
                "file": name, "lines": lines,
                "added": sum(line.startswith("+") for line in lines),
                "removed": sum(line.startswith("-") for line in lines),
            })
    return found


def prompt_diffs(versions: dict[str, dict], results: Path) -> dict[str, list[dict]]:
    """How the prompts changed from one version to another, for every two whose only difference is their prompts, by
    their names as "from to"; from the source kept in each version's folder."""
    return {
        f"{a} {b}": changes(results / a / "src" / PROMPTS, results / b / "src" / PROMPTS)
        for a, b in itertools.permutations(versions, 2)
        if versions[a].get("prompts") and versions[b].get("prompts") and versions[a]["prompts"] != versions[b]["prompts"]
        and versions[a].get("code") == versions[b].get("code")
    }


def thumb(path: Path) -> str:
    image = Image.open(path).convert("RGB")
    image.thumbnail((THUMB_WIDTH, THUMB_WIDTH))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=70)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()


def said(events: list[dict]) -> list[str]:
    """What the computer-use agent told the user before its tool calls, in order."""
    return [
        " ".join(event["text"].split())
        for event in events
        if event["type"] == MODEL and not event.get("agent") and event.get("tool_calls") and event["text"].strip()
    ]


def screen(path: Path, report_dir: Path) -> dict | None:
    if not path.is_file():
        return None
    href = path.relative_to(report_dir) if path.is_relative_to(report_dir) else path
    return {"src": thumb(path), "href": str(href)}


def end_screen(run: Path, logged: str | None) -> Path:
    """The last full screen of a run: the one taken after its last desktop task ended, not a zoomed-in crop."""
    screens = sorted(path for path in run.glob("*.png") if "zoom" not in path.stem)
    return screens[-1] if screens else run / (logged or "-")


def run_data(row: dict, report_dir: Path) -> dict:
    """What the page needs of one run (a result.json with its folder `dir`, `grade` line and `verdict`)."""
    folder = row["dir"]
    data = {
        "id": f"{version_of(row)}/{folder.parent.name}/{folder.name}", "started": row["started"], "task": row["task"],
        "attempt": row["attempt"], "side": side(row), "version": version_of(row),
        "goal": row["goal"], "expect": row["expect"], "model": row.get("model") or "",
        "grade": row["grade"], "verdict": row["verdict"],
    }
    if row.get("stop_reason") == "setup_failed" or not row.get("run"):
        return data | {"setup": row.get("setup") or "not run"}
    run = folder / "run"
    return data | {
        "calls": row.get("calls"), "actions": row.get("actions"), "seconds": row.get("seconds"),
        "cost": row.get("cost"), "summary": row.get("summary") or "",
        "tasks": [task["stop_reason"] for task in row.get("tasks") or []],
        "words": row["words"],
        "steps": row["steps"],
        "start": screen(folder / (row.get("start_screen") or "-"), report_dir),
        "end": screen(end_screen(run, row.get("end_screen")), report_dir),
    }


def render(rows: list[dict], out: Path, order: list[str], numbers: dict[str, int]) -> Path:
    """Write the page for these runs, listing tasks in `order` (then any dropped since) with their `numbers`."""
    if not rows:
        raise SystemExit("no eval runs")
    runs = [run_data(row, out.parent) for row in sorted(rows, key=lambda row: row["started"])]
    tasks = [*order, *sorted({run["task"] for run in runs} - set(order))]
    found = versions(rows, out.parent)
    payload = {
        "runs": runs, "order": tasks, "numbers": numbers, "versions": found, "diffs": prompt_diffs(found, out.parent),
    }
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    out.write_text(TEMPLATE.replace("__DATA__", data), encoding="utf-8")
    return out


TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Eval report</title>
<style>
:root { --bg:#fbfbfa; --fg:#18181b; --muted:#71717a; --faint:#a1a1aa; --line:#e7e7e4; --soft:#f3f3f1;
  --pass:#16a34a; --fail:#dc2626; --none:#a1a1aa; }
@media (prefers-color-scheme: dark) { :root { --bg:#111113; --fg:#ededef; --muted:#9a9aa3; --faint:#62626b;
  --line:#26262b; --soft:#19191c; --pass:#4ade80; --fail:#f87171; --none:#62626b; color-scheme:dark } }
* { box-sizing:border-box }
body { margin:0; background:var(--bg); color:var(--fg); -webkit-font-smoothing:antialiased;
  font:14px/1.6 -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", "PingFang TC", "Microsoft JhengHei", sans-serif }
main { max-width:960px; margin:0 auto; padding:56px 24px 96px }
button, select, input { font:inherit; color:inherit }
.muted { color:var(--muted) } .faint { color:var(--faint) }
header.top { display:flex; align-items:flex-start; justify-content:space-between; gap:16px }
h1 { font-size:28px; font-weight:600; letter-spacing:-0.02em; margin:0 }
#sub { margin:8px 0 0; color:var(--muted) } #sub div + div { margin-top:2px }
#sub .k { color:var(--faint); margin-right:6px } #sub .side { display:inline-block; width:54px; color:var(--faint) } #sub .agent { display:inline-block; white-space:nowrap; margin-right:20px }
select, input[type="datetime-local"] { background:transparent; border:1px solid var(--line); border-radius:999px;
  padding:6px 14px; cursor:pointer }
.select { position:relative; display:inline-block; flex:none }
.select select { appearance:none; -webkit-appearance:none; padding:7px 40px 7px 16px; max-width:100% }
.select { max-width:100%; min-width:0 }
.select::after { content:""; position:absolute; right:17px; top:50%; width:6px; height:6px; pointer-events:none;
  border-right:1.5px solid var(--muted); border-bottom:1.5px solid var(--muted); transform:translateY(-70%) rotate(45deg) }
select:hover, input[type="datetime-local"]:hover { border-color:var(--faint) }
select:focus, input:focus, button:focus { outline:none }
button:focus-visible { outline:2px solid var(--faint); outline-offset:2px }
.versions { display:flex; flex-direction:column; gap:8px; margin:24px 0 0 }
.versions label > span:first-child { width:44px; flex:none }
.versions label { display:flex; align-items:center; gap:10px; min-width:0; max-width:100%; font-size:13px; color:var(--faint) }
.versions .select { width:min(440px, 100%) } .versions select { width:100%; text-overflow:ellipsis; color:var(--fg) }
.stats { display:grid; grid-template-columns:repeat(4, minmax(0, 1fr)); gap:24px; margin:48px 0 40px }
.stat dt { font-size:12px; color:var(--muted); margin-bottom:6px }
.stat dd { margin:0; font-size:30px; font-weight:500; letter-spacing:-0.02em; font-variant-numeric:tabular-nums;
  white-space:nowrap }
.stat dd { display:flex; align-items:center } /* the arrow sits at the numbers' middle */
.stat dd .from { color:var(--faint); font-weight:400 } .stat dd .arrow { color:var(--faint); font-size:20px; margin:0 8px }
.stat .note { font-size:13px; color:var(--muted); margin-top:2px; font-variant-numeric:tabular-nums }
.good { color:var(--pass) } .bad { color:var(--fail) }
.verdict { margin:48px 0 0 }
.verdict h2 { margin:0; font-size:20px; font-weight:600; letter-spacing:-0.01em }
.verdict p { margin:4px 0 0; font-size:13px; color:var(--muted) }
.verdict + .stats { margin-top:32px }
.list-head, .row > summary { display:grid; grid-template-columns:var(--cols); gap:16px;
  align-items:baseline; padding:14px 0 }
.list-head { font-size:12px; color:var(--faint); border-bottom:1px solid var(--line); position:sticky; top:0; z-index:1;
  background:var(--bg) }
.row { border-bottom:1px solid var(--line) }
.row > summary { cursor:pointer; list-style:none } .row > summary::-webkit-details-marker { display:none }
.row > summary:hover .name { text-decoration:underline; text-decoration-color:var(--faint); text-underline-offset:3px }
.name { font-weight:500 } .no { display:inline-block; width:28px; color:var(--faint); font-variant-numeric:tabular-nums }
.status { display:inline-flex; align-items:center; gap:7px; white-space:nowrap }
.status::before { content:""; width:7px; height:7px; border-radius:50%; background:var(--none) }
.status.pass::before { background:var(--pass) } .status.fail::before { background:var(--fail) }
.status .num { color:var(--faint); font-size:12px; font-variant-numeric:tabular-nums }
.delta { font-variant-numeric:tabular-nums; text-align:right } .list-head .delta { text-align:right }
[data-tip] { position:relative }
[data-tip]:hover::after { content:attr(data-tip); position:absolute; left:50%; transform:translateX(-50%);
  bottom:calc(100% + 6px); z-index:2; padding:4px 8px; border-radius:6px; background:var(--fg); color:var(--bg);
  font-size:12px; font-weight:400; line-height:1.5; text-align:left; white-space:nowrap; pointer-events:none }
.task { padding:4px 0 32px }
.task .meta { display:grid; grid-template-columns:72px minmax(0, 1fr); gap:4px 16px; margin:0 0 24px; font-size:13px }
.task .meta dt { color:var(--faint) } .task .meta dd { margin:0 }
.runs { display:grid; grid-template-columns:repeat(var(--sides), minmax(0, 1fr)); gap:32px }
.runs > div { display:flex; flex-direction:column; gap:32px; min-width:0 }
.run header { display:flex; justify-content:space-between; align-items:baseline; gap:8px; margin-bottom:8px }
.run header b { font-weight:500 }
.run .facts { font-size:12px; color:var(--faint); margin:0 0 12px }
.run .grade { font-size:13px; color:var(--muted); margin:0 0 12px }
.reply { margin:0 0 16px; padding-left:14px; border-left:2px solid var(--line); white-space:pre-wrap; overflow-wrap:anywhere }
.said { margin:0 0 16px } .said p { font-size:12px; color:var(--faint); margin:0 0 6px }
.said ol, .steps { margin:0; padding-left:18px; overflow-wrap:anywhere; color:var(--muted) } .said li { margin:2px 0 }
.screens { display:grid; grid-template-columns:1fr 1fr; gap:10px; margin:0 0 12px }
figure { margin:0 } figure img { width:100%; aspect-ratio:16 / 10; object-fit:cover; object-position:top;
  border-radius:6px; display:block; outline:1px solid var(--line) }
figcaption { font-size:11px; color:var(--faint); margin-top:4px }
details.more summary { font-size:12px; color:var(--faint); cursor:pointer } .steps { font-size:12px; margin-top:8px }
code { font:12px ui-monospace, SFMono-Regular, Menlo, monospace }
.empty { padding:96px 0; text-align:center; color:var(--muted) }
.changes { margin:0 0 40px } .changes h3 { margin:0 0 4px; font-size:12px; font-weight:400; color:var(--muted) }
.changes details { margin-top:8px } .changes summary { cursor:pointer; font-size:13px }
.changes .count { margin-left:8px; font-size:12px; font-variant-numeric:tabular-nums }
.diff { margin:8px 0 0; padding:12px 14px; border:1px solid var(--line); border-radius:8px; background:var(--soft);
  font:12px/1.55 ui-monospace, SFMono-Regular, Menlo, monospace; white-space:pre; overflow:auto; max-height:480px }
.diff .add { color:var(--pass) } .diff .del { color:var(--fail) } .diff .hunk { color:var(--faint) }
@media (max-width: 720px) {
  main { padding:32px 16px 64px }
  header.top { flex-direction:column }
  .stats { grid-template-columns:repeat(2, minmax(0, 1fr)); gap:28px 16px; margin-top:36px }
  .stat dd { font-size:24px }
  .verdict { margin-top:36px }
  .list-head, .row > summary { grid-template-columns:var(--cols-narrow); gap:10px }
  .status .num { display:none }
  .runs { grid-template-columns:minmax(0, 1fr) }
  .versions label { width:100% } .versions .select { flex:1; width:auto }
}
</style></head><body><main>
<header class="top"><div><h1>Eval report</h1><div id="sub"></div></div></header>
<div class="versions">
  <label><span>Before</span><span class="select"><select id="before" aria-label="Before"></select></span></label>
  <label><span>After</span><span class="select"><select id="after" aria-label="After"></select></span></label>
</div>
<div id="view"></div>
</main>
<script type="application/json" id="data">__DATA__</script>
<script>
const { runs: RUNS, order: ORDER, numbers: NUMBERS, versions: VERSIONS, diffs: DIFFS } = JSON.parse(document.getElementById("data").textContent)
const WORDS = { pass: "Pass", fail: "Fail", ungraded: "Not graded", setup: "Setup failed" }

const label = (t) => `${+t.slice(5, 7)}/${+t.slice(8, 10)} ${t.slice(11, 16)}` // when a run started: YYYY-MM-DDTHH:MM:SS
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c])
const md = (text) => esc(text).replace(/\\*\\*(.+?)\\*\\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>")
const change = (a, b) => (a ? `${b >= a ? "+" : "−"}${Math.round((Math.abs(b - a) / a) * 100)}%` : "")
const median = (values) => { const s = [...values].sort((a, b) => a - b); const m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2 }
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`
const title = (word) => word.charAt(0).toUpperCase() + word.slice(1)
const clip = (text, n) => (text.length > n ? `${text.slice(0, n - 1)}…` : text)
// "main openai:gpt-6.1-sol low, computer openai:gpt-6-luna high" as each agent's model and effort.
const MODEL_NAME = (spec) => {
  const [first, ...rest] = spec.split(":").at(-1).split("-")
  return first === "gpt" ? `GPT-${rest[0]} ${rest.slice(1).map(title).join(" ")}` : [first, ...rest].map(title).join(" ")
}
const agents = (model) => [...model.matchAll(/(\\w+) \\S+?:(\\S+) (\\w+)/g)].map(([, agent, spec, effort]) =>
  `<span class="agent"><span class="k">${title(agent)} agent</span>${esc(MODEL_NAME(spec))} · ${esc(effort)}</span>`).join("")

// A change for the better (lower) is green, one for the worse red; under 5% either way is no change.
const tone = (a, b) => { const p = a ? (b - a) / a : 0; return p <= -0.05 ? "good" : p >= 0.05 ? "bad" : "" }

// What runs are compared as (a side): a version with its agents' models, as eval.py run recorded them. The sides that
// have runs, the newest commit first, and on one commit the one run last first.
const runsOf = (key) => RUNS.filter((run) => run.side === key)
const lastRun = (key) => runsOf(key).at(-1).started
const versionOf = (key) => runsOf(key)[0].version
const modelOf = (key) => runsOf(key)[0].model
const date = (key) => VERSIONS[versionOf(key)].date || ""
const KEYS = [...new Set(RUNS.map((run) => run.side))]
  .sort((a, b) => date(b).localeCompare(date(a)) || lastRun(b).localeCompare(lastRun(a)))
// Each agent's model and effort in a side, as "Computer agent GPT-6 Luna high"; a side's label names only the agents
// whose model or effort differs between the sides.
const agentsOf = (key) => [...modelOf(key).matchAll(/(\\w+) \\S+?:(\\S+) (\\w+)/g)]
  .map(([, agent, spec, effort]) => [agent, `${title(agent)} agent ${MODEL_NAME(spec)} ${effort}`])
const VARIES = new Set(KEYS.flatMap(agentsOf).map(([agent]) => agent)
  .filter((agent) => new Set(KEYS.map((key) => agentsOf(key).find(([a]) => a === agent)?.[1])).size > 1))
const describe = (key) => [
  versionOf(key) === versionOf(KEYS[0]) ? "Latest" : "", // the newest commit is marked
  versionOf(key), ...agentsOf(key).filter(([agent]) => VARIES.has(agent)).map(([, text]) => text),
  clip(VERSIONS[versionOf(key)].title, 64),
].filter(Boolean).join(" · ")
// Before lists every side; After, every other one. With one side, both list it.
const afterKeys = () => (KEYS.length > 1 ? KEYS.filter((key) => key !== state.before) : KEYS)
function options() {
  const option = (key) => `<option value="${esc(key)}">${esc(describe(key))}</option>`
  document.getElementById("before").innerHTML = KEYS.map(option).join("")
  document.getElementById("after").innerHTML = afterKeys().map(option).join("")
}
// Keep the two sides different: an After that is Before, or none, falls back to the other side run last.
const recentFirst = (keys) => [...keys].sort((a, b) => lastRun(b).localeCompare(lastRun(a)))
function settle() {
  if (!KEYS.includes(state.before)) state.before = KEYS[0]
  if (!afterKeys().includes(state.after)) state.after = recentFirst(afterKeys())[0]
}

// What the reader picked, kept in the address: the two versions. By default, the version run
// last against the one run last before it, the older commit as Before.
const state = { before: "", after: "" }
const opened = new Set()
function readHash() {
  const hash = new URLSearchParams(location.hash.slice(1))
  const recent = recentFirst(KEYS)
  let [after, before] = [recent[0], recent[1] ?? recent[0]]
  if (KEYS.indexOf(before) < KEYS.indexOf(after)) [before, after] = [after, before] // the older commit, or run first
  state.before = KEYS.includes(hash.get("before")) ? hash.get("before") : before
  state.after = KEYS.includes(hash.get("after")) ? hash.get("after") : after
  settle()
}
function writeHash() {
  const hash = new URLSearchParams({ before: state.before, after: state.after })
  history.replaceState(null, "", `#${hash}`)
}
const role = (key) => (key === state.before ? "Before" : "After")

const outcome = (run) => (run.setup ? "setup" : run.verdict || "ungraded")
// The run of a task and version that counts: the latest, unless it never got past setup.
const counted = (list) => list.findLast((run) => !run.setup) || list.at(-1) || null

// Four numbers, on the tasks every side ran and graded; with two sides, first → second.
function summary(byTask, sides) {
  const sets = [...byTask].map(([task, bySide]) => [task, sides.map((s) => counted(bySide.get(s) || []))])
  const both = sets.filter(([, runs]) => runs.every((run) => run?.verdict))
  const cols = sides.map((s, i) => {
    const runs = both.map(([, r]) => r[i])
    const sum = (key) => runs.reduce((total, run) => total + (run[key] || 0), 0)
    return { passed: runs.filter((run) => run.verdict === "pass").length, of: runs.length,
      calls: sum("calls"), seconds: sum("seconds"), minutes: Math.round(sum("seconds") / 60), cost: sum("cost") }
  })
  const two = sides.length === 2
  const pct = (a, b) => (a ? (b - a) / a : 0)
  const delta = (key) => (two ? `<span class="${tone(cols[0][key], cols[1][key])}">${change(cols[0][key], cols[1][key])}</span>` : "")
  const value = (format, key) => two
    ? `<span class="from">${format(cols[0][key])}</span><span class="arrow">→</span><span>${format(cols[1][key])}</span>`
    : format(cols[0][key])
  const stat = (name, format, key, note) => `<div class="stat"><dt>${name}</dt><dd>${value(format, key)}</dd><div class="note">${note}</div></div>`
  const faster = two ? both.filter(([, [a, b]]) => (b.seconds || 0) < (a.seconds || 0)).length : 0
  const ratio = two && both.length ? median(both.map(([, [a, b]]) => (b.seconds || 0) / (a.seconds || 1))) : 0
  return `${two ? verdict(cols, sides, pct) : ""}<dl class="stats">
    ${stat("Passed", (n) => n, "passed", `of ${cols.at(-1).of}`)}
    ${stat("Model calls", (n) => n, "calls", delta("calls"))}
    ${stat("Time", (n) => `${n}<small> min</small>`, "minutes", two ? `${delta("seconds")} · faster on ${faster} of ${both.length}` : "")}
    ${stat("Cost", (n) => `$${n.toFixed(2)}`, "cost", delta("cost"))}
  </dl>`
}

// Better, worse or mixed, second side against the first: passes first, then calls, time and cost.
function verdict(cols, sides, pct) {
  const [a, b] = cols
  const passes = b.passed - a.passed
  const moves = [["calls", "fewer calls", "more calls"], ["seconds", "faster", "slower"], ["cost", "cheaper", "costlier"]]
    .map(([key, down, up]) => { const p = pct(a[key], b[key]); return Math.abs(p) < 0.05 ? null : [p < 0, `${Math.round(Math.abs(p) * 100)}% ${p < 0 ? down : up}`] })
    .filter(Boolean)
  const better = moves.filter(([good]) => good).length, worse = moves.length - better
  const [tone, word] = passes < 0 ? ["bad", "worse"] : passes > 0 ? (worse ? ["", "mixed"] : ["good", "better"])
    : better && !worse ? ["good", "better"] : worse && !better ? ["bad", "worse"] : better ? ["", "mixed"] : ["", "about the same"]
  const why = [passes ? `${Math.abs(passes)} ${passes > 0 ? "more" : "fewer"} passed` : "same passes", ...moves.map(([, text]) => text)]
  return `<div class="verdict"><h2>After is <span class="${tone}">${word}</span></h2><p>${why.join(" · ")}</p></div>`
}

function status(run, numbers = true) {
  const kind = outcome(run)
  const num = numbers && run.calls != null ? `<span class="num">${run.calls} calls · ${Math.round(run.seconds || 0)}s</span>` : ""
  return `<span class="status ${kind}">${WORDS[kind]}${num}</span>`
}

function panel(run) {
  const head = `<header><span><b>${role(run.side)}</b> <span class="faint">${esc(run.version)} · #${run.attempt} · ${label(run.started)}</span> · ${status(run, false)}</span></header>`
  if (run.setup) return `<div class="run">${head}<p class="facts">The setup did not finish (${esc(run.setup)}); not run.</p></div>`
  const figure = (shot, caption) => shot ? `<figure><a href="${esc(shot.href)}" target="_blank"><img src="${shot.src}" alt="${caption}" loading="lazy"></a><figcaption>${caption}</figcaption></figure>` : ""
  return `<div class="run">${head}
    <p class="facts">${run.calls} model calls · ${run.actions} actions · ${Math.round(run.seconds || 0)}s · $${(run.cost || 0).toFixed(3)}</p>
    ${run.grade ? `<p class="grade">${esc(run.grade)}</p>` : ""}
    <div class="reply">${md(run.summary || "(no reply)")}</div>
    ${run.words.length ? `<div class="said"><p>Said on ${run.words.length} of ${run.calls} steps</p><ol>${run.words.map((w) => `<li>${md(w)}</li>`).join("")}</ol></div>` : ""}
    <div class="screens">${figure(run.start, "Start")}${figure(run.end, "End")}</div>
    <details class="more"><summary>${plural(run.steps.length, "action")}</summary><ol class="steps">${run.steps.map((s) => `<li>${esc(s)}</li>`).join("")}</ol></details></div>`
}

// What else differs between the two versions picked: their prompts, the rest of their code, or neither. Versions run
// before the eval kept their prompts' digest say nothing.
function differs(sides) {
  const [a, b] = sides.map((key) => VERSIONS[versionOf(key)])
  if (sides.length < 2 || !a.prompts || !b.prompts) return ""
  const prompts = a.prompts !== b.prompts, code = a.code !== b.code
  return `<div>${prompts && code ? "The prompts and the rest of the code differ" : prompts ? "Only the prompts differ"
    : code ? "Same prompts; the rest of the code differs" : "Same prompts and code"}</div>`
}

// When only the prompts differ, how they changed from Before to After: each prompt file's diff.
function promptChanges(sides) {
  const files = sides.length === 2 ? DIFFS[`${versionOf(sides[0])} ${versionOf(sides[1])}`] : null
  if (!files?.length) return ""
  const kind = (line) => (line.startsWith("@@") ? "hunk" : line[0] === "+" ? "add" : line[0] === "-" ? "del" : "")
  const file = ({ file, lines, added, removed }) => `<details open><summary><code>${esc(file)}</code><span class="count">
    <span class="good">+${added}</span> <span class="bad">−${removed}</span></span></summary><pre class="diff">${
    lines.map((line) => `<span class="${kind(line)}">${esc(line)}</span>`).join("\\n")}</pre></details>`
  return `<section class="changes"><h3>How the prompts changed</h3>${files.map(file).join("")}</section>`
}

function render() {
  const sides = state.before === state.after ? [state.before] : [state.before, state.after]
  const picked = RUNS.filter((run) => sides.includes(run.side))
  const byTask = new Map()
  for (const task of ORDER) {
    const list = picked.filter((run) => run.task === task)
    if (list.length) byTask.set(task, new Map(sides.map((s) => [s, list.filter((run) => run.side === s)])))
  }
  options()
  document.getElementById("before").value = state.before
  document.getElementById("after").value = state.after
  // The agents' models: once when both sides share them, else each side's.
  const models = sides.map(modelOf)
  document.getElementById("sub").innerHTML = (new Set(models).size === 1
    ? `<div>${agents(models[0])}</div>`
    : sides.map((key) => `<div><span class="side">${role(key)}</span>${agents(modelOf(key))}</div>`).join("")) +
    differs(sides) +
    (sides.length === 1 ? `<div>Run another version or model to compare two.</div>` : "")
  const view = document.getElementById("view")
  const two = sides.length === 2
  view.style.setProperty("--sides", sides.length || 1)
  view.style.setProperty("--cols", `minmax(0, 1fr) repeat(${sides.length}, 132px)${two ? " repeat(2, 72px)" : ""}`)
  view.style.setProperty("--cols-narrow", `minmax(0, 1fr) repeat(${sides.length}, auto)${two ? " repeat(2, 44px)" : ""}`)
  if (!picked.length) {
    view.innerHTML = `<p class="empty">No runs of these.</p>`
    return
  }
  const rows = [...byTask].map(([task, bySide]) => {
    // The task as its latest run asked it: goals name the run's own files.
    const any = [...bySide.values()].flat().sort((x, y) => x.started.localeCompare(y.started)).at(-1)
    const cells = sides.map((s) => {
      const run = counted(bySide.get(s) || [])
      return run ? `<span>${status(run, false)}</span>` : `<span class="faint">–</span>`
    }).join("")
    // After against Before: how many more or fewer model calls, and how much more or less time; only where both runs
    // count, as in the numbers above.
    const [a, b] = sides.map((s) => counted(bySide.get(s) || []))
    // On hover, the two values: "28 → 22" calls, "158 → 138" seconds.
    const tip = (key, x, y) => `${Math.round(x)} → ${Math.round(y)}`
    const delta = (key) => a?.verdict && b?.verdict
      ? `<span class="delta ${tone(a[key], b[key])}"><span data-tip="${tip(key, a[key], b[key])}">${change(a[key], b[key]) || "0%"}</span></span>`
      : `<span class="delta faint">–</span>`
    const deltas = two ? delta("calls") + delta("seconds") : ""
    // One column per side, its latest run first.
    const panels = sides.map((s) => `<div>${[...(bySide.get(s) || [])].reverse().map(panel).join("")}</div>`).join("")
    return `<details class="row" data-task="${esc(task)}" ${opened.has(task) ? "open" : ""}><summary><span><span class="no">${NUMBERS[task] ? String(NUMBERS[task]).padStart(2, "0") : "–"}</span><span class="name">${esc(task)}</span></span>${cells}${deltas}</summary>
      <div class="task"><dl class="meta"><dt>Goal</dt><dd>${esc(any.goal)}</dd><dt>Expect</dt><dd>${esc(any.expect)}</dd></dl><div class="runs">${panels}</div></div></details>`
  }).join("")
  view.innerHTML = `${summary(byTask, sides)}${promptChanges(sides)}<div class="list">
    <div class="list-head"><span>Task</span>${sides.map((s) => `<span>${role(s)}</span>`).join("")}${two ? `<span class="delta">Calls</span><span class="delta">Time</span>` : ""}</div>${rows}</div>`
}

for (const id of ["before", "after"]) {
  const select = document.getElementById(id)
  select.addEventListener("change", () => {
    state[id] = select.value
    settle()
    select.blur() // a choice made with the mouse leaves no focus ring behind
    writeHash(); render()
  })
}
const view = document.getElementById("view")
view.addEventListener("toggle", (event) => {
  const task = event.target.dataset?.task
  if (task) event.target.open ? opened.add(task) : opened.delete(task)
}, true)
addEventListener("hashchange", () => { readHash(); render() })
readHash()
render()
</script></body></html>
"""
