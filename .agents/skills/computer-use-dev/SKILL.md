---
name: computer-use-dev
description: Investigate and change the computer-use repository across runtime, web, CLI and eval. Use for non-trivial features, bug fixes, performance work, refactors, prompt or model changes, and architecture questions in this repository.
---

# Working on computer-use

Read the matching playbook only. Repository paths below are relative to the repository root; playbook and
script links
are relative to this skill. Use this alongside any applicable AGENTS.md and the user's current instructions.

## The system

The runtime (`runtime/`, Python in Docker) runs the agents and serves the HTTP API on port 8000. It drives one
Windows
desktop over RDP, and one run uses the desktop at a time (`RunLock`); conversations without the desktop run in
parallel. The web page (`clients/web/`, React, bun) and the CLI (`clients/cli/`, stdlib only) are clients of
that API
and nothing else. The eval (`eval/`) serves the version under test on port 8001 beside the main server and
drives it
through the CLI's client. Each area's README has its layout table; read it before editing the area.

| You changed | Check | See it on the real surface |
|---|---|---|
| `runtime/src/` | `scripts/check runtime` | `eval/ev serve` (replaces an idle server on 8001), then the CLI or the web page with `CU_API_URL=http://127.0.0.1:8001` |
| `runtime/src/computer_use/prompts/` | `scripts/check runtime` | an eval A/B ([prompt-or-model-change](playbooks/prompt-or-model-change.md)) |
| `clients/web/` | `scripts/check web` | the `web` dev server using an available browser tool; the `design-system` skill for sizes and icons |
| `clients/cli/` | `scripts/check cli` | `uv run --project clients/cli computer-use …` against 8000 or 8001 |
| `eval/` | `scripts/check runtime` (`test_eval.py`) | `eval/ev tasks`, `eval/ev report` |

`scripts/check` means `.agents/skills/computer-use-dev/scripts/check`, run from the repository root. It selects
checks from the diff since the merge base with `main`, including untracked files. Use an explicit area, `--all` or
`--base REF` when that better matches the scope. It does not run dependency audits or the secret scan.

## Rules

- **Say the goal first.** Your first message restates the goal and the smallest change you expect to meet it.
  Do not
  wait for confirmation. If the evidence rules out the change asked for, show it and stop.
- **Subtract before you add.** Ask what can be removed or merged first; choose the smallest change that covers
  the observed
  cases. Handle an edge case when evidence or an existing contract requires it. Keep a seam when it names a
  real boundary
  (the ports in `adapters.py`, tools grouped by what they act on); drop one with one caller and nothing to vary.
- **Smaller, never harder to read.** Subtraction stops where readability or extensibility would suffer: do not
  inline
  a named idea into a long function, merge two things that change for different reasons, or shorten code into
  cleverness. Names say what a thing is; one function does one job. The next case extends through an existing entry
  point by adding an entry, not a branch: a port's adapter in `adapters.py`, a tool module in `tools/`, a
  command in
  the CLI's `COMMANDS`, a settings page in `PAGES`.
- **Follow the major products.** Before changing the agent loop, the prompts or runtime behaviour, check how
  OpenAI,
  Anthropic and LangChain do it and cite them. When they agree, follow them; when we differ, say why. Do not
  build a
  general mechanism for a case only we have.
- **Stay generic.** No prompt rule that fixes one eval task. No setting or code path for one model provider.
  Hardcode a
  measured default; add a setting only when a real deployment needs to change it. User choices live in the
  client and
  are sent with each run.
- **Name the data first.** Before logic, name the data shape and the one place it lives. A change to the event
  record
  spans `runtime/src/computer_use/events.py` (and `storage.FORMAT`), `clients/web/src/lib/api.ts` and `thread.ts`,
  `clients/cli/src/computer_use_cli/render.py` and `eval/html_report.py`; `tests/unit/test_event_contract.py`
  pins it.
- **Prove it on the real surface.** Tests prove branches, not that it works. A change is done when you have seen it
  on its surface (table above). "Inconclusive" or the wrong surface is not a pass; say so.
- **Explain the number.** Before reporting a speedup or an eval result, find what limits it and rule out that it
  measured something else. See the [perf](playbooks/perf.md) playbook.
- **The desktop and the checkout are shared.** Before anything that types on the desktop, restarts or rebuilds the
  runtime, run `uv run --project clients/cli computer-use status --idle` and stop if it fails. Never send
  input while
  the user has control. Other sessions may share this checkout: before committing, run `git branch --show-current`
  and `git log --oneline main..HEAD`, and stage only your own files.
- **Unit tests stay offline**, loopback included (the `no_network` fixtures enforce it). Fake the transport and
  the clock. The explicitly marked `model` and `mongo` tests are exceptions; the default runtime checks
  exclude both.
  Setting `CU_TEST_MONGO_URL` enables the MongoDB contract tests, which create and drop temporary databases.
- **Code reads like its neighbours.** Imports at the top of the module (break a cycle by moving code, as
  `adapters.py` does). Comments are short, give the why, and name no product. Docs and names describe the code, not
  the change that made it. No compatibility code for old conversations: bump `storage.FORMAT` instead.
- **The repository is public.** No personal or machine details (hosts, accounts, addresses, installed software,
  employer) in code, docs or commit messages.

## Autonomy

Go ahead with reversible work: edits, tests, branches, local servers, `eval/ev serve`.

Require authorization for commits, merges, pushes, container rebuilds or restarts, eval runs (they change the
Windows
machine and spend API money), desktop input and data deletion. An explicit request or earlier authorization in the
current session is sufficient within its scope; ask only for an action outside that scope. Complete independent
preparation and checks before asking. Never `rm -rf` under `runtime/data`; move things to `runtime/data/trash`.

When asked whether to do something, give your real judgment. "This does not earn its place" is a valid answer.

## Playbooks

Use the matching playbook to guide the work. Keep a short plan for multi-step work and adapt it to the task;
explain a skipped validation when it affects confidence. Simple edits do not need a copied checklist.

- [Investigation](playbooks/investigation.md): a read-only question. How does X work, why is Y so, should we
  do X or Y.
- [Bug fix](playbooks/bug-fix.md): reproduce a defect, find the root cause, fix it with evidence.
- [Feature](playbooks/feature.md): new or changed behaviour, from a named data shape. UI work starts from mockups.
- [Refactor](playbooks/refactor.md): change structure, keep behaviour.
- [Perf](playbooks/perf.md): a measured slowness, improved against a baseline.
- [Prompt or model change](playbooks/prompt-or-model-change.md): change what the agents are told or which model
  runs, judged by an eval A/B.
- [Ship](playbooks/ship.md): check, commit, merge to main and bring the container up to date. Ends every playbook
  that changes code, when the user asks for it.

## The reply

Short declarative sentences. Lead with what changed for the user of the product, then what the next maintainer
inherits. Every claim carries its evidence (a command's output, a file and line, a number with how it was measured)
or says it is a guess. Never hand the user a check you could run yourself.
