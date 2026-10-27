"""A run's events as lines on the terminal, as they come."""

import json

# The fields every input action carries for approval; a confirm event says what they asked.
CONFIRM_FIELDS = ("needs_confirmation", "consequence")
# How the user answered a step awaiting approval.
DECIDED = {"approved": "Approved.", "declined": "Declined", "took_control": "You took the desktop to do it yourself."}
MAIN = "main"


def shown_args(args: dict) -> dict:
    """An action's arguments as people read them: without the approval fields and those left empty."""
    shown = {key: value for key, value in args.items() if key not in CONFIRM_FIELDS and value is not None}
    if isinstance(shown.get("actions"), list):
        shown["actions"] = [
            {key: value for key, value in step.items() if value is not None} if isinstance(step, dict) else step
            for step in shown["actions"]
        ]
    return shown


def line(event: dict) -> str | None:
    """What the terminal shows of one event, or None for one it does not show."""
    main = event.get("agent") == MAIN
    match event.get("type"):
        case "note":
            return event["text"]
        case "message":
            return f"      user: {event['text']}"
        case "title":
            return f"      title: {event['text']}"
        case "task":
            return f"      {event['tool']} {event['state']}: {event['brief']}"
        case "model" if event.get("text", "").strip():
            return f"      {'main' if main else 'model'}: {event['text'].strip()}"
        case "action":
            args = json.dumps(shown_args(event["args"]), ensure_ascii=False)
            outcome = "" if event["status"] == "success" else f"  -> {event['result']}"
            number = f"m{event['n']}" if main else str(event["n"])
            return f"[{number:>3}] {event['tool']} {args}{outcome}"
        case "confirm":
            return (
                f"The agent asks you to approve: {event['consequence']}\n"
                "Answer on the web page, or run `computer-use approve` or `computer-use reject --message \"…\"`."
            )
        case "review":
            verdict = "lets it through" if event["allow"] else "leaves it to you"
            return f"      Auto review {verdict}: {event.get('reason') or event.get('error', '')}"
        case "decision" if event.get("by") != "auto":
            said = f": {event['note']}" if event.get("note") else ""
            return f"      {DECIDED.get(event['outcome'], event['outcome'])}{said}"
    return None
