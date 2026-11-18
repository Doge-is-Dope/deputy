"""The models the runtime offers: each as its maker names it, at its list price, with the efforts it takes."""

from typing import NamedTuple

from computer_use.agent.usage import Price


class Model(NamedTuple):
    name: str
    price: Price
    efforts: tuple[str, ...]


LOW_TO_MAX = ("low", "medium", "high", "xhigh", "max")

# Prices: short-context rates (prompts up to 272K tokens) from OpenAI's pricing page on 2026-11-18, and Anthropic's on
# 2026-10-20 (Claude Haiku 5.5: prompts up to 100K tokens; five times these beyond).
# Efforts: GPT-6.2's are the API's own list when it refused "none" and "minimal" (2026-11-18); Claude Haiku 5.5's are
# from platform.claude.com/docs/en/about-claude/models (2026-10-20); GPT-6 Luna's and Claude Sonnet and Opus 5.5's as
# langchain-openai 1.7.2 and langchain-anthropic 1.7.6 list them.
MODELS = {
    "openai:gpt-6-luna": Model(
        "GPT-6 Luna", Price(input=0.10, cached=0.01, cache_write=0.125, output=0.50), ("none", *LOW_TO_MAX)
    ),
    "openai:gpt-6.1-terra": Model(
        "GPT-6.1 Terra", Price(input=1.00, cached=0.05, cache_write=1.25, output=5.00), ("none", *LOW_TO_MAX)
    ),
    "openai:gpt-6.2-sol": Model("GPT-6.2 Sol", Price(input=2.00, cached=0.10, cache_write=2.50, output=10.00), LOW_TO_MAX),
    "openai:gpt-6.2-astra": Model(
        "GPT-6.2 Astra", Price(input=8.00, cached=0.40, cache_write=10.00, output=40.00), LOW_TO_MAX
    ),
    "anthropic:claude-haiku-5-5": Model(
        "Claude Haiku 5.5", Price(input=0.10, cached=0.01, cache_write=0.125, output=0.50), LOW_TO_MAX
    ),
    "anthropic:claude-sonnet-5-5": Model(
        "Claude Sonnet 5.5", Price(input=2.00, cached=0.10, cache_write=2.50, output=10.00), LOW_TO_MAX
    ),
    "anthropic:claude-opus-5-5": Model(
        "Claude Opus 5.5", Price(input=4.00, cached=0.20, cache_write=5.00, output=20.00), LOW_TO_MAX
    ),
}


def model_name(spec: str) -> str:
    """One not offered goes by its id, without the provider."""
    return MODELS[spec].name if spec in MODELS else spec.partition(":")[2] or spec
