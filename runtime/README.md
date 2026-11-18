# computer-use runtime

The runtime runs the agents, controls the Windows desktop and serves the HTTP API. To start the web UI or CLI, see the [main README](../README.md#quick-start).

## Design

![Runtime architecture](../diagrams/runtime.svg)

The API server and the agents reach everything outside the runtime through six interfaces. Each backend is chosen in the settings and can be swapped without touching the rest:

| Interface | Backend | Options |
| --- | --- | --- |
| Sign-in | — | none, token or proxy ([Sign-in](#sign-in)) |
| Run store | Database | MongoDB, or files under `CU_DATA_DIR` when `CU_DATABASE_URL` is empty |
| File store | Data volume | local files |
| Models | Model APIs | OpenAI or Anthropic models |
| Code runner | Code sandbox | the code-runner container, over a Unix socket |
| Computer | Windows VM | RDP |

## How it works

- **Agents.** The main agent answers, or starts background tasks (up to six, one on the desktop): `computer` uses the mouse and keyboard, `coding` runs code in the code runner, which has no network and no access to Windows.
- **Windows Tools** (optional). The desktop agent can also run PowerShell with `run_command`. A running command stops when the user takes the desktop.
- **Takeover.** The user takes the desktop from the web live view or `computer-use takeover`; the agent asks for it for passwords, CAPTCHAs, administrator prompts and payments.
- **Approvals.** A step the agent flags waits for the user's approval; **Settings → Permissions** can send it to an auto reviewer first.
- **Models.** Defaults come from `.env` (`CU_MAIN_MODEL`, `CU_COMPUTER_MODEL`); **Settings → Model** overrides them.

## Setup

### Requirements

- Docker Compose (and [uv](https://docs.astral.sh/uv/) for development)
- An OpenAI API key for the default models, and an Anthropic API key (`ANTHROPIC_API_KEY`) for the Claude models
- Windows Pro or Enterprise with Remote Desktop enabled and a dedicated standard account in **Remote Desktop Users**, with English (US) as its keyboard

### Start the stack

```bash
cp .env.example .env   # set OPENAI_API_KEY, RDP_HOST, RDP_USER, RDP_PASSWORD, MONGO_ROOT_PASSWORD, MONGO_RUNTIME_PASSWORD
docker compose up -d --build
```

The web page is at <http://localhost:8080> and the API at <http://localhost:8000>. Everything listens on 127.0.0.1; to open the page from other machines, set `CU_BIND`, `CU_TURN_URL`, `CU_WEB_URL` and `CU_AUTH=token` in `.env`.

- **RDP sign-in refused:** the runtime stops trying, so the account is not locked. Fix `.env` and run `docker compose up -d runtime`.
- **RDP certificate changed on purpose:** run `docker compose down` and `docker volume rm computer-use_rdp-certs`.

### Windows machine

Optional: Windows Tools v0.3.1, for `run_command`.

1. On Windows, as the RDP account, run its `install-windows-tools.cmd` while no task runs and the live view is closed: the line it prints is the key to that computer.
2. Put that line in `.env` as `WINDOWS_TOOLS_URL`.
3. Run `docker compose up -d runtime`.

**Settings → Desktop** shows whether it answers. With no **Windows commands** row there, the runtime has no URL: check `.env` and run step 3 again. To update, run the new release's installer: the line stays the same.

Also optional: Python with pypdf and openpyxl, for PDFs and spreadsheets. On Windows, as the RDP account:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File windows-setup.ps1
```

### Sign-in

`CU_AUTH` selects it: `none` (default, loopback only), `token` (`CU_AUTH_TOKEN`, generated if unset) or `proxy` (trusts `CU_AUTH_HEADER` from `CU_AUTH_PROXIES`). Each user sees only their own records.

## Layout

```text
runtime/
├── src/computer_use/
│   ├── server.py         # The HTTP API's routes
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
│   ├── files/            # The file store: screenshots and attachments
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

For tracing, set `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` in `.env`.
