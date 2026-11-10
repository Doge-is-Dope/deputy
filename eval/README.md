# Windows evaluation

Run Windows desktop tasks through the runtime, grade the results by hand, and compare code versions or models. These tasks make real changes on the connected Windows test machine and call model APIs.

## Quick start

First, complete the [runtime setup](../runtime/README.md#setup). Keep the runtime container running and its Windows connection active. Use a dedicated test desktop.

From the repository root, install the local Python environment used by `eval/ev`:

```bash
uv sync --frozen --project runtime
```

Close unrelated windows on the Windows machine. Once the desktop is ready for testing, save its initial screenshot as the local baseline:

```bash
eval/ev reset --accept
```

Then list the tasks, run a sample and create the report:

```bash
eval/ev tasks              # list the tasks
eval/ev run 10 13          # run tasks 10 and 13
eval/ev report             # pass rates, the grading sheet and the HTML report
```

`eval/ev` runs [eval.py](eval.py) with the runtime's Python and the [CLI](../clients/cli/README.md)'s API client. Each run copies the selected `runtime/src` into the running container and starts an eval server on port 8001. Source changes need no image rebuild; dependency changes do.

To try a version by hand the same way, `eval/ev serve [--version REF]` serves it on port 8001 until Ctrl-C. Docker commands use your current Docker context (`docker context use` or `DOCKER_CONTEXT`).

The eval and web servers share stored runs and the desktop lock. Only one run can use the desktop at a time. Task setups and the cleanup script hold the same lock while they type; if something else holds it, the eval stops. Eval conversations appear under the eval project in the web UI. To follow them live, run `CU_API_URL=http://127.0.0.1:8001 bun run dev` in `clients/web/`. Versions predating the CLI's HTTP API client are unsupported.

## Tasks

[tasks.jsonl](tasks.jsonl) holds 22 tasks, one per line. `eval/ev tasks 10` shows one task in full, with the
PowerShell that sets it up.

| Kind | Tasks |
|---|---|
| Windows Agent Arena | 01–07: Notepad, Calculator, Paint, Explorer, Settings, Chrome |
| Back-office web pages | 08–09: fill a form, reconcile a page with a spreadsheet; 21: an ID from one page, its phone from a 250-page table |
| OSWorld Windows (Office) | 10–12, 14–16: Excel, Word, PowerPoint, multi-app |
| Typing Traditional Chinese | 13 |
| Infeasible: the right answer is "this cannot be done" | 17–18, scored apart |
| Distractor: a similar open file must be left alone | 19 |
| Keyboard only: a submenu ignores the mouse | 20: export from a menu whose submenu takes only the keyboard |
| Professional system: function codes, query mode, value lists, maker-checker | 22: a local mock, change a party's phone and leave it unauthorized |

Each line defines one task: its number (`no`), ID (`id`), source, starting state (`start`), goal (`goal`),
expected result (`expect`) and setup steps (`setup`). The setup steps are converted to PowerShell by
`step_script` in [winsetup.py](winsetup.py). Optional fields are `feasible: false` and `max_steps` (default 60).

The `{name}` placeholder becomes `ev-<version>-<no>-<attempt>`, giving each attempt its own files. Keep task numbers stable while results filed under them are kept.

## Running

```bash
eval/ev run 10 13 --trials 3                       # run each task three times
eval/ev run 10 --version HEAD                      # use the latest committed runtime source
eval/ev run 10 --computer openai:gpt-6-luna medium # override the desktop model and effort
```

Omit the task numbers to run all 22 tasks. Without `--version`, the evaluator uses the current working-tree source, including uncommitted changes under `runtime/src`.

Before each task, `run` checks that the desktop is connected, available and matches the local `clean-desktop.png` baseline. It waits up to a minute for reconnection. It then sets up the task through PowerShell, runs the goal and closes any windows it opened without saving.

Close unrelated windows yourself before testing. If only the wallpaper changed, update the baseline with `eval/ev reset --accept`.

Steps the agent asks approval for are approved automatically; add `--ask` to answer them yourself.

Results go to `results/<version>/<NN-task>/<attempt>/` (`result.json`, `start.png`, the run's log and screenshots
as `computer-use export` writes them). See [versions and prompts](#versions-and-prompts) for how a version is named.

## Versions and prompts

The eval compares results: of two prompt versions, two code versions or two model setups.

Versions use the short commit hash. Uncommitted changes under `runtime/src` add a source digest, such as `e856315-80cad5`, keeping each revision's results separate. Use `--note` to give the version a readable label in reports. The label stays until a later run replaces it.

```bash
eval/ev run 10 13 --trials 3 --note "shorter plan steps"
```

Each version saves its tested source in `src/`, including uncommitted prompts. Its `version.json` records separate digests for `runtime/src/computer_use/prompts/` and the remaining code. The report identifies comparisons where only prompts changed and shows their diff below the results.

## Grading

Open `results/<version>/grade.md`. Each run shows the goal, what to expect, the agent's reply, the start and end
screens and the actions. Write `pass` or `fail` after `Grade:`, then why. Leave a run ungraded to leave it out.

`eval/ev report [versions]` rebuilds the sheets (keeping the grades), prints each version's pass rate and per-task
numbers, and writes `results/report.html`, where you pick two versions or model setups to compare side by side.
The report's thumbnails link to the screenshots next to it, so keep it in `results/`.

## Settings and repeated trials

`result.json` records requested agents in `settings.requested_agents` and effective models and efforts in `settings.agents`. The HTML report also uses the readable `model` field. Screenshot pruning settings (`settings.screenshots`, `keep`/`every`) are read from constants in the saved source without executing it. Missing constants are recorded as unknown; runtime defaults stay unchanged.

The terminal report groups **all trials** by source, effective models and efforts, pruning settings, language, step limit and approval mode. Each group shows:

- Pass/graded, ungraded and not-started counts, plus task endings.
- Main/subagent calls (`M/S`) and agent cost across all started trials.
- Per-task p50/p95 duration for successful runs. Failed and ungraded timings remain in individual results. Small-sample p95 is descriptive, not a reliable tail estimate.

Infeasible tasks are graded separately. Use terminal groups for repeated A/B comparisons; the HTML compares the latest trials for diagnosis.

Usage totals come from the exported end event, counted once per agent and model. Reasoning tokens are included in output; cache-read ratios are weighted by input tokens. Title costs are shown separately.

Missing usage and interrupted calls stay unknown: `?` means unknown, and `0.01200+?1` means a known subtotal plus one unknown trial. Older records use available export metrics and mark missing settings as `legacy` or `unknown`. Generating a report never rewrites exports or results.

Reports read each result and trajectory once, then share compact summaries between the grading sheet and HTML. Statistics skip screenshot decoding and do not cache full conversations. Run offline regression checks in the runtime test environment:

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
