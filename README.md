# Computer Use

An AI agent that controls Windows over Remote Desktop (RDP) using screenshots, mouse and keyboard input. Watch live or take over at any time. The runtime runs in Docker; Windows needs no agent installed.

Desktop control and takeover have been tested; full web-flow acceptance testing is pending.

![Architecture](diagrams/architecture.svg)

## Repository structure

```text
computer-use/
├── runtime/                  # Python runtime: agents, HTTP API and its Docker stack
├── code-runner/              # Isolated code execution container
├── clients/                  # Clients of the runtime's HTTP API
│   ├── web/                  # React UI: conversations, live view and takeover
│   └── cli/                  # Command line
├── eval/                     # Windows evaluation tasks and reports
├── diagrams/                 # Architecture diagrams
└── .github/workflows/        # CI checks
```

## Requirements

- Docker Compose, an OpenAI API key and a Windows PC with Remote Desktop ([details](runtime/README.md#requirements))
- Node.js 24, Bun 1.4.4 and uv for the web UI and the CLI

## Quick start

Configure and start the runtime as described in [runtime setup](runtime/README.md#setup).

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

- [Runtime](runtime/README.md): setup, agents, API and tests
- [CLI](clients/cli/README.md): the command line
- [Web](clients/web/README.md): front-end development
- [Evaluation](eval/README.md): Windows tasks and result comparisons
