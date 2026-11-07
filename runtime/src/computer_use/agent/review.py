"""Auto review of actions the computer agent flags for approval.

Only an explicit allow for a low- or medium-risk action covered by the user's words skips manual approval; any
unclear, failed, unreadable or timed-out review falls back to the user.

Only user messages authorize actions. Screens and agent statements are evidence; a successful action record shows input
was sent, not that the goal was achieved. For deletes and overwrites, the named target must also occur verbatim in the
user's messages or recorded action input; this establishes neither identity nor authorization."""

import asyncio
import json
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from computer_use.tools.common import image_block
from computer_use.agent.usage import usage_of
from computer_use.events import shown_args
from computer_use.prompts.review import REVIEW_PROMPT, review_request
from computer_use.storage import MAIN

# A review that times out proves nothing either way, so the user is asked.
REVIEW_SECONDS = 30



class Review(BaseModel):
    """The reviewer's answer for one step."""

    risk: Literal["low", "medium", "high"]
    authorization: Literal["high", "medium", "low", "unknown"]
    decision: Literal["allow", "ask"]
    reason: str = Field(description="One short sentence, in the user's language")
    # Required: an answer that leaves it out cannot be read, and the user is asked. An empty one says the step deletes
    # or overwrites nothing, which only the reviewer judges.
    target: str = Field(description="The exact name of what the step deletes or overwrites; empty if nothing")
    evidence: str = Field(
        default="", description="The user's words naming the target, or the recorded action creating it"
    )


@dataclass(frozen=True)
class Verdict:
    """Whether the step may go ahead without the user, and the review as the log keeps it."""

    allow: bool
    review: dict


def allows(review: Review, sources: Sequence[str]) -> bool:
    """Allow only authorized, non-high-risk steps whose named target occurs verbatim (case- and space-sensitive) in
    `sources`, the user's messages and sent action input. An empty target skips the match; evidence is only logged."""
    if review.decision != "allow" or review.risk == "high" or review.authorization not in ("high", "medium"):
        return False
    if not review.target.strip():
        return True
    return any(review.target in source for source in sources)


def action_records(events: Iterable[dict]) -> list[str]:
    """Each action the computer-use agent sent, as the tool and arguments the runtime recorded, for auto review.
    Only actions whose input went out ("success"; not that a file was saved, say) count: not one that failed, was held
    back or declined, nor a batch that stopped partway."""
    return [
        f"{event['tool']} {json.dumps(shown_args(event['args']), ensure_ascii=False)}"
        for event in events
        if event["type"] == "action" and event.get("agent") != MAIN and event.get("status") == "success"
    ]


async def review_step(
    model: BaseChatModel, context: str, step: str, png: bytes | None, sources: Sequence[str] = ()
) -> Verdict:
    """Review one step against the conversation and actions so far (`context`) and the screen it decided from. A review
    that fails, takes too long or cannot be read allows nothing: the user is asked."""
    message = HumanMessage(content=[{"type": "text", "text": review_request(context, step)},
                                    *([image_block(png)] if png else [])])
    started = time.monotonic()
    try:
        answer = await asyncio.wait_for(
            model.with_structured_output(Review, include_raw=True).ainvoke([SystemMessage(REVIEW_PROMPT), message]),
            REVIEW_SECONDS,
        )
    except TimeoutError:
        return Verdict(False, {"error": f"no answer within {REVIEW_SECONDS} s", "seconds": REVIEW_SECONDS})
    except Exception as error:  # e.g. the model service is down: the user decides
        return Verdict(False, {"error": f"{type(error).__name__}: {error}", "seconds": time.monotonic() - started})
    seconds = round(time.monotonic() - started, 1)
    usage = usage_of(answer["raw"]) if answer.get("raw") is not None else {}
    review = answer.get("parsed")
    if not isinstance(review, Review):
        return Verdict(False, {"error": f"unreadable answer: {answer.get('parsing_error')}", "seconds": seconds,
                               "usage": usage})
    return Verdict(allows(review, sources), {**review.model_dump(), "seconds": seconds, "usage": usage})
