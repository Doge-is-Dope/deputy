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
└── .github/workflows/        # CI checks and image builds
```

## Requirements

- Docker Compose, an OpenAI API key and a Windows PC with Remote Desktop ([details](runtime/README.md#requirements))
- For development: Node.js 24, Bun 1.4.4 and uv

## Quick start

Download `deploy.tar.gz` from the [latest release](../../releases/latest), unpack it, and start the stack:

```bash
tar -xzf deploy.tar.gz && cd deputy
cp .env.example .env   # set OPENAI_API_KEY, RDP_HOST, RDP_USER, RDP_PASSWORD, MONGO_ROOT_PASSWORD, MONGO_RUNTIME_PASSWORD
docker compose up -d
```

It pulls that version's images; no build or source is needed. To upgrade, unpack the next release's bundle over it and run `docker compose up -d` again. From a clone, build the same stack instead as described in [runtime setup](runtime/README.md#setup).

Open <http://localhost:8080> and send a task. Or send it from a terminal with the [CLI](clients/cli/README.md):

```bash
uv run --project clients/cli computer-use run "<goal>"
```

## Documentation

- [Runtime](runtime/README.md): setup, agents, API and tests
- [CLI](clients/cli/README.md): the command line
- [Web](clients/web/README.md): front-end development
- [Evaluation](eval/README.md): Windows tasks and result comparisons
