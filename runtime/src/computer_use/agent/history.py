"""Read recorded runs, restore model messages, and summarize conversation history from the run store."""

import base64
import json
from collections.abc import Callable, Iterable
from operator import itemgetter

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage, messages_from_dict

from computer_use.middleware.common import pruned, without_screenshots
from computer_use.tools.common import image_blocks, is_image
from computer_use.events import shown_args
from computer_use.storage import MAIN, TASK, TURN, RunId, Runs, Thread, supported


async def thread_of(store: Runs, run: RunId) -> Thread | None:
    """The conversation a run belongs to, its first run's id; None for a run that is missing, not started, or in an
    unsupported format."""
    events = await store.events(run, messages=False)
    return events[0]["thread"] if supported(events) else None


async def has_title(store: Runs, thread: Thread) -> bool:
    """Whether any of the conversation's runs is named, read from the summaries."""
    return any(summary.title is not None for summary in await store.runs(thread))


async def can_continue(store: Runs, thread: Thread) -> bool:
    return await thread_of(store, thread) == thread


async def with_images(store: Runs, run: RunId, message: BaseMessage) -> BaseMessage:
    if not isinstance(message.content, list):
        return message
    blocks = list(message.content)
    for index, block in enumerate(blocks):
        if is_image(block) and "file" in block:
            png = await store.get_file(run, block["file"])
            rest = {key: value for key, value in block.items() if key != "file"}
            blocks[index] = rest | {"base64": base64.b64encode(png).decode()}
    return message.model_copy(update={"content": blocks})


def in_call_order[T](items: list[T], message: Callable[[T], BaseMessage] = lambda item: item) -> list[T]:
    """Tool results put back in the order of the calls that asked for them; they are logged as each one finishes."""
    result = list(items)
    for index, item in enumerate(result):
        each = message(item)
        if isinstance(each, AIMessage) and len(each.tool_calls) > 1:
            order = {call["id"]: number for number, call in enumerate(each.tool_calls)}
            end = index + 1
            while end < len(result) and isinstance(message(result[end]), ToolMessage):
                end += 1
            result[index + 1:end] = sorted(
                result[index + 1:end], key=lambda tool: order.get(message(tool).tool_call_id, 0)
            )
    return result


async def load_conversation(store: Runs, thread: Thread) -> list[BaseMessage]:
    """Every message the main agent saw, oldest first. Screenshots its next model call would prune are replaced before
    they are read: a later turn only adds screenshots, so one pruned once stays pruned."""
    placed: list[tuple[RunId, BaseMessage]] = []
    for summary in await store.runs(thread):
        if summary.kind != TURN:
            continue
        placed += [
            (summary.id, messages_from_dict([event["message"]])[0])
            for event in await store.events(summary.id) if event.get("agent") == MAIN and "message" in event
        ]
    placed = in_call_order(placed, itemgetter(1))
    carrying = [index for index, (_, message) in enumerate(placed) if image_blocks(message)]
    dropped = set(carrying[:pruned(len(carrying))])
    return [
        without_screenshots(message) if index in dropped else await with_images(store, run, message)
        for index, (run, message) in enumerate(placed)
    ]


async def untold(store: Runs, thread: Thread) -> list[dict]:
    """The tasks that stopped before they ended and that the main agent was never told of: a stop ended their session,
    the user stopped one and the session ended before the main agent heard, or the runtime died (`open`: the log has
    no end). Each as its log's start event, with `open` and `by`. A task is known by its log, or by its id within its
    session: each session numbers its tasks from t1, and a stop is told in a later session than the task's."""
    told, stopped = set(), []
    for summary in await store.runs(thread):
        events = await store.events(summary.id)
        if not supported(events):
            continue
        start = events[0]
        if start["kind"] == TASK:
            end = next((event for event in events if event["type"] == "end"), None)
            if end is None or end["stop_reason"] == "stopped":
                stopped.append({**start, "open": end is None, "by": (end or {}).get("by")})
            continue
        for event in events:
            if event.get("agent") != MAIN:
                continue
            runtime = event.get("message", {}).get("data", {}).get("additional_kwargs", {}).get("runtime", {})
            if event["type"] == "input" and runtime.get("record"):
                told.add(runtime["record"])
            elif event["type"] == "input" and runtime.get("id"):
                told.add((start["session"], runtime["id"]))
            if event["type"] == "action" and event["tool"] == "stop_task" and event["status"] == "success":
                told.add((start["session"], event["args"].get("task_id")))
    return [task for task in stopped if task["run"] not in told and (task["session"], task["id"]) not in told]


def action_lines(events: Iterable[dict]) -> list[str]:
    """One line per action of a task's agent, and one each time the user took the desktop and gave it back; the main
    agent learns the user's corrections from these. A tool call that never got a result (the run died mid-action) is
    left out: whether it happened shows on the next screenshot.
    """
    lines, thought, reviewed, declined = [], "", set(), {}
    for event in events:
        if event.get("agent") == MAIN:
            continue
        if event["type"] == "model":
            thought = " ".join(event["text"].split())
        elif event["type"] == "decision" and event.get("by") == "auto":
            reviewed.add(event["id"])
        elif event["type"] == "decision" and event.get("outcome") == "declined":
            declined[event["id"]] = " ".join((event.get("note") or "").split())
        elif event["type"] == "note" and event.get("code") == "controlReturned":
            lines.append(f"The user had the desktop for {event['data'].get('seconds', 0):.0f} seconds, then gave it back.")
        elif event["type"] == "action":
            args = json.dumps(shown_args(event["args"]), ensure_ascii=False)[:200]
            asked = ""
            if event["args"].get("needs_confirmation") is True:
                who = "auto review let it through" if event.get("id") in reviewed else "asked the user to approve"
                asked = f" ({who}: {event['args'].get('consequence')})"
            if event["tool"] == "computer_batch":
                # A batch can stop partway: keep every reported step and the unsent suffix.
                outcome = " | ".join(
                    line[:200] for line in (event["result"] or "").splitlines()
                    if line and not line.startswith("Screen ")
                )
            elif event.get("id") in declined:
                note = declined[event["id"]]
                outcome = "the user declined it" + (f", saying: {note}" if note else ", saying nothing")
            else:
                outcome = (event["result"] or "").split("\n", 1)[0][:200]
            said = f"{thought} -> " if thought else ""
            lines.append(f"{said}{event['tool']} {args}{asked} -> {event['status']}: {outcome}")
            thought = ""
    return lines


async def latest_plan(store: Runs, thread: Thread) -> dict | None:
    """The newest plan snapshot in a conversation's logs, its tasks' included; None if it has no plan."""
    snapshots = [
        event for summary in await store.runs(thread)
        for event in await store.events(summary.id, messages=False) if event["type"] == "plan"
    ]
    return max(snapshots, key=itemgetter("version"), default=None)


def user_messages(events: list[dict]) -> list[str]:
    start = events[0] if events and events[0]["type"] == "start" else {}
    return [*([start["goal"]] if start.get("goal") else []), *(event["text"] for event in events if event["type"] == "message")]


def tasks(events: list[dict]) -> list[dict]:
    """Completed tasks of every agent, oldest first, from the runtime's task-ended inputs."""
    return [
        {"agent": runtime["agent"], "task": runtime["brief"], **runtime["artifact"]}
        for event in events
        if event.get("agent") == MAIN and event["type"] == "input"
        and (runtime := event["message"]["data"].get("additional_kwargs", {}).get("runtime", {}))
        and runtime.get("event") == "task_ended"
    ]
