"""Shared contract for the agents the main agent hands tasks to; a subclass provides its tool metadata and `run`."""

from collections.abc import Callable, Sequence
from typing import ClassVar

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, ModelCallLimitMiddleware
from langchain_core.messages import HumanMessage

from computer_use.agent.inbox import Inbox
from computer_use.middleware.common import raise_if_stopped, retrying_failed_streams
from computer_use.middleware.subagent import SubagentMiddleware
from computer_use.agent.trajectory import Trajectory
from computer_use.config import RunChoices, Settings
from computer_use.agent.history import action_lines, tasks, user_messages
from computer_use.prompts import notes
from computer_use.storage import MAIN, TURN

# How a task ended. "replied": its own last turn called no tool. The runtime stopped the others: "step_limit" when its
# last allowed model call still asked for a tool, "error" when what it works on could not be used at all, or a reason of
# its agent's own. Only a task that replied has a reply.
StopReason = str

# A task's result as the main agent reads it, and what the log keeps of it for later tasks' blackboard.
Result = tuple[list[dict], dict]


MakeAgent = Callable[[Trajectory, str], "Subagent"]


class Subagent:
    """An agent on one task the main agent handed it, started afresh on a log of its own."""

    agent: ClassVar[str]  # its name in the settings, and in start_task
    name: ClassVar[str]  # what its result calls it, e.g. "computer-use agent"
    about: ClassVar[str]  # its line in start_task's description

    def __init__(
        self,
        settings: Settings,
        log: Trajectory,
        thread: str,
        session: str,
        request: str,
        max_steps: int,
        user: Inbox,
        choices: RunChoices,
        taught: str,
    ):
        self.settings = settings
        self.choices = choices
        self.log = log
        self.session = session
        self.thread = thread  # the conversation, whose logs make the blackboard
        self.request = request  # the user's message, which every task quotes word for word
        self.max_steps = max_steps  # model calls per task
        self.user = user
        self.stop_reason: StopReason | None = None  # None until its task has ended
        self._start: HumanMessage | None = None  # the task's first message, once it is logged
        self.taught = taught  # the remembered rules its task was handed over with, word for word

    async def run(self, task: str, told: Inbox) -> Result:
        """Carry out a task, reading what the main agent tells it meanwhile (`told`)."""
        raise NotImplementedError

    async def steps(self) -> list[str]:
        return await self.actions_since(self._start) if self._start else []

    def words(self) -> list[str]:
        """The user's messages in this run so far, word for word, those the main agent has read included."""
        return [self.request, *(message.text for message in self.user.read(MAIN))]

    async def opening(self, task: str) -> str:
        requests, earlier = await self.earlier()
        return notes.opening(task, self.words(), notes.blackboard(requests, earlier), self.taught)

    async def earlier(self) -> tuple[list[str], list[dict]]:
        """For the blackboard: the user's messages before this session's, and every task before this one, this
        session's included."""
        requests, earlier = [], []
        for summary in await self.log.store.runs(self.thread):
            if summary.kind != TURN:
                continue
            events = await self.log.store.events(summary.id)
            if events and events[0]["type"] == "start" and events[0]["session"] != self.session:
                requests += user_messages(events)
            earlier += tasks(events)
        return requests, earlier

    async def actions_since(self, start: HumanMessage) -> list[str]:
        return action_lines(await self.events_since(start))

    async def events_since(self, start: HumanMessage) -> list[dict]:
        events = await self.log.store.events(self.log.run)
        begin = next(n for n, event in enumerate(events) if event.get("message", {}).get("data", {}).get("id") == start.id)
        return events[begin:]

    async def invoke(
        self, model, tools: list, prompt: str, guard: SubagentMiddleware, start: HumanMessage,
        middleware: Sequence[AgentMiddleware] = (),
    ) -> str:
        """Run the task's agent until it replies or the runtime stops it; its reply, and how it stopped in
        `stop_reason`. The middleware runs in order: `guard`, the agent's own, the model call limit, then retries of
        failed streams. Middleware every subagent needs goes in this list."""
        stack = [
            guard, *middleware, ModelCallLimitMiddleware(run_limit=self.max_steps, exit_behavior="end"),
            retrying_failed_streams(),
        ]
        agent = create_agent(model, tools, system_prompt=prompt, middleware=stack)
        config = {
            # Each model call passes through every graph node once; only a backstop: the model call limit ends the
            # task first.
            "recursion_limit": self.max_steps * len(agent.get_graph().nodes) + 10,
            # A LangSmith trace carries this run's id as metadata.
            "metadata": {"run": self.log.run},
        }
        state = await agent.ainvoke({"messages": [start]}, config)
        raise_if_stopped()
        # The model call limit's closing message is added by the graph itself, past the hooks that log the others.
        for message in state["messages"][1:]:
            if message.id not in self.log.recorded:
                await self.log.input(message, "end")
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
        """How the task ended, in the main agent's words."""
        raise NotImplementedError

    def report(self, reply: str, actions: list[str], after: str = "") -> str:
        return notes.report(self.name, self.how(), reply, actions, after)
