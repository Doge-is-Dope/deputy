"""Append-only run log: model messages, usage, actions and screenshot files, kept by the run store.

Main-agent events carry agent="main"; subagent events are untagged. Listeners
receive events as they are written. history.load_conversation restores the main
conversation from these logs; subagents start each task afresh. A thread is
named after its first run's id."""

import base64
import json
import uuid
from collections.abc import Callable, Sequence
from contextvars import ContextVar
from typing import Unpack

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage, message_to_dict

from computer_use.agent.failures import error_code
from computer_use.agent.models import PRICES
from computer_use.desktop.actions import CONFIRM_FIELDS
from computer_use.events import NoteCode, NoteData, NoteEvent
from computer_use.storage import FORMAT, LOCAL_USER, MAIN, RunId, RunStore
# The background task whose work is being logged, set in it as it starts (agent.background): its events carry its id.
TASK: ContextVar[str | None] = ContextVar("task", default=None)
# How the user answered a step awaiting approval, as the terminal says it.
DECIDED = {"approved": "Approved.", "declined": "Declined", "took_control": "You took the desktop to do it yourself."}

Listener = Callable[[dict], None]


def text_of(message) -> str:
    if isinstance(message.content, str):
        return message.content
    return "\n".join(
        block["text"] for block in message.content if isinstance(block, dict) and block.get("type") == "text"
    )


def no_tokens() -> dict[str, int]:
    return {"input": 0, "cached": 0, "cache_write": 0, "output": 0, "reasoning": 0}


def usage_of(message: AIMessage) -> dict[str, int]:
    """Tokens one model reply used. Cached and cache-write tokens are part of input, reasoning part of output."""
    usage = message.usage_metadata or {}
    details = usage.get("input_token_details") or {}
    return {
        "input": usage.get("input_tokens", 0),
        "cached": details.get("cache_read", 0),
        "cache_write": details.get("cache_creation", 0),
        "output": usage.get("output_tokens", 0),
        "reasoning": (usage.get("output_token_details") or {}).get("reasoning", 0),
    }


def cost_breakdown(tokens: dict[str, int], price) -> dict[str, float]:
    """US dollars for these tokens at list prices, by kind: input neither read from nor written to the cache, cache
    reads, cache writes, and output (reasoning included)."""
    plain = tokens["input"] - tokens["cached"] - tokens["cache_write"]
    return {
        "input": plain * price.input / 1_000_000,
        "cached": tokens["cached"] * price.cached / 1_000_000,
        "cache_write": tokens["cache_write"] * price.cache_write / 1_000_000,
        "output": tokens["output"] * price.output / 1_000_000,
    }


def shown_args(args: dict) -> dict:
    """An action's arguments as people read them: without the approval fields every input action carries (the
    approval is told apart, by its confirm event), nor those left empty, which in a batch's actions are most of them
    and once cut the text it typed out of an action's line (2026-10-08)."""
    shown = {key: value for key, value in args.items() if key not in CONFIRM_FIELDS and value is not None}
    if isinstance(shown.get("actions"), list):
        shown["actions"] = [
            {key: value for key, value in step.items() if value is not None} if isinstance(step, dict) else step
            for step in shown["actions"]
        ]
    return shown


def print_event(event: dict) -> None:
    """Show a run's progress on the terminal; the main agent's lines are marked as its own."""
    main = event.get("agent") == MAIN
    match event["type"]:
        case "note":
            print(event["text"], flush=True)
        case "message":
            print(f"      user: {event['text']}", flush=True)
        case "title":
            print(f"      title: {event['text']}", flush=True)
        case "task":
            print(f"      {event['tool']} {event['state']}: {event['brief']}", flush=True)
        case "model" if event["text"].strip():
            print(f"      {'main' if main else 'model'}: {event['text'].strip()}", flush=True)
        case "action":
            args = json.dumps(shown_args(event["args"]), ensure_ascii=False)
            outcome = "" if event["status"] == "success" else f"  -> {event['result']}"
            number = f"m{event['n']}" if main else str(event["n"])
            print(f"[{number:>3}] {event['tool']} {args}{outcome}", flush=True)
        case "confirm":
            print(
                f"The agent asks you to approve: {event['consequence']}\n"
                "Answer on the web page, or run `computer-use approve` or `computer-use reject --message \"…\"`.",
                flush=True,
            )
        case "review":
            verdict = "lets it through" if event["allow"] else "leaves it to you"
            why = event.get("reason") or event.get("error", "")
            print(f"      Auto review {verdict}: {why}", flush=True)
        case "decision" if event.get("by") == "auto":
            pass  # its review just said why
        case "decision":
            said = f": {event['note']}" if event.get("note") else ""
            print(f"      {DECIDED.get(event['outcome'], event['outcome'])}{said}", flush=True)


class Trajectory:
    """A run's log as it is written: `open` makes the run in the store, then each method appends one event."""

    def __init__(self, store: RunStore, run: RunId, listeners: Sequence[Listener] = ()):
        self.store = store
        self.run = run
        self.listeners = listeners
        # The computer-use agent's actions, model calls and tokens, then the main agent's.
        self.actions, self.calls, self.tokens = 0, 0, no_tokens()
        self.main_actions, self.main_calls, self.main_tokens = 0, 0, no_tokens()
        self.cut_calls = 0  # model calls a stop cut off, whose usage never came
        # The tokens of each agent with each model, for what they cost, in the order they were first used; and the model
        # and name each agent works with now (`uses`).
        self.agent_tokens: dict[tuple[str, str], dict[str, int]] = {}
        self.models: dict[str | None, str] = {}
        self.names: dict[str | None, str] = {MAIN: MAIN}
        self.recorded: set[str] = set()  # the ids of the messages written so far

    @classmethod
    async def open(cls, store: RunStore, listeners: Sequence[Listener] = ()) -> "Trajectory":
        return cls(store, await store.create(), listeners)

    def _write(self, event: dict) -> None:
        if (task := TASK.get()) is not None:
            event = {**event, "task": task}
        _, event = self.store.append(self.run, event)
        for listener in self.listeners:
            listener(event)

    def _event(self, kind: str, agent: str | None, **fields) -> None:
        self._write({"type": kind, **({"agent": agent} if agent else {}), **fields})

    def start(
        self, goal: str, thread: str | None, model: str, main_model: str, computer: bool = False,
        approvals: str = "ask", project: str | None = None, user: str = LOCAL_USER,
    ) -> None:
        """The log's format; the run's id, so listeners know which run the events belong to; its conversation (the
        first run's id); the user's message; both agents' models, since a model's reasoning
        carries over only within its family; whether the user asked for the computer; how the user chose to have
        steps approved as the run started, which they may change while it works (each `confirm` says how it was); the
        id of the project its conversation was begun in, which the web page lists it under (None for none); and whose
        it is (auth.Identity's id), the only one who sees it."""
        self._write({
            "type": "start", "v": FORMAT, "run": self.run, "thread": thread or self.run, "goal": goal,
            "model": model, "main_model": main_model, "computer": computer, "approvals": approvals, "project": project,
            "user": user,
        })

    def _named(self, agent: str | None, name: str) -> str:
        """Files are named after the action they come with: the main agent's apart from the computer-use agent's."""
        return f"main-{self.main_actions:03d}-{name}" if agent == MAIN else f"{self.actions:03d}-{name}"

    def _free(self, name: str) -> str:
        """A file name not taken yet: two screens can come at the same point, e.g. two tasks before any action."""
        free, n = name, 1
        while self.store.has_file(self.run, f"{free}.png"):
            n += 1
            free = f"{name}_{n}"
        return free

    def _record(self, message: BaseMessage, name: str) -> dict:
        """The message exactly as the model gets it, with each image saved as a file named after `name`.

        A message without an id gets one first, so the graph keeps the same id instead of assigning another.
        """
        message.id = message.id or str(uuid.uuid4())
        self.recorded.add(message.id)
        record = message_to_dict(message)
        content = record["data"].get("content")
        images = [index for index, block in enumerate(content) if is_image(block)] if isinstance(content, list) else []
        name = self._free(name) if images else name
        for number, index in enumerate(images, 1):
            file = f"{name}.png" if number == 1 else f"{name}-{number}.png"
            block = content[index]
            self.store.put_file(self.run, file, base64.b64decode(block["base64"]))
            content[index] = {key: value for key, value in block.items() if key != "base64"} | {"file": file}
        return record

    def input(self, message: BaseMessage, name: str, agent: str | None = None) -> None:
        """A message the runtime adds to a conversation: the user's message, a task and its first screen, a fresh
        screen after the user returns control or the desktop reconnects, a result left unknown, a closing message."""
        self._event("input", agent, message=self._record(message, self._named(agent, name)))

    def uses(self, model: str, agent: str | None = None, name: str | None = None) -> None:
        """The model an agent works with from here on: the main agent's (MAIN) for the run, a subagent's for its task,
        by its name in the settings. Its model calls' tokens are priced as that model's."""
        self.models[agent] = model
        if name:
            self.names[agent] = name

    def _count(self, usage: dict[str, int], agent: str | None, model: str | None = None) -> None:
        tokens = self.main_tokens if agent == MAIN else self.tokens
        key = (self.names.get(agent, ""), model or self.models.get(agent, ""))
        by_agent = self.agent_tokens.setdefault(key, no_tokens())
        for kind, count in usage.items():
            tokens[kind] += count
            by_agent[kind] += count

    def usage(self) -> dict[str, int]:
        """The tokens both agents used."""
        return {key: self.tokens[key] + self.main_tokens[key] for key in self.tokens}

    def cost(self) -> dict[str, float] | None:
        """What the tokens of every model cost by kind, at list prices; None when a model that used tokens has no
        known price."""
        if any(PRICES.get(model) is None and any(tokens.values()) for (_, model), tokens in self.agent_tokens.items()):
            return None
        total = {"input": 0.0, "cached": 0.0, "cache_write": 0.0, "output": 0.0}
        for (_, model), tokens in self.agent_tokens.items():
            for kind, dollars in (cost_breakdown(tokens, PRICES[model]) if model in PRICES else {}).items():
                total[kind] += dollars
        return total

    def by_agent(self) -> list[dict]:
        """Each agent's tokens with each model, in the order first used, and what they cost (None when the model has no
        known price): the main agent's, then each subagent's by its name in the settings."""
        return [
            {"agent": name, "model": model, "usage": tokens,
             "cost": cost_breakdown(tokens, PRICES[model]) if model in PRICES else None}
            for (name, model), tokens in self.agent_tokens.items() if any(tokens.values())
        ]

    def end(self, stop_reason: str, summary: str, computer: str | None, error: Exception | None = None) -> None:
        """How the run ended (the main agent replied, or it was stopped or failed), the main agent's reply, how the
        computer-use agent's last task ended (None when the desktop was not used); then the tokens the run used and,
        when the models' prices are known and no call was cut off by a stop, what each kind cost, in all and by agent
        and model (the web shows it). A run that failed also says why:
        the exception, and its code (failures.py), which the page explains in words."""
        event = {
            "type": "end", "stop_reason": stop_reason, "computer": computer, "summary": summary,
            "usage": self.usage(), "cost": None if self.cut_calls else self.cost(), "agents": self.by_agent(),
        }
        if error is not None:
            event |= {"error": f"{type(error).__name__}: {error}", "error_code": error_code(error)}
        self._write(event)

    def note(self, text: str, code: NoteCode | None = None, **data: Unpack[NoteData]) -> None:
        event: NoteEvent = {"type": "note", "text": text, "code": code, "data": data}
        self._write(event)

    def title(self, text: str, usage: dict[str, int], seconds: float, model: str) -> None:
        """The independent title call's result and cost, even after the agent run has ended."""
        price = PRICES.get(model)
        self._write({"type": "title", "text": text, "usage": usage, "seconds": round(seconds, 2),
                     "model": model, "cost": cost_breakdown(usage, price) if price else None})

    def task(self, state: str, id: str, tool: str, brief: str, title: str = "") -> None:
        """Work the main agent handed over in the background starting or ending (agent.background): the page shows the
        agent at work in between, from the events that carry its id, under its title."""
        self._write({"type": "task", "state": state, "id": id, "tool": tool, "brief": brief, "title": title})

    def message(self, id: str, text: str) -> None:
        """A message the user sent while the run worked, once an agent has read it (agent.inbox): from here on it is
        part of the conversation, which the page shows in its place."""
        self._write({"type": "message", "id": id, "text": text})

    def confirm(self, call: dict, consequence: str, png: bytes | None, auto_review: bool = False) -> str | None:
        """A step the computer-use agent asked the user to approve, the screen it decided from with its target marked,
        and whether auto review looks at it first, as the user had it then; returns the screenshot's file name. Not a
        message the model saw, so it carries none."""
        screenshot = None
        if png is not None:
            screenshot = f"{self._free(self._named(None, 'confirm'))}.png"
            self.store.put_file(self.run, screenshot, png)
        self._event(
            "confirm", None, id=call["id"], tool=call["name"], args=shown_args(call["args"]), consequence=consequence,
            screenshot=screenshot, auto_review=auto_review,
        )
        return screenshot

    def review(self, id: str, allow: bool, review: dict) -> None:
        """What auto review made of the step `id` (`agent.review`): whether it lets it through, and why. Its model is
        the main agent's, so its tokens count as the main agent's."""
        self._count(review.get("usage") or {}, MAIN)
        self._event("review", None, id=id, allow=allow, **review)

    def decision(self, id: str, outcome: str, note: str = "", by: str = "") -> None:
        """How the step `id` was answered: approved, declined (with what the user said), or took_control; and who
        answered, for who decided each step: the user on the web page or the command line ("web", "cli"), or auto
        review ("auto", with its reason as the note)."""
        self._event("decision", None, id=id, outcome=outcome, note=note, by=by)

    def model(self, message: AIMessage, agent: str | None = None, cut: bool = False) -> None:
        """A model's reply. The part of one a stop cut off (`cut`) has no usage: its call was counted by `cut()`."""
        calls = [{"name": call["name"], "args": call["args"]} for call in message.tool_calls]
        usage = None if cut else usage_of(message)
        if usage is not None:
            if agent == MAIN:
                self.main_calls += 1
            else:
                self.calls += 1
            self._count(usage, agent)
        record = self._record(message, self._named(agent, "model"))
        model = {"model": self.models[agent]} if agent in self.models else {}
        self._event("model", agent, text=message.text, tool_calls=calls, usage=usage, **model, message=record)

    def token_summary(self) -> str:
        """Model calls and tokens so far, and their cost when the models' prices are known."""
        tokens, cost = self.usage(), self.cost()
        summary = (
            f"{self.calls + self.main_calls} model calls ({self.main_calls} by the main agent) used "
            f"{tokens['input']:,} input tokens ({tokens['cached']:,} cached) and {tokens['output']:,} output tokens "
            f"({tokens['reasoning']:,} reasoning)"
        )
        if cost is not None:
            summary += f", about ${sum(cost.values()):.4f} at list prices"
        if self.cut_calls:
            summary += f", not counting {self.cut_calls} the stop cut off, whose usage is not known"
        return summary + "."

    def cut(self) -> None:
        """A model call a stop cut off. The provider bills what it read and wrote so far, but a reply's usage comes only
        with its end, so the run's cost is not known."""
        self.cut_calls += 1

    def action(self, call: dict, result: ToolMessage, agent: str | None = None) -> None:
        if agent == MAIN:
            self.main_actions += 1
        else:
            self.actions += 1
        record = self._record(result, self._named(agent, call["name"]))
        content = record["data"]["content"]
        screenshot = next((block["file"] for block in content if is_image(block)), None) if isinstance(content, list) else None
        self._event(
            "action", agent,
            n=self.main_actions if agent == MAIN else self.actions,
            id=call["id"],
            tool=call["name"],
            args=call["args"],
            status=getattr(result, "status", "success"),
            reason=(result.artifact or {}).get("reason") if isinstance(result.artifact, dict) else None,
            result=text_of(result),
            screenshot=screenshot,
            message=record,
        )


def is_image(block) -> bool:
    return isinstance(block, dict) and block.get("type") == "image"
