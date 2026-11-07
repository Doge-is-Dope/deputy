"""Shared model-facing content and call results."""

import base64
from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId

from computer_use.events import ActionReason

CallId = Annotated[str, InjectedToolCallId]


def image_block(png: bytes) -> dict:
    return {"type": "image", "base64": base64.b64encode(png).decode(), "mime_type": "image/png"}


def is_image(block) -> bool:
    return isinstance(block, dict) and block.get("type") == "image"


def image_blocks(message) -> list[dict]:
    if not isinstance(message.content, list):
        return []
    return [block for block in message.content if is_image(block)]


def not_executed(call: dict, reason: str, code: ActionReason) -> ToolMessage:
    """A call the runtime turned away, as its result: why, in words, and as a code the page reads."""
    return ToolMessage(
        content=f"Not executed: {reason}", tool_call_id=call["id"], name=call["name"], status="error",
        artifact={"reason": code},
    )
