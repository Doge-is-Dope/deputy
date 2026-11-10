"""The main agent's turns: what the user sends and tasks report while it works, messages that name an agent handed to
it, the limit on hand-overs, and every message logged as it arrives."""

import asyncio
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool

from computer_use.agent.background import Background, from_user, runtime_message
from computer_use.streaming import Draft
from computer_use.agent.inbox import Inbox
from computer_use.agent.plan import MAX_STEPS
from computer_use.agent.trajectory import MAIN, Trajectory
from computer_use.middleware.common import prune_screenshots, with_section
from computer_use.prompts import notes
from computer_use.tools.ask_user import ASK_USER
from computer_use.tools.common import not_executed
from computer_use.tools.plan import WRITE_PLAN
from computer_use.tools.tasks import START_TASK, STOP_TASK, TELL_TASK

# Allow a round of hand-overs plus one retry for each step of the plan, or for a message without one. Only the rounds
# handed over while none of the run's tasks runs count: work handed over while some run spreads past the most tasks at
# once.
ROUNDS_PER_STEP = 2
MENTION_TITLE = 20


@dataclass(frozen=True)
class Mention:
    """How the user sends a message to an agent by naming it, and what the main agent hears of it: that it hands the
    message over in this reply (`asked`), or that the runtime did as it did not (`handed`)."""

    agent: str
    words: re.Pattern
    asked: str
    handed: str

    def said(self, message: str) -> bool:
        return self.words.search(message) is not None

    def title(self, message: str) -> str:
        """The title of a message the runtime hands over itself: its first words, without the mention."""
        words = " ".join(self.words.sub("", message).split())
        return words if len(words) <= MENTION_TITLE else words[:MENTION_TITLE - 1] + "…"


def over_limit(request, idle: set[str]) -> ToolMessage | None:
    """A refusal once the user's latest message has used its rounds of hand-overs: ROUNDS_PER_STEP for each step of the
    latest plan, this reply's included, or for the message without one. Only the replies the main agent wrote while none
    of its tasks ran (`idle`, by id) count."""
    if request.tool_call["name"] != START_TASK:
        return None
    messages = request.state["messages"]
    latest = next(index for index in range(len(messages) - 1, -1, -1) if from_user(messages[index]))
    steps, rounds = 1, 0
    for index, message in enumerate(messages):
        if not isinstance(message, AIMessage):
            continue
        for call in message.tool_calls:
            if call["name"] == WRITE_PLAN and isinstance(written := call["args"].get("steps"), list):
                steps = min(max(len(written), 1), MAX_STEPS)
        if index > latest and message.id in idle and any(call["name"] == START_TASK for call in message.tool_calls):
            rounds += 1
    if rounds <= ROUNDS_PER_STEP * steps:
        return None
    return not_executed(request.tool_call, notes.message_rounds(ROUNDS_PER_STEP * steps), "taskLimit")


def lost_arguments(reply: AIMessage, tools: Sequence) -> bool:
    """Whether a call came back with no arguments though its tool requires some: a stream can lose them all."""
    empty = {call["name"] for call in reply.tool_calls if not call["args"]}
    return any(
        isinstance(each, BaseTool) and each.name in empty
        and convert_to_openai_tool(each)["function"]["parameters"].get("required")
        for each in tools
    ) if empty else False


class RestartingDraft(AgentMiddleware):
    """Inside the retries of the main agent's model calls (common.retrying_failed_streams): each try writes its draft
    afresh, what a failed one wrote taken back. A reply whose calls lost their arguments is sent for once more; if that
    one lost them too, the calls fail and the model hears why."""

    def __init__(self, draft: Draft):
        super().__init__()
        self.draft = draft

    async def awrap_model_call(self, request, handler):
        self.draft.restart()
        response = await handler(request)
        if lost_arguments(response.result[-1], request.tools):
            self.draft.restart()
            response = await handler(request)
        return response


class ChatMiddleware(AgentMiddleware):
    """Handle steering, task reports, delegation limits, messages that name an agent, and logging."""

    def __init__(
        self, log: Trajectory, inbox: Inbox, background: Background, given: int, mentioned: set[str], draft: Draft,
        hand_mentioned: Callable[[str], Awaitable[str]], date: str, mention: Mention | None, idle: set[str],
        calls: set[asyncio.Future],
    ):
        super().__init__()
        self.log = log
        self.inbox = inbox
        self.background = background
        self.given = given  # messages the turn started with, logged already
        self.mentioned = mentioned  # the ids of the user's messages that name an agent, not handed over yet
        self.hand_mentioned = hand_mentioned  # hands such messages over when the main agent's reply does not
        self.date = date  # fixed for the run, appended after the rules and recalled memory
        self.notes: list[HumanMessage] = []  # the runtime's words for its next call, after its last calls' results
        self.draft = draft
        self.busy = False  # whether tasks ran when the main agent's model was last called
        self.idle = idle  # its replies written while none ran, whose hand-overs count (over_limit), across turns
        self.calls = calls  # its task tools' calls under way, each to finish even if the turn is stopped
        self.mention = mention  # how the user names an agent, if they can

    @hook_config(can_jump_to=["end"])
    async def abefore_model(self, state, runtime) -> dict | None:
        """Inject what arrived since the last call: task reports, the runtime's notes, and the user's messages word for
        word. A message naming a free agent comes with the runtime's word that it does; one naming an agent at work is
        the main agent's to pass on. With none, a turn that has just handed work over or told a task something ends
        there: nothing asks the main agent for more until a task ends or the user writes."""
        messages = self.background.reports()
        for message in messages:
            await self.log.input(message, "task-ended", MAIN)
        for note in self.notes:
            await self.log.input(note, "mention-handed", MAIN)
        messages += self.notes
        self.notes = []
        sent = self.inbox.take(MAIN)
        for each in sent:
            message = HumanMessage(content=each.text, id=each.id)
            await self.log.input(message, "message", MAIN)
            messages.append(message)
            if self.names_a_free_agent(each.text):
                self.mentioned.add(each.id)
                messages.append(asked := runtime_message(self.mention.asked, "mention_asked"))
                await self.log.input(asked, "mention-asked", MAIN)
        if sent and (status := await self.background.status()) is not None:
            await self.log.input(status, "task-status", MAIN)
            messages.append(status)
        if messages:
            return {"messages": messages}
        # The results of its last reply's calls: work handed over, or a task told something, waits on the task; a
        # question waits on the user.
        results = []
        for message in reversed(state["messages"]):
            if not isinstance(message, ToolMessage):
                break
            results.append(message)
        if any(result.name in (START_TASK, TELL_TASK, ASK_USER) and result.status != "error" for result in results):
            return {"jump_to": "end"}
        return None

    def names_a_free_agent(self, message: str) -> bool:
        return (self.mention is not None and self.mention.said(message)
                and self.background.working(self.mention.agent) is None)

    async def awrap_model_call(self, request, handler):
        self.busy = self.background.running
        dated = with_section(request, self.date)
        try:
            return await handler(dated.override(messages=prune_screenshots(request.messages)))
        except asyncio.CancelledError:
            self.log.cut()
            raise

    @hook_config(can_jump_to=["model"])
    async def aafter_model(self, state, runtime) -> dict | None:
        for message in state["messages"][self.given:]:
            if isinstance(message, AIMessage) and message.id not in self.log.recorded:
                await self.log.model(message, MAIN)
        if isinstance(newest := state["messages"][-1], AIMessage) and not self.busy:
            self.idle.add(newest.id)
        self.draft.clear()  # in the same step as the log line, so the page never has both or neither
        if isinstance(newest, AIMessage) and self.mentioned:
            return await self.to_the_mentioned(state["messages"], newest)
        return None

    async def to_the_mentioned(self, messages: list[BaseMessage], reply: AIMessage) -> dict | None:
        """The user's messages that name an agent go to it: by the main agent's reply, or, when the reply hands none
        over (a plan written first is not that reply yet), by the runtime, as they are. The main agent hears so at once
        when its reply called nothing, else after the results of what it called."""
        if {call["name"] for call in reply.tool_calls} == {WRITE_PLAN}:
            return None
        asked = [message.text for message in messages if message.id in self.mentioned]
        self.mentioned.clear()
        handing = (call["args"].get("agent") for call in reply.tool_calls if call["name"] == START_TASK)
        if self.mention.agent in handing:
            return None
        handed = await self.hand_mentioned("\n\n".join(asked))
        note = runtime_message(self.mention.handed + handed, "mention_handed")
        if reply.tool_calls:
            self.notes.append(note)
            return None
        await self.log.input(note, "mention-handed", MAIN)
        return {"messages": [note], "jump_to": "model"}

    async def awrap_tool_call(self, request, handler):
        if request.tool_call["name"] not in (START_TASK, TELL_TASK, STOP_TASK):
            return await self.call(request, handler)
        # A stop of the turn lets a hand-over finish and be logged, so whether it happened is known.
        call = asyncio.ensure_future(self.call(request, handler))
        self.calls.add(call)
        call.add_done_callback(self.calls.discard)
        return await asyncio.shield(call)

    async def call(self, request, handler):
        result = over_limit(request, self.idle) or await handler(request)
        await self.log.action(request.tool_call, result, MAIN)
        return result
