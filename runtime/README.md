# computer-use runtime

The runtime runs the agents, controls the Windows desktop and serves the HTTP API. To start the web UI or CLI, see the [main README](../README.md#quick-start).

## Design

![Runtime architecture](../diagrams/runtime.svg)

The API server and the agents reach everything outside the runtime through six interfaces, drawn on its edge. Each one's backend is chosen from the settings and can be swapped without touching the rest:

| Interface | Backend | Options |
| --- | --- | --- |
| Sign-in | — | none, token or proxy ([Sign-in](#sign-in)) |
| Run store | Database | MongoDB, or files under `CU_DATA_DIR` when `CU_DATABASE_URL` is empty |
| File store | Data volume | local files |
| Models | Model APIs | OpenAI or Anthropic models |
| Code runner | Code sandbox | the code-runner container, over a Unix socket |
| Computer | Windows VM | RDP |

## Setup

### Requirements

- Docker Compose (and [uv](https://docs.astral.sh/uv/) for development)
- An OpenAI API key for the default models
- Windows Pro or Enterprise with Remote Desktop enabled and a dedicated standard account in **Remote Desktop Users**, with English (US) as its keyboard

### Start the stack

```bash
cp .env.example .env   # set OPENAI_API_KEY, RDP_HOST, RDP_USER, RDP_PASSWORD, MONGO_ROOT_PASSWORD, MONGO_RUNTIME_PASSWORD
docker compose up -d --build
```

The web page is at <http://localhost:8080> and the API at <http://localhost:8000>. Everything listens on 127.0.0.1; to open the page from other machines, set `CU_BIND`, `CU_TURN_URL`, `CU_WEB_URL` and `CU_AUTH=token` in `.env`.

If Windows refuses the RDP sign-in, the runtime stops trying so the account is not locked: fix `.env` and run `docker compose up -d runtime`. After a legitimate change of the PC's RDP certificate, run `docker compose down` and `docker volume rm computer-use_rdp-certs`.

### Windows machine

Optional: the Windows Tools host, for the agent's `run_command`, and Python with pypdf and openpyxl, which those commands use for PDFs and spreadsheets. [windows-setup.ps1](windows-setup.ps1) installs both; run it on Windows as the RDP account, then set `WINDOWS_TOOLS_PATH` in `.env`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File windows-setup.ps1 -HostProgram .\windows-tools-host.exe
```

## Layout

```text
runtime/
├── src/computer_use/
│   ├── agent/            # Main, desktop and coding agents
│   ├── tools/            # What agents call
│   ├── middleware/       # What runs around model and tool calls
│   ├── prompts/          # Everything the agents are told
│   ├── skills/           # Instructions an agent reads when needed, a folder for each agent
│   ├── desktop/          # Screenshots, input and live view
│   ├── computers/        # The desktop port and its RDP backend
│   ├── native/           # Commands on Windows through the Windows Tools host
│   ├── sandbox/          # The code runner client
│   ├── storage/          # The run store: files or MongoDB
│   ├── memory/           # What the agent remembers for each user
│   └── auth/             # Sign-in methods
├── tests/
└── Dockerfile, compose.yaml, windows-setup.ps1
```

## Development

```bash
uv sync --frozen
uv run pytest           # fake screen, no model calls
uv run pytest -m model  # real models, with the API key in .env
```

The store tests also run on MongoDB:

```bash
docker run -d --name cu-mongo-dev --ulimit nofile=64000:64000 -p 127.0.0.1:27017:27017 mongo:8.3.13 --replSet rs0
until docker exec cu-mongo-dev mongosh --quiet --eval 'try { rs.status() } catch (e) { rs.initiate({_id: "rs0", members: [{_id: 0, host: "localhost:27017"}]}) }'; do sleep 1; done
CU_TEST_MONGO_URL="mongodb://localhost:27017/?replicaSet=rs0" uv run pytest -m mongo
```

## How it works

- **Agents.** The main agent answers, or hands work to background tasks (up to six, one on the desktop): `computer` operates Windows by mouse and keyboard, `coding` runs code in the code runner, a container with no network or access to Windows.
- **Windows Tools** (optional). The desktop agent can also run PowerShell on Windows with `run_command`; the runtime starts the host there by itself before a desktop task.
- **Takeover.** The user can take the desktop from the web live view or `computer-use takeover`; the agent asks for it for passwords, CAPTCHAs, administrator prompts and payments.
- **Approvals.** A flagged step waits for the user's approval; **Settings → Permissions** can send it to an auto reviewer first.
- **Models.** Defaults come from `.env` (`CU_MAIN_MODEL`, `CU_COMPUTER_MODEL`); **Settings → Model** overrides them.

## Sign-in

`CU_AUTH` selects it: `none` (default, loopback only), `token` (`CU_AUTH_TOKEN`, generated if unset) or `proxy` (trusts `CU_AUTH_HEADER` from `CU_AUTH_PROXIES`). Each user sees only their own records.

## HTTP API

Routes are in [server.py](src/computer_use/server.py). Conversations run in parallel; one desktop task runs at a time. For tracing, set `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` in `.env`.
