# computer-use CLI

The command line for the runtime. Like the web page, it only talks to the runtime's HTTP API: it never imports the
runtime's code or reads its files, so it runs on any machine that can reach the API. It needs only Python 3.11 or
later, with no other packages.

## Usage

From the repository root, with the runtime up ([main README](../../README.md#quick-start)):

```bash
uv run --project clients/cli computer-use run "<goal>"                    # send the desktop a goal and follow the run
uv run --project clients/cli computer-use run "<next goal>" --thread RUN  # continue the conversation containing RUN
uv run --project clients/cli computer-use run "<goal>" --project eval     # list the conversation under eval
uv run --project clients/cli computer-use resume [RUN]                    # send a run's message again (default: the latest)
uv run --project clients/cli computer-use observe [--out FILE]            # save a screenshot of the desktop
uv run --project clients/cli computer-use takeover / return               # take over the desktop / hand it back
uv run --project clients/cli computer-use approve / reject [--message …]  # answer the step waiting for your approval
uv run --project clients/cli computer-use status                          # who has the desktop, which runs are going
uv run --project clients/cli computer-use export RUN FOLDER               # save a run's record and screenshots
```

To have `computer-use` on your path instead, run `uv tool install ./clients/cli`.

`run` and `resume` take `--max-steps N`, and `--main MODEL [EFFORT]` and `--computer MODEL [EFFORT]` to choose the
agents' models for that run. The API is `http://127.0.0.1:8000` unless `--api` or `CU_API_URL` says otherwise.

`run` shows the run's steps as they happen, then the main agent's reply (`Agent:`), how the last desktop task ended
(`Desktop:`) and the run's id (`Run:`). Ctrl-C stops the run; a second Ctrl-C leaves without waiting for it to end.
Its exit codes are:

- `0`: the computer-use agent replied.
- `2`: the task ended another way, the desktop was not used, or the runtime turned the message away.
- `130`: the run was stopped.

## Development

```bash
cd clients/cli
uv run --frozen pytest   # no test opens a socket: a fake API answers every request
```

The client in `src/computer_use_cli/client.py` is also what the [eval](../../eval/README.md) drives the runtime with.
