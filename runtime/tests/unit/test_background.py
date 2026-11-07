import asyncio

import httpx
import openai

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

import computer_use.agent.main_agent as main_agent
import computer_use.agent.computer_agent as computer_agent
from computer_use.agent.background import Background, Job, report
from computer_use.storage import MAIN
from conftest import run_turn
from conftest import events_of, first_run
from computer_use.desktop.control import RunLock
from computer_use.agent.inbox import Inbox
from conftest import ScriptedModel, delegate, logged, sent_while_pressing, telling, tool_call, use_script

pytestmark = pytest.mark.usefixtures("the_log_is_the_whole_record")


async def test_one_task_uses_the_computer_at_a_time(settings, computer, monkeypatch):
    computer_model, main_model = use_script(monkeypatch, [
        AIMessage(content="", tool_calls=[tool_call("c1", "key", text="win")]),
        AIMessage("Opened Start."),
    ], main=[
        delegate("Open Start.", "m1"), delegate("Open Notepad too.", "m2"), AIMessage("One thing at a time."),
        AIMessage("Start is open."),
    ])
    inbox = Inbox()
    # While the task runs, the user writes; the main agent tries to start another and replies, and then it goes on.
    sent_while_pressing(computer, inbox, "and open Notepad too", until=lambda: len(main_model.received) >= 3)

    result = await run_turn(settings, "open start", max_steps=10, computer=computer, inbox=inbox)

    refused = next(m for m in main_model.received[2] if isinstance(m, ToolMessage) and m.tool_call_id == "m2")
    assert refused.status == "error" and refused.text.startswith("Not executed: task t1 is using the computer")
    assert len(computer_model.received) == 2 and result.reply == "Start is open."


async def test_the_desktop_is_let_go_of_once_its_task_ends(settings, computer, monkeypatch):
    holders = []

    class Watching(ScriptedModel):
        async def ainvoke(self, input, config=None, **kwargs):
            holders.append(RunLock(settings.run_lock_path).holder())
            return await super().ainvoke(input, config, **kwargs)

    main = Watching(messages=iter([delegate(), AIMessage("Done.")]), received=[], bindings=[])
    use_script(monkeypatch, [AIMessage("Opened Start.")])
    monkeypatch.setattr(main_agent, "build_chat_model", lambda _spec, _settings, **_: main)

    await run_turn(settings, "open start", max_steps=10, computer=computer)

    # Free before the task, and free again once it ended, while the main agent checks it.
    assert [holder is None for holder in holders] == [True, True]


async def test_a_task_that_fails_outright_is_told_to_the_main_agent_which_answers(settings, computer, monkeypatch):
    class Broken(ScriptedModel):
        async def ainvoke(self, input, config=None, **kwargs):
            raise RuntimeError("model service down")

    _, main_model = use_script(monkeypatch, [], main=[delegate(), AIMessage("The task failed: the model is down.")])
    monkeypatch.setattr(computer_agent, "build_chat_model", lambda _spec, _settings: Broken(messages=iter([])))

    result = await run_turn(settings, "open start", max_steps=10, computer=computer)

    # Its own log ends in the error; the main agent hears why, as of a task that ended, and the session goes on.
    ends = [event for event in events_of(settings, first_run(settings)) if event["type"] == "end"]
    assert [end["stop_reason"] for end in ends] == ["replied", "error", "replied"]
    told = main_model.received[1][-1]
    assert told.additional_kwargs["runtime"]["event"] == "task_failed"
    assert "t1" in told.text and "RuntimeError: model service down" in told.text
    assert result.reply == "The task failed: the model is down."


async def test_a_turn_that_hands_work_over_ends_there(settings, computer, monkeypatch):
    _, main_model = use_script(monkeypatch, [AIMessage("Opened Start.")], main=[
        AIMessage(content="Opening Start.", tool_calls=[tool_call("m1", "start_task", agent="computer", title="Task", task="Open Start.")]),
        AIMessage("Start is open."),
    ])

    result = await run_turn(settings, "open start", max_steps=10, computer=computer)

    assert len(main_model.received) == 2 and result.reply == "Start is open."
    replies = [e["text"] for e in logged(result, "model", MAIN)]
    assert replies == ["Opening Start.", "Start is open."]


async def test_what_it_is_told_while_it_writes_its_reply_it_reads_before_ending(settings, computer, monkeypatch):
    told, inbox = telling(monkeypatch), Inbox()

    class Replying(ScriptedModel):  # while it writes the reply that would end the task, the user changes it
        async def ainvoke(self, input, config=None, **kwargs):
            if len(self.received) == 1:
                inbox.put("and close it again")
                for _ in range(1000):
                    if told:
                        break
                    await asyncio.sleep(0.01)
            return await super().ainvoke(input, config, **kwargs)

    _, main_model = use_script(monkeypatch, [], main=[
        delegate("Open Start."),
        AIMessage(content="", tool_calls=[tool_call("m2", "tell_task", task_id="t1", message="Close Start again.")]),
        AIMessage("Start was opened, then closed."),
    ])
    computer_model = Replying(messages=iter([
        AIMessage(content="", tool_calls=[tool_call("c1", "key", text="win")]),
        AIMessage("Opened Start."),
        AIMessage("Closed Start again."),
    ]), received=[], bindings=[])
    monkeypatch.setattr(computer_agent, "build_chat_model", lambda _spec, _settings: computer_model)

    result = await run_turn(settings, "open start", max_steps=10, computer=computer, inbox=inbox)

    assert len(computer_model.received) == 3
    note = computer_model.received[2][-1]
    assert isinstance(note, HumanMessage) and "Close Start again." in note.text
    ended = next(m for m in main_model.received[-1] if "has ended" in m.text)
    assert "Closed Start again." in ended.text and "ended before reading" not in ended.text
    assert result.reply == "Start was opened, then closed."


async def test_what_a_task_is_told_as_it_ends_reaches_the_main_agent_as_unread(tmp_path):
    class Turn:
        def task(self, *args):
            pass

    background, done = Background(), asyncio.Event()

    async def work(_id, inbox):  # ends without reading what it is told meanwhile
        await done.wait()
        return [{"type": "text", "text": "Opened Start."}], {}

    id = background.start("computer", "Open Start.", work, lambda: [], turn=Turn(), record="r1")
    background.tell(id, "Close Start again.")
    done.set()
    await background.wait()

    (report,) = background.reports()
    assert "Opened Start." in report.text
    assert "It ended before reading what you told it with tell_task:\nClose Start again." in report.text


async def test_tasks_past_the_most_at_once_are_refused_until_one_ends(tmp_path):
    from computer_use.agent.background import MAX_TASKS

    class Turn:
        def task(self, *args):
            pass

    background, done = Background(), asyncio.Event()

    async def work(_id, _inbox):
        await done.wait()
        return [], {}

    ids = [background.start("coding", "Add.", work, lambda: [], turn=Turn(), record=f"r{n}") for n in range(MAX_TASKS)]

    assert ids == [f"t{n}" for n in range(1, MAX_TASKS + 1)] and background.full
    await background.stop(ids[0])
    assert not background.full
    done.set()
    await background.wait()


def test_a_task_the_model_service_failed_is_told_as_the_model_services_error():
    job = Job("t1", "r1", "coding", "Write a.txt.", 0.0, Inbox(), None, None)
    overloaded = openai.APIError("Our servers are currently overloaded.", httpx.Request("POST", "https://api.invalid"),
                                 body={"type": "server_error"})

    assert "the model service reported an error. APIError: Our servers" in report(job, overloaded).text
    assert "model service" not in report(job, RuntimeError("runner down")).text
