"""Real model calls against CU_COMPUTER_MODEL. Run with `uv run pytest -m model`; needs an API key in .env."""

import os

import pytest

from computer_use.agent.computer_agent import ComputerAgent
from computer_use.agent.models import build_chat_model, chosen
from computer_use.config import Settings

# One event loop for the module: langchain-openai caches its HTTP client, which is bound to the loop it first ran on.
pytestmark = [pytest.mark.model, pytest.mark.asyncio(loop_scope="module")]


async def test_screenshot_reaches_model(observe_conversation, computer):
    # The keys and model come from .env here, unlike the deterministic tests.
    settings = Settings()
    choice = chosen(settings, "computer")
    provider = choice.model.partition(":")[0]
    if not (getattr(settings, f"{provider}_api_key", None) or os.environ.get(f"{provider.upper()}_API_KEY")):
        pytest.skip(f"no API key for {choice.model}")
    tools, messages = observe_conversation
    reply = await build_chat_model(choice, settings).bind_tools(tools).ainvoke(messages)
    # The code is drawn only in the screenshot, so a correct answer proves it arrived as an image.
    assert computer.CODE in reply.text, f"{choice.model} answered {reply.text!r}"


async def test_the_main_agent_answers_a_question_itself_and_says_what_it_will_do_as_it_hands_desktop_work_over():
    from langchain_core.messages import HumanMessage, SystemMessage

    from computer_use.tools.tasks import handover_tools, TaskTool
    from computer_use.prompts.main import MAIN_PROMPT

    settings = Settings()
    provider = settings.main_model.partition(":")[0]
    if not (getattr(settings, f"{provider}_api_key", None) or os.environ.get(f"{provider.upper()}_API_KEY")):
        pytest.skip(f"no API key for {settings.main_model}")
    main = build_chat_model(chosen(settings, "main"), settings)
    # Only the tools' descriptions reach the model here; nothing calls them, so they need no desktop or task.
    desktop = TaskTool(ComputerAgent.agent, ComputerAgent.about, None)  # schema only
    model = main.bind_tools(handover_tools([desktop], None, None))

    async def reply(message: str):
        return await model.ainvoke([SystemMessage(MAIN_PROMPT), HumanMessage(message)])

    assert (await reply("What is 128 times 37?")).tool_calls == []
    handed = await reply("Open Notepad on my computer and type hello.")
    assert [(call["name"], call["args"]["agent"]) for call in handed.tool_calls] == [("start_task", "computer")]
    # Until the task ends, these words are all the user hears from it.
    assert handed.text.strip(), "it handed the task over without a word to the user"
