# computer-use runtime

This directory contains the Python agents, desktop control and HTTP API. For setup and your first task, see the [main README](../README.md#quick-start).

![Runtime: the web UI and the CLI reach it through sign-in and the API server, whose agents keep each user's runs in the run store, operate the Windows VM through the computer and run code in the sandbox through the code runner](../diagrams/runtime.svg)

The agents call the model APIs and log each run through the run store (`storage/`), which keeps it in `data/runs/<time>/steps.jsonl` with its screenshots beside it.

## Development

Use [uv](https://docs.astral.sh/uv/) for local development. It installs the Python 3.15 version specified in `.python-version`.

```bash
cd runtime
uv sync --frozen
uv run pytest           # deterministic tests with a fake screen, no model calls
uv run pytest -m model  # calls real models with the API key in .env
```

Dependencies are pinned in `pyproject.toml` and locked in `uv.lock`. To upgrade, update the pins, regenerate the lockfile and run both test suites.

Every client reaches the runtime through its [HTTP API](#http-api): the web page, the [CLI](../clients/cli/README.md) and the [eval](../eval/README.md). Only the API's server runs agents.

## How it works

**Agents.** The main agent (`agent/main_agent.py`) answers directly or delegates background tasks, up to six at once, only one of them on the computer:

- `computer_use` operates Windows with mouse and keyboard input (`agent/computer_agent.py`).
- `write_code` runs code in a separate container with no network, secrets or access to Windows or runtime files (`agent/coding_agent.py`, `../code-runner/`).

Each delegated task gets its own context: a brief, the user's original messages and a short conversation history. The main agent checks desktop results against the actions taken and a fresh screenshot. A message that mentions `@Computer` comes with a note to hand it to the desktop agent, and the runtime hands it over itself if the main agent does not. Shared task behavior lives in `agent/subagent.py`.

**Prompts** (`prompts/`). Everything the runtime tells its agents in its own words lives here: system prompts, what the main agent is told about each agent, and the runtime's notes, refusals and task reports. Tool definitions stay with their tools, and what the desktop or the code runner reports about an action stays with them. The [eval](../eval/README.md#versions-and-prompts) names a version's prompts by this folder's contents, so change wording here.

**Plans and limits.** For work with three or more distinct steps, the main agent keeps a visible plan through `write_todos` and updates it before delegating. It hands each plan step, or each message without a plan, over at most twice; rounds handed over while earlier tasks still run do not count, so work spread past six tasks at once is not refused. Each task has an ID used by `tell_task`, `stop_task` and its log events. Tool calls from the same reply run concurrently.

**Models and choices.** Defaults come from `.env`: `CU_MAIN_MODEL`/`CU_MAIN_EFFORT` for the main agent and `CU_MODEL`/`CU_EFFORT` for the desktop agent. Use **Settings → Model** to override an agent's model and reasoning effort. Available models are defined in `agent/models.py`. Subagents can inherit the main agent's choices.

The client keeps choices and sends `agents`, `approvals` and `locale` with each message to `POST /api/runs`; the CLI sends the models given with `--main` and `--computer`. Model changes apply to the next run; approval changes apply to the next flagged step. The desktop agent uses the UI language, or the user's message language when the client sends none. Without `approvals`, every flagged step asks.

**Task endings.** `replied` means the agent replied. Other outcomes are `step_limit`, `stuck` (repeated identical actions left the screen unchanged), `disconnected` (the desktop did not reconnect within 60 seconds), `declined` (three declined steps) or `error`. The main agent explains the outcome in its reply.

**History.** A conversation's runs share a thread named after its first run's folder. Each run stores model messages, events and screenshots under `data/runs/<time>/`; `steps.jsonl` restores the main conversation for later runs. An interrupted handover is recorded as "result unknown" and is not automatically resent.

**Sign-in** (`auth/`). `CU_AUTH` picks how a request proves who sent it; the runtime keeps no session. `none` (default) needs nothing and serves only the loopback address unless set explicitly, as `compose.yaml` does for its 127.0.0.1 ports. `token` takes `CU_AUTH_TOKEN` (made anew each start when unset) as a bearer token or a cookie; the runtime prints a sign-in link (`#token=…`) that signs the page in, and the CLI sends the same variable. `proxy` believes a sign-in proxy's `CU_AUTH_HEADER` from the networks in `CU_AUTH_PROXIES` only. Another way plugs in as an `Authenticator` (`auth/base.py`), which brings its own sign-in routes; an `Identity` has a path-safe `id` and a `name` to show. Browser requests that change something are accepted only from the page's own origin. Each run records its user's id in its `start` event; the list, search, the agent's `search_conversations` and every route on a run or conversation see only the asker's (another user's is a 404). The desktop is still one, shared.

**Search.** `GET /api/search?q=` finds conversations by what the user and the main agent said in them (`RunStore.search`): one hit per conversation with the words around the match, most recently active first, by reading the logs; there is no index. The web page matches names itself and merges the two (⌘K). The main agent's `search_conversations` tool runs the same search over the user's other conversations, as Claude desktop's `search_session_transcripts` does.

**Takeover.** Use the web live view or `computer-use takeover` to take control. The agent sends no input during takeover and observes a fresh screen after control returns. It requests takeover for passwords, CAPTCHAs, administrator prompts and payment details. The runtime enforces ownership for both agent and live-view input.

**Text input.** Both the agent and live view send text through the RDP Unicode keyboard pipe. Select English (US) in the Windows session so an active Chinese IME does not intercept punctuation; Chinese text and emoji still arrive as Unicode. Typing leaves the clipboard untouched. Clipboard redirection remains available for manual copy/paste and eval setup.

**Approvals** (`agent/confirm.py`). Flagged actions wait for approval, rejection with an optional reason, or takeover. The web composer uses Enter to approve and Esc to decline; the CLI uses `approve` and `reject`. Silence never approves.

**Auto review** (`agent/review.py`). Settings → Permissions can send flagged steps to a reviewer first. It allows only low- or medium-risk actions covered by the user's words. High-risk or unclear actions, and failed or timed-out reviews, still go to the user. For deletes and overwrites, the reviewer's target must occur verbatim in user messages or sent action input; this check alone does not prove authorization or target identity.

**Input restrictions.** The desktop agent has screen, mouse and keyboard tools. Run, Command Prompt and PowerShell are allowed; system shortcuts such as Win+X, Ctrl+Shift+Esc and Ctrl+Alt+Delete, and typing `regedit` or `taskmgr`, are blocked.

## Diagnostics

**LangSmith.** Tracing is off by default. To enable it, set `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` in `.env`, then rebuild. `LANGSMITH_PROJECT` selects the project. Model-call traces retain full conversation text; screenshots and encrypted reasoning are omitted.

**Event delivery.** Each viewer has an ordered, bounded queue. Overflow disconnects it so it can reconnect from its durable event cursor and current draft snapshot. An event-count boundary keeps durable events and queued text in order, including across renames. A run this server does not run, such as one of the eval's server, streams what it has logged so far, then ends.

## HTTP API

Compose starts the API at <http://localhost:8000>. To run it outside the container (desktop actions still need an RDP session and an X display):

```bash
uv run computer-use-runtime
```

The API supports runs, server-sent events (SSE), screenshots, the screen now (`GET /api/screen`), stopping, takeover, approvals (`POST /api/approval`) and the live view. `POST /api/live` exchanges the WebRTC offer and answer used to establish the connection. Routes are in [server.py](src/computer_use/server.py).

- **One run at a time on the desktop** (`RunLock`), across every server sharing it, such as the eval's. A message takes the desktop when the main agent first uses it; if another run has it, the main agent is told so and tells the user. A message sent with `"computer": true` or mentioning `@Computer`, as every CLI `run` is, takes it at the start and gets a 409 when it is busy.
- Messages the main agent answers without the desktop never take it, so other conversations go on meanwhile. Each conversation takes one message at a time.
- **Live view:** aiortc sends WebRTC from the runtime. The browser cannot reach the container's internal address, so media goes through coturn in the container (TURN over TCP on `127.0.0.1:3478`, set by `CU_TURN_URL`), with a new password on every start that `/api/status` hands to the page.

## Limitations

- The API and live view have no login and bind only to 127.0.0.1.
- A crash can lose the last log line.
- An action stopped midway is recorded as result unknown; the model may do it again if it cannot tell whether it took effect.
