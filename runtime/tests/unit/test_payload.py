"""Offline check that screenshots in tool results are serialized as image content per provider.

Uses each integration's private `_get_request_payload`, so a dependency upgrade
that changes serialization fails here before it costs a real model call.
"""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, message_to_dict

from computer_use.agent.models import build_chat_model
from computer_use.config import Choice
from computer_use.agent.history import restore


def _payload(settings, conversation, spec):
    settings.anthropic_api_key = "sk-offline"
    settings.openai_api_key = "sk-offline"
    tools, messages = conversation
    bound = build_chat_model(Choice(spec, "high"), settings).bind_tools(tools)
    return bound.bound._get_request_payload(messages, **bound.kwargs)


def test_anthropic_puts_image_inside_tool_result(settings, observe_conversation):
    payload = _payload(settings, observe_conversation, "anthropic:claude-opus-5-5")

    assert payload["output_config"] == {"effort": "high"}
    # Thinking blocks whose conversation changed under them (pruned screenshots) are dropped, not an error.
    assert payload["thinking"]["block_binding"] == {"prefix_mismatch_behavior": "drop_block"}
    assert payload["betas"] == ["thinking-binding-controls-2026-08-01"]
    assert payload["cache_control"] == {"type": "ephemeral"}
    tool_result = payload["messages"][-1]["content"][0]
    assert tool_result["type"] == "tool_result"
    assert tool_result["tool_use_id"] == "call_observe"
    image = tool_result["content"][1]
    assert image["type"] == "image"
    assert image["source"]["type"] == "base64"
    assert image["source"]["media_type"] == "image/png"


def test_anthropic_gets_a_failed_result_with_the_screen_as_a_plain_one(settings, observe_conversation):
    # Anthropic takes only text in a result marked an error; ours carry the screen, so the mark goes, the text stays.
    tools, messages = observe_conversation
    failed = messages[-1].model_copy(update={"status": "error"})
    payload = _payload(settings, (tools, [*messages[:-1], failed]), "anthropic:claude-haiku-5-5")

    tool_result = payload["messages"][-1]["content"][0]
    assert "is_error" not in tool_result and tool_result["content"][1]["type"] == "image"
    text_only = ToolMessage("Not executed: no such key.", tool_call_id="call_observe", name="observe", status="error")
    payload = _payload(settings, (tools, [*messages[:-1], text_only]), "anthropic:claude-haiku-5-5")
    assert payload["messages"][-1]["content"][0]["is_error"] is True


def test_openai_responses_puts_image_inside_function_call_output_at_original_resolution(settings, observe_conversation):
    tools, messages = observe_conversation
    # A run starts with the screen in the first user message, then gets one in every tool result.
    first_screen = HumanMessage(content=messages[-1].content)
    payload = _payload(settings, (tools, [first_screen, *messages[1:]]), "openai:gpt-6.1-sol")

    assert payload["reasoning"] == {"effort": "high"}
    user, output = payload["input"][0], payload["input"][-1]
    assert output["type"] == "function_call_output"
    assert output["call_id"] == "call_observe"
    image = output["output"][1]
    assert image["type"] == "input_image"
    assert image["image_url"].startswith("data:image/png;base64,")
    images = [block for block in [*user["content"], *output["output"]] if block["type"] == "input_image"]
    assert len(images) == 2
    assert all(image["detail"] == "original" for image in images)


def test_model_calls_time_out_instead_of_hanging(settings):
    settings.anthropic_api_key = settings.openai_api_key = "sk-offline"
    openai = build_chat_model(Choice("openai:gpt-6.1-sol", "low"), settings)
    anthropic = build_chat_model(Choice("anthropic:claude-opus-5-5", "high"), settings)
    assert (openai.request_timeout, openai.max_retries) == (120, 2)
    assert (anthropic.default_request_timeout, anthropic.max_retries) == (120, 2)


def test_only_a_model_built_to_stream_streams(settings):
    # The main agent's (agent.main_agent): streaming it would stream the subagents' calls under it too, unless they say no.
    settings.anthropic_api_key = settings.openai_api_key = "sk-offline"
    for spec in ("openai:gpt-6-luna", "anthropic:claude-opus-5-5"):
        assert build_chat_model(Choice(spec, "high"), settings).disable_streaming is True
        assert build_chat_model(Choice(spec, "high"), settings, stream=True).disable_streaming is False


def test_openai_is_offered_the_hand_over_tools_and_left_to_choose_among_them(settings):
    from computer_use.agent.computer_agent import ComputerAgent
    from computer_use.agent.main_agent import handover_tools

    settings.openai_api_key = "sk-offline"
    desktop = ComputerAgent(settings, None, None, None, "thread", "@Computer open Notepad", 10)  # never run here
    tools = handover_tools([desktop], lock=None, background=None, user=None)
    bound = build_chat_model(Choice("openai:gpt-6-luna", "high"), settings).bind_tools(tools)
    payload = bound.bound._get_request_payload([HumanMessage("@Computer open Notepad")], **bound.kwargs)

    assert "tool_choice" not in payload  # a message for the desktop is not forced (agent.main_agent DESKTOP_ASKED)
    # Without a code runner, it is not offered the coding agent's write_code.
    assert [each["name"] for each in payload["tools"]] == ["computer_use", "tell_task", "stop_task"]
    assert list(payload["tools"][0]["parameters"]["properties"]) == ["title", "task"]
    assert list(payload["tools"][2]["parameters"]["properties"]) == ["task_id"]


async def test_openai_responses_gets_back_an_update_before_a_call_as_commentary_after_the_log_restores_it(settings, store):
    """OpenAI asks for each message's phase back as it came: an update the agent sends before its tool calls taken
    for its final answer can end its turn early. The log keeps the message as the model gave it (agent.trajectory)."""
    settings.openai_api_key = "sk-offline"
    update = AIMessage(
        content=[{"type": "text", "text": "Opening File Explorer to read C:.", "phase": "commentary", "id": "msg_1"}],
        tool_calls=[{"id": "call_1", "name": "key", "args": {"text": "win+e"}, "type": "tool_call"}],
    )
    answer = AIMessage(content=[{"type": "text", "text": "C: has 41 GB free.", "phase": "final_answer", "id": "msg_2"}])
    messages = [HumanMessage("How much space is left on C:?"), update, ToolMessage("Pressed win+e.", tool_call_id="call_1"),
                answer, HumanMessage("Thanks.")]
    restored = [await restore(store, "r1", message_to_dict(message)) for message in messages]

    payload = build_chat_model(Choice("openai:gpt-6-luna", "high"), settings)._get_request_payload(restored)

    said = [item for item in payload["input"] if item.get("type") == "message" and item.get("role") == "assistant"]
    assert [(item["content"][0]["text"], item["phase"]) for item in said] == [
        ("Opening File Explorer to read C:.", "commentary"), ("C: has 41 GB free.", "final_answer"),
    ]


def test_claude_is_offered_with_every_effort_it_takes(settings):
    from computer_use.agent.models import efforts, offered

    settings.main_model = "anthropic:claude-haiku-5-5"
    claude = [spec for spec in offered(settings) if spec.startswith("anthropic:")]
    assert claude == ["anthropic:claude-haiku-5-5", "anthropic:claude-sonnet-5-5", "anthropic:claude-opus-5-5"]
    assert all(efforts(spec) == ("low", "medium", "high", "xhigh", "max") for spec in claude)
