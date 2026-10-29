"""Read recorded runs, restore model messages, and summarize conversation history.

Only the current event format is available to conversations. Draft replies remain in the runner's memory;
this module reads the durable messages and events from the run store.
"""

import base64
import json
from collections.abc import Callable, Iterable
from operator import itemgetter

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage, messages_from_dict

from computer_use.agent.middleware import KEEP_SCREENSHOTS, PRUNE_EVERY, pruned, without_screenshots
from computer_use.agent.tools import image_blocks
from computer_use.agent.trajectory import is_image, shown_args
from computer_use.storage import MAIN, Event, RunId, RunStore, Thread, supported


async def thread_of(store: RunStore, run: RunId) -> Thread | None:
    """The conversation a run belongs to, its first run's id; None for a run that is missing, not started yet, or in
    an unsupported format."""
    events = await store.events(run)
    return events[0]["thread"] if supported(events) else None


async def has_title(store: RunStore, thread: Thread) -> bool:
    """Whether any of the conversation's runs is named, the user's or the runtime's; from the summaries, which read
    only the records that changed."""
    return any(summary.title is not None for summary in await store.summaries() if summary.thread == thread)


async def can_continue(store: RunStore, thread: Thread) -> bool:
    """Whether the conversation exists in the supported format and can receive a next message."""
    return await thread_of(store, thread) == thread


async def with_images(store: RunStore, run: RunId, message: BaseMessage) -> BaseMessage:
    """The message with its images read back from their files."""
    if not isinstance(message.content, list):
        return message
    blocks = list(message.content)
    for index, block in enumerate(blocks):
        if is_image(block) and "file" in block:
            png = await store.get_file(run, block["file"])
            rest = {key: value for key, value in block.items() if key != "file"}
            blocks[index] = rest | {"base64": base64.b64encode(png).decode()}
    return message.model_copy(update={"content": blocks})


async def restore(store: RunStore, run: RunId, record: dict) -> BaseMessage:
    """A recorded message with its images read back from their files."""
    return await with_images(store, run, messages_from_dict([record])[0])


def in_call_order[T](items: list[T], message: Callable[[T], BaseMessage] = lambda item: item) -> list[T]:
    """Tool results put back in the order of the calls that asked for them; they are logged as each one finishes.
    `message` finds each item's message when the items carry more than it."""
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


async def main_messages(store: RunStore, run: RunId, events: list[Event]) -> list[BaseMessage]:
    """The main agent's recorded messages in one run, in their original order."""
    return [
        await restore(store, run, event["message"])
        for event in events if event.get("agent") == MAIN and "message" in event
    ]


async def load_conversation(store: RunStore, thread: Thread) -> list[BaseMessage]:
    """Every message the main agent saw in a current-format conversation, oldest first. The screenshots its next
    model call would prune (agent.middleware) are replaced before they are read: a later turn only adds screenshots,
    so one pruned once stays pruned, and the call sends the same messages either way."""
    placed: list[tuple[RunId, BaseMessage]] = []
    for run in await store.conversation(thread):
        placed += [
            (run, messages_from_dict([event["message"]])[0])
            for event in await store.events(run) if event.get("agent") == MAIN and "message" in event
        ]
    placed = in_call_order(placed, itemgetter(1))
    carrying = [index for index, (_, message) in enumerate(placed) if image_blocks(message)]
    dropped = set(carrying[:pruned(len(carrying), KEEP_SCREENSHOTS, PRUNE_EVERY)])
    return [
        without_screenshots(message) if index in dropped else await with_images(store, run, message)
        for index, (run, message) in enumerate(placed)
    ]


async def cut_off(store: RunStore, thread: Thread) -> list[Event]:
    """The tasks the conversation's latest run started and logged no end of, as their start events: the runtime died
    under them, so that run could not tell of them. Any stop that runs its course logs each task's end."""
    runs = await store.conversation(thread)
    events = [event for event in await store.events(runs[-1]) if event["type"] == "task"] if runs else []
    ended = {event["id"] for event in events if event["state"] != "started"}
    return [event for event in events if event["state"] == "started" and event["id"] not in ended]


def action_records(events: Iterable[dict]) -> list[str]:
    """The input the computer-use agent sent, as the runtime recorded it: each action's tool and arguments, without
    what it said before it or what came of it, for auto review, which takes only these and the user's words as facts.
    Only actions whose input went out ("success"; it does not mean a file was saved, say) count: not one that failed,
    was held back or declined, and not a batch that stopped partway, some of whose input never went out."""
    return [
        f"{event['tool']} {json.dumps(shown_args(event['args']), ensure_ascii=False)}"
        for event in events
        if event["type"] == "action" and event.get("agent") != MAIN and event.get("status") == "success"
    ]


def action_lines(events: Iterable[dict]) -> list[str]:
    """One line per action of the computer-use agent: what it said before it, what it did (and, for a step that needed
    approval, what it said the step would do, and whether the user or auto review was asked), and what came of it: for
    a step the user declined, all they said of it. And a line each time the user took the desktop and gave it back,
    with how long they had it. These are what the main agent learns the user's corrections from.

    A tool call that never got a result (the run died mid-action) is left out: whether it happened shows on the
    next screenshot.
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
                # A batch can stop partway. Preserve every reported step and the unsent suffix,
                # not just the first step (or the opening failure message).
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


def text_entry_screens(events: Iterable[dict], limit: int = 2) -> list[tuple[int, str]]:
    """Recent full-screen observations before text entry, for the handoff's historical evidence.

    For example, typing a filename and clicking Save in one batch otherwise hides the
    save dialog from the main agent. These are recorded observations, not proof of what
    happened afterward. Cropped zooms must not replace the full-screen observation.
    Action numbers match the task's action summary, rather than the run's cumulative log.
    """
    screen = None
    number = 0
    checkpoints: list[tuple[int, str]] = []
    for event in events:
        if event.get("agent") == MAIN:
            continue
        if event["type"] == "input":
            blocks = event.get("message", {}).get("data", {}).get("content", [])
            if isinstance(blocks, list):
                for block in blocks:
                    if isinstance(block, dict) and block.get("type") == "image" and block.get("file"):
                        screen = block["file"]
        elif event["type"] == "action":
            number += 1
            typing = event["tool"] == "type" or (
                event["tool"] == "computer_batch"
                and any(step.get("action") == "type" for step in event["args"].get("actions", []))
            )
            if typing and screen:
                checkpoints = [(n, name) for n, name in checkpoints if name != screen]
                checkpoints.append((number, screen))
            if event.get("screenshot") and event["tool"] != "zoom":
                screen = event["screenshot"]
    return checkpoints[-limit:] if limit > 0 else []


def user_messages(events: list[dict]) -> list[str]:
    """What the user said in a run, oldest first: the message it answers, then those sent while it worked."""
    start = events[0] if events and events[0]["type"] == "start" else {}
    return [start.get("goal", ""), *(event["text"] for event in events if event["type"] == "message")]


def tasks(events: list[dict]) -> list[dict]:
    """Completed tasks of every agent the main agent hands work to, oldest first: the tool that handed each over, and
    the brief and artifact recorded in the runtime's task-ended input."""
    return [
        {"tool": runtime["tool"], "task": runtime["brief"], **runtime["artifact"]}
        for event in events
        if event.get("agent") == MAIN and event["type"] == "input"
        and (runtime := event["message"]["data"].get("additional_kwargs", {}).get("runtime", {}))
        and runtime.get("event") == "task_ended"
    ]
