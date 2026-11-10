"""Append-only run log: model messages, usage, actions and screenshot files, kept by the run store.

A run records a turn of the main agent or a task it handed over. Main-agent events carry agent="main"; a task's
agent's are untagged. A thread is named after its first turn's id, and a session after the id of the turn that began
it."""

import base64
import uuid
from collections.abc import Callable, Sequence
from typing import Unpack

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage, message_to_dict

from computer_use.agent.failures import error_code
from computer_use.agent.usage import PRICES, cost_breakdown, no_tokens, usage_of
from computer_use.events import NoteCode, NoteData, NoteEvent, PlanSnapshot
from computer_use.storage import FORMAT, MAIN, TASK, TURN, RunId, Runs
from computer_use.tools.common import is_image

Listener = Callable[[RunId, dict], None]  # called with a run's id and each event as it is written


def text_of(message) -> str:
    if isinstance(message.content, str):
        return message.content
    return "\n".join(
        block["text"] for block in message.content if isinstance(block, dict) and block.get("type") == "text"
    )


class Trajectory:
    """A run's log as it is written: `open` makes the run in the store, then each method appends one event."""

    def __init__(self, store: Runs, run: RunId, listeners: Sequence[Listener] = ()):
        self.store = store
        self.run = run
        self.listeners = listeners
        # The computer-use agent's actions and model calls, then the main agent's.
        self.actions, self.calls = 0, 0
        self.main_actions, self.main_calls = 0, 0
        self.cut_calls = 0  # model calls a stop cut off, whose usage never came
        # Tokens by (agent name, model), in the order first used; and the model and name each agent works with now.
        self.agent_tokens: dict[tuple[str, str], dict[str, int]] = {}
        self.models: dict[str | None, str] = {}
        self.names: dict[str | None, str] = {MAIN: MAIN}
        self.recorded: set[str] = set()  # ids of the messages written
        self.files: set[str] = set()

    @classmethod
    async def open(cls, store: Runs, listeners: Sequence[Listener] = ()) -> "Trajectory":
        return cls(store, await store.create(), listeners)

    def _write(self, event: dict) -> None:
        event = self.store.append(self.run, event)
        for listener in self.listeners:
            listener(self.run, event)

    def _event(self, kind: str, agent: str | None, **fields) -> None:
        self._write({"type": kind, **({"agent": agent} if agent else {}), **fields})

    def start(
        self, goal: str, thread: str | None, model: str, main_model: str, computer: bool = False,
        approvals: str = "ask", project: str | None = None, session: str | None = None, sent: float | None = None,
    ) -> None:
        """A turn's log. `goal` is the user's message that began the session, "" for a later turn. Both agents' models
        are recorded since a model's reasoning carries over only within its family; `approvals` is how the user chose
        to have steps approved as the session started, which they may change while it works (each `confirm` says how
        it was). `sent` is when a message that waited for this run came."""
        self._write({
            "type": "start", "v": FORMAT, "kind": TURN, "run": self.run, "thread": thread or self.run,
            "session": session or self.run, "goal": goal, "model": model, "main_model": main_model,
            "computer": computer, "approvals": approvals, "project": project, "user": self.store.user,
            **({"sent": sent} if sent is not None else {}),
        })

    def start_task(self, thread: str, session: str, parent: str, id: str, agent: str, brief: str, title: str) -> None:
        """A task's log, started by the turn `parent`; `id` is the task's id there."""
        self._write({
            "type": "start", "v": FORMAT, "kind": TASK, "run": self.run, "thread": thread, "session": session,
            "parent": parent, "id": id, "agent": agent, "goal": brief, "title": title, "user": self.store.user,
        })

    def _named(self, agent: str | None, name: str) -> str:
        """Files are named after the action they come with: the main agent's apart from the computer-use agent's."""
        return f"main-{self.main_actions:03d}-{name}" if agent == MAIN else f"{self.actions:03d}-{name}"

    def _free(self, name: str) -> str:
        """Reserves a free file name: two screenshots can share a step name."""
        free, n = name, 1
        while f"{free}.png" in self.files:
            n += 1
            free = f"{name}_{n}"
        self.files.add(f"{free}.png")
        return free

    async def _record(self, message: BaseMessage, name: str) -> dict:
        """The message as the model gets it, each image saved as a file named after `name`; names are reserved before
        any write. A message without an id gets one first, so the graph keeps it instead of assigning another.
        """
        message.id = message.id or str(uuid.uuid4())
        self.recorded.add(message.id)
        record = message_to_dict(message)
        content = record["data"].get("content")
        images = [index for index, block in enumerate(content) if is_image(block)] if isinstance(content, list) else []
        name = self._free(name) if images else name
        files = []
        for number, index in enumerate(images, 1):
            file = f"{name}.png" if number == 1 else f"{name}-{number}.png"
            self.files.add(file)
            block = content[index]
            files.append((file, base64.b64decode(block["base64"])))
            content[index] = {key: value for key, value in block.items() if key != "base64"} | {"file": file}
        for file, data in files:
            await self.store.put_file(self.run, file, data)
        return record

    async def input(self, message: BaseMessage, name: str, agent: str | None = None) -> None:
        self._event("input", agent, message=await self._record(message, self._named(agent, name)))

    def uses(self, model: str, agent: str | None = None, name: str | None = None) -> None:
        """The model an agent works with from here on, by which its tokens are priced; a subagent is `name`d as in the
        settings."""
        self.models[agent] = model
        if name:
            self.names[agent] = name

    def _count(self, usage: dict[str, int], agent: str | None, model: str | None = None) -> None:
        key = (self.names.get(agent, ""), model or self.models.get(agent, ""))
        by_agent = self.agent_tokens.setdefault(key, no_tokens())
        for kind, count in usage.items():
            by_agent[kind] += count

    def usage(self) -> dict[str, int]:
        return {kind: sum(tokens[kind] for tokens in self.agent_tokens.values()) for kind in no_tokens()}

    def cost(self) -> dict[str, float] | None:
        """What the tokens cost by kind at list prices; None when a model that used tokens has no known price."""
        if any(PRICES.get(model) is None and any(tokens.values()) for (_, model), tokens in self.agent_tokens.items()):
            return None
        total = {"input": 0.0, "cached": 0.0, "cache_write": 0.0, "output": 0.0}
        for (_, model), tokens in self.agent_tokens.items():
            for kind, dollars in (cost_breakdown(tokens, PRICES[model]) if model in PRICES else {}).items():
                total[kind] += dollars
        return total

    def by_agent(self) -> list[dict]:
        """Each agent's tokens with each model, in the order first used, and what they cost (None without a known
        price)."""
        return [
            {"agent": name, "model": model, "usage": tokens,
             "cost": cost_breakdown(tokens, PRICES[model]) if model in PRICES else None}
            for (name, model), tokens in self.agent_tokens.items() if any(tokens.values())
        ]

    def end(self, stop_reason: str, summary: str, computer: str | None, error: Exception | None = None,
            by: str | None = None) -> None:
        """How the run ended, with the tokens used and, when prices are known and no call was cut off by a stop, what
        they cost. A failed run records the exception and its code; `by` says who stopped a task."""
        event = {
            "type": "end", "stop_reason": stop_reason, "computer": computer, "summary": summary,
            "usage": self.usage(), "cost": None if self.cut_calls else self.cost(), "agents": self.by_agent(),
        }
        if error is not None:
            event |= {"error": f"{type(error).__name__}: {error}", "error_code": error_code(error)}
        if by is not None:
            event["by"] = by
        self._write(event)

    def note(self, text: str, code: NoteCode | None = None, **data: Unpack[NoteData]) -> None:
        event: NoteEvent = {"type": "note", "text": text, "code": code, "data": data}
        self._write(event)

    def title(self, text: str, usage: dict[str, int], seconds: float, model: str) -> None:
        """The title call's result and cost; it may arrive after the run has ended."""
        price = PRICES.get(model)
        self._write({"type": "title", "text": text, "usage": usage, "seconds": round(seconds, 2),
                     "model": model, "cost": cost_breakdown(usage, price) if price else None})

    def plan(self, snapshot: PlanSnapshot) -> None:
        """The conversation's plan as it stands; like a title, it may arrive after the turn has ended."""
        self._write({"type": "plan", **snapshot})

    def task(self, id: str, agent: str, brief: str, title: str, record: str) -> None:
        """A task started from this turn; the page shows it at work from its own log, `record`."""
        self._write({"type": "task", "state": "started", "id": id, "agent": agent, "brief": brief, "title": title,
                     "record": record})

    def message(self, id: str, text: str, sent: float) -> None:
        """A message the user sent while the run worked, logged once an agent has read it; `sent` is when it came."""
        self._write({"type": "message", "id": id, "text": text, "sent": sent})

    async def confirm(
        self, call: dict, args: dict, consequence: str, png: bytes | None, auto_review: bool = False,
    ) -> str | None:
        """A step the computer-use agent asked the user to approve, with `auto_review` as the user had it then; returns
        the screenshot's file name. Not a message the model saw, so it carries none."""
        screenshot = None
        if png is not None:
            screenshot = f"{self._free(self._named(None, 'confirm'))}.png"
            await self.store.put_file(self.run, screenshot, png)
        self._event(
            "confirm", None, id=call["id"], tool=call["name"], args=args, consequence=consequence,
            screenshot=screenshot, auto_review=auto_review,
        )
        return screenshot

    def review(self, id: str, allow: bool, review: dict) -> None:
        """What auto review made of the step `id`. Its model is the main agent's, so its tokens count as the main
        agent's."""
        self._count(review.get("usage") or {}, MAIN)
        self._event("review", None, id=id, allow=allow, **review)

    def decision(self, id: str, outcome: str, note: str = "", by: str = "") -> None:
        """How the step `id` was answered: approved, declined (with what the user said), or took_control; `by` is "web",
        "cli" or "auto" (with its reason as the note)."""
        self._event("decision", None, id=id, outcome=outcome, note=note, by=by)

    async def model(self, message: AIMessage, agent: str | None = None, cut: bool = False) -> None:
        """A model's reply. The part of one a stop cut off (`cut`) has no usage: its call was counted by `cut()`."""
        calls = [{"name": call["name"], "args": call["args"]} for call in message.tool_calls]
        usage = None if cut else usage_of(message)
        if usage is not None:
            if agent == MAIN:
                self.main_calls += 1
            else:
                self.calls += 1
            self._count(usage, agent)
        record = await self._record(message, self._named(agent, "model"))
        model = {"model": self.models[agent]} if agent in self.models else {}
        self._event("model", agent, text=message.text, tool_calls=calls, usage=usage, **model, message=record)

    def cut(self) -> None:
        """A model call a stop cut off. The provider bills it, but a reply's usage comes only with its end, so the run's
        cost is not known."""
        self.cut_calls += 1

    async def action(self, call: dict, result: ToolMessage, agent: str | None = None) -> None:
        if agent == MAIN:
            self.main_actions += 1
        else:
            self.actions += 1
        record = await self._record(result, self._named(agent, call["name"]))
        content = record["data"]["content"]
        screenshot = next((block["file"] for block in content if is_image(block)), None) if isinstance(content, list) else None
        artifact = result.artifact if isinstance(result.artifact, dict) else {}
        self._event(
            "action", agent,
            n=self.main_actions if agent == MAIN else self.actions,
            id=call["id"],
            tool=call["name"],
            args=call["args"],
            status=getattr(result, "status", "success"),
            reason=artifact.get("reason"),
            **({"answer": artifact["answer"]} if "answer" in artifact else {}),
            result=text_of(result),
            screenshot=screenshot,
            message=record,
        )
