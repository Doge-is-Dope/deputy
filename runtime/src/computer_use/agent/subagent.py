"""Shared contract and history for agents delegated by the main agent.

Each task gets fresh context: its brief, verbatim user messages and a bounded
text history. A subclass provides its tool metadata and run implementation."""

from typing import ClassVar, Literal

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware
from langchain_core.messages import HumanMessage

from computer_use.agent.inbox import Inbox
from computer_use.agent.middleware import SubagentMiddleware
from computer_use.agent.trajectory import Trajectory
from computer_use.config import RunChoices, Settings
from computer_use.agent.history import action_lines, action_records, tasks, user_messages
from computer_use.prompts import notes
from computer_use.storage import MAIN

# How a task ended. The agent stopped itself by replying ("replied"): its own last turn called no tool, however many
# model calls that took, as Anthropic's and OpenAI's agent loops tell a finished run. The runtime stopped the others:
# "step_limit" when its last allowed model call still asked for a tool, "stuck" when its actions kept leaving the
# screen as it was, "disconnected" when the desktop did not reconnect in time, "declined" when the user declined
# MAX_DECLINES of its steps (agent.confirm), "error" when what it works on could not be used at all. Only a task that
# replied has a reply.
StopReason = Literal["replied", "step_limit", "stuck", "disconnected", "declined", "error"]

# A task's result as the main agent reads it (text, and maybe a screenshot), and what the log keeps of it for the
# blackboard of later tasks: how it stopped, its reply and its actions.
Result = tuple[list[dict], dict]


class Subagent:
    """An agent of one run that the main agent hands tasks to, each to a copy of its own, started afresh on the run's
    log."""

    tool: ClassVar[str]  # the main agent's tool that hands it a task
    agent: ClassVar[str]  # its name in the settings
    name: ClassVar[str]  # what the main agent calls it, e.g. "computer agent"
    description: ClassVar[str]  # that tool's description
    brief: ClassVar[str]  # what that tool's task argument should say
    prompt: ClassVar[str]  # its part of the main agent's prompt
    uses_computer: ClassVar[bool] = False  # it takes the computer (the run lock) while it works

    def __init__(
        self,
        settings: Settings,
        log: Trajectory,
        thread: str,
        request: str,
        max_steps: int,
        user: Inbox | None = None,
        choices: RunChoices = RunChoices(),
    ):
        self.settings = settings
        self.choices = choices  # what the user chose for the run: the agents' models, how steps are approved
        self.log = log
        self.thread = thread  # the conversation, whose logs make the blackboard
        self.request = request  # the user's message, which every task quotes word for word
        self.max_steps = max_steps  # model calls per task
        self.user = user if user is not None else Inbox()  # what the user sends while the run works
        self.stop_reason: StopReason | None = None  # how the last task ended; None until one has run
        self._start: HumanMessage | None = None  # the task's first message, once it is logged
        self.task: str | None = None  # the task's id, which its events in the log carry
        self.taught = ""  # the rules the user taught that its task was handed over with, word for word

    async def run(self, task: str, told: Inbox) -> Result:
        """Carry out a task, reading what the main agent tells it meanwhile (`told`): its result for the main agent."""
        raise NotImplementedError

    async def steps(self) -> list[str]:
        """The running task's steps so far, read back from the log: what it said, what it did, and what came of it."""
        return await self.actions_since(self._start) if self._start else []

    def words(self) -> list[str]:
        """The user's messages in this run so far, word for word: the one it answers, and those the main agent has
        read that they sent while it worked."""
        return [self.request, *(message.text for message in self.user.read(MAIN))]

    async def opening(self, task: str) -> str:
        """The task's first message: its goal, the user's words, and the blackboard of the conversation so far."""
        requests, earlier = await self.earlier()
        return notes.opening(task, self.words(), notes.blackboard(requests, earlier), self.taught)

    async def earlier(self) -> tuple[list[str], list[dict]]:
        """The conversation so far, read back from its logs, for the blackboard: the user's messages before this
        run's, and every task before this one, this run's included."""
        requests, earlier = [], []
        for run in await self.log.store.conversation(self.thread):
            events = await self.log.store.events(run)
            if run != self.log.run and events and events[0]["type"] == "start":
                requests += user_messages(events)
            earlier += tasks(events)
        return requests, earlier

    async def records(self) -> list[str]:
        """Every action whose input an agent sent in this conversation, this task's included: tools and arguments
        only, as the runtime recorded them."""
        runs = await self.log.store.conversation(self.thread)
        return [record for run in runs for record in action_records(await self.log.store.events(run))]

    async def actions_since(self, start: HumanMessage) -> list[str]:
        """The task's actions, read back from the log: those after its first message."""
        return action_lines(await self.events_since(start))

    async def events_since(self, start: HumanMessage) -> list[dict]:
        """Only this task's records, including its initial observation."""
        events = [event for event in await self.log.store.events(self.log.run) if event.get("task") == self.task]
        begin = next(n for n, event in enumerate(events) if event.get("message", {}).get("data", {}).get("id") == start.id)
        return events[begin:]

    async def invoke(self, model, tools: list, prompt: str, guard: SubagentMiddleware, start: HumanMessage) -> str:
        """Run the task's agent from its first message until it replies or the runtime stops it; its reply, and how it
        stopped in `stop_reason`. Each step logs its messages as they arrive (a reply before its action runs), so the
        log is the record."""
        agent = create_agent(
            model, tools, system_prompt=prompt,
            middleware=[guard, ModelCallLimitMiddleware(run_limit=self.max_steps, exit_behavior="end")],
        )
        config = {
            # Each model call passes through every graph node once (middleware hooks, model, tools). The recursion
            # limit is only a backstop; the model call limit ends the task first.
            "recursion_limit": self.max_steps * len(agent.get_graph().nodes) + 10,
            # A LangSmith trace carries this run's id as metadata.
            "metadata": {"run": self.log.run},
        }
        state = await agent.ainvoke({"messages": [start]}, config)
        # The model call limit's closing message is added by the graph itself, past the hooks that log the others.
        for message in state["messages"][1:]:
            if message.id not in self.log.recorded:
                self.log.input(message, "end")
        # The transcript's last message may be the runtime's (the model call limit's, or the guard's), not the agent's.
        own = guard.last
        if guard.stopped is not None:
            self.stop_reason = guard.stopped
        elif own is not None and not own.tool_calls:
            self.stop_reason = "replied"
        else:
            self.stop_reason = "step_limit"
        return own.text.strip() if self.stop_reason == "replied" else ""

    def how(self) -> str:
        """How the last task ended, in the main agent's words (its prompts module's `stopped`)."""
        raise NotImplementedError

    def report(self, reply: str, actions: list[str], after: str = "") -> str:
        """A task's result as the main agent reads it (`notes.report`)."""
        return notes.report(self.name, self.how(), reply, actions, after)
