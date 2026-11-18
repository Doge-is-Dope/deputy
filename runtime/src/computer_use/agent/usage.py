"""What a model call used and what it costs: tokens by kind, at list prices."""

from typing import NamedTuple

from langchain_core.messages import AIMessage


class Price(NamedTuple):
    """US dollars per million tokens."""

    input: float
    cached: float
    cache_write: float
    output: float


# Where a reply's usage counts cache writes: writes split by cache lifetime leave the generic count at 0.
CACHE_WRITES = ("cache_creation", "ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens")


def no_tokens() -> dict[str, int]:
    return {"input": 0, "cached": 0, "cache_write": 0, "output": 0, "reasoning": 0}


def usage_of(message: AIMessage) -> dict[str, int]:
    """Tokens one model reply used. Cached and cache-write tokens are part of input, reasoning part of output."""
    usage = message.usage_metadata or {}
    details = usage.get("input_token_details") or {}
    return {
        "input": usage.get("input_tokens", 0),
        "cached": details.get("cache_read", 0),
        "cache_write": sum(details.get(key) or 0 for key in CACHE_WRITES),
        "output": usage.get("output_tokens", 0),
        "reasoning": (usage.get("output_token_details") or {}).get("reasoning", 0),
    }


def cost_breakdown(tokens: dict[str, int], price) -> dict[str, float]:
    """US dollars for these tokens at list prices, by kind: input neither read from nor written to the cache, cache
    reads, cache writes, and output (reasoning included)."""
    plain = tokens["input"] - tokens["cached"] - tokens["cache_write"]
    return {
        "input": plain * price.input / 1_000_000,
        "cached": tokens["cached"] * price.cached / 1_000_000,
        "cache_write": tokens["cache_write"] * price.cache_write / 1_000_000,
        "output": tokens["output"] * price.output / 1_000_000,
    }
