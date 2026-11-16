"""The coding agent's tools: bash, write_file and view_image in the conversation's folder on the code runner; and what
the user attached, put in that folder for it."""

import asyncio
import base64
import io
import logging
from collections.abc import Sequence
from functools import partial
from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool, ToolException, tool
from PIL import Image
from pydantic import Field

from computer_use.sandbox import CodeRunner
from computer_use.tools.common import CallId

logger = logging.getLogger(__name__)

RUN_SECONDS = 120
# What view_image shows: the images a model takes, as the user's are, read by their headers only.
VIEWABLE = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}
MAX_SIDE = 2048
MAX_VIEWED = 5 * 1024 * 1024
# Where what the user attached sits in the conversation's folder, by the name it was attached under.
ATTACHED = "attachments"


class Attached:
    """What the user attached, put in the conversation's folder under ATTACHED. The session's own message's files
    (`media`) replace any of their names, as soon as the message is stored (`put_new`). Each earlier one (in `logs`,
    read from the run's `files`) is put where the folder lacks that revision, since it lasts only as long as the runner,
    once a coding task starts (`place`): a session with neither never asks the runner. Of files with one name, the
    latest.

    A file is put once: it waits in `new` or `earlier` until it is there. One the folder or the store turns away is
    left out: the coding agent finds it missing and says so. CodeRunnerError leaves it, and those after it, to be
    tried again."""

    def __init__(self, runner: CodeRunner, files, thread: str, logs: Sequence, media: Sequence[dict], run: str):
        self.runner, self.files, self.thread, self.run = runner, files, thread, run
        self.new = [(block["filename"], partial(self._put_new, block)) for block in media]
        self.earlier = []
        names = {name for name, _ in self.new}
        for log in reversed(logs):
            for event in reversed(log.events):
                for each in event.get("attachments", ()) if event.get("type") == "input" else ():
                    if each["name"] not in names:
                        names.add(each["name"])
                        self.earlier.append((each["name"], partial(self._put_earlier, log.summary.id, each)))
        self._lock = asyncio.Lock()  # tasks that start together put each file once

    async def put_new(self) -> None:
        async with self._lock:
            await self._put(self.new)

    async def place(self) -> None:
        async with self._lock:
            await self._put(self.new)
            await self._put(self.earlier)

    async def _put(self, waiting: list) -> None:
        while waiting:
            name, put = waiting[0]
            try:
                await put()
            except (ValueError, FileNotFoundError) as error:
                logger.warning("Could not put %s in %s's folder: %s", name, self.thread, error)
            del waiting[0]

    async def _put_new(self, block: dict) -> None:
        await self.runner.put(self.thread, f"{ATTACHED}/{block['filename']}", base64.b64decode(block["base64"]), self.run)

    async def _put_earlier(self, log: str, each: dict) -> None:
        # A filename alone could still hold an older upload after a failed replacement.
        if not await self.runner.has(self.thread, path := f"{ATTACHED}/{each['name']}", log):
            await self.runner.put(self.thread, path, await self.files.get_file(log, each["file"]), log)


def coding_tools(runner: CodeRunner, thread: str, task: str) -> list[BaseTool]:
    """bash, write_file and view_image for a task (its log's id), in the conversation's folder on the code runner."""

    # Not a docstring: the limit is told from RUN_SECONDS, so the two cannot differ.
    @tool(description=(
        "Run commands with bash in your working folder; returns the exit code and what they printed, stdout and "
        f"stderr together, cut in the middle when long. A command still running after {RUN_SECONDS} seconds is stopped."
    ))
    async def bash(
        script: Annotated[str, Field(description="The commands, run with bash in your working folder.")],
    ) -> str:
        try:
            output = await runner.run(thread, task, script, RUN_SECONDS)
        except ValueError as refused:
            raise ToolException(f"Not executed: {refused}.")
        if output.code is None:
            raise ToolException(f"Stopped: it ran for more than {RUN_SECONDS} seconds. What it printed:\n{output.text}")
        return f"Exit code {output.code}.\n{output.text}"

    @tool
    async def write_file(
        path: Annotated[str, Field(description="A path in your working folder.")],
        content: Annotated[str, Field(description="The file's whole text.")],
    ) -> str:
        """Write a text file in your working folder, replacing any there."""
        try:
            return await runner.write(thread, path, content)
        except ValueError as refused:
            raise ToolException(f"Not executed: {refused}.")

    @tool
    async def view_image(
        path: Annotated[str, Field(description="An image's path in your working folder: PNG, JPEG or WebP.")],
        call_id: CallId,
    ) -> ToolMessage:
        """Look at an image in your working folder, at most 2048 pixels on its long side and 5 MB. Save any other
        picture as one first, such as with Pillow: another format, a frame, a page, a chart you drew."""
        try:
            data = await runner.read(thread, path)
        except FileNotFoundError:
            raise ToolException(f"Not executed: there is no {path} in your working folder.")
        except ValueError as refused:
            raise ToolException(f"Not executed: {refused}.")
        mime_type = viewable(path, data)
        image = {"type": "image", "base64": base64.b64encode(data).decode(), "mime_type": mime_type}
        return ToolMessage(content=[{"type": "text", "text": path}, image], tool_call_id=call_id, name="view_image")

    tools = [bash, write_file, view_image]
    for each in tools:  # a refused or failed command is the agent's to hear and work around
        each.handle_tool_error = True
    return tools


def viewable(path: str, data: bytes) -> str:
    """The image's type, once it is one a model takes and small enough; ToolException saying how to make it so."""
    try:
        with Image.open(io.BytesIO(data), formats=tuple(VIEWABLE)) as image:
            kind, size = image.format, image.size
    except (OSError, Image.DecompressionBombError):
        raise ToolException(f"Not executed: {path} is not a PNG, JPEG or WebP image; save it as one first.") from None
    if max(size) > MAX_SIDE or len(data) > MAX_VIEWED:
        raise ToolException(
            f"Not executed: {path} is {size[0]}x{size[1]}, {len(data) // 1024} KB; save a copy at most {MAX_SIDE} "
            f"pixels on its long side and {MAX_VIEWED // 2**20} MB first."
        )
    return VIEWABLE[kind]
