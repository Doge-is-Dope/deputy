"""Auto review of actions the computer agent flags for approval.

Only an explicit allow for a low- or medium-risk action covered by the user's
words skips manual approval. Unclear, failed, unreadable or timed-out reviews
fall back to the user. Unflagged actions never reach the reviewer.

Only user messages authorize actions. Screens and agent statements are evidence;
successful action records show input was sent, not that the goal was achieved.
For deletes and overwrites, the named target must also occur verbatim in the
user's messages or recorded action input; this check does not establish identity
or authorization."""

import asyncio
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from computer_use.agent.tools import image_block
from computer_use.agent.trajectory import usage_of
from computer_use.prompts.review import REVIEW_PROMPT, review_request

# How long a review may take before the user is asked instead; a review that times out proves nothing either way.
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
    """Allow only authorized, non-high-risk steps with a verbatim target match when named.

    sources contains user messages and sent action input. Matching does not prove
    target identity, ownership or authorization. Names are case- and space-sensitive;
    an empty target skips the match. Quoted evidence is retained only for the log."""
    if review.decision != "allow" or review.risk == "high" or review.authorization not in ("high", "medium"):
        return False
    if not review.target.strip():
        return True
    return any(review.target in source for source in sources)


async def review_step(
    model: BaseChatModel, context: str, step: str, png: bytes | None, sources: Sequence[str] = ()
) -> Verdict:
    """Review one step: the conversation as the computer-use agent got it plus what it did since (`context`), the step
    and its arguments (`step`), the screen it decided from with its target marked, and where its target must be named
    (`sources`: the user's messages and the actions whose input was sent). A review that fails, takes too long or
    cannot be read allows nothing: the user is asked."""
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
