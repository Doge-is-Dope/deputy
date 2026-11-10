# computer-use runtime

The runtime runs the agents, controls the desktop and serves the HTTP API. This directory also holds its Docker stack. To start the web UI or CLI, see the [main README](../README.md#quick-start).

![Runtime architecture](../diagrams/runtime.svg)

## Setup

### Requirements

- Docker Compose (and [uv](https://docs.astral.sh/uv/) for development)
- An OpenAI API key for the default models
- Windows Pro or Enterprise with Remote Desktop enabled and a dedicated standard account in **Remote Desktop Users**. Select English (US) as its keyboard, so a Chinese IME does not catch punctuation.

### Start the stack

From this directory:

```bash
cp .env.example .env   # set OPENAI_API_KEY, RDP_HOST, RDP_USER, RDP_PASSWORD, MONGO_ROOT_PASSWORD, MONGO_RUNTIME_PASSWORD
docker compose up -d --build
```

Compose starts the web page at <http://localhost:8080>, the runtime's API at <http://localhost:8000>, the code runner and MongoDB. Screenshots are kept in `data/`; deleting a conversation removes its records for good.

Everything listens on 127.0.0.1. To open the page from other machines, set `CU_BIND`, `CU_TURN_URL` and `CU_WEB_URL` in `.env` with `CU_AUTH=token`; the API stays on this machine and other machines reach it through the page's `/api`. A sign-in proxy (`CU_AUTH=proxy`) must front the runtime directly, since behind the web service every request comes from it.

The runtime trusts the PC's RDP certificate on first use. After a legitimate certificate change, run `docker compose down` and `docker volume rm computer-use_rdp-certs`.

## Layout

```text
runtime/
├── src/computer_use/
│   ├── agent/            # Main, desktop and coding agents; sessions; hand-overs
│   ├── tools/            # What agents call: desktop, code runner, conversation and task tools
│   ├── middleware/       # What runs around agents' model and tool calls
│   ├── execution/        # A desktop task put together; approvals
│   ├── prompts/          # Everything the agents are told, versioned by the eval
│   ├── desktop/          # Screenshots, input, live view and their routes
│   ├── computers/        # The Computer port and its RDP backend
│   ├── sandbox/          # The CodeRunner port and its HTTP client
│   ├── storage/          # The run store: files or MongoDB
│   ├── files/            # Where screenshots are kept
│   ├── memory/           # What the agent remembers for each user
│   ├── auth/             # Sign-in methods
│   └── serve.py, server.py, routes.py, config.py, adapters.py (which adapter serves each port)
├── tests/
├── mongo/                # The MongoDB container's start-up scripts
└── Dockerfile, compose.yaml, entrypoint.sh, rdp-entrypoint.sh
```

## Development

```bash
uv sync --frozen
uv run pytest           # fake screen, no model calls
uv run pytest -m model  # real models, with the API key in .env
```

The store tests also run on MongoDB, against a one-member replica set:

```bash
docker run -d --name cu-mongo-dev --ulimit nofile=64000:64000 -p 127.0.0.1:27017:27017 mongo:8.3.13 --replSet rs0
until docker exec cu-mongo-dev mongosh --quiet --eval 'try { rs.status() } catch (e) { rs.initiate({_id: "rs0", members: [{_id: 0, host: "localhost:27017"}]}) }'; do sleep 1; done
CU_TEST_MONGO_URL="mongodb://localhost:27017/?replicaSet=rs0" uv run pytest -m mongo
```

Dependencies are pinned in `pyproject.toml` and locked in `uv.lock`; after an upgrade, run both suites.

## How it works

- **Agents.** The main agent (`agent/main_agent.py`) answers, or hands work to background tasks with `start_task`: up to six at once, one of them on the desktop. `computer` operates Windows by mouse and keyboard; `coding` runs code in a container with no network, secrets or access to Windows. The main agent checks desktop results against the action log and a fresh screenshot. `@Computer` in a message sends it to the desktop agent.
- **Core.** Sessions, tasks and the log load nothing of the desktop, the code runner or memory (`tests/unit/test_layers.py`): a hand-over asks a `Resource`, a message may name an agent by a `Mention`, and a session asks a `SessionMemory`. `agent/main_agent.py` puts them together for a run.
- **Sessions** (`agent/session.py`). A message starts a session, which lasts until nothing is at work. Each main-agent turn and each task logs its own record. User messages and task endings wake the main agent; a failed task is reported to it with the error.
- **Questions** (`tools/ask_user.py`). The main agent asks with `ask_user`: a card in the conversation, with up to four options (its recommendation first, or several to choose from) or none for an answer to type. The call ends its turn; the user's next message, chosen on the card or typed in the composer, is the answer.
- **Plan** (`agent/plan.py`, `agent/blackboard.py`, `tools/plan.py`). The main agent writes what it intends to do with `write_plan`, the whole list each time, and `start_task` may name the steps a task carries out. The runtime checks only the list's shape: nothing holds a step back or refuses a hand-over. Agents report steps done with `finish_step`; when a task ends, the main agent hears which steps are neither done nor being worked on. A task's agent starts with the plan and the other tasks at work, can read them again with `read_blackboard`, and can put a question to the main agent with `ask`, which waits until it is answered. Each change is logged as a whole snapshot; the page and the next session take the highest version.
- **Prompts** (`prompts/`). Everything the agents are told. The [eval](../eval/README.md#versions-and-prompts) tracks this folder to tell prompt changes apart.
- **Skills** (`middleware/skills.py`). An agent carrying `SkillsMiddleware` has the skills in `skills/shared/` and in `skills/<agent>/`: its system prompt lists each one's name and description, and `read_skill` reads one when its work calls for it. All three agents carry it; no skills ship yet.
- **Models.** Defaults come from `.env` (`CU_MAIN_MODEL`, `CU_COMPUTER_MODEL` and their `_EFFORT`); **Settings → Model** overrides them per agent, the CLI with `--main` and `--computer`. Models are listed, with their prices, in `agent/usage.py`. A model call whose stream fails partway is retried up to five times.
- **Storage.** `CU_DATABASE_URL` picks MongoDB (Compose's default) or, when empty, files under `CU_DATA_DIR`. If a crash leaves MongoDB's summaries out of step with its events, rebuild them with the runtime stopped: `docker compose run --rm runtime python -m computer_use.storage.rebuild`.
- **Desktop backend.** `computers.Computer` is the desktop port; `adapters.build_computer` picks the backend, RDP for now. Backends return lossless, cursor-free images, raise `ComputerError` for failed or uncertain input and never replay input.
- **Screen judge** (`desktop/judge.py`). A fast yes or no about screens, with no call to the agent's model: `press_while` asks it before each press, and a key the stale-screen check holds back is sent when it finds only animation changed. `adapters.build_screen_judge` picks OpenAI's Decisions API when `OPENAI_API_KEY` is set; without a judge, `press_while` is not offered and such keys are refused.
- **Takeover.** Use the web live view or `computer-use takeover`. The agent sends no input meanwhile, and looks at a fresh screen once control is back. It asks for a takeover for passwords, CAPTCHAs, administrator prompts and payments. If the desktop connection is lost, the agent waits for it to come back and carries on; control stays as it was.
- **Approvals** (`execution/approvals.py`). A flagged step waits for approval, a decline with a reason, or a takeover; silence never approves. **Settings → Permissions** can send flagged steps to an auto reviewer first (`agent/review.py`), which lets through only low- or medium-risk steps the user's words cover.
- **Input restrictions.** Run, Command Prompt and PowerShell are allowed; system shortcuts such as Win+X, Ctrl+Shift+Esc and Ctrl+Alt+Delete, and typing `regedit` or `taskmgr`, are blocked.

## Sign-in

`CU_AUTH` selects it:

- `none` (default): no sign-in; the API answers only on loopback, for `localhost`, `127.0.0.1` or `[::1]`.
- `token`: `CU_AUTH_TOKEN` as a bearer token or cookie, generated at startup if unset; the runtime prints a sign-in link.
- `proxy`: trusts `CU_AUTH_HEADER` only from `CU_AUTH_PROXIES`.

Each user sees only their own records. A runtime serves one person and one desktop. To add a method, implement `Authenticator` in `auth/base.py`.

## HTTP API

Routes are in [server.py](src/computer_use/server.py). To run the API outside the container: `uv run computer-use-runtime` (desktop actions still need an RDP session and an X display).

- **Desktop:** one desktop task at a time across all servers (`RunLock`). `"computer": true` or `@Computer` takes the desktop at once, or returns 409.
- **Concurrency:** conversations run in parallel; a message sent while a session works joins it.
- **Stopping:** `POST /api/runs/{id}/stop` stops one turn or task; `POST /api/conversations/{thread}/stop` stops the whole session.
- **Live view:** WebRTC through coturn (`CU_TURN_URL`, TURN over TCP on port 3478, `localhost` by default), with a password made at startup.
- **Tracing:** set `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` in `.env`, then rebuild. Screenshots are left out of traces.

## Limitations

- With the files store, a crash can lose the last log line.
- An action stopped midway is recorded as result unknown; the agent may do it again if it cannot tell whether it took effect.
