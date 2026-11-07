"""Keeps optional LangSmith traces small: model calls keep full text context, graph nodes only the newest message;
screenshots, encrypted reasoning and repeated tool schemas are omitted."""

from dataclasses import fields, is_dataclass, replace
from functools import cache

import langsmith
from langchain_core.messages import BaseMessage
from langchain_core.tools import BaseTool
from langsmith.utils import tracing_is_enabled

SCREENSHOT_NOT_TRACED = {"type": "text", "text": "[screenshot not traced]"}
NOT_TRACED = "[not traced]"


@cache
def configure_tracing() -> None:
    """Once per process: LangChain's tracer uses this client for every run."""
    if tracing_is_enabled():
        client = langsmith.Client(hide_inputs=for_trace, hide_outputs=for_trace)
        langsmith.configure(client=client)


def is_image(value) -> bool:
    # A model call's messages are traced serialized, with images as OpenAI-style "image_url" blocks.
    return isinstance(value, dict) and value.get("type") in ("image", "image_url")


def for_trace(value):
    """A copy of a run's inputs or outputs for LangSmith, leaving the traced objects alone."""
    if isinstance(value, BaseMessage):
        update = {"content": for_trace(value.content), "additional_kwargs": for_trace(value.additional_kwargs)}
        return value.model_copy(update=update)
    if isinstance(value, BaseTool):  # its ~1 KB definition is the same on every call
        return value.name
    if is_image(value):
        return SCREENSHOT_NOT_TRACED
    if isinstance(value, dict):
        return {key: NOT_TRACED if key == "encrypted_content" else for_trace(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        if len(value) > 1 and all(isinstance(item, BaseMessage) for item in value):  # a conversation in graph state
            return [f"[{len(value) - 1} earlier messages not traced]", for_trace(value[-1])]
        return [for_trace(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):  # a model call's response, a tool's command
        traced = {field.name: for_trace(getattr(value, field.name)) for field in fields(value) if field.init}
        return replace(value, **traced)
    return value
