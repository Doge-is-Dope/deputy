"""Steering messages, read after the current action and before the next model call.

The main agent reads user messages; background tasks read its instructions.
Unread user messages continue in the next run. All access is on the server's
event loop, so no lock is needed."""

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from computer_use.storage import MAIN

if TYPE_CHECKING:
    from computer_use.agent.trajectory import Trajectory

# An agent the main agent hands work to (agent.subagent), as a reader; the main agent reads as MAIN.
SUBAGENT = "subagent"


@dataclass
class Message:
    id: str
    text: str
    time: float  # when the user sent it
    read_by: set[str] = field(default_factory=set)


class Inbox:
    """A run's messages from the user, oldest first, and which agent has read each."""

    def __init__(self):
        self._messages: list[Message] = []
        self.closed = False
        self.log: Trajectory | None = None  # where the first read of each message is logged, once the run has one
        self._arrived = asyncio.Event()

    def put(self, text: str) -> Message | None:
        """Take a message for the run; None once the run has ended."""
        if self.closed:
            return None
        message = Message(str(uuid.uuid4()), text, time.time())
        self._messages.append(message)
        self._arrived.set()
        return message

    def unread(self, reader: str) -> bool:
        """Whether a message waits for this agent."""
        return any(reader not in message.read_by for message in self._messages)

    async def wait(self, reader: str) -> None:
        """Until a message waits for this agent."""
        while not self.unread(reader):
            self._arrived.clear()
            await self._arrived.wait()

    def take(self, reader: str) -> list[Message]:
        """The messages this agent has not read yet, now read. The first agent to read one logs it: the page shows it
        from then on as part of the conversation."""
        new = [message for message in self._messages if reader not in message.read_by]
        for message in new:
            if not message.read_by and self.log is not None:
                self.log.message(message.id, message.text)
            message.read_by.add(reader)
        return new

    def read(self, reader: str) -> list[Message]:
        """The messages this agent has read, oldest first."""
        return [message for message in self._messages if reader in message.read_by]

    def pending(self) -> list[Message]:
        """The messages no agent has read yet."""
        return [message for message in self._messages if not message.read_by]

    def withdraw(self, id: str) -> bool:
        """Take back a message no agent has read yet; False once one has, or for one that is not here."""
        message = next((each for each in self._messages if each.id == id), None)
        if message is None or message.read_by:
            return False
        self._messages.remove(message)
        return True

    def close(self) -> list[Message]:
        """Take no more messages, and return those the main agent has not read: the run ended before it could."""
        self.closed = True
        return [message for message in self._messages if MAIN not in message.read_by]
