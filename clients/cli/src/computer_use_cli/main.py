"""The `computer-use` command: send the desktop a goal, follow its run, and answer it, through the runtime's API."""

import argparse
import struct
import sys
from datetime import datetime
from pathlib import Path

from computer_use_cli import render
from computer_use_cli.client import ApiError, Client

# Default model-call budget per desktop task; --max-steps overrides it.
MAX_STEPS = 60
# Exit codes: the computer-use agent replied; the task ended another way, the desktop was not used, or the command
# could not run; the run was stopped.
REPLIED, OTHER, STOPPED = 0, 2, 130


def choices(main: list[str] | None, computer: list[str] | None) -> dict[str, dict[str, str]] | None:
    """The agents' models and efforts as `--main MODEL [EFFORT]` and `--computer MODEL [EFFORT]` give them."""
    agents = {}
    for agent, spec in (("main", main), ("computer", computer)):
        if spec:
            if len(spec) > 2:
                raise SystemExit(f"--{agent} takes a model and an optional effort, got: {' '.join(spec)}")
            agents[agent] = {"model": spec[0], **({"effort": spec[1]} if len(spec) == 2 else {})}
    return agents or None


def refused(error: ApiError, thread: str | None = None) -> int:
    """Say why a message was not taken."""
    reason, holder = error.body.get("reason"), error.body.get("run")
    if error.status == 409 and reason == "desktop":
        print(f"Not started: another run has the desktop: {holder or 'one that is starting'}. Stop it on the web page, "
              "or wait until it ends.", file=sys.stderr)
    elif error.status == 409 and reason == "conversation":
        print(f"Not started: this conversation has a run in progress: {holder or 'one that is starting'}.",
              file=sys.stderr)
    elif error.status == 404 and thread:
        print(f"Conversation {thread} cannot be continued: it is missing or uses an unsupported log format.",
              file=sys.stderr)
    else:
        print(f"Not started: {error}", file=sys.stderr)
    return OTHER


def follow(client: Client, run: str) -> int:
    """Show a run's events until it ends, then its reply and how its desktop task ended. Ctrl-C stops the run, and
    its end is still shown; a second Ctrl-C leaves without waiting."""
    last, end, stopping = -1, None, False
    while True:
        try:
            done = False
            for event in client.events(run, last):
                if event.kind == "line":
                    last = event.index if event.index is not None else last + 1
                    if (text := render.line(event.data)) is not None:
                        print(text, flush=True)
                    if event.data.get("type") == "end":
                        end = event.data
                elif event.kind == "done":
                    done = True
            if done:
                break
        except KeyboardInterrupt:
            if stopping:
                raise
            stopping = True
            print("\nStopping the run…", file=sys.stderr, flush=True)
            try:
                client.stop(run)
            except ApiError as error:
                if error.status != 409:  # 409: it had ended already
                    raise
    if end is None:
        print(f"\nThe run ended without saying how.\nRun: {run}", file=sys.stderr)
        return OTHER
    if end.get("stop_reason") == "cancelled":
        print(f"\nStopped.\nRun: {run}", file=sys.stderr)
        return STOPPED
    print(f"\nAgent: {end.get('summary', '')}")
    print(f"Desktop: {end.get('computer') or 'not used'}\nRun: {run}")
    return REPLIED if end.get("computer") == "replied" else OTHER


def send(client: Client, goal: str, args: argparse.Namespace, thread: str | None = None, project: str | None = None
         ) -> int:
    """Send a goal to the desktop and follow the run it starts."""
    try:
        started = client.start(
            goal, thread=thread, project=project, max_steps=args.max_steps, computer=True,
            agents=choices(args.main, args.computer),
        )
    except ApiError as error:
        if error.status == 0:
            raise
        return refused(error, thread)
    if "message" in started:
        print(f"Sent to the run in progress, {started['id']}.")
    return follow(client, started["id"])


def cmd_run(client: Client, args: argparse.Namespace) -> int:
    """A goal for the desktop: the main agent always hands it to the computer-use agent, then checks the result."""
    return send(client, args.goal, args, thread=args.thread, project=args.project)


def cmd_resume(client: Client, args: argparse.Namespace) -> int:
    """Send a run's message again, in its conversation: the given run, or the latest."""
    run = args.run or max((each["id"] for each in client.runs()), default=None)
    if run is None:
        print("No runs in the supported log format to continue.", file=sys.stderr)
        return OTHER
    try:
        start = client.start_of(run)
    except (ApiError, StopIteration):
        print(f"{run} cannot be continued: it is missing or uses an unsupported log format.", file=sys.stderr)
        return OTHER
    print(f"Continuing {run} in its conversation {start['thread']}.")
    return send(client, start["goal"], args, thread=start["thread"])


def png_size(png: bytes) -> tuple[int, int]:
    """A PNG's width and height, from its header."""
    return struct.unpack(">II", png[16:24])


def cmd_observe(client: Client, args: argparse.Namespace) -> int:
    try:
        png = client.screen()
    except ApiError as error:
        if error.status == 0:
            raise
        print(f"No screenshot: {error}", file=sys.stderr)
        return OTHER
    width, height = png_size(png)
    out = Path(args.out or f"observations/{datetime.now():%Y%m%d-%H%M%S}.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(png)
    print(f"Screen {width}x{height}. {client.status()['computer']['detail']}.")
    print(f"Screenshot saved to {out}")
    return 0


def cmd_takeover(client: Client, args: argparse.Namespace) -> int:
    client.control("user")
    print("You have control; the agent sends no actions until you return it.\nUse the desktop in the web page's live "
          "view. Run `computer-use return` when you are done.")
    return 0


def cmd_return(client: Client, args: argparse.Namespace) -> int:
    client.control("agent")
    print("Control returned to the agent; it re-observes before acting.")
    return 0


def answer(client: Client, decision: str, note: str) -> int:
    """Answer the step the running run waits for the user to approve, as the web page does."""
    pending = client.status().get("approval")
    if pending is not None:
        try:
            client.answer(pending["id"], decision, note.strip())
        except ApiError as error:
            if error.status != 409:  # 409: answered meanwhile, or no longer waiting
                raise
            pending = None
    if pending is None:
        print("No step is waiting for your approval.", file=sys.stderr)
        return OTHER
    print(f"{'Approved' if decision == 'approve' else 'Declined'}: {pending['consequence']}")
    return 0


def cmd_approve(client: Client, args: argparse.Namespace) -> int:
    return answer(client, "approve", "")


def cmd_reject(client: Client, args: argparse.Namespace) -> int:
    return answer(client, "reject", args.message)


def cmd_status(client: Client, args: argparse.Namespace) -> int:
    status = client.status()
    control = status["control"]
    why = f" ({control['reason']})" if control.get("reason") else ""
    print(f"Desktop: {status['computer']['detail']}; {control['owner']} has control{why}.")
    print(f"Using the desktop: {status['active'] or 'no run'}.")
    for item in status["running"]:
        print(f"Running: {item['run']} in conversation {item['thread']}.")
    if approval := status.get("approval"):
        print(f"Waiting for your approval: {approval['consequence']}")
    return 0


def cmd_export(client: Client, args: argparse.Namespace) -> int:
    events, files = client.export(args.run, Path(args.folder))
    print(f"Wrote {args.run} to {args.folder}: {len(events)} events, {len(files)} files.")
    return 0


COMMANDS = {
    "run": cmd_run,
    "resume": cmd_resume,
    "observe": cmd_observe,
    "takeover": cmd_takeover,
    "return": cmd_return,
    "approve": cmd_approve,
    "reject": cmd_reject,
    "status": cmd_status,
    "export": cmd_export,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="computer-use", description="Drive a computer-use runtime over its API.")
    parser.add_argument("--api", help="the runtime's API (default: $CU_API_URL, else http://127.0.0.1:8000)")
    sub = parser.add_subparsers(dest="command", required=True)

    def runs(command: argparse.ArgumentParser) -> None:
        command.add_argument("--max-steps", type=int, default=MAX_STEPS, help="model call limit per desktop task")
        command.add_argument("--main", nargs="+", metavar="MODEL [EFFORT]", help="the main agent's model and effort")
        command.add_argument("--computer", nargs="+", metavar="MODEL [EFFORT]",
                             help="the computer-use agent's model and effort")

    run = sub.add_parser("run", help="Let the agent carry out a goal on the desktop")
    run.add_argument("goal")
    run.add_argument("--thread", help="an earlier run's conversation to continue with this goal")
    run.add_argument("--project", help="the project the web page lists the conversation under, e.g. eval")
    runs(run)
    resume = sub.add_parser("resume", help="Send a run's message again, in its conversation")
    resume.add_argument("run", nargs="?", help="the run's id (default: the latest)")
    runs(resume)
    observe = sub.add_parser("observe", help="Save a screenshot of the desktop")
    observe.add_argument("--out", help="where to save it (default: observations/<time>.png)")
    sub.add_parser("takeover", help="Take control of the desktop; the agent stops acting")
    sub.add_parser("return", help="Return control to the agent")
    sub.add_parser("approve", help="Approve the step the agent is waiting for you to approve")
    reject = sub.add_parser("reject", help="Decline the step the agent is waiting for you to approve")
    reject.add_argument("--message", default="", help="why, or what to do instead; the agent reads it")
    sub.add_parser("status", help="Who has the desktop and which runs are going")
    export = sub.add_parser("export", help="Save a run's record and screenshots to a folder")
    export.add_argument("run")
    export.add_argument("folder")
    return parser


def main(argv: list[str] | None = None, client: Client | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return COMMANDS[args.command](client or Client(args.api), args)
    except ApiError as error:
        print(f"{error}", file=sys.stderr)
        return OTHER
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
        return STOPPED


if __name__ == "__main__":
    sys.exit(main())
