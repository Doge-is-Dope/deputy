"""Run lifecycle shared by the HTTP endpoints: task ownership, steering messages, drafts, and cancellation.

Durable events are written by run_turn; drafts and inboxes exist only while a run is active here. Only this
server runs agents; another server sharing the desktop, as the eval's does, shows through the desktop lock.
"""

import asyncio
import traceback
from dataclasses import dataclass, replace

from computer_use.memory import MemoryStore
from computer_use.agent.main_agent import forced, run_turn
from computer_use.agent.draft import Draft
from computer_use.agent.inbox import Inbox, Message
from computer_use.agent.trajectory import print_event
from computer_use.agent.title import Titles
from computer_use.computers import Computer
from computer_use.sandbox import CodeRunner
from computer_use.storage import LOCAL_USER, RunStore
from computer_use.config import Approvals, RunChoices, Settings


class ConversationBusy(RuntimeError):
    """The conversation is occupied: `run` is its id, None while starting or deleting."""

    def __init__(self, run: str | None):
        super().__init__(f"this conversation is busy: {run or 'starting or being deleted'}")
        self.run = run


@dataclass
class Running:
    """Active run state: task, inbox, draft, limits and the latest user choices."""

    run: str | None
    task: asyncio.Task | None
    inbox: Inbox
    max_steps: int
    draft: Draft
    choices: RunChoices = RunChoices()
    user: str = LOCAL_USER  # whose the conversation is


class Runner:
    """The runs this server started, while they go on: one per conversation, any number of conversations. Which run
    has the desktop, started here or by another server sharing it, is the run lock's to say."""

    def __init__(
        self, settings: Settings, computer: Computer, store: RunStore, code_runner: CodeRunner | None = None,
        memory: MemoryStore | None = None,
    ):
        self.settings = settings
        self.computer = computer
        self.store = store  # where the runs are kept
        self.code_runner = code_runner  # where the coding agent's commands run; None: no coding agent
        self.memory = memory  # what the agent remembers for each user; None: nothing
        self.runs: dict[str, Running] = {}  # by conversation
        self.error: dict | None = None  # the last run that died with an error: its id and the error
        self.following: set[asyncio.Task] = set()  # runs being started with what an ended run did not read
        self.closing = False  # the server is shutting down: what its runs did not read goes nowhere
        self.titles = Titles(settings, self.store)

    def running(self, user: str | None = None) -> dict[str, str]:
        """The runs in progress, by conversation; only `user`'s, when given."""
        return {
            thread: each.run for thread, each in self.runs.items()
            if each.run is not None and user in (None, each.user)
        }

    def inbox(self, run: str) -> Inbox | None:
        """The messages of a run in progress, or None for one that has ended or was not started here."""
        return next((each.inbox for each in self.runs.values() if each.run == run), None)

    def draft(self, run: str) -> Draft | None:
        """The reply the main agent of a run in progress is writing, or None for a run that has ended or was not
        started here."""
        return next((each.draft for each in self.runs.values() if each.run == run), None)

    def send(self, thread: str, text: str, choices: RunChoices = RunChoices()) -> tuple[str, Message] | None:
        """Hand a message to the conversation's run in progress: (its id, the message), or None when the conversation
        has no run here. ConversationBusy while its run is starting. The run keeps the models it started with: those
        sent with the message are the next run's, should it carry on with what this one did not read. How steps are
        approved applies from its next step that needs approval."""
        running = self.runs.get(thread)
        if running is None:
            return None
        if running.run is None:
            raise ConversationBusy(None)
        running.choices = choices
        return running.run, running.inbox.put(text)

    def choose(self, run: str, approvals: Approvals) -> bool:
        """Answer a run's next step that needs approval as the user just chose in the page's settings; False for a run
        that has ended or was not started here."""
        running = next((each for each in self.runs.values() if each.run == run), None)
        if running is None:
            return False
        running.choices = replace(running.choices, approvals=approvals)
        return True

    async def delete(self, thread: str) -> list[str]:
        """Reserve an idle conversation while its records are read and moved to trash."""
        if thread in self.runs:
            raise ConversationBusy(self.runs[thread].run)
        self.runs[thread] = Running(None, None, Inbox(), 0, Draft())
        try:
            return await self.store.delete(thread)
        finally:
            self.runs.pop(thread, None)

    async def start(
        self,
        goal: str,
        max_steps: int,
        thread: str | None = None,
        force_computer: bool = False,
        take_control: bool = False,
        choices: RunChoices = RunChoices(),
        project: str | None = None,
        user: str = LOCAL_USER,
    ) -> str:
        """Start a run of `user`'s in the background, with their `choices` for it, in `project` for a new conversation
        begun there on the page, and return its id once its log exists.
        ConversationBusy while the conversation has a run in progress; DesktopBusy, for a message for the desktop, while
        another run has it."""
        running = Running(None, None, Inbox(), max_steps, Draft(), choices, user)
        if thread is not None:
            if thread in self.runs:
                raise ConversationBusy(self.runs[thread].run)
            # Before anything awaits, so a second message at once is turned away.
            self.runs[thread] = running
        started = asyncio.get_running_loop().create_future()

        def on_event(event: dict) -> None:
            running.draft.stream.record(event)
            if event["type"] == "start" and not started.done():
                started.set_result(event["run"])

        listeners = (print_event, on_event)
        task = asyncio.create_task(
            run_turn(
                self.settings, goal, max_steps, self.computer, self.store, listeners, thread, force_computer,
                take_control, running.inbox, running.draft, self.code_runner, choices, titles=self.titles,
                approvals=lambda: running.choices.approvals, project=project, user=user, memory=self.memory,
            )
        )
        try:
            await asyncio.wait([started, task], return_when=asyncio.FIRST_COMPLETED)
            if not started.done():  # it failed before it began, e.g. another run has the desktop
                started.cancel()
                task.result()
        except BaseException:
            if thread is not None:
                self.runs.pop(thread, None)
            raise
        running.run, running.task = started.result(), task
        key = thread or running.run  # a new conversation is named after its first run
        self.runs[key] = running
        task.add_done_callback(lambda done: self._ended(key, running, done))
        return running.run

    def _ended(self, thread: str, running: Running, task: asyncio.Task) -> None:
        running.draft.stream.close()  # subscribed readers keep their own queued data after ownership is removed
        if self.runs.get(thread) is running:
            del self.runs[thread]
        unread = running.inbox.close()
        if not task.cancelled() and (error := task.exception()) is not None:
            traceback.print_exception(error)
            self.error = {"run": running.run, "message": f"{type(error).__name__}: {error}"}
        # What the run did not read goes on as the conversation's next message, once it ends or is stopped.
        if unread and not self.closing:
            follow = asyncio.get_running_loop().create_task(
                self._follow(thread, unread, running.max_steps, running.choices, running.user)
            )
            self.following.add(follow)
            follow.add_done_callback(self.following.discard)

    async def _follow(
        self, thread: str, unread: list[Message], max_steps: int, choices: RunChoices, user: str
    ) -> None:
        """Start the conversation's next run with the first message an ended run did not read, and the choices sent
        last; the others go to it as sent while it works."""
        first, *rest = unread
        try:
            await self.start(first.text, max_steps, thread, forced(first.text), choices=choices, user=user)
        except Exception as error:  # e.g. another run took the desktop meanwhile
            traceback.print_exception(error)
            return
        for message in rest:
            self.runs[thread].inbox.put(message.text)

    def started(self, run: str) -> bool:
        return run in self.running().values()

    async def stop(self, run: str | None = None) -> None:
        """Cancel a run, or every run; each log ends as cancelled, and its conversation's next message carries on."""
        tasks = [
            each.task for each in list(self.runs.values())
            if each.task is not None and not each.task.done() and run in (None, each.run)
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(tasks)

    async def close(self) -> None:
        """Stop every run as the server shuts down, starting none with what they did not read."""
        self.closing = True
        await self.stop()
        await self.titles.close()
        if self.code_runner is not None:
            await self.code_runner.close()
