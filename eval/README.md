# Windows evaluation

Run Windows desktop tasks through the runtime, grade the results by hand, and compare code versions or models. These tasks make real changes on the connected Windows test machine and call model APIs.

## Quick start

First, complete the [runtime setup](../README.md#quick-start). Keep the runtime container running and its Windows connection active. Use a dedicated test desktop.

From the repository root, install the local Python environment used by `eval/ev`:

```bash
uv sync --frozen --project runtime
```

Close unrelated windows on the Windows machine. Once the desktop is ready for testing, save its initial screenshot as the local baseline:

```bash
eval/ev reset --accept
```

Then list the tasks, run a sample in English and create the report:

```bash
eval/ev tasks              # list the tasks
eval/ev run 11 14 --lang en # run tasks 11 and 14 in English
eval/ev report             # pass rates, the grading sheet and the HTML report
```

`eval/ev` runs [eval.py](eval.py) with the runtime's Python. It needs the runtime container up
(`docker compose up` in `runtime/`) and the Windows PC connected. Each `run` copies the selected `runtime/src` into
the container and serves it there on port 8001, beside the server the web page uses, so source changes do not require
rebuilding the image. Dependency changes still require rebuilding it. The eval drives that server through the
[CLI](../clients/cli/README.md)'s API client, as any client would.

Both servers share the container's runs and its desktop lock, so only one run uses the desktop at a time. The web page
lists the eval's conversations under the eval project; to follow one live, point a web page at port 8001
(`CU_API_URL=http://127.0.0.1:8001 bun run dev` in `clients/web/`). Versions from before the CLI became an API client have
no server the eval can drive, so they cannot be run this way.

## Tasks

[tasks.jsonl](tasks.jsonl) holds 20 tasks, one per line, each asked in Traditional Chinese (default) or English
(`--lang en`). `eval/ev tasks 11` shows one task in full, with the PowerShell that sets it up.

| Kind | Tasks |
|---|---|
| Windows Agent Arena | 01–07: Notepad, Calculator, Paint, Explorer, Settings, Chrome |
| Back-office web pages | 08–10: look up a table, fill a form, reconcile a page with a spreadsheet |
| OSWorld Windows (Office) | 11–13, 15–17: Excel, Word, PowerPoint, multi-app |
| Typing Traditional Chinese | 14 |
| Infeasible: the right answer is "this cannot be done" | 18–19, scored apart |
| Distractor: a similar open file must be left alone | 20 |

Each line defines one task: its number (`no`), ID (`id`), source, starting state (`start`), goal in both languages
(`goal`), expected result (`expect`) and setup steps (`setup`). The setup steps are converted to PowerShell by
`step_script` in [winsetup.py](winsetup.py). Optional fields are `feasible: false` and `max_steps` (default 60).

The `{name}` placeholder becomes `ev-<version>-<no>-<attempt>`, giving each attempt its own files. Keep existing task numbers stable when editing the task list.

## Running

```bash
eval/ev run 11 14 --trials 3 --lang en                    # run each task three times
eval/ev run 11 --version HEAD --lang en                   # use the latest committed runtime source
eval/ev run 11 --computer openai:gpt-6-luna medium --lang en # override the desktop model and effort
```

Omit the task numbers to run all 20 tasks. Omit `--lang en` to use Traditional Chinese. Without `--version`, the evaluator uses the current working-tree source, including uncommitted changes under `runtime/src`.

Before each task, `run` checks that the desktop is connected (waiting up to a minute for it to come back), that
nobody else has it, and that the screen matches `clean-desktop.png` (local, not in Git). It then builds the starting
state by pasting PowerShell into the Run dialog, runs the goal, and closes what the run opened without saving. It
never closes windows it did not open: if the desktop is cluttered before the first task, close them yourself, or run
`eval/ev reset --accept` if only the wallpaper changed.

Steps the agent asks approval for are approved automatically; add `--ask` to answer them yourself.

Results go to `results/<version>/<NN-task>/<attempt>/` (`result.json`, `start.png`, the run's log and screenshots
as `computer-use export` writes them). See [versions and prompts](#versions-and-prompts) for how a version is named.

## Versions and prompts

The eval compares results: of two prompt versions, two code versions or two model setups.

A version is named by its short commit. When `runtime/src` has uncommitted changes, a digest of the source is added
(`e856315-80cad5`), so each set of changes is a version of its own: tweak a prompt, run again, and the results go to a
new folder rather than mixing with the last one. Name what a version changes with `--note`; the report and the
terminal summary call the version by it, and it stays until a later run gives another.

```bash
eval/ev run 11 14 --trials 3 --note "shorter plan steps"
```

The runtime keeps everything its agents are told in `runtime/src/computer_use/prompts/`. Each version's `version.json`
records a digest of that folder and one of the rest of the code, and the report says of the two versions picked
whether only their prompts differ, so a change in results can be put down to the prompts. When they do, it shows how
the prompts changed, below the numbers. Each version's folder keeps `src/`, the source it ran, which those diffs come
from and which keeps the wording of a prompt that did well, even one never committed.

## Grading

Open `results/<version>/grade.md`. Each run shows the goal, what to expect, the agent's reply, the start and end
screens and the actions. Write `pass` or `fail` after `Grade:`, then why. Leave a run ungraded to leave it out.

`eval/ev report [versions]` rebuilds the sheets (keeping the grades), prints each version's pass rate and per-task
numbers, and writes `results/report.html`, where you pick two versions or model setups to compare side by side.
The report's thumbnails link to the screenshots next to it, so keep it in `results/`.

## Settings and repeated trials

New `result.json` files keep `settings.requested_agents` and the resolved `settings.agents`, using the tested
server's defaults and supported efforts. The readable `model` field stays available to the HTML report. Pruning
metadata (`settings.screenshots`, `keep`/`every`) comes from literal constants in the saved source, without importing
that code; an implementation without those constants is recorded as unknown. No runtime defaults are changed.

The terminal report uses **all trials**, grouped by source, effective models/efforts, pruning settings, language,
step limit and approval mode. It shows pass/graded, ungraded and not-started counts, endings, total main/subagent
calls (`M/S`), per-task successful-run p50/p95 seconds and all-started-trial agent cost. Failed and ungraded trials do not
make the latency numbers look faster; their timings remain in the individual results. Small-sample p95 is
descriptive, not a reliable tail-latency estimate.
Infeasible tasks are marked and graded separately. The HTML keeps its existing latest-trial comparison for diagnosis;
use the terminal groups when assessing repeated A/B runs.

Token/cache summaries use the exported end event's per-agent/model usage, not model usage added to it again.
Reasoning tokens are already part of output. Cache-read ratios are weighted by recorded input tokens. Interrupted
calls and missing usage/cost remain unknown: `?` is unknown, and `0.01200+?1` is a known subtotal with one unknown
trial. Independent title costs are shown separately. Legacy records get available metrics from their exports but
missing settings stay `legacy`/`unknown`, rather than being assigned today's defaults. Exports and result files
are not rewritten by `report`.

A report reads each result and trajectory once, shares compact action/text summaries between the grading sheet
and HTML, and releases the full trajectory data. Statistics do not decode screenshots or retain full conversations
in a persistent cache. Offline regression checks use the existing runtime test environment:

```bash
cd runtime
.venv/bin/python -m pytest tests/unit/test_eval.py -q
```

## Fair comparisons

- **Alternate** versions or models from task to task: model latency drifts over hours.
- **Run each task at least three times** before claiming a change helped.
- **Reset state an earlier run left** (a setting turned on stays on) with a `registry` or `reset-app` setup step.
- **Watch for a frozen screen**: after a reconnect the RDP client can keep showing an old frame (the taskbar clock
  stops). Kill `xfreerdp3` in the container and drop those runs.
- **Keep the Mac awake** (`caffeinate -i -s`), or the connection drops mid-run.
