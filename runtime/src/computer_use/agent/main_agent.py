"""The main agent, which talks with the user and hands work to agents, and a run of it.

A run is a session of the conversation (agent.session): it ends when the main agent has replied, no task runs and no
message waits."""

import contextlib
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from functools import partial

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel

from computer_use.agent import title
from computer_use.agent.background import Background
from computer_use.agent.blackboard import Blackboard
from computer_use.agent.coding_agent import CodingAgent
from computer_use.agent.computer_agent import MENTION, ComputerAgent, DesktopResource
from computer_use.agent.history import Earlier, take_up
from computer_use.agent.inbox import Inbox
from computer_use.agent.models import MAIN_AGENT, build_chat_model, chosen
from computer_use.agent.plan import Plan
from computer_use.agent.session import Opening, Session
from computer_use.agent.subagent import MakeAgent, Subagent, TaskContext
from computer_use.agent.tracing import configure_tracing
from computer_use.agent.trajectory import MAIN, Listener, Trajectory
from computer_use.computers import Computer
from computer_use.config import Approvals, RunChoices, Settings
from computer_use.desktop.control import Control, RunLock, hand_over
from computer_use.desktop.judge import ScreenJudge
from computer_use.native.lease import Lease
from computer_use.memory import MemoryStore
from computer_use.middleware.memory import UserMemory
from computer_use.middleware.skills import SkillsMiddleware
from computer_use.prompts.main import MAIN_PROMPT
from computer_use.sandbox import CodeRunner, CodeRunnerError
from computer_use.tools.coding import Attached
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
    windows: Lease | None = None,
    choices: RunChoices = RunChoices(),
    titles: title.Titles | None = None,
    approvals: Callable[[], Approvals] | None = None,
    project: str | None = None,
    memory: MemoryStore | None = None,
    opened: Callable[[Session], None] | None = None,
    sent: float | None = None,
    media: Sequence[dict] = (),
    kept: Callable[[], Awaitable[None]] | None = None,
) -> TurnResult:
    """Answer a message, continuing `thread` when given; the run belongs to the store's user, in `project` when it
    begins a conversation there.

    Raises ValueError if the thread cannot be continued, and DesktopBusy if force_computer finds the RunLock held. take_control transfers ownership only after the lock is acquired. Failure or
    cancellation stops the tasks and closes the log with usage, then raises.

    `max_steps` limits each task. `choices` fixes the models for the session; `approvals` is read for each step."""
    configure_tracing()
    earlier = await take_up(store, thread) if thread is not None else Earlier()
    main = chosen(settings, MAIN_AGENT, choices.agents)  # the main agent's, for the whole session
    inbox = inbox if inbox is not None else Inbox()
    lock = RunLock(settings.run_lock_path)
    draft = draft if draft is not None else Draft()
    approvals = approvals if approvals is not None else lambda: choices.approvals
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
        thread = thread or log.run
        if titles is not None:
            titles.start(log, thread)
        background = Background()
        blackboard = Blackboard(store, thread, log.run, Plan(), background)
        blackboard.add_turns(earlier.logs)
        context = TaskContext(
            settings=settings, thread=thread, request=message, max_steps=max_steps, user=inbox, choices=choices,
            blackboard=blackboard,
        )
        agents: dict[type[Subagent], MakeAgent] = {
            ComputerAgent: lambda task, taught: ComputerAgent(
                context, task, taught, computer, control, approvals, judge, windows,
            ),
        }
        # Offered while the runner is down too: a task then fails at once, saying so, rather than going to the desktop.
        attached = None
        if code_runner is not None:
            attached = Attached(code_runner, store, thread, earlier.logs,
                                [each for each in media if "filename" in each], log.run)
            agents[CodingAgent] = lambda task, taught: CodingAgent(context, task, taught, code_runner, attached)
        # A message that continues a conversation is in the conversation's project, as its first turn says.
        if earlier.logs:
            project = earlier.project
        remembering = (
            UserMemory(memory, store.user, project, thread, learn=choices.learn, use=choices.recall)
            if memory is not None else None
        )

        async def stored() -> None:
            """The message and its files are in the run's store: its uploads can go, and its files to the folder."""
            if kept is not None:
                await kept()
            if attached is not None:
                with contextlib.suppress(CodeRunnerError):  # left for a coding task, which says the runner is down
                    await attached.put_new()

        session = Session(
            partial(main_agent, build_chat_model(main, settings, stream=True)), first=log, thread=thread,
            agents=agents, resources={ComputerAgent.agent: DesktopResource(computer, lock)}, mention=MENTION,
            inbox=inbox, draft=draft, choices=choices,
            models=(computer_model, main.model), memory=remembering, project=project,
            watch=settings.web_url, background=background, blackboard=blackboard,
        )
        if opened is not None:  # the caller's hold on it, to stop its turn or a task on its own
            opened(session)
        reply = await session.run(Opening(message, force_computer, earlier, media, stored if media else None))
        return TurnResult(reply, log.run)
    finally:
        if lock.held:
            lock.release()

