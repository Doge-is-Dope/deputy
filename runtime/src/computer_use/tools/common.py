"""Shared model-facing content and call results."""

import base64
import re
from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId

from computer_use.events import ActionReason

CallId = Annotated[str, InjectedToolCallId]
# The media a model reads (screenshots, what the user attached), by type: the extension each is kept under.
MEDIA_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "application/pdf": "pdf"}
# Any other file the user attaches is kept under its own extension, as far as this reads one.
EXTENSION = re.compile(r"\.([A-Za-z0-9]{1,10})$")


def image_block(png: bytes) -> dict:
    return {"type": "image", "base64": base64.b64encode(png).decode(), "mime_type": "image/png"}


def is_media(block) -> bool:
    """An image or a file: kept as a file of the run, apart from its record."""
    return isinstance(block, dict) and block.get("type") in ("image", "file")


def is_kept(block) -> bool:
    """A file no model reads, only code: kept for the coding agent and the page, never sent to a model."""
    return is_media(block) and block.get("mime_type") not in MEDIA_TYPES


def extension_of(block: dict) -> str:
    if known := MEDIA_TYPES.get(block.get("mime_type")):
        return known
    found = EXTENSION.search(block.get("filename", ""))
    return found[1].lower() if found else "bin"


def for_model(message):
    """The message as a model takes it: without the files only code opens."""
    if not isinstance(message.content, list) or not any(is_kept(block) for block in message.content):
        return message
    return message.model_copy(update={"content": [block for block in message.content if not is_kept(block)]})


def is_screenshot(block) -> bool:
    """An image the runtime took. What the user attached carries its file name and is never pruned."""
    return isinstance(block, dict) and block.get("type") == "image" and "filename" not in block


def screenshot_blocks(message) -> list[dict]:
    if not isinstance(message.content, list):
        return []
    return [block for block in message.content if is_screenshot(block)]


def not_executed(call: dict, reason: str, code: ActionReason) -> ToolMessage:
    """A call the runtime turned away, as its result: why, in words, and as a code the page reads."""
    return ToolMessage(
        content=f"Not executed: {reason}", tool_call_id=call["id"], name=call["name"], status="error",
        artifact={"reason": code},
    )


def confirmation(args: dict) -> tuple[bool, str | None]:
    """A JSON-schema tool's needs_confirmation and consequence, checked as a typed tool's would be."""
    needed, consequence = args.get("needs_confirmation"), args.get("consequence")
    if type(needed) is not bool or not isinstance(consequence, str | None):
        raise ValueError("needs_confirmation must be true or false, and consequence text or null.")
    return needed, consequence
