# Computer Use

An AI agent that controls Windows over Remote Desktop (RDP) using screenshots, mouse and keyboard input. Watch live or take over at any time. The runtime runs in Docker; Windows needs no agent installed.

Desktop control and takeover have been tested; full web-flow acceptance testing is pending. By default the runtime answers only this machine; to reach it from elsewhere, set `CU_AUTH` to a token or a sign-in proxy (see `runtime/.env.example`).

![Architecture](diagrams/architecture.svg)

## Repository structure

```text
computer-use/
├── runtime/                  # Python runtime: agents and the HTTP API
│   ├── src/computer_use/
│   │   ├── agent/            # Main, desktop and coding agents
│   │   ├── prompts/          # Everything the agents are told, versioned by the eval
│   │   ├── desktop/          # Screenshots, input and live view
│   │   ├── computers/        # The Computer port and its RDP backend
│   │   ├── sandbox/          # The CodeRunner port and its HTTP client
│   │   ├── storage/          # The RunStore port and its file backend
│   │   └── serve.py, server.py, config.py
│   ├── tests/                # Unit and model tests
│   └── Dockerfile, compose.yaml
├── code-runner/              # Isolated code execution container
├── clients/                  # Clients of the runtime's HTTP API
│   ├── web/                  # React UI: conversations, live view and takeover
│   └── cli/                  # Command line
├── eval/                     # Windows evaluation tasks and reports
├── diagrams/                 # Architecture diagrams
└── .github/workflows/        # CI checks
```

## Requirements

- Docker Compose, Node.js 24, Bun 1.4.4 and uv
- An OpenAI API key for the default models
- Windows Pro or Enterprise with Remote Desktop enabled and a dedicated standard account in **Remote Desktop Users**

## Quick start

From the repository root, create the configuration:

```bash
cp runtime/.env.example runtime/.env
```

Set `OPENAI_API_KEY`, `RDP_HOST`, `RDP_USER` and `RDP_PASSWORD` in `runtime/.env`, then start the runtime:

```bash
cd runtime
docker compose up -d --build
```

In a new terminal at the repository root, start the web UI:

```bash
cd clients/web
bun install --frozen-lockfile
bun run dev
```

Open <http://localhost:5173> and send a task. Or send it from a terminal with the [CLI](clients/cli/README.md):

```bash
uv run --project clients/cli computer-use run "<goal>"
```

## Documentation

- [Runtime](runtime/README.md): agents, API and tests
- [CLI](clients/cli/README.md): the command line
- [Web](clients/web/README.md): front-end development
- [Evaluation](eval/README.md): Windows tasks and result comparisons
