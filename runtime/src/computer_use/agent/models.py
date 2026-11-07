"""Build chat models, and resolve model and effort choices."""

from collections.abc import Iterable
from functools import lru_cache

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from computer_use.agent.usage import PRICES
from computer_use.config import FOLLOW, Choice, Settings


# Bound provider retries so an unresponsive request cannot hold a run for many minutes.
MODEL_TIMEOUT = 120
MODEL_RETRIES = 2


class FullResolutionChatOpenAI(ChatOpenAI):
    """Sends screenshots with detail="original" to preserve pixel coordinates."""

    def _get_request_payload(self, input_, *, stop=None, **kwargs) -> dict:
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        for item in payload.get("input", []):
            blocks = item.get("output") if item.get("type") == "function_call_output" else item.get("content")
            for block in blocks if isinstance(blocks, list) else []:
                if block.get("type") == "input_image":
                    block.setdefault("detail", "original")
        return payload


class AgentChatAnthropic(ChatAnthropic):
    """Anthropic's chat model with the system prompt cached on its own, and failed tool results with screenshots sent
    without the is_error flag.

    Anthropic reads a cache only where an earlier call marked one. The conversation's mark moves with its newest block,
    and pruned screenshots change the conversation under it; the system prompt's mark survives them. Anthropic error
    results accept only text; the message still explains the failure."""

    def _get_request_payload(self, input_, *, stop=None, **kwargs) -> dict:
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        if system := payload.get("system"):
            blocks = [{"type": "text", "text": system}] if isinstance(system, str) else system
            blocks[-1]["cache_control"] = {"type": "ephemeral"}
            payload["system"] = blocks
        for message in payload.get("messages", []):
            for block in message["content"] if isinstance(message.get("content"), list) else []:
                if block.get("type") == "tool_result" and block.get("is_error") and isinstance(block.get("content"), list):
                    if any(part.get("type") != "text" for part in block["content"]):
                        del block["is_error"]
        return payload


# Reasoning effort levels, lowest first, as LangChain names them for every provider.
LEVELS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")
# The efforts of models whose LangChain profile does not list them, from the provider's model page.
EFFORTS = {
    # developers.openai.com/api/docs/models/gpt-6.1-sol (2026-10-18): "none" and "minimal" are not supported.
    "openai:gpt-6.1-sol": ("low", "medium", "high", "xhigh", "max"),
    "openai:gpt-6.1-terra": ("none", "low", "medium", "high", "xhigh", "max"),
    # platform.claude.com/docs/en/about-claude/models (2026-10-20); langchain-anthropic 1.7.5 has no profile for it.
    "anthropic:claude-haiku-5-5": ("low", "medium", "high", "xhigh", "max"),
}
# The efforts assumed of a model nothing lists: those every reasoning model of both providers takes.
COMMON_EFFORTS = ("low", "medium", "high")
MAIN_AGENT = "main"

# Screenshot pruning rewrites the prompt prefix, invalidating later thinking signatures.
# Drop mismatched blocks so Claude reasons again; requires the beta below.
THINKING = {"type": "adaptive", "display": "summarized", "block_binding": {"prefix_mismatch_behavior": "drop_block"}}
BETAS = ["thinking-binding-controls-2026-08-01"]


def offered(settings: Settings) -> tuple[str, ...]:
    return tuple(dict.fromkeys(spec for spec in (*PRICES, settings.main_model, settings.computer_model) if spec))


@lru_cache
def efforts(spec: str) -> tuple[str, ...]:
    if spec in EFFORTS:
        return EFFORTS[spec]
    provider, _, name = spec.partition(":")
    model = {"openai": ChatOpenAI, "anthropic": ChatAnthropic}.get(provider)
    levels = (model(model=name, api_key="unused").profile or {}).get("reasoning_effort_levels") if model else None
    return tuple(level for level in LEVELS if level in levels) if levels else COMMON_EFFORTS


def clamp(effort: str, levels: tuple[str, ...]) -> str:
    """The highest supported effort at or below this one, or the lowest available."""
    rank = LEVELS.index(effort) if effort in LEVELS else len(LEVELS)
    below = [level for level in levels if LEVELS.index(level) <= rank]
    return below[-1] if below else levels[0]


def starting(settings: Settings, agents: Iterable[str] = ()) -> dict[str, dict[str, str]]:
    """Each agent's model and effort before the user chooses: the main agent's; the computer agent's own, or FOLLOW
    where unset; FOLLOW for any other of `agents`."""
    start = {
        MAIN_AGENT: {"model": settings.main_model, "effort": settings.main_effort},
        "computer": {"model": settings.computer_model or FOLLOW, "effort": settings.computer_effort or FOLLOW},
    }
    return start | {agent: {"model": FOLLOW, "effort": FOLLOW} for agent in agents if agent not in start}


def chosen(settings: Settings, agent: str, choices: dict[str, dict[str, str]] | None = None) -> Choice:
    """The model and effort an agent works with in a run: what the user chose (`choices`, by agent), else `starting`.
    A subagent's model or effort that follows (FOLLOW) is the main agent's, and so is a model not offered. The page
    works these out the same way (clients/web/src/lib/choices.ts)."""
    start, models = starting(settings, (agent,)), offered(settings)

    def of(name: str) -> dict[str, str]:
        return start[name] | (choices or {}).get(name, {})

    main = of(MAIN_AGENT)
    model = main["model"] if main["model"] in models else settings.main_model
    effort = main["effort"]
    if agent != MAIN_AGENT:
        own = of(agent)
        model = own["model"] if own["model"] != FOLLOW and own["model"] in models else model
        effort = own["effort"] if own["effort"] != FOLLOW else effort
    return Choice(model, clamp(effort, efforts(model)))


def build_chat_model(choice: Choice, settings: Settings, stream: bool = False) -> BaseChatModel:
    """The model of a choice. Only the main agent's streams: streaming it would otherwise stream every model call
    under it, the subagents' in the background included."""
    provider, _, name = choice.model.partition(":")
    if not name:
        raise ValueError(f"Model spec must look like 'provider:model', got {choice.model!r}")

    if provider == "openai":
        kwargs: dict = {
            "model": name,
            "use_responses_api": True,
            "reasoning_effort": choice.effort,
            "timeout": MODEL_TIMEOUT,
            "max_retries": MODEL_RETRIES,
            "disable_streaming": not stream,
        }
        if settings.openai_api_key:
            kwargs["api_key"] = settings.openai_api_key
        return FullResolutionChatOpenAI(**kwargs)

    if provider == "anthropic":
        kwargs = {
            "model": name,
            "max_tokens": 16000,
            "reasoning_effort": choice.effort,
            "thinking": THINKING,
            "betas": BETAS,
            # Anthropic caches only up to a marked block, so mark the end of the prompt on every call, as OpenAI does
            # unasked. Pruned screenshots change the prompt before the newest messages; the system prompt's own mark
            # (AgentChatAnthropic) outlasts them.
            "model_kwargs": {"cache_control": {"type": "ephemeral"}},
            "timeout": MODEL_TIMEOUT,
            "max_retries": MODEL_RETRIES,
            "disable_streaming": not stream,
        }
        if settings.anthropic_api_key:
            kwargs["api_key"] = settings.anthropic_api_key
        return AgentChatAnthropic(**kwargs)

    raise ValueError(f"Unsupported model provider {provider!r}")

