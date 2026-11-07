"""Helpers the middleware share: screenshot pruning, a section added to the system prompt, and a stop LangGraph
swallowed."""

import asyncio

from langchain.agents.middleware import ModelRequest, ModelRetryMiddleware
from langchain_core.messages import SystemMessage

from computer_use.agent.failures import failed_in_stream
from computer_use.tools.common import image_blocks, is_image

# Prune old screenshots in batches to preserve prompt-cache reuse between prunes.
# Keep between KEEP_SCREENSHOTS and KEEP_SCREENSHOTS + PRUNE_EVERY - 1 images.
KEEP_SCREENSHOTS = 3
PRUNE_EVERY = 5
REMOVED_SCREENSHOT = {"type": "text", "text": "[earlier screenshot removed]"}

# A model call whose stream failed partway is tried again this many times, waiting RETRY_DELAY seconds, then twice as
# long each time (up to RETRY_MAX_DELAY).
STREAM_RETRIES = 5
RETRY_DELAY = 1.0
RETRY_MAX_DELAY = 30.0


def pruned(carrying: int, keep: int = KEEP_SCREENSHOTS, every: int = PRUNE_EVERY) -> int:
    """How many of the oldest `carrying` messages with images lose them: `every` at a time, keeping at least `keep`."""
    return (carrying - keep) // every * every if carrying > keep else 0


def without_screenshots(message):
    """The message with each of its images replaced by a note that it was removed."""
    blocks = [REMOVED_SCREENSHOT if is_image(block) else block for block in message.content]
    return message.model_copy(update={"content": blocks})


def prune_screenshots(messages: list, keep: int = KEEP_SCREENSHOTS, every: int = PRUNE_EVERY) -> list:
    """Remove images from the oldest messages that carry them, `every` messages at a time, keeping at least `keep`."""
    result = list(messages)
    carrying = [index for index, message in enumerate(result) if image_blocks(message)]
    for index in carrying[:pruned(len(carrying), keep, every)]:
        result[index] = without_screenshots(result[index])
    return result


def with_section(request: ModelRequest, section: str) -> ModelRequest:
    """The request with `section` added to the end of its system message."""
    blocks = [*request.system_message.content_blocks] if request.system_message is not None else []
    added = {"type": "text", "text": f"\n\n{section}" if blocks else section}
    return request.override(system_message=SystemMessage(content=[*blocks, added]))


def raise_if_stopped() -> None:
    """Re-raises a stop that LangGraph swallowed while cleaning up its stream between steps."""
    if (task := asyncio.current_task()) is not None and task.cancelling():
        raise asyncio.CancelledError


def retrying_failed_streams() -> ModelRetryMiddleware:
    """Tries a model call again when its stream failed partway (failures.failed_in_stream); raises once out of tries.
    Innermost of an agent's middleware, so the others see one call."""
    return ModelRetryMiddleware(
        max_retries=STREAM_RETRIES, retry_on=failed_in_stream, on_failure="error",
        initial_delay=RETRY_DELAY, max_delay=RETRY_MAX_DELAY,
    )
