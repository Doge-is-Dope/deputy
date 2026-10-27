"""A conversation is named from its first message by a small model in the background (agent.title): the name goes into
the run's log, where the page lists the conversation by it; a run never waits for it, one that is stopped or fails still
gets it, and one that gets none leaves it to the conversation's next run."""

import asyncio
import json

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

import computer_use.agent.main_agent as main_agent
import computer_use.agent.title as title
from computer_use.agent.models import build_chat_model
from computer_use.config import Choice, RunChoices, Settings
from computer_use.agent.history import has_title
from conftest import run_turn
from conftest import read_events, run_dir
from conftest import SCRIPTED_TITLE, ScriptedModel, run_folder, use_script


@pytest.fixture(autouse=True)
async def titles(settings, store, monkeypatch):
    jobs = title.Titles(settings, store)
    run = main_agent.run_turn

    async def run_with_titles(*args, **kwargs):
        return await run(*args, **kwargs, titles=jobs)

    monkeypatch.setattr(main_agent, "run_turn", run_with_titles)
    yield jobs
    await jobs.close()


@pytest.mark.parametrize(("reply", "cleaned"), [
    ("Paste a sum into Notepad", "Paste a sum into Notepad"),
    ('Title: "Paste a sum into Notepad."', "Paste a sum into Notepad"),
    ("**用小算盤算出結果貼到記事本。**\n\nA second line.", "用小算盤算出結果貼到記事本"),
    ("「打開記事本」", "打開記事本"),
    ("  \n # List the  Documents folder!  ", "List the Documents folder"),
    ("x" * 100, "x" * title.MAX_CHARS),
    ('""', None),
    ("", None),
])
def test_a_reply_is_cleaned_to_its_title(reply, cleaned):
    assert title.clean(reply) == cleaned


async def test_the_title_model_reads_the_first_message_alone_at_low_effort(settings, monkeypatch):
    model = ScriptedModel(messages=iter([AIMessage('{"title":"Paste a sum into Notepad"}')]), received=[], bindings=[])
    built = []
    monkeypatch.setattr(title, "build_chat_model", lambda choice, _, **__: built.append(choice) or model)

    named = await title.generate_title(settings, "Use Calculator to work out 128 × 37 and paste the result into Notepad")

    assert named is not None and named[0] == "Paste a sum into Notepad"
    assert built == [Choice(title.MODEL, "low")]
    assert model.bindings == [{"method": "json_schema", "strict": True, "include_raw": True}]
    (asked,) = model.received
    assert [type(message) for message in asked] == [SystemMessage, HumanMessage]
    assert asked[0].text == title.TITLE_PROMPT and "128 × 37" in asked[1].text


async def test_a_long_message_is_cut_and_a_failed_or_slow_call_names_nothing(settings, monkeypatch, capsys):
    model = ScriptedModel(messages=iter([AIMessage('{"title":"Long message"}')]), received=[], bindings=[])
    monkeypatch.setattr(title, "build_chat_model", lambda *_, **__: model)
    assert await title.generate_title(settings, "x" * 5000) is not None
    assert len(model.received[0][1].text) == title.MESSAGE_CHARS

    class Failing:
        def with_structured_output(self, *_, **__):
            return self

        async def ainvoke(self, *_, **__):
            raise RuntimeError("no key")

    monkeypatch.setattr(title, "build_chat_model", lambda *_, **__: Failing())
    assert await title.generate_title(settings, "hi") is None
    assert "no title: RuntimeError: no key" in capsys.readouterr().out

    class Slow(Failing):
        async def ainvoke(self, *_, **__):
            await asyncio.sleep(1)

    monkeypatch.setattr(title, "CALL_SECONDS", 0.01)
    monkeypatch.setattr(title, "build_chat_model", lambda *_, **__: Slow())
    assert await title.generate_title(settings, "hi") is None


def test_the_title_model_is_its_own_setting_at_low_effort(monkeypatch):
    settings = Settings(_env_file=None, main_model="openai:main-model", computer_model="openai:computer-model")
    assert title.title_model(settings) == Choice(title.MODEL, "low")  # unset, whatever the agents' are
    monkeypatch.setenv("CU_TITLE_MODEL", "openai:gpt-6.1-sol")
    assert title.title_model(Settings(_env_file=None)) == Choice("openai:gpt-6.1-sol", "low")


@pytest.mark.parametrize(("content", "named"), [
    ({"type": "output_text", "text": '{"title":"計算乘積"}', "annotations": []}, "計算乘積"),
    ({"type": "output_text", "text": json.dumps({"title": "x" * 81}), "annotations": []}, "x" * title.MAX_CHARS),
    ({"type": "output_text", "text": '{"title":123}', "annotations": []}, None),
    ({"type": "output_text", "text": '{"wrong":"title"}', "annotations": []}, None),
    ({"type": "output_text", "text": '{"title":"ok","extra":true}', "annotations": []}, None),
    ({"type": "output_text", "text": '{"title":"   "}', "annotations": []}, None),
    ({"type": "output_text", "text": 'plain text', "annotations": []}, None),
    ({"type": "refusal", "refusal": "Cannot provide a title"}, None),
])
async def test_structured_titles_use_the_responses_schema_and_reject_invalid_output(
    settings, monkeypatch, content, named
):
    # Use the real LangChain/OpenAI serialization and parsing, with only HTTP replaced.
    from openai import AsyncOpenAI

    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={
            "id": "resp_title", "object": "response", "created_at": 0, "status": "completed",
            "model": "gpt-6-luna", "error": None, "incomplete_details": None,
            "output": [{"id": "msg_title", "type": "message", "role": "assistant", "status": "completed",
                        "content": [content]}],
            "usage": {"input_tokens": 30, "output_tokens": 8, "total_tokens": 38,
                      "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}},
        })

    settings.openai_api_key = "sk-offline"
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        model = build_chat_model(title.title_model(settings), settings)
        model.root_async_client = AsyncOpenAI(api_key="sk-offline", http_client=client)
        model.async_client = model.root_async_client.chat.completions
        monkeypatch.setattr(title, "build_chat_model", lambda *_, **__: model)
        result = await title.generate_title(settings, "幫我計算 128 乘以 37")

    (request,) = requests
    assert request["model"] == title.MODEL.partition(":")[2]
    assert request["reasoning"] == {"effort": "low"}
    output_format = request["text"]["format"]
    assert output_format["type"] == "json_schema" and output_format["strict"] is True
    assert output_format["schema"]["required"] == ["title"]
    assert output_format["schema"]["additionalProperties"] is False
    field = output_format["schema"]["properties"]["title"]
    assert field["type"] == "string" and not {"minLength", "maxLength"} & field.keys()  # title.clean cuts a long one
    usage = {"input": 30, "cached": 0, "cache_write": 0, "output": 8, "reasoning": 0}
    assert result == ((named, usage) if named else None)


async def test_model_setup_failure_does_not_fail_the_conversation(settings, computer, monkeypatch, store):
    use_script(monkeypatch, [], main=[AIMessage("Hello.")])

    def fail(*_, **__):
        raise ValueError("unsupported title model")

    monkeypatch.setattr(title, "build_chat_model", fail)
    result = await run_turn(settings, "Hi", max_steps=10, computer=computer)
    events = read_events(run_dir(settings, result.run))
    assert events[-1]["type"] == "end" and events[-1]["stop_reason"] == "replied"
    assert not await has_title(store, result.run)


async def test_a_title_that_cannot_start_does_not_fail_the_run(settings, store, computer, monkeypatch, capsys):
    use_script(monkeypatch, [], main=[AIMessage("Hello.")])

    async def unreadable(*_):
        raise ValueError("unreadable log")

    monkeypatch.setattr(store, "events", unreadable)
    result = await run_turn(settings, "Hi", max_steps=10, computer=computer)
    assert read_events(run_dir(settings, result.run))[-1]["stop_reason"] == "replied"
    assert "no title: ValueError: unreadable log" in capsys.readouterr().out


async def test_a_new_conversation_is_named_once_in_its_first_run(settings, computer, monkeypatch, titles, store):
    use_script(monkeypatch, [], main=[AIMessage("4736."), AIMessage("Yes.")])
    built, builder = [], title.build_chat_model
    monkeypatch.setattr(title, "build_chat_model", lambda choice, settings: built.append(choice) or builder(choice, settings))

    settings.title_model = "openai:independent-title-model"
    first = await run_turn(
        settings, "What is 128 x 37?", max_steps=10, computer=computer,
        choices=RunChoices(agents={"computer": {"model": "follow"}, "main": {"model": "openai:gpt-6.1-sol"}}),
    )
    await titles.close(cancel=False)
    events = read_events(run_dir(settings, first.run))
    (named,) = [event for event in events if event["type"] == "title"]
    assert named["text"] == SCRIPTED_TITLE and named["usage"]["input"] >= 0 and named["seconds"] >= 0
    assert built == [title.title_model(settings)] and built[0].model == "openai:independent-title-model"
    assert any(event["type"] == "end" for event in events)
    assert await has_title(store, first.run)

    second = await run_turn(settings, "Sure?", max_steps=10, computer=computer, thread=first.run)
    assert [event["type"] for event in read_events(run_dir(settings, second.run)) if event["type"] == "title"] == []


async def test_a_conversation_left_unnamed_is_named_at_its_next_run(settings, computer, monkeypatch, titles, store):
    use_script(monkeypatch, [], main=[AIMessage("4736."), AIMessage("Yes.")])
    calls = []

    async def nothing(_settings, message, _choice=None):
        calls.append(message)
        return None

    monkeypatch.setattr(title, "generate_title", nothing)
    first = await run_turn(settings, "What is 128 x 37?", max_steps=10, computer=computer)
    await titles.close(cancel=False)
    assert not await has_title(store, first.run) and calls == ["What is 128 x 37?"]

    async def named(_settings, message, _choice=None):
        calls.append(message)
        return "Multiplying numbers", {"input": 1, "cached": 0, "cache_write": 0, "output": 1, "reasoning": 0}

    monkeypatch.setattr(title, "generate_title", named)
    second = await run_turn(settings, "Sure?", max_steps=10, computer=computer, thread=first.run)
    # Named from the conversation's first message, not the one that started this run.
    await titles.close(cancel=False)
    assert calls == ["What is 128 x 37?", "What is 128 x 37?"]
    (event,) = [event for event in read_events(run_dir(settings, second.run)) if event["type"] == "title"]
    assert event["text"] == "Multiplying numbers"


async def test_a_title_outlives_its_run_and_is_not_duplicated_by_the_next(settings, computer, monkeypatch, titles, store):
    use_script(monkeypatch, [], main=[AIMessage("4736."), AIMessage("Yes.")])
    gate, asked = asyncio.Event(), asyncio.Event()
    calls = []

    async def slow(_settings, message, _choice=None):
        calls.append(message)
        asked.set()
        await gate.wait()
        return "Multiplying numbers", {"input": 10, "cached": 0, "cache_write": 0, "output": 4, "reasoning": 0}

    monkeypatch.setattr(title, "generate_title", slow)
    first = await asyncio.wait_for(run_turn(settings, "128 x 37?", max_steps=10, computer=computer), 1)
    await asked.wait()
    assert first.run in titles.tasks and not await has_title(store, first.run)
    assert read_events(run_dir(settings, first.run))[-1]["type"] == "end"
    second = await run_turn(settings, "Sure?", max_steps=10, computer=computer, thread=first.run)
    assert calls == ["128 x 37?"] and not await has_title(store, first.run)
    before = read_events(run_dir(settings, first.run))[-1]
    revision = await store.revision()
    gate.set()
    await titles.close(cancel=False)
    events = read_events(run_dir(settings, first.run))
    assert events[-1]["type"] == "title" and events[-1]["text"] == "Multiplying numbers"
    assert events[-1]["model"] == title.MODEL and events[-1]["cost"]["output"] > 0
    assert next(event for event in events if event["type"] == "end") == before
    assert not any(event["type"] == "title" for event in read_events(run_dir(settings, second.run)))
    assert not titles.tasks and await store.revision() > revision


@pytest.mark.parametrize("outcome", ["stopped", "failed"])
async def test_stopping_or_failing_the_agent_does_not_cancel_its_title(settings, computer, monkeypatch, titles, outcome):
    asked, finish_title, fail_agent = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def slow(*_):
        asked.set()
        await finish_title.wait()
        return "Independent title", {"input": 1, "cached": 0, "cache_write": 0, "output": 1, "reasoning": 0}

    async def fail(*_):
        await fail_agent.wait()
        raise RuntimeError("agent failed")

    monkeypatch.setattr(title, "generate_title", slow)
    monkeypatch.setattr(main_agent, "speak", fail)
    use_script(monkeypatch, [], main=[])
    task = asyncio.create_task(run_turn(settings, "Hi", max_steps=10, computer=computer))
    await asked.wait()
    if outcome == "stopped":
        task.cancel()
    else:
        fail_agent.set()
    with pytest.raises(asyncio.CancelledError if outcome == "stopped" else RuntimeError):
        await task
    folder = run_folder(settings)
    assert folder.name in titles.tasks and read_events(folder)[-1]["type"] == "end"
    finish_title.set()
    await titles.close(cancel=False)
    assert read_events(folder)[-1]["text"] == "Independent title"


async def test_runtime_shutdown_cancels_pending_titles(settings, computer, monkeypatch, titles, store):
    asked, cancelled = asyncio.Event(), asyncio.Event()
    use_script(monkeypatch, [], main=[AIMessage("Hi.")])

    async def slow(*_):
        asked.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(title, "generate_title", slow)
    result = await run_turn(settings, "Hi", max_steps=10, computer=computer)
    await asked.wait()
    await titles.close()
    assert cancelled.is_set() and not titles.tasks
    assert not await has_title(store, result.run)
