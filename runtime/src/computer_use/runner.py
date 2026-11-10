"""Run lifecycle shared by the HTTP endpoints: task ownership, steering messages, drafts, and cancellation.

Drafts and inboxes exist only while a run is active here. Another server sharing the desktop shows through the
desktop lock.
"""

import asyncio
import traceback
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace

from computer_use.agent.session import Session
from computer_use.agent.inbox import Inbox, Message
from computer_use.agent.title import Titles
from computer_use.streaming import Draft, Live
from computer_use.storage import LOCAL_USER, TURN, RunStore
from computer_use.config import Approvals, RunChoices


class ConversationBusy(RuntimeError):
    """The conversation is occupied: `run` is its id, None while starting or deleting."""

    def __init__(self, run: str | None):
        super().__init__(f"this conversation is busy: {run or 'starting or being deleted'}")
        self.run = run


@dataclass
class Running:
    """A session in progress, with the logs it has open: the turn under way, if any, and the tasks at work."""

    run: str | None  # its first turn's id
    task: asyncio.Task | None
    inbox: Inbox
    max_steps: int
    draft: Draft
    choices: RunChoices = RunChoices()
    user: str = LOCAL_USER
    goal: str = ""
    turn: str | None = None
    tasks: list[str] = field(default_factory=list)
    session: Session | None = None


class Runner:
    """The runs this server started, while they go on: one per conversation. `start_turn` runs one."""

    def __init__(self, store: RunStore, start_turn: Callable[..., Awaitable], titles: Titles):
        self.store = store
        self.start_turn = start_turn
        self.titles = titles
        self.live = Live()
        self.runs: dict[str, Running] = {}  # by conversation
        self.error: dict | None = None  # the last run that died with an error: its id, the error and whose it was
        self.following: set[asyncio.Task] = set()  # runs being started with what an ended run did not read
        self.closing = False  # the server is shutting down: what its runs did not read goes nowhere

    def running(self, user: str | None = None) -> dict[str, str]:
        """The runs in progress, by conversation; only `user`'s, when given."""
        return {
            thread: each.run for thread, each in self.runs.items()
            if each.run is not None and user in (None, each.user)
        }

    def session(self, run: str) -> Running | None:
        """The session `run` began, or None if it ended or was not started here."""
        return next((each for each in self.runs.values() if each.run == run), None)

    def inbox(self, run: str) -> Inbox | None:
        return each.inbox if (each := self.session(run)) is not None else None

    def send(
        self, thread: str, text: str, choices: RunChoices = RunChoices(), queued: bool = False
    ) -> tuple[str, Message] | None:
        """Hand a message to the conversation's run, or `queued` for the run after it: (its id, the message), or None
        when the conversation has no run here. ConversationBusy while its run is starting. The run keeps the models
        it started with: those sent now are the next run's. Approvals apply from its next step that needs them."""
        running = self.runs.get(thread)
        if running is None:
            return None
        if running.run is None:
            raise ConversationBusy(None)
        running.choices = choices
        return running.run, running.inbox.put(text, queued)

    def choose(self, run: str, approvals: Approvals) -> bool:
        """Sets how a run answers its next step that needs approval; False if it ended or is not here."""
        running = self.session(run)
        if running is None:
            return False
        running.choices = replace(running.choices, approvals=approvals)
        return True

    async def delete(self, thread: str, user: str = LOCAL_USER) -> list[str]:
        """Reserves an idle conversation while its records and files are erased."""
        if thread in self.runs:
            raise ConversationBusy(self.runs[thread].run)
        self.runs[thread] = Running(None, None, Inbox(), 0, Draft())
        try:
            return await self.store.of(user).delete(thread)
        finally:
            self.runs.pop(thread, None)

    async def start(
        self,
        goal: str,
        max_steps: int,
        *,
        thread: str | None = None,
        force_computer: bool = False,
        take_control: bool = False,
        choices: RunChoices = RunChoices(),
        project: str | None = None,
        user: str = LOCAL_USER,
        sent: float | None = None,
    ) -> str:
        """Starts a run in the background and returns its id once its log exists.
        ConversationBusy while the conversation has a run in progress; DesktopBusy, for a message for the desktop,
        while another run has it."""
        running = Running(None, None, Inbox(), max_steps, Draft(), choices, user, goal)
        if thread is not None:
            if thread in self.runs:
                raise ConversationBusy(self.runs[thread].run)
            # Before anything awaits, so a second message at once is turned away.
            self.runs[thread] = running
        started = asyncio.get_running_loop().create_future()

        def on_event(run: str, event: dict) -> None:
            if event["type"] == "start":
                if not started.done():
                    started.set_result(run)
                turn = event["kind"] == TURN
                self.live.open(run, running.draft if turn else None)
                if turn:
                    running.turn = run
                else:
                    running.tasks.append(run)
            self.live.publish(run, event)
            if event["type"] == "end":
                self.live.close(run)
                if running.turn == run:
                    running.turn = None
                elif run in running.tasks:
                    running.tasks.remove(run)

        listeners = (on_event,)
        task = asyncio.create_task(
            self.start_turn(
                goal, max_steps=max_steps, store=self.store.of(user),
                listeners=listeners, thread=thread, force_computer=force_computer, take_control=take_control,
                inbox=running.inbox, draft=running.draft, choices=choices,
                titles=self.titles, approvals=lambda: running.choices.approvals, project=project,
                opened=lambda session: setattr(running, "session", session), sent=sent,
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
        for run in [running.turn, *running.tasks]:  # a log a stop or crash left without an end
            if run is not None:
                self.live.close(run)
        if self.runs.get(thread) is running:
            del self.runs[thread]
        unread = running.inbox.close()
        if not task.cancelled() and (error := task.exception()) is not None:
            traceback.print_exception(error)
            self.error = {"run": running.run, "message": f"{type(error).__name__}: {error}", "user": running.user}
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
        """Starts the conversation's next run with the first message an ended run did not read; the others go to it
        as sent while it works, and queued ones stay queued."""
        first, *rest = sorted(unread, key=lambda message: message.queued)  # stable: in the order sent
        try:
            await self.start(
                first.text, max_steps, thread=thread, choices=choices, user=user, sent=first.time
            )
        except Exception as error:  # e.g. another run took the desktop meanwhile
            traceback.print_exception(error)
            return
        for message in rest:
            self.runs[thread].inbox.put(message.text, message.queued)

    async def stop_one(self, run: str) -> bool:
        """Stops one log of a session, a turn or a task; the rest goes on. False if not in progress here."""
        for each in list(self.runs.values()):
            if each.session is None:
                continue
            if each.turn == run:
                return each.session.stop_turn()
            if run in each.tasks:
                return await each.session.background.stop_for_user(run)
        return False

    async def stop(self, run: str | None = None) -> None:
        """Cancels a run, or every run; each log ends as cancelled."""
        tasks = [
            each.task for each in list(self.runs.values())
            if each.task is not None and not each.task.done() and run in (None, each.run)
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(tasks)

    async def close(self) -> None:
        self.closing = True
        await self.stop()
        await self.titles.close()
