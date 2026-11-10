"""The main agent, which talks with the user and hands work to agents, and a run of it.

A run is a session of the conversation (agent.session): it ends when the main agent has replied, no task runs and no
message waits."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage

from computer_use.agent import title
from computer_use.agent.background import Background
from computer_use.agent.blackboard import Blackboard
from computer_use.agent.coding_agent import CodingAgent
from computer_use.agent.computer_agent import MENTION, ComputerAgent
from computer_use.agent.history import can_continue, load_conversation, untold
from computer_use.agent.inbox import Inbox
from computer_use.agent.models import MAIN_AGENT, build_chat_model, chosen
from computer_use.agent.plan import Plan
from computer_use.agent.session import Opening, Session
from computer_use.agent.subagent import MakeAgent, StopReason, Subagent, TaskContext
from computer_use.agent.tracing import configure_tracing
from computer_use.agent.trajectory import MAIN, Listener, Trajectory
from computer_use.computers import Computer
from computer_use.config import Approvals, RunChoices, Settings
from computer_use.desktop.control import Control, RunLock, hand_over
from computer_use.desktop.judge import ScreenJudge
from computer_use.execution.desktop import DesktopResource
from computer_use.memory import MemoryStore
from computer_use.middleware.memory import UserMemory
from computer_use.middleware.skills import SkillsMiddleware
from computer_use.prompts.main import MAIN_PROMPT
from computer_use.sandbox import CodeRunner
from computer_use.storage import Runs
from computer_use.streaming import Draft

# The agents the main agent may hand work to with start_task.
SUBAGENTS: tuple[type[Subagent], ...] = (ComputerAgent, CodingAgent)


def main_agent(model: BaseChatModel, tools: Sequence, middleware: Sequence):
    """The main agent for one turn: its model, its tools and what runs around its calls, after its skills."""
    return create_agent(
        model,
        tools,
        system_prompt=MAIN_PROMPT,
        middleware=[SkillsMiddleware(MAIN_AGENT), *middleware],
    )


@dataclass
class TurnResult:
    reply: str
    run: str
    computer: StopReason | None  # how the last desktop task ended; None when the desktop was not used


async def run_turn(
    settings: Settings,
    message: str,
    *,
    max_steps: int,
    computer: Computer,
    control: Control,
    store: Runs,
    listeners: Sequence[Listener] = (),
    thread: str | None = None,
    force_computer: bool = False,
    take_control: bool = False,
    inbox: Inbox | None = None,
    draft: Draft | None = None,
    code_runner: CodeRunner | None = None,
    judge: ScreenJudge | None = None,
    choices: RunChoices = RunChoices(),
    titles: title.Titles | None = None,
    approvals: Callable[[], Approvals] | None = None,
    project: str | None = None,
    memory: MemoryStore | None = None,
    opened: Callable[[Session], None] | None = None,
    sent: float | None = None,
) -> TurnResult:
    """Answer a message, continuing `thread` when given; the run belongs to the store's user, in `project` when it
    begins a conversation there.

    Raises ValueError if the thread cannot be continued, and DesktopBusy if force_computer, or a message that mentions
    the desktop, finds the RunLock held. take_control transfers ownership only after the lock is acquired. Failure or
    cancellation stops the tasks and closes the log with usage, then raises.

    `max_steps` limits each task. `choices` fixes the models for the session; `approvals` is read for each step."""
    configure_tracing()
    earlier: list[BaseMessage] = []
    stopped: list[dict] = []
    if thread is not None:
        if not await can_continue(store, thread):
            raise ValueError(f"conversation {thread} is missing or uses an unsupported log format")
        earlier = await load_conversation(store, thread)
        stopped = await untold(store, thread)
    main = chosen(settings, MAIN_AGENT, choices.agents)  # the main agent's, for the whole session
    inbox = inbox if inbox is not None else Inbox()
    lock = RunLock(settings.run_lock_path)
    draft = draft if draft is not None else Draft()
    approvals = approvals if approvals is not None else lambda: choices.approvals
    force_computer = force_computer or MENTION.said(message)
    if force_computer:
        lock.acquire()
    try:
        # Control is not taken unasked: a task that starts while the user has the desktop waits until they return it.
        if take_control and lock.held:
            await hand_over(control, computer, "agent", "returned by user")
        log = await Trajectory.open(store, listeners)
        if lock.held:
            lock.name(log.run)
        computer_model = chosen(settings, ComputerAgent.agent, choices.agents).model
        log.start(message, thread, computer_model, main.model, force_computer, choices.approvals, project, sent=sent)
        log.uses(main.model, MAIN)
        inbox.log = log
        thread = thread or log.run
        if titles is not None:
            titles.start(log, thread)
        background = Background()
        blackboard = Blackboard(store, thread, log.run, Plan(), background)
        context = TaskContext(
            settings=settings, thread=thread, request=message, max_steps=max_steps, user=inbox, choices=choices,
            blackboard=blackboard,
        )
        agents: dict[type[Subagent], MakeAgent] = {
            ComputerAgent: lambda task, taught: ComputerAgent(
                context, task, taught, computer, control, approvals, judge,
            ),
        }
        if code_runner is not None and (await code_runner.status()).connected:
            agents[CodingAgent] = lambda task, taught: CodingAgent(context, task, taught, code_runner)
        # A message that continues a conversation is in the conversation's project, as its first turn says.
        if thread != log.run and (runs := await store.runs(thread)):
            project = runs[0].project
        remembering = (
            UserMemory(memory, store.user, project, thread, learn=choices.learn, use=choices.recall)
            if memory is not None else None
        )
        session = Session(
            partial(main_agent, build_chat_model(main, settings, stream=True)), first=log, thread=thread,
            agents=agents, resources={ComputerAgent.agent: DesktopResource(computer, lock)}, mention=MENTION,
            computer=ComputerAgent.agent, inbox=inbox, draft=draft, choices=choices,
            models=(computer_model, main.model), memory=remembering, project=project,
            watch=settings.web_url, background=background, blackboard=blackboard,
        )
        if opened is not None:  # the caller's hold on it, to stop its turn or a task on its own
            opened(session)
        reply = await session.run(Opening(message, force_computer, earlier, stopped))
        return TurnResult(reply, log.run, session.latest())
    finally:
        if lock.held:
            lock.release()

