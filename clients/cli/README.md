# computer-use CLI

Control the runtime from any machine that can reach its HTTP API. The CLI needs Python 3.11 or later, with no additional packages or access to runtime files.

## Usage

From the repository root, with the runtime up ([runtime setup](../../runtime/README.md#setup)):

```bash
uv run --project clients/cli computer-use run "<goal>"                    # send the desktop a goal and follow the run
uv run --project clients/cli computer-use run "<next goal>" --thread RUN  # continue the conversation containing RUN
uv run --project clients/cli computer-use run "<goal>" --project eval     # list the conversation under eval
uv run --project clients/cli computer-use resume [RUN]                    # send a run's message again (default: the latest)
uv run --project clients/cli computer-use observe [--out FILE]            # save a screenshot of the desktop
uv run --project clients/cli computer-use takeover / return               # take over the desktop / hand it back
uv run --project clients/cli computer-use approve / reject [--message …]  # answer the step waiting for your approval
uv run --project clients/cli computer-use status [--idle]                 # who has the desktop, which runs are going
uv run --project clients/cli computer-use agents                          # the agents at work, by the id stop takes
uv run --project clients/cli computer-use stop ID                         # stop one agent; the others go on
uv run --project clients/cli computer-use export RUN FOLDER               # save a session's records and screenshots
```

To have `computer-use` on your path instead, run `uv tool install ./clients/cli`.

Use `--max-steps N` to limit a run, and `--main MODEL [EFFORT]` or `--computer MODEL [EFFORT]` to choose models. Both `run` and `resume` accept these options. The API defaults to `http://127.0.0.1:8000`; override it with `--api` or `CU_API_URL`.

`run` follows the session the message starts until it is quiet: the steps of each turn and each task as they
happen, a line as each task ends, then the main agent's last reply (`Agent:`), how the last desktop task ended
(`Desktop:`) and the run's id (`Run:`). Ctrl-C stops the whole session, its reply and every task; a second Ctrl-C
leaves without waiting for it to end. `export` writes each of the session's records, its turns' and its tasks', to a
folder of its own.
Its exit codes are:

- `0`: the computer-use agent replied.
- `2`: the task ended another way, the desktop was not used, or the runtime turned the message away.
- `130`: the run was stopped.

`status --idle` exits `1` while a run is going, you have control of the desktop, or remote lease synchronization is pending, so a restart can wait on it:
`computer-use status --idle && docker compose up -d --build`.

## Development

```bash
cd clients/cli
uv run --frozen pytest   # no test opens a socket: a fake API answers every request
```

The [eval](../../eval/README.md) uses the same API client, `src/computer_use_cli/client.py`.
