"""A conversation while it has work: the main agent's turns, one at a time, and the tasks they hand over.

A session begins with a user's message and ends once the main agent has replied, no task runs and no message waits.
The main agent wakes for a turn when the user writes or a task ends. Each turn has a log of its own, as each task has;
what the main agent has said and heard stays in memory from turn to turn. A session is named after its first turn."""

import asyncio
import contextlib
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, ToolMessage
from langgraph.graph.state import CompiledStateGraph

from computer_use.agent.background import USER, Background, Job, Resource, runtime_message
from computer_use.agent.handover import SessionMemory, task_tool
from computer_use.agent.blackboard import Blackboard
from computer_use.agent.history import latest_plan, load_conversation
from computer_use.agent.inbox import Inbox
from computer_use.agent.plan import Plan
from computer_use.agent.subagent import MakeAgent, Result, StopReason, Subagent
from computer_use.agent.trajectory import MAIN, Trajectory
from computer_use.config import RunChoices
from computer_use.middleware.chat import ChatMiddleware, Mention, RestartingDraft
from computer_use.middleware.common import raise_if_stopped, retrying_failed_streams
from computer_use.prompts import notes
from computer_use.streaming import Draft
from computer_use.tools.ask_user import ask_user
from computer_use.tools.conversations import conversation_tools
from computer_use.tools.plan import plan_tool
from computer_use.tools.tasks import TaskTool, handover_tools

# Only a backstop: a turn replies, or hands work over and replies.
MAIN_CALLS = 8


def unanswered(messages: list[BaseMessage]) -> list[ToolMessage]:
    """Results for the tool calls a stopped turn left without one, saying the outcome is unknown. Model APIs reject a
    call without a result; the action is not sent again."""
    asked = next((index for index in range(len(messages) - 1, -1, -1) if isinstance(messages[index], AIMessage)), None)
    if asked is None:
        return []
    answered = {message.tool_call_id for message in messages[asked + 1:] if isinstance(message, ToolMessage)}
    return [
        ToolMessage(content=notes.UNKNOWN_RESULT, tool_call_id=call["id"], name=call["name"], status="error")
        for call in messages[asked].tool_calls
        if call["id"] not in answered
    ]


async def next_event(inbox: Inbox, background: Background) -> None:
    waits = [asyncio.ensure_future(inbox.wait(MAIN)), asyncio.ensure_future(background.wait())]
    try:
        await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for waiting in waits:
            waiting.cancel()


def final_answer(chunk: AIMessageChunk) -> bool:
    """Whether a piece of a model's stream starts its final reply. OpenAI's Responses API marks each message's phase
    before its first word; other models' replies count as final only once the session ends."""
    blocks = chunk.content if isinstance(chunk.content, list) else []
    return any(isinstance(block, dict) and block.get("phase") == "final_answer" for block in blocks)


async def speak(agent, messages: list[BaseMessage], config: dict, draft: Draft) -> dict:
    """The main agent's turn until it ends, as the state ainvoke would return it, with its words going into the draft
    as its model writes them: the model node's text only, not what the agents it hands work to write in its tools."""
    state = {}
    stream = agent.astream({"messages": messages}, config, stream_mode=["messages", "values"])
    async with contextlib.aclosing(stream):
        async for mode, data in stream:
            if mode == "values":
                state = data
                continue
            chunk, metadata = data
            if not isinstance(chunk, AIMessageChunk) or metadata.get("langgraph_node") != "model":
                continue
            if final_answer(chunk):
                draft.answer(metadata["langgraph_checkpoint_ns"])
            if chunk.text:
                draft.add(metadata["langgraph_checkpoint_ns"], chunk.text)
    raise_if_stopped()
    return state


MainAgent = Callable[[Sequence, Sequence], CompiledStateGraph]


@dataclass(frozen=True)
class Opening:
    """How a session begins: the user's message, whether it names an agent, what the main agent heard before, and the
    tasks of earlier sessions it was never told stopped."""

    message: str
    mentioned: bool
    earlier: list[BaseMessage]
    untold: Sequence[dict]


class Session:
    """A conversation's main agent and the tasks it hands to `agents` while it has work. `first` is its first turn's
    log, begun by the caller; `resources` are what an agent's tasks hold while they run, by the agent's name;
    `computer` is the agent whose latest ending its turns' logs keep."""

    def __init__(
        self, main_agent: MainAgent, *, first: Trajectory, thread: str, agents: dict[type[Subagent], MakeAgent],
        resources: dict[str, Resource], mention: Mention | None, computer: str,
        inbox: Inbox, draft: Draft, choices: RunChoices, models: tuple[str, str], memory: SessionMemory | None,
        project: str | None, watch: str, background: Background, blackboard: Blackboard,
    ):
        self.main_agent, self.thread, self.agents, self.watch = main_agent, thread, agents, watch
        self.resources, self.mention, self.computer, self.inbox, self.draft = resources, mention, computer, inbox, draft
        self.choices, self.models, self.memory, self.project = choices, models, memory, project
        self.id, self.first = first.run, first
        self.log: Trajectory | None = first  # the turn under way
        self.turns = [first.run]
        self.background, self.blackboard = background, blackboard
        background.on_task = self.task_changed
        self.date = notes.today(choices.timezone)  # fixed while the session works, appended after the rules
        self.idle: set[str] = set()  # replies the main agent wrote while no task ran, whose hand-overs count
        self.messages: list[BaseMessage] = []
        self.tools: list = []
        self.handing: dict[str, TaskTool] = {}  # what hands a task over, by the agent's name
        self.planned = False  # this session wrote the plan: one restored from an earlier session is no work of its own
        self.turning: asyncio.Task | None = None  # the turn under way, which the user may stop on its own
        self.calls: set[asyncio.Future] = set()  # task tools' calls under way, which a stopped turn lets finish

    def latest(self) -> StopReason | None:
        return self.background.latest.get(self.computer)

    def current(self) -> Trajectory:
        """The log of the turn under way; tasks are handed over only from one."""
        return self.log

    def show_plan(self) -> None:
        """Log the plan as it stands, for the page, in the turn under way; without one, the next turn shows it."""
        if self.log is not None:
            self.blackboard.show(self.log)

    def plan_written(self, revised: bool) -> None:
        self.planned = True
        self.show_plan()
        if revised:
            self.background.notify(notes.PLAN_UPDATED)

    def task_changed(self, job: Job, outcome: Result | BaseException | None) -> None:
        """A task started or ended. One that ended leaves the main agent a word, with its result, on the steps nobody
        is on: only an agent knows whether its work is done, so the runtime marks nothing."""
        if isinstance(outcome, tuple):
            left = self.blackboard.plan.view(self.background.on_steps()) if self.planned else []
            job.plan_note = notes.plan_left([step["id"] for step in left if step["status"] == "pending"])
        self.show_plan()

    async def start(self, opening: Opening) -> HumanMessage:
        """Open the session in its first turn, closing the logs of tasks the runtime died under; the user's message,
        which the first turn answers."""
        log = self.log
        log.note(f"Goal: {opening.message}\nWatch: {self.watch}\nRun: {log.run}", "goal")
        if unknown := unanswered(opening.earlier):
            log.note(f"The previous run stopped during {', '.join(r.name for r in unknown)}; whether it happened is unknown.",
                     "interrupted", tool=", ".join(r.name for r in unknown))
            for result in unknown:
                await log.input(result, "unknown", MAIN)
        stopped = []
        for task in opening.untold:
            if task["open"]:  # nothing runs it any more
                closing = Trajectory(log.store, task["run"])
                closing.end("stopped", "", None)
                await log.store.flush(task["run"])
            told = notes.stopped_by_user if task["by"] == USER else notes.task_stopped
            note = runtime_message(told(task["id"], task["agent"], task["goal"]), "task_stopped",
                                   id=task["id"], agent=task["agent"], record=task["run"])
            await log.input(note, "stopped", MAIN)
            stopped.append(note)
        start = HumanMessage(content=opening.message)
        await log.input(start, "message", MAIN)
        self.messages = [*opening.earlier, *unknown, *stopped, start]
        if opening.mentioned:
            self.messages.append(asked := runtime_message(self.mention.asked, "mention_asked"))
            await log.input(asked, "mention-asked", MAIN)
        if opening.earlier and (saved := await latest_plan(log.store, self.thread)) is not None:
            self.blackboard.plan = Plan.restored(saved)
        rules = await self.memory.recall() if self.memory is not None else False
        tasks = [task_tool(kind, make, self.background, self.inbox, self.current, self.id, self.thread, self.memory,
                           self.resources.get(kind.agent)) for kind, make in self.agents.items()]
        self.handing = {each.agent: each for each in tasks}
        self.tools = [*handover_tools(tasks, self.background, self.inbox, with_rules=rules),
                      plan_tool(self.blackboard.plan, self.plan_written), ask_user,
                      *conversation_tools(log.store, self.thread)]
        return start

    async def hand_mentioned(self, text: str) -> str:
        """Hand the user's words to the agent they name as they are, when the main agent's reply did not; what handing
        them over answers."""
        call_id = f"runtime-{uuid.uuid4().hex[:12]}"
        handed = await self.handing[self.mention.agent].start(self.mention.title(text), text, [], [], call_id)
        return handed.text if isinstance(handed, ToolMessage) else handed

    async def open_turn(self) -> Trajectory:
        log = await Trajectory.open(self.first.store, self.first.listeners)
        computer_model, main_model = self.models
        log.start("", self.thread, computer_model, main_model, False, self.choices.approvals, self.project, self.id)
        log.uses(main_model, MAIN)
        self.turns.append(log.run)
        return log

    async def turn(self, mentioned: set[str]) -> None:
        """One turn of the main agent, in the log under way, which ends with it; `mentioned` are the ids of the user's
        messages that name an agent, not yet handed over."""
        log = self.log
        self.inbox.log = log
        given = len(self.messages)
        chat = ChatMiddleware(log, self.inbox, self.background, given, mentioned, self.draft, self.hand_mentioned,
                              self.date, self.mention, self.idle, self.calls)
        remembering = self.memory.middleware(log.run) if self.memory is not None else []
        agent = self.main_agent(
            self.tools, [*remembering, chat, retrying_failed_streams(), RestartingDraft(self.draft)]
        )
        config = {
            "recursion_limit": MAIN_CALLS * len(agent.get_graph().nodes) + 10,
            # A LangSmith trace carries the thread (its conversation) and this turn's id as metadata.
            "configurable": {"thread_id": self.thread},
            "metadata": {"run": log.run},
        }
        state = await speak(agent, self.messages, config, self.draft)
        for added in state["messages"][given:]:  # any the graph added past the hooks that log the others
            if added.id not in log.recorded:
                await log.input(added, "end", MAIN)
        self.messages = state["messages"]
        said = next((m for m in reversed(self.messages[given:]) if isinstance(m, AIMessage)), None)
        log.end("replied", said.text.strip() if said is not None else "", self.latest())
        self.draft.clear()  # in the same step as the turn's end, so the page never has both or neither
        self.log = None

    async def run(self, opening: Opening) -> str:
        """The session from its opening until it is quiet; the main agent's last reply. A stop or failure ends the
        turn under way and stops every task, which ends their logs, then is raised."""
        try:
            start = await self.start(opening)
            mentioned = {start.id} if opening.mentioned else set()
            while True:
                self.turning = asyncio.create_task(self.turn(mentioned))
                try:
                    await self.turning
                except asyncio.CancelledError:
                    if asyncio.current_task().cancelling():  # the session was stopped, not only its turn
                        raise
                    await self.stopped()
                mentioned = set()
                if not await self.woken():
                    break
                self.log = await self.open_turn()
                self.show_plan()
        except (asyncio.CancelledError, Exception) as error:
            await self.cut(error)
            for run in self.turns:
                with contextlib.suppress(Exception):  # the stop or error is what to tell; the store logs its own
                    await self.first.store.flush(run)
            raise
        finally:
            self.draft.clear()  # also a call that failed partway
            await asyncio.gather(*self.calls, return_exceptions=True)  # so no task starts after the stop
            await self.background.stop()
        for run in self.turns:  # a session ends once its turns' records are stored
            await self.first.store.flush(run)
        final = next((m for m in reversed(self.messages) if isinstance(m, AIMessage)), None)
        return final.text.strip() if final is not None else ""

    async def woken(self) -> bool:
        """Wait until the user's message, a task's question, or its end or failure wakes the main agent: True; False once nothing
        could, with no task at work. A task the user stopped does not wake it: it hears of it at its next call."""
        while not (self.background.news or self.inbox.unread(MAIN)):
            if not self.background.running:
                return False
            await next_event(self.inbox, self.background)
        return True

    def stop_turn(self) -> bool:
        """Stop the turn under way; the tasks it handed over go on. False when none is."""
        if self.turning is None or self.turning.done():
            return False
        self.turning.cancel()
        return True

    async def stopped(self) -> None:
        """End a turn the user stopped, keeping what the main agent wrote of its reply, with a note that the user
        stopped it there."""
        log = self.log
        await asyncio.gather(*self.calls, return_exceptions=True)  # hand-overs under way finish and are logged
        if self.draft.text:
            await log.model(AIMessage(content=self.draft.text), MAIN, cut=True)
        await log.store.flush(log.run)  # read back below
        self.messages = await load_conversation(log.store, self.thread)
        for result in unanswered(self.messages):  # each right after its call, as model APIs take them
            await log.input(result, "unknown", MAIN)
            self.messages.append(result)
        note = runtime_message(notes.REPLY_STOPPED_BY_USER, "reply_stopped")
        await log.input(note, "stopped", MAIN)
        self.messages.append(note)
        log.end("cancelled", "", self.latest())
        self.draft.clear()
        self.log = None

    async def cut(self, error: BaseException) -> None:
        """End the turn under way, if any, as stopped or failed; the next session is told a reply was cut off."""
        log, stopped = self.log, isinstance(error, asyncio.CancelledError)
        if log is None:
            return
        if stopped and self.draft.text:
            await log.model(AIMessage(content=self.draft.text), MAIN, cut=True)
            note = runtime_message(notes.REPLY_STOPPED, "reply_stopped")
            await log.input(note, "stopped", MAIN)
        log.end("cancelled" if stopped else "error", "", self.latest(), None if stopped else error)
        self.log = None
