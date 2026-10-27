"""LangSmith traces carry no screenshots or encrypted reasoning, and graph nodes only a conversation's newest message
and the tools' names."""

import base64
from unittest.mock import MagicMock

import langsmith
from langchain.agents.middleware.types import ModelResponse
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langchain_core.tracers import LangChainTracer

from computer_use.agent.tools import image_block
from computer_use.agent.tracing import SCREENSHOT_NOT_TRACED, for_trace
from conftest import fixture_png

SCREENS = ("FIRST", "NEWEST")
ENCRYPTED = "gAAAAB-encrypted-reasoning"


def conversation() -> list:
    call = {"id": "c1", "name": "key", "args": {"text": "ctrl+s"}, "type": "tool_call"}
    reasoning = {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": ENCRYPTED}
    first, newest = (image_block(fixture_png(code)) for code in SCREENS)
    return [
        HumanMessage(content=[{"type": "text", "text": "Goal: save"}, first]),
        AIMessage(content=[reasoning, {"type": "text", "text": "Saving."}], tool_calls=[call]),
        ToolMessage(content=[{"type": "text", "text": "Pressed ctrl+s."}, newest], tool_call_id="c1"),
    ]


def screenshots_in(data) -> list[str]:
    return [code for code in SCREENS if base64.b64encode(fixture_png(code)).decode() in str(data)]


def test_graph_state_is_traced_with_its_newest_message_only():
    messages = conversation()

    traced = for_trace({"messages": messages, "goals": ["save"]})

    note, newest = traced["messages"]
    assert note == "[2 earlier messages not traced]"
    assert newest.content == [{"type": "text", "text": "Pressed ctrl+s."}, SCREENSHOT_NOT_TRACED]
    assert traced["goals"] == ["save"]
    assert screenshots_in(messages) == list(SCREENS) and ENCRYPTED in str(messages)  # the agent's own keep theirs


def test_node_traces_tools_by_name():
    @tool
    def key(text: str) -> str:
        """Press keys."""
        return text

    assert for_trace({"request": {"tools": [key], "tool": key}}) == {"request": {"tools": ["key"], "tool": "key"}}


def test_node_output_is_traced_without_encrypted_reasoning():
    response = ModelResponse(result=[conversation()[1]])

    traced = for_trace({"output": response})

    assert isinstance(traced["output"], ModelResponse)
    assert ENCRYPTED not in str(traced) and "Saving." in str(traced)
    assert ENCRYPTED in str(response)


def test_model_call_is_traced_whole_without_screenshots_or_encrypted_reasoning():
    client = MagicMock(spec=langsmith.Client)  # receives the runs as LangChain hands them to LangSmith
    model = GenericFakeChatModel(messages=iter([AIMessage("Saved.")]))
    model.invoke(conversation(), config={"callbacks": [LangChainTracer(client=client)]})

    inputs = client.create_run.call_args.kwargs["inputs"]
    traced = for_trace(inputs)

    assert screenshots_in(inputs) == list(SCREENS) and ENCRYPTED in str(inputs)
    assert len(traced["messages"][0]) == 3  # every message the model saw
    assert screenshots_in(traced) == [] and ENCRYPTED not in str(traced)
    assert "Saving." in str(traced) and "Pressed ctrl+s." in str(traced)
