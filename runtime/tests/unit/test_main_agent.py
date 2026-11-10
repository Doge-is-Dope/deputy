import asyncio
import contextlib
import json
import time
from datetime import datetime

import httpx
import openai
import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.tools import tool

import computer_use.agent.main_agent as main_agent
import computer_use.agent.session as session
import computer_use.agent.computer_agent as computer_agent
import computer_use.middleware.chat as chat
import computer_use.middleware.common as common
import computer_use.tools.conversations as conversations
from computer_use.middleware.common import raise_if_stopped
from computer_use.prompts import notes
from computer_use.prompts.computer import DESKTOP_ASKED, DESKTOP_HANDED
from computer_use.agent.background import from_user
from computer_use.streaming import Draft
from computer_use.agent.inbox import Inbox
from computer_use.config import RunChoices
from computer_use.memory.files import FileMemoryStore
from computer_use.storage import MAIN
from computer_use.storage.files import FileRuns
from computer_use.desktop.control import RunLock
from conftest import run_turn, runs_dir
from conftest import crash_point, events_of, first_run, read_events, run_file, task_folder, task_states
from conftest import (
    ScriptedModel,
    StreamingModel,
    computer_use_result,
    delegate,
    fixture_png,
    logged,
    sent_while_pressing,
    telling,
    tool_call,
    use_script,
)

pytestmark = pytest.mark.usefixtures("the_log_is_the_whole_record")


def system_text(messages) -> str:
    content = messages[0].content
    return content if isinstance(content, str) else "".join(block["text"] for block in content)


def first_text(messages) -> str:
    message = next(m for m in messages if isinstance(m, HumanMessage))
    return message.content if isinstance(message.content, str) else message.content[0]["text"]


async def test_a_question_is_answered_without_touching_the_desktop(settings, computer, monkeypatch):
    computer_model, _ = use_script(monkeypatch, [], main=[AIMessage("128 x 37 = 4736.")])

    result = await run_turn(settings, "What is 128 x 37?", max_steps=10, computer=computer)

    assert (result.reply, result.computer) == ("128 x 37 = 4736.", None)
    assert computer.calls == [] and computer.releases == 0 and computer_model.received == []
    assert not settings.control_path.exists()
    assert not settings.run_lock_path.exists()
    events = events_of(settings, result.run)
    assert all(event.get("agent") == MAIN for event in events if "message" in event)
    end = events[-1]
    assert (end["type"], end["stop_reason"], end["computer"], end["summary"]) == ("end", "replied", None, "128 x 37 = 4736.")


@pytest.mark.parametrize(
    "message", ["@Computer open Notepad", "@computer", "  @COMPUTER打開記事本", "請 @Computer 打開記事本", "用@Computer開記事本"]
)
def test_a_message_that_mentions_at_computer_is_for_the_desktop(message):
    assert computer_agent.MENTION.said(message)


@pytest.mark.parametrize("message", ["open Notepad", "@Computers are fast", "write to me@computer.org"])
def test_other_messages_are_not(message):
    assert not computer_agent.MENTION.said(message)


@pytest.mark.parametrize("forced", [True, False])
async def test_a_message_for_the_desktop_comes_with_the_runtimes_word_rather_than_a_forced_tool(
    settings, computer, monkeypatch, forced
):
    _, main_model = use_script(monkeypatch, [AIMessage("Opened it.")])

    await run_turn(settings, "open notepad", max_steps=10, computer=computer, force_computer=forced)

    # Free to hand other work over with it, as no model is forced to call one tool.
    assert [binding.get("tool_choice") for binding in main_model.bindings] == [None, None]
    assert all("parallel_tool_calls" not in binding for binding in main_model.bindings)
    last = main_model.received[0][-1]
    assert (not from_user(last) and DESKTOP_ASKED in last.text) is forced


async def test_a_message_for_the_desktop_the_main_agent_does_not_hand_over_the_runtime_hands_over_as_it_is(
    settings, computer, monkeypatch
):
    computer_model, main_model = use_script(monkeypatch, [AIMessage("Opened Notepad.")], main=[
        AIMessage("Sure."), AIMessage("It is on the desktop now."), AIMessage("Notepad is open."),
    ])

    result = await run_turn(
        settings, "@Computer open notepad", max_steps=10, computer=computer, force_computer=True
    )

    assert result.reply == "Notepad is open." and len(computer_model.received) == 1
    events = events_of(settings, result.run)
    (started,) = [event for event in events if event["type"] == "task" and event["state"] == "started"]
    assert (started["agent"], started["title"]) == ("computer", "open notepad")
    assert started["brief"] == "@Computer open notepad"
    # Told at once, as its reply called nothing: it says so in its next call, before the task ends.
    told = main_model.received[1][-1]
    assert not from_user(told) and told.text.startswith("[From the runtime, not the user] " + DESKTOP_HANDED)
    assert "Started in the background as task t1." in told.text


async def test_a_plan_written_first_is_not_taken_for_a_reply_that_leaves_the_desktop_out(
    settings, computer, monkeypatch
):
    computer_model, _ = use_script(monkeypatch, [AIMessage("Opened Notepad.")], main=[
        AIMessage(content="", tool_calls=[tool_call("m1-plan", "write_plan", steps=plan(None, None))]),
        delegate("Open Notepad.", "m1"),
        AIMessage("Notepad is open."),
    ])

    result = await run_turn(
        settings, "@Computer open notepad, then type hi", max_steps=10, computer=computer, force_computer=True
    )

    assert result.reply == "Notepad is open." and len(computer_model.received) == 1
    events = events_of(settings, result.run)
    briefs = [event["brief"] for event in events if event["type"] == "task" and event["state"] == "started"]
    assert briefs == ["Open Notepad."]  # the main agent's own hand-over, no other


async def test_each_agent_gets_its_own_model_and_effort(settings, computer, monkeypatch):
    built = []
    use_script(monkeypatch, [AIMessage("Opened it.")])
    for module in (main_agent, computer_agent):
        scripted = module.build_chat_model
        monkeypatch.setattr(module, "build_chat_model", lambda choice, s, scripted=scripted, **kw: built.append(
            (choice.model, choice.effort)) or scripted(choice, s, **kw))
    settings = settings.model_copy(update={
        "computer_model": "openai:gpt-6-luna", "computer_effort": "high", "main_model": "openai:gpt-6.1-sol",
        "main_effort": "medium",
    })

    await run_turn(settings, "open notepad", max_steps=10, computer=computer)

    assert built == [("openai:gpt-6.1-sol", "medium"), ("openai:gpt-6-luna", "high")]


def test_a_choice_follows_the_main_agent_unless_changed_and_its_effort_is_one_the_model_takes(settings):
    from computer_use.agent.models import chosen
    from computer_use.config import Choice

    assert chosen(settings, "coding") == Choice(settings.main_model, settings.main_effort)  # never chosen
    choices = {
        "main": {"model": "openai:gpt-6.1-sol", "effort": "medium"},
        "computer": {"model": "openai:gpt-5-gone", "effort": "none"},  # a model no longer offered
        "coding": {"model": "openai:gpt-6-luna", "effort": "follow"},
    }
    # The main agent's model, at the lowest effort it takes: GPT-6.1 Sol has no "none".
    assert chosen(settings, "computer", choices) == Choice("openai:gpt-6.1-sol", "low")
    assert chosen(settings, "coding", choices) == Choice("openai:gpt-6-luna", "medium")
    following = settings.model_copy(update={"computer_model": "", "computer_effort": ""})
    assert chosen(following, "computer") == Choice(settings.main_model, settings.main_effort)


async def test_the_main_agent_gets_how_the_task_ended_and_a_screenshot_taken_after_it_stopped(
    settings, computer, monkeypatch
):
    use_script(monkeypatch, [AIMessage("Nothing needed doing.")])
    taken = []

    def screen():  # every screenshot shows its own number
        taken.append(len(taken) + 1)
        return fixture_png(str(taken[-1]))

    computer.screen = screen

    result = await run_turn(settings, "look at the screen", max_steps=10, computer=computer)

    handback = computer_use_result(result)
    assert handback["result"].startswith("The computer-use agent stopped: it replied.")
    assert "Its final message (a claim, not evidence): Nothing needed doing." in handback["result"]
    assert "Its actions (0):\n(none)" in handback["result"]
    assert taken == [1, 2]  # the task's first screen, then one more after it stopped
    assert run_file(settings, result.run, handback["screenshot"]).read_bytes() == fixture_png("2")


async def test_the_computer_use_agent_gets_the_task_and_the_users_words(settings, computer, monkeypatch):
    computer_model, _ = use_script(monkeypatch, [AIMessage("Opened it.")], main=[
        delegate("Open Notepad and type the user's text exactly."), AIMessage("Done."),
    ])

    await run_turn(settings, "打開記事本，輸入「明天 3 點開會」", max_steps=10, computer=computer)

    text = first_text(computer_model.received[0])
    assert text.startswith("Goal: Open Notepad and type the user's text exactly.")
    assert "word for word: 打開記事本，輸入「明天 3 點開會」" in text
    assert "Earlier in this conversation" not in text


def test_a_task_in_the_users_own_words_is_marked_as_theirs():
    # Only the user's own words give permission, so the agent must tell them from the main agent's brief.
    assert notes.opening("刪掉桌面的 test.txt", ["刪掉桌面的 test.txt"]) == "Goal, in the user's own words: 刪掉桌面的 test.txt"
    briefed = notes.opening("Delete test.txt on the desktop.", ["刪掉桌面的 test.txt"])
    assert briefed.startswith("Goal: Delete test.txt on the desktop.\n\nThe user's message this task comes from")
    steered = notes.opening("Delete test.txt and a.txt.", ["刪掉桌面的 test.txt", "還有 a.txt"])
    listed = "The user's messages this task comes from, word for word, oldest first:\n- 刪掉桌面的 test.txt\n- 還有 a.txt"
    assert listed in steered


async def test_each_task_starts_afresh_with_a_blackboard_of_the_conversation(settings, computer, monkeypatch):
    computer_model, _ = use_script(monkeypatch, [
        AIMessage(content="", tool_calls=[tool_call("c1", "key", text="win")]),
        AIMessage("Opened Start."),
        AIMessage("Closed it."),
    ], main=[
        delegate("Open Start.", "m1"), delegate("Close Start.", "m2"), AIMessage("Done."),
    ])
    first = await run_turn(settings, "open and close start", max_steps=10, computer=computer)

    second_task = computer_model.received[-1]
    assert [type(m).__name__ for m in second_task] == ["SystemMessage", "HumanMessage"]
    board = first_text(second_task)
    assert "An earlier task, handed to the computer agent: Open Start.\nIt ended: replied. Its final message: Opened Start." in board
    assert '  key {"text": "win"} -> success: Pressed win.' in board

    computer_model, _ = use_script(monkeypatch, [AIMessage("Checked.")])
    await run_turn(settings, "check it", max_steps=10, computer=computer, thread=first.run)

    board = first_text(computer_model.received[0])
    assert "The user's earlier messages, oldest first:\n- open and close start" in board
    assert board.index("An earlier task, handed to the computer agent: Open Start.") < board.index("An earlier task, handed to the computer agent: Close Start.")


async def test_desktop_work_is_handed_over_at_most_twice_per_message(settings, computer, monkeypatch):
    computer_model, main_model = use_script(monkeypatch, [AIMessage("Did it."), AIMessage("Did it again.")], main=[
        delegate("Try.", "m1"), delegate("Try again.", "m2"), delegate("Once more.", "m3"), AIMessage("Done."),
    ])

    result = await run_turn(settings, "do it", max_steps=10, computer=computer)

    assert result.reply == "Done." and len(computer_model.received) == 2  # two tasks ran
    held_back = next(m for m in main_model.received[-1] if isinstance(m, ToolMessage) and m.tool_call_id == "m3")
    assert held_back.status == "error" and held_back.text.startswith(
        "Not executed: this message's work was handed over 2 times already")
    assert [event["id"] for event in logged(result, "action", MAIN) if event["status"] == "error"] == ["m3"]


async def test_two_computer_tasks_in_one_reply_start_one(settings, computer, monkeypatch):
    computer_model, _ = use_script(monkeypatch, [AIMessage("Did it.")], main=[
        AIMessage(content="", tool_calls=[
            tool_call("m1-plan", "write_plan", steps=plan(None, None)),
            tool_call("m1", "start_task", agent="computer", title="Task", task="One."),
            tool_call("m2", "start_task", agent="computer", title="Task", task="Two."),
        ]),
        AIMessage("On it."),
        AIMessage("Done."),
    ])

    result = await run_turn(settings, "do two things", max_steps=10, computer=computer)

    assert len(computer_model.received) == 1
    actions = {event["id"]: event for event in logged(result, "action", MAIN)}
    # The calls run at once: either may take the computer, and the other hears it is in use.
    assert actions["m1-plan"]["status"] == "success"
    assert sorted((actions[id]["status"], actions[id].get("reason")) for id in ("m1", "m2")) == [
        ("error", "computerInUse"), ("success", None),
    ]


async def test_the_main_agents_conversation_continues_from_its_runs_logs(settings, computer, monkeypatch):
    use_script(monkeypatch, [], main=[AIMessage("Hello.")])
    first = await run_turn(settings, "hi", max_steps=10, computer=computer)
    _, main_model = use_script(monkeypatch, [], main=[AIMessage("You said hi.")])

    await run_turn(settings, "what did I say?", max_steps=10, computer=computer, thread=first.run)

    seen = main_model.received[0][1:]  # past the system prompt
    assert [(type(m).__name__, m.text) for m in seen] == [
        ("HumanMessage", "hi"), ("AIMessage", "Hello."), ("HumanMessage", "what did I say?"),
    ]


async def test_legacy_runs_are_not_restored_or_sent_to_a_model(settings, computer, monkeypatch):
    old = runs_dir(settings.data_dir) / "20261006-120000"
    old.mkdir(parents=True)
    before = json.dumps({"type": "start", "v": 1, "run": old.name, "thread": old.name,
                         "goal": "open notepad", "time": 0}) + "\n"
    (old / "steps.jsonl").write_text(before)
    computer_model, main_model = use_script(monkeypatch, [AIMessage("Must not run.")])

    with pytest.raises(ValueError, match="unsupported log format"):
        await run_turn(settings, "now save it", max_steps=10, computer=computer, thread=old.name)

    assert computer_model.received == main_model.received == []
    assert (old / "steps.jsonl").read_text() == before


async def test_a_task_stopped_with_its_run_is_told_to_the_next_run_and_not_sent_again(settings, computer, monkeypatch):
    pressing, presses = asyncio.Event(), []

    async def press(combos):  # the key press never returns, as if the run were stopped while it ran
        presses.append(combos)
        pressing.set()
        await asyncio.Event().wait()

    computer.press = press
    use_script(monkeypatch, [AIMessage(content="Open Start.", tool_calls=[tool_call("c1", "key", text="win")])])
    run = asyncio.create_task(run_turn(settings, "open start", max_steps=10, computer=computer))
    await pressing.wait()
    run.cancel()
    await asyncio.gather(run, return_exceptions=True)
    thread = first_run(settings)
    _, main_model = use_script(monkeypatch, [], main=[AIMessage("It may or may not have opened.")])

    await run_turn(settings, "open start", max_steps=10, computer=computer, thread=thread)

    note = next(m for m in main_model.received[0] if not from_user(m) and isinstance(m, HumanMessage))
    assert "The run was stopped, and the background task t1 (computer agent) with it" in note.text and len(presses) == 1


async def test_a_stop_stays_a_stop_when_its_record_cannot_be_stored(settings, computer, monkeypatch):
    pressing = asyncio.Event()

    async def press(combos):
        pressing.set()
        await asyncio.Event().wait()

    async def unstored(store, run):
        raise OSError("disk full")

    computer.press = press
    monkeypatch.setattr(FileRuns, "flush", unstored)
    use_script(monkeypatch, [AIMessage(content="Open Start.", tool_calls=[tool_call("c1", "key", text="win")])])
    run = asyncio.create_task(run_turn(settings, "open start", max_steps=10, computer=computer))
    await pressing.wait()
    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run


async def test_a_task_the_runtime_died_under_is_told_to_the_next_run(settings, computer, monkeypatch):
    pressing = asyncio.Event()

    async def press(combos):
        pressing.set()
        await asyncio.Event().wait()

    computer.press = press
    use_script(monkeypatch, [AIMessage(content="Open Start.", tool_calls=[tool_call("c1", "key", text="win")])])
    run = asyncio.create_task(run_turn(settings, "open start", max_steps=10, computer=computer))
    await pressing.wait()
    died = crash_point(settings)
    run.cancel()
    await asyncio.gather(run, return_exceptions=True)
    died()
    thread = first_run(settings)
    _, main_model = use_script(monkeypatch, [], main=[AIMessage("It may or may not have opened.")])

    await run_turn(settings, "did it open?", max_steps=10, computer=computer, thread=thread)

    notes_heard = [m.text for m in main_model.received[0] if not from_user(m) and isinstance(m, HumanMessage)]
    assert len(notes_heard) == 1
    assert "The run was stopped, and the background task t1 (computer agent) with it" in notes_heard[0]


def test_a_call_a_stopped_run_left_unanswered_is_answered_as_unknown():
    asked = AIMessage(content="", tool_calls=[tool_call("m1", "stop_task", task_id="t1")])

    (unknown,) = session.unanswered([HumanMessage("stop it"), asked])

    assert (unknown.tool_call_id, unknown.status) == ("m1", "error") and "unknown" in unknown.text
    assert session.unanswered([HumanMessage("hi"), AIMessage("Hello.")]) == []


async def test_what_the_user_sends_while_the_main_agent_works_reaches_its_next_call_word_for_word(
    settings, computer, monkeypatch
):
    _, main_model = use_script(monkeypatch, [], main=[AIMessage("Paris, and Rome.")])
    inbox = Inbox()
    inbox.put("and Italy?")  # sent before its first model call

    result = await run_turn(settings, "capital of France?", max_steps=10, computer=computer, inbox=inbox)

    asked = [m.text for m in main_model.received[0] if isinstance(m, HumanMessage)]
    assert asked == ["capital of France?", "and Italy?"]
    assert [event["text"] for event in events_of(settings, result.run) if event["type"] == "message"] == ["and Italy?"]
    assert inbox.close() == []
    _, main_model = use_script(monkeypatch, [], main=[AIMessage("Yes.")])

    await run_turn(settings, "sure?", max_steps=10, computer=computer, thread=result.run)

    seen = [(type(m).__name__, m.text) for m in main_model.received[0][1:]]
    assert seen == [
        ("HumanMessage", "capital of France?"), ("HumanMessage", "and Italy?"), ("AIMessage", "Paris, and Rome."),
        ("HumanMessage", "sure?"),
    ]


async def test_the_main_agent_answers_while_a_desktop_task_runs(settings, computer, monkeypatch):
    computer_model, main_model = use_script(monkeypatch, [
        AIMessage(content="", tool_calls=[tool_call("c1", "key", text="win")]),
        AIMessage("Opened Start."),
    ], main=[delegate("Open Start."), AIMessage("Paris."), AIMessage("Start is open.")])
    inbox = Inbox()
    # The key press lasts until the main agent has been asked again: it answers while the task is under way.
    sent_while_pressing(computer, inbox, "capital of France?", until=lambda: len(main_model.received) >= 2)

    result = await run_turn(settings, "open start", max_steps=10, computer=computer, inbox=inbox)

    events = events_of(settings, result.run)
    answered = next(n for n, e in enumerate(events) if e["type"] == "model" and e["text"] == "Paris.")
    ended = next(n for n, e in enumerate(events) if e["type"] == "end" and e["stop_reason"] == "ended")
    assert answered < ended and result.reply == "Start is open."
    asked = main_model.received[1]
    assert (type(asked[-2]), asked[-2].text) == (HumanMessage, "capital of France?")
    status = asked[-1]
    assert status.additional_kwargs["runtime"]["event"] == "task_status"
    assert "Task t1 (computer agent) is still running" in status.text
    assert "You asked: Open Start." in status.text


async def test_a_run_lets_go_of_the_desktop_before_its_reply(settings, computer, monkeypatch):
    use_script(monkeypatch, [AIMessage("Opened it.")])  # by default the main agent hands it over, then says "Done."
    seen = []

    def at_the_reply(run, event):
        if event["type"] == "model" and event.get("agent") == MAIN and not event["tool_calls"]:
            seen.append(RunLock(settings.run_lock_path).holder())

    await run_turn(settings, "open notepad", max_steps=10, computer=computer, listeners=(at_the_reply,))

    assert seen == [None]  # another run may take the desktop while this one writes its reply


async def test_what_the_user_changes_meanwhile_the_main_agent_tells_the_task_with_their_words(
    settings, computer, monkeypatch
):
    told = telling(monkeypatch)
    computer_model, main_model = use_script(monkeypatch, [
        AIMessage(content="", tool_calls=[tool_call("c1", "key", text="win")]),
        AIMessage("Opened Start, then closed it."),
    ], main=[
        delegate("Open Start."),
        # Telling it ends the turn: the main agent is asked again only once the task has ended.
        AIMessage(content="", tool_calls=[tool_call("m2", "tell_task", task_id="t1", message="Close Start again once it is open.")]),
        AIMessage("Start was opened, then closed."),
    ])
    inbox = Inbox()
    sent_while_pressing(computer, inbox, "@Computer and close it again", until=lambda: bool(told))

    result = await run_turn(settings, "open start", max_steps=10, computer=computer, inbox=inbox)

    note = computer_model.received[1][-1]  # after the key press's result, before its next decision
    assert isinstance(note, HumanMessage) and note.text.startswith("From the main agent, while you work.")
    assert "Close Start again once it is open." in note.text and "- @Computer and close it again" in note.text
    assert [binding.get("tool_choice") for binding in main_model.bindings] == [None] * 3
    assert result.reply == "Start was opened, then closed."
    assert [event["text"] for event in events_of(settings, result.run) if event["type"] == "message"] == [
        "@Computer and close it again"
    ]


async def test_the_main_agent_stops_the_task_when_asked(settings, computer, monkeypatch):
    computer_model, main_model = use_script(monkeypatch, [
        AIMessage(content="", tool_calls=[tool_call("c1", "key", text="win")]),
        AIMessage("never asked"),
    ], main=[
        delegate("Open Start."),
        AIMessage(content="", tool_calls=[tool_call("m2", "stop_task", task_id="t1")]),
        AIMessage("Stopped it."),
    ])
    inbox, holding = Inbox(), asyncio.Event()
    pressed = computer.press

    async def press(combos):  # the user writes, and the press lasts until the task is stopped
        inbox.put("stop")
        await pressed(combos)
        await holding.wait()

    computer.press = press

    result = await asyncio.wait_for(
        run_turn(settings, "open start", max_steps=10, computer=computer, inbox=inbox), timeout=20
    )

    assert result.reply == "Stopped it." and len(computer_model.received) == 1
    # What it held is let go of, by the action cut short and again as the task ends.
    assert task_states(settings, result.run) == [("t1", "started"), ("t1", "stopped")] and computer.releases == 2


async def test_a_message_for_the_desktop_sent_before_a_task_is_handed_over_and_quoted_in_it(
    settings, computer, monkeypatch
):
    computer_model, main_model = use_script(monkeypatch, [AIMessage("Opened it.")])
    inbox = Inbox()
    inbox.put("@Computer open notepad")

    await run_turn(settings, "hi", max_steps=10, computer=computer, inbox=inbox)

    assert [binding.get("tool_choice") for binding in main_model.bindings] == [None, None]
    sent, word = main_model.received[0][-2:]
    assert from_user(sent) and sent.text == "@Computer open notepad" and DESKTOP_ASKED in word.text
    assert "The user's messages this task comes from, word for word, oldest first:\n- hi\n- @Computer open notepad" in (
        first_text(computer_model.received[0])
    )


async def test_a_message_sent_while_the_run_works_brings_its_own_two_desktop_tasks(settings, computer, monkeypatch):
    def press(call_id):
        return AIMessage(content="", tool_calls=[tool_call(call_id, "key", text="win")])

    computer_model, main_model = use_script(
        monkeypatch,
        [press("c1"), AIMessage("Did it."), press("c2"), AIMessage("Again."), AIMessage("Did the new one.")],
        main=[
            delegate("Try.", "m1"), delegate("Try again.", "m2"),
            AIMessage("Noted: after this one."),
            delegate("The new one.", "m3"),
            AIMessage("Done."),
        ],
    )
    inbox = Inbox()
    # During the second task, until the main agent has answered it.
    sent_while_pressing(computer, inbox, None, "and one more thing", until=lambda: len(main_model.received) >= 3)

    result = await run_turn(settings, "do it", max_steps=10, computer=computer, inbox=inbox)

    assert [event["status"] for event in logged(result, "action", MAIN)] == ["success", "success", "success"]


async def test_the_main_agents_words_are_its_draft_while_its_model_writes_them_and_never_the_tasks(
    settings, computer, monkeypatch
):
    computer_model = StreamingModel(messages=iter([AIMessage("Opened Notepad.")]), received=[], bindings=[])
    main_model = StreamingModel(
        messages=iter([delegate(), AIMessage("Notepad is open on the desktop.")]), received=[], bindings=[]
    )
    monkeypatch.setattr(computer_agent, "build_chat_model", lambda _spec, _settings: computer_model)
    monkeypatch.setattr(main_agent, "build_chat_model", lambda _spec, _settings, **_: main_model)
    grown, logged_with = [], []

    class Watched(Draft):
        def add(self, call, text):
            super().add(call, text)
            grown.append(self.text)

    draft = Watched()

    def listener(run, event):
        if event["type"] == "model" and event.get("agent") == MAIN:
            logged_with.append((event["text"], draft.text))

    await run_turn(
        settings, "open notepad", max_steps=10, computer=computer, listeners=(listener,), draft=draft
    )

    reply = "Notepad is open on the desktop."
    assert len(grown) > 1 and grown[-1] == reply and all(reply.startswith(text) for text in grown)
    assert logged_with == [("", ""), (reply, reply)] and draft.text == ""


async def test_a_reply_its_model_marks_as_final_reaches_viewers_as_final_from_its_start(settings, computer, monkeypatch):
    phases = iter(["commentary", "final_answer"])

    class Marking(StreamingModel):  # marks each message's phase before its first word, as the Responses API does
        async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
            yield ChatGenerationChunk(message=AIMessageChunk(content=[{"type": "text", "text": "", "phase": next(phases)}]))
            async for chunk in super()._astream(messages, stop, run_manager, **kwargs):
                yield chunk

    words = AIMessage(content="On it.", tool_calls=delegate().tool_calls)
    main = Marking(messages=iter([words, AIMessage("Notepad is open.")]), received=[], bindings=[])
    use_script(monkeypatch, [AIMessage("Opened Notepad.")])
    monkeypatch.setattr(main_agent, "build_chat_model", lambda _spec, _settings, **_: main)
    published = []
    draft = Draft()
    draft.stream.publish = lambda kind, data: published.append((kind, data))

    await run_turn(settings, "open notepad", max_steps=10, computer=computer, draft=draft)

    # Each call's draft starts whole; only the one its model marked final says so, before any of its words.
    wholes = [data for kind, data in published if kind == "draft"]
    assert [data["final"] for data in wholes] == [False, True] and wholes[1]["text"] == ""
    final = published.index(("draft", {"text": "", "final": True}))
    assert "".join(data["text"] for _, data in published[final + 1:]) == "Notepad is open."
    assert draft.final is False


async def test_a_reply_whose_stream_fails_partway_is_written_again_from_the_start(settings, computer, monkeypatch):
    class Overloaded(StreamingModel):  # the first try writes a few words, then the API says it is overloaded
        tries: int = 0

        async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
            self.tries += 1
            if self.tries == 1:
                yield ChatGenerationChunk(message=AIMessageChunk(content="Half a "))
                raise openai.APIError("overloaded", httpx.Request("POST", "https://api.invalid"),
                                      body={"type": "server_error", "message": "overloaded"})
            async for chunk in super()._astream(messages, stop, run_manager, **kwargs):
                yield chunk

    model = Overloaded(messages=iter([AIMessage("Paris is the capital.")]), received=[], bindings=[])
    monkeypatch.setattr(main_agent, "build_chat_model", lambda _spec, _settings, **_: model)
    monkeypatch.setattr(common, "RETRY_DELAY", 0)
    published = []
    draft = Draft()
    draft.stream.publish = lambda kind, data: published.append((kind, data["text"]))

    await run_turn(settings, "capital of France?", max_steps=10, computer=computer, draft=draft)

    events = events_of(settings, first_run(settings))
    assert [event["text"] for event in events if event["type"] == "model"] == ["Paris is the capital."]
    assert next(event for event in events if event["type"] == "end")["stop_reason"] == "replied"
    # What the failed try wrote is taken back before the next one writes.
    taken = published.index(("draft", ""))
    assert published[:taken] == [("draft", "Half a ")] and published[taken + 1][0] == "draft"
    assert "".join(text for _, text in published[taken + 1:]) == "Paris is the capital."


async def test_a_reply_cut_off_by_a_stop_is_kept_as_written_and_the_next_run_hears_it_was_cut_off(
    settings, computer, monkeypatch
):
    class Stuck(StreamingModel):  # writes a few words, then never finishes
        async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
            for text in ("Paris ", "is "):
                yield ChatGenerationChunk(message=AIMessageChunk(content=text))
            await asyncio.Event().wait()

    stuck = Stuck(messages=iter([]), received=[], bindings=[])
    monkeypatch.setattr(main_agent, "build_chat_model", lambda _spec, _settings, **_: stuck)
    draft = Draft()
    run = asyncio.create_task(
        run_turn(settings, "capital of France?", max_steps=10, computer=computer, draft=draft)
    )
    for _ in range(200):
        if draft.text == "Paris is ":
            break
        await asyncio.sleep(0.01)
    run.cancel()
    await asyncio.gather(run, return_exceptions=True)
    thread = first_run(settings)
    # Its usage never came: kept as unknown, and with it what the run cost, rather than as nothing.
    events = events_of(settings, first_run(settings))
    (cut,) = [event for event in events if event["type"] == "model"]
    end = next(event for event in events if event["type"] == "end")
    assert cut["text"] == "Paris is " and cut["usage"] is None and (end["stop_reason"], end["cost"]) == ("cancelled", None)
    _, main_model = use_script(monkeypatch, [], main=[AIMessage("Paris.")])

    await run_turn(settings, "go on", max_steps=10, computer=computer, thread=thread)

    said = [m.text for m in main_model.received[0] if isinstance(m, AIMessage)]
    note = next(m for m in main_model.received[0] if not from_user(m) and isinstance(m, HumanMessage))
    assert said == ["Paris is "] and "while you were writing the reply above" in note.text and draft.text == ""


async def test_a_task_whose_model_call_a_stop_cuts_off_leaves_the_runs_cost_unknown(settings, computer, monkeypatch):
    asked = asyncio.Event()

    class Hanging(ScriptedModel):  # the computer-use agent's call never answers
        async def ainvoke(self, input, config=None, **kwargs):
            asked.set()
            await asyncio.Event().wait()

    _, main_model = use_script(monkeypatch, [], main=[delegate("Open Start."), AIMessage("Done.")])
    monkeypatch.setattr(computer_agent, "build_chat_model",
                        lambda _spec, _settings: Hanging(messages=iter([]), received=[], bindings=[]))
    run = asyncio.create_task(run_turn(settings, "open start", max_steps=10, computer=computer))
    await asyncio.wait_for(asked.wait(), 5)  # the stop comes while the call is in flight
    run.cancel()
    await asyncio.gather(run, return_exceptions=True)

    # The turn that handed it over knows its cost; the task's, whose call was cut off, does not.
    ends = {e["stop_reason"]: e for e in events_of(settings, first_run(settings)) if e["type"] == "end"}
    assert ends["replied"]["cost"] is not None and ends["stopped"]["cost"] is None


async def test_a_stop_swallowed_inside_a_graph_is_raised_again():
    async def graph():
        with contextlib.suppress(asyncio.CancelledError):  # as LangGraph's stream cleans up between steps
            await asyncio.Event().wait()
        raise_if_stopped()

    task = asyncio.create_task(graph())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def plan(*marks: bool | None) -> list[dict]:
    """A plan's steps A, B, ..., each marked done (True), opened again (False) or left as it is (None)."""
    flags = {True: {"done": True}, False: {"reopen": True}, None: {}}
    return [{"id": "ABCDEFG"[n], "title": f"Do {'ABCDEFG'[n]}.", **flags[mark]} for n, mark in enumerate(marks)]


def handing_over(call_id: str, steps: list[dict] | None, task="Do it.", first="plan", on=None) -> AIMessage:
    calls = [tool_call(call_id, "start_task", agent="computer", title="Task", task=task, **({"steps": on} if on else {}))]
    if steps is not None:
        written = tool_call(f"{call_id}-plan", "write_plan", steps=steps)
        calls = [written, *calls] if first == "plan" else [*calls, written]
    return AIMessage(content="", tool_calls=calls)


def snapshots(settings, result) -> list[dict]:
    """The plan's snapshots in every turn of the run's session, oldest first."""
    folders = sorted(path for path in runs_dir(settings.data_dir).iterdir() if path.is_dir())
    logs = [read_events(folder) for folder in folders]
    found = [event for log in logs for event in log if event["type"] == "plan"]
    return sorted(found, key=lambda event: event["version"])


def shown(snapshot: dict) -> dict[str, tuple[str, list[str]]]:
    return {step["id"]: (step["status"], step["tasks"]) for step in snapshot["steps"]}


@pytest.mark.parametrize("first", ["plan", "task"])
async def test_a_plan_beside_a_hand_over_shows_the_task_on_its_step_in_either_order_and_ends_the_turn(
    settings, computer, monkeypatch, first
):
    computer_model, main_model = use_script(monkeypatch, [
        AIMessage(content="", tool_calls=[tool_call("c1", "finish_step", steps=["A"])]),
        AIMessage("Did A."),
    ], main=[
        handing_over("m1", plan(None, None), first=first, on=["A"]),
        AIMessage("Done."),
    ])

    result = await run_turn(settings, "do A then B", max_steps=10, computer=computer)

    assert result.reply == "Done." and len(computer_model.received) == 2 and len(main_model.received) == 2
    seen = snapshots(settings, result)
    assert [each["version"] for each in seen] == sorted({each["version"] for each in seen})
    assert any(shown(each) == {"A": ("in_progress", ["t1"]), "B": ("pending", [])} for each in seen)
    assert shown(seen[-1]) == {"A": ("completed", []), "B": ("pending", [])}
    assert notes.plan_left(["B"]) in main_model.received[1][-1].text


async def test_a_task_that_did_not_reply_leaves_its_step_undone(settings, computer, monkeypatch):
    _, main_model = use_script(monkeypatch, [AIMessage(content="", tool_calls=[tool_call("c1", "screenshot")])], main=[
        handing_over("m1", plan(None), on=["A"]),
        AIMessage("It ran out of steps."),
    ])

    result = await run_turn(settings, "do A", max_steps=1, computer=computer)

    assert shown(snapshots(settings, result)[-1]) == {"A": ("pending", [])}
    assert notes.plan_left(["A"]) in main_model.received[1][-1].text


async def test_the_main_agent_marks_steps_and_the_plan_goes_on_in_the_next_message(settings, computer, monkeypatch):
    use_script(monkeypatch, [AIMessage("Did A.")], main=[
        handing_over("m1", plan(None, None), on=["A"]),
        AIMessage(content="", tool_calls=[tool_call("m2", "write_plan", steps=plan(False, True))]),
        AIMessage("A fell short."),
    ])
    first = await run_turn(settings, "do A then B", max_steps=10, computer=computer)
    before = snapshots(settings, first)[-1]
    assert shown(before) == {"A": ("pending", []), "B": ("completed", [])}

    use_script(monkeypatch, [], main=[
        AIMessage(content="", tool_calls=[tool_call("m3", "write_plan", steps=plan(None, None))]),
        AIMessage("Still so."),
    ])
    second = await run_turn(settings, "where are we?", max_steps=10, computer=computer, thread=first.run)

    latest = snapshots(settings, second)[-1]
    assert latest["version"] > before["version"]
    assert shown(latest) == {"A": ("pending", []), "B": ("completed", [])}


async def test_a_list_that_is_no_plan_is_a_failed_call_the_main_agent_can_answer(settings, computer, monkeypatch):
    twice = [{"id": "A", "title": "One"}, {"id": "A", "title": "Two"}]
    _, main_model = use_script(monkeypatch, [], main=[
        AIMessage(content="", tool_calls=[tool_call("m1", "write_plan", steps=twice)]),
        AIMessage("Sorry."),
    ])

    result = await run_turn(settings, "plan it", max_steps=10, computer=computer)

    answer = next(m for m in main_model.received[-1] if isinstance(m, ToolMessage))
    assert answer.status == "error" and notes.bad_plan(12) in answer.text
    assert result.reply == "Sorry." and snapshots(settings, result) == []


async def test_a_task_starts_with_the_plan_and_reports_each_step_it_finishes(settings, computer, monkeypatch):
    computer_model, _ = use_script(monkeypatch, [
        AIMessage(content="", tool_calls=[tool_call("c1", "finish_step", steps=["A"])]),
        AIMessage(content="", tool_calls=[tool_call("c2", "finish_step", steps=["B"])]),
        AIMessage("Did both."),
    ], main=[handing_over("m1", plan(None, None), on=["A", "B"]), AIMessage("Done.")])

    result = await run_turn(settings, "do A then B", max_steps=10, computer=computer)

    opening = next(m for m in computer_model.received[0] if isinstance(m, HumanMessage))
    assert "- A. [in progress: you] Do A." in opening.text
    assert {"read_blackboard", "finish_step", "ask"} <= {tool.name for tool in computer_model.bindings[0]["tools"]}
    seen = [shown(each) for each in snapshots(settings, result)]
    assert {"A": ("completed", ["t1"]), "B": ("in_progress", ["t1"])} in seen
    assert seen[-1] == {"A": ("completed", []), "B": ("completed", [])}


def asks(question: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[tool_call("c1", "ask", question=question)])


async def test_a_task_that_asks_goes_on_with_the_main_agents_answer(settings, computer, monkeypatch):
    computer_model, main_model = use_script(monkeypatch, [asks("Which file?"), AIMessage("Used B.")], main=[
        handing_over("m1", plan(None), on=["A"]),
        AIMessage(content="", tool_calls=[tool_call("m2", "tell_task", task_id="t1", message="Use B.")]),
        AIMessage("Done."),
    ])

    result = await run_turn(settings, "do A", max_steps=10, computer=computer)

    assert result.reply == "Done."
    told = main_model.received[1][-1]
    assert not from_user(told) and notes.task_asks("t1", "computer", "Which file?") in told.text
    answer = next(m for m in computer_model.received[1] if isinstance(m, ToolMessage) and m.tool_call_id == "c1")
    assert answer.text == "Use B."


async def test_a_question_the_main_agent_puts_to_the_user_waits_for_the_user(settings, computer, monkeypatch):
    computer_model, main_model = use_script(monkeypatch, [asks("Which file?"), AIMessage("Used B.")], main=[
        handing_over("m1", plan(None), on=["A"]),
        AIMessage("Should it use A or B?"),
        AIMessage(content="", tool_calls=[tool_call("m2", "tell_task", task_id="t1", message="B, the user says.")]),
        AIMessage("Done."),
    ])
    inbox = Inbox()

    async def answer_once_asked():
        while len(main_model.received) < 2:
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.05)
        assert len(computer_model.received) == 1  # still waiting
        inbox.put("Use B")

    answering = asyncio.create_task(answer_once_asked())
    result = await run_turn(settings, "do A", max_steps=10, computer=computer, inbox=inbox)
    await answering

    assert result.reply == "Done."
    answer = next(m for m in computer_model.received[1] if isinstance(m, ToolMessage) and m.tool_call_id == "c1")
    assert answer.text.startswith("B, the user says.") and "Use B" in answer.text  # the user's own words reach the agent
    folders = [read_events(path) for path in runs_dir(settings.data_dir).iterdir() if path.is_dir()]
    (asked,) = [event for log in folders for event in log if event["type"] == "action" and event["tool"] == "ask"]
    assert asked["answer"] == "B, the user says."  # what the page shows: the runtime's addition is left out


async def test_a_reply_whose_calls_lost_their_arguments_is_sent_for_again(settings, computer, monkeypatch):
    computer_model, main_model = use_script(monkeypatch, [AIMessage("Did it.")], main=[
        AIMessage(content="", tool_calls=[tool_call("lost", "start_task")]),
        delegate("Do it.", "m1"),
        AIMessage("Done."),
    ])

    result = await run_turn(settings, "do it", max_steps=10, computer=computer)

    assert result.reply == "Done." and len(computer_model.received) == 1 and len(main_model.received) == 3
    assert [event["id"] for event in logged(result, "action", MAIN)] == ["m1"]


async def test_arguments_lost_twice_are_a_failed_call_the_model_hears_of(settings, computer, monkeypatch):
    lost = AIMessage(content="", tool_calls=[tool_call("lost", "start_task")])
    _, main_model = use_script(monkeypatch, [], main=[lost, lost, AIMessage("Could not hand it over.")])

    result = await run_turn(settings, "do it", max_steps=10, computer=computer)

    assert result.reply == "Could not hand it over." and len(main_model.received) == 3
    assert [event["status"] for event in logged(result, "action", MAIN)] == ["error"]


@tool
def no_arguments() -> str:
    """Takes nothing."""
    return ""


@tool
def one_argument(text: str) -> str:
    """Takes some text."""
    return text


@pytest.mark.parametrize(("name", "args", "lost"), [
    ("one_argument", {}, True),
    ("one_argument", {"text": "hi"}, False),
    ("no_arguments", {}, False),
])
def test_only_a_tool_that_requires_arguments_can_lose_them(name, args, lost):
    reply = AIMessage(content="", tool_calls=[tool_call("c1", name, **args)])
    assert chat.lost_arguments(reply, [no_arguments, one_argument]) is lost


async def test_a_list_too_long_to_be_a_plan_does_not_buy_more_hand_overs(settings, computer, monkeypatch):
    many = [{"id": str(n), "title": "A step"} for n in range(500)]
    _, main_model = use_script(monkeypatch, [AIMessage("Did it.")] * 30, main=[
        AIMessage(content="", tool_calls=[tool_call("bad", "write_plan", steps=many)]),
        *[handing_over(f"m{n}", None) for n in range(26)],
        AIMessage("Stopped."),
    ])

    result = await run_turn(settings, "do it", max_steps=10, computer=computer)

    refused = [e for e in logged(result, "action", MAIN) if e["status"] == "error" and e.get("reason") == "taskLimit"]
    assert len(refused) == 2 and result.reply == "Stopped."


async def test_work_is_handed_over_twice_for_each_step_of_the_latest_plan(settings, computer, monkeypatch):
    computer_model, _ = use_script(
        monkeypatch, [AIMessage("Tried A."), AIMessage("Tried A again."), AIMessage("Did B.")],
        main=[
            handing_over("m1", plan(None)),
            handing_over("m2", None, task="A, again."),
            handing_over("m3", None, task="A, once more."),
            handing_over("m4", plan(None, None)),
            AIMessage("Done."),
        ],
    )

    result = await run_turn(settings, "do A then B", max_steps=10, computer=computer)

    assert result.reply == "Done." and len(computer_model.received) == 3
    refused = {event["id"]: event for event in logged(result, "action", MAIN) if event["status"] == "error"}
    assert list(refused) == ["m3"]
    assert refused["m3"]["reason"] == "taskLimit" and "was handed over 2 times" in refused["m3"]["result"]


async def test_the_main_agent_finds_other_conversations_by_what_was_said_in_them(settings, computer, monkeypatch):
    use_script(monkeypatch, [], main=[AIMessage("Wrote the meeting notes in Notepad.")])
    await run_turn(settings, "write the meeting notes", max_steps=10, computer=computer)
    searching = AIMessage(content="", tool_calls=[tool_call("s1", "search_conversations", query="NOTEPAD")])
    _, main_model = use_script(monkeypatch, [], main=[searching, AIMessage("It was the meeting notes.")])

    # This conversation mentions Notepad too, but a search finds only the others.
    result = await run_turn(settings, "which chat was about notepad?", max_steps=10, computer=computer)

    assert result.reply == "It was the meeting notes."
    answer = main_model.received[-1][-1]
    assert isinstance(answer, ToolMessage) and answer.content.startswith(notes.FOUND)
    (found,) = json.loads(answer.content.removeprefix(notes.FOUND))
    assert found["id"] == first_run(settings)
    assert (found["title"], found["snippet"]) == ("write the meeting notes", "…he meeting notes in Notepad.")
    assert abs(datetime.fromisoformat(found["last_active"]).timestamp() - time.time()) < 120
    assert computer.calls == []


async def test_the_main_agents_search_finds_only_its_users_conversations(settings, computer, monkeypatch):
    use_script(monkeypatch, [], main=[AIMessage("Wrote bob's notes in Notepad.")])
    await run_turn(settings, "write the notes", max_steps=10, computer=computer, user="bob")
    searching = AIMessage(content="", tool_calls=[tool_call("s1", "search_conversations", query="notepad")])
    _, main_model = use_script(monkeypatch, [], main=[searching, AIMessage("None.")])

    await run_turn(settings, "which chat was about notepad?", max_steps=10, computer=computer, user="alice")

    assert main_model.received[-1][-1].content == notes.NOTHING_FOUND


async def test_the_main_agent_reads_a_conversation_it_found_across_its_turns(settings, computer, monkeypatch):
    use_script(monkeypatch, [], main=[AIMessage("Wrote it in Notepad.")])
    await run_turn(settings, "write the notes", max_steps=10, computer=computer)
    thread = first_run(settings)
    use_script(monkeypatch, [], main=[AIMessage("Saved to D:\\Reports.")])
    await run_turn(settings, "save them", max_steps=10, computer=computer, thread=thread)
    reading = AIMessage(content="", tool_calls=[tool_call("r1", "read_conversation", id=thread)])
    _, main_model = use_script(monkeypatch, [], main=[reading, AIMessage("In D:\\Reports.")])

    await run_turn(settings, "where did the notes go?", max_steps=10, computer=computer)

    assert main_model.received[-1][-1].content == notes.conversation(
        "User: write the notes\n\nYou: Wrote it in Notepad.\n\nUser: save them\n\nYou: Saved to D:\\Reports.", 0
    )


async def test_a_long_conversation_is_read_from_its_latest_words(settings, computer, monkeypatch):
    use_script(monkeypatch, [], main=[AIMessage("Done.")])
    await run_turn(settings, "write the notes", max_steps=10, computer=computer)
    monkeypatch.setattr(conversations, "READ_CHARS", 10)
    reading = AIMessage(content="", tool_calls=[tool_call("r1", "read_conversation", id=first_run(settings))])
    _, main_model = use_script(monkeypatch, [], main=[reading, AIMessage("Done.")])

    await run_turn(settings, "what happened?", max_steps=10, computer=computer)

    # "User: write the notes\n\nYou: Done." is 33 characters.
    assert main_model.received[-1][-1].content == notes.conversation("You: Done.", left_out=23)


async def test_the_main_agent_cannot_read_another_users_conversation(settings, computer, monkeypatch):
    use_script(monkeypatch, [], main=[AIMessage("Wrote bob's notes.")])
    await run_turn(settings, "write the notes", max_steps=10, computer=computer, user="bob")
    thread = next((settings.data_dir / "users").glob("*/runs/*")).name
    reading = AIMessage(content="", tool_calls=[tool_call("r1", "read_conversation", id=thread)])
    _, main_model = use_script(monkeypatch, [], main=[reading, AIMessage("None.")])

    await run_turn(settings, "read bob's notes", max_steps=10, computer=computer, user="alice")

    assert main_model.received[-1][-1].content == notes.no_conversation(thread)


async def test_a_correction_is_remembered_and_a_later_task_is_handed_the_rule_word_for_word(
    settings, computer, monkeypatch
):
    memory, choices = FileMemoryStore(settings.data_dir), RunChoices(learn=True, recall=True)
    remembering = AIMessage(content="", tool_calls=[tool_call(
        "r1", "remember", rule="用內網查報表", why="Google 上是舊版", applies="查公司報表", scope="personal",
        learned_from="said",
    )])
    use_script(monkeypatch, [], main=[remembering, AIMessage("好。")])
    await run_turn(settings, "以後查報表用內網，Google 上是舊版", max_steps=10, computer=computer, choices=choices,
                   memory=memory)
    (rule,) = await memory.list("local")

    handing = AIMessage(content="", tool_calls=[
        tool_call("m1", "start_task", agent="computer", title="Task", task="查九月的報表", rules=[rule.id, "unknown"])
    ])
    computer_model, main_model = use_script(monkeypatch, [AIMessage("Done.")], main=[handing, AIMessage("Done.")])
    result = await run_turn(settings, "查九月的報表", max_steps=10, computer=computer, choices=choices, memory=memory)

    assert f"[{rule.id}] 用內網查報表" in system_text(main_model.received[0])
    assert "- 用內網查報表 (why: Google 上是舊版; applies: 查公司報表)" in first_text(computer_model.received[0])
    assert (await memory.get("local", rule.id)).uses == 1
    # In the task's log, which the page shows it in.
    note = next(each for each in read_events(task_folder(settings, result.run, "t1")) if each.get("code") == "memoryUsed")
    assert note["data"]["rules"] == [{"id": rule.id, "text": "用內網查報表"}]


async def test_memory_is_neither_written_nor_followed_unless_the_user_chose_it(settings, computer, monkeypatch):
    memory = FileMemoryStore(settings.data_dir)
    remembering = AIMessage(content="", tool_calls=[tool_call(
        "r1", "remember", rule="x", why="y", applies="z", scope="personal", learned_from="said",
    )])
    _, main_model = use_script(monkeypatch, [], main=[remembering, AIMessage("好。")])
    await run_turn(settings, "以後都這樣", max_steps=10, computer=computer, memory=memory)
    assert await memory.list("local") == []
    system = system_text(main_model.received[0])
    assert "## Memory" not in system and "## What you remember" not in system and "Today is " in system


def asking(**args) -> AIMessage:
    return AIMessage(content="", tool_calls=[tool_call("ask", "ask_user", question="Which one?", **args)])


async def test_asking_the_user_ends_the_turn_until_they_answer(settings, computer, monkeypatch):
    _, main_model = use_script(monkeypatch, [], main=[
        asking(options=[{"label": "The first", "reason": "It is newer."}], placeholder="Or name another"),
    ])

    result = await run_turn(settings, "Pick one for me", max_steps=10, computer=computer)

    assert len(main_model.received) == 1
    (action,) = logged(result, "action", MAIN)
    assert (action["tool"], action["status"]) == ("ask_user", "success")
    assert action["args"]["options"] == [{"label": "The first", "reason": "It is newer."}]


async def test_a_question_with_too_many_options_goes_back_to_the_main_agent(settings, computer, monkeypatch):
    options = [{"label": f"Option {n}", "reason": "Why not."} for n in range(5)]
    _, main_model = use_script(monkeypatch, [], main=[asking(options=options), AIMessage("Tell me which one you want.")])

    result = await run_turn(settings, "Pick one for me", max_steps=10, computer=computer)

    assert result.reply == "Tell me which one you want." and len(main_model.received) == 2
    (action,) = logged(result, "action", MAIN)
    assert action["status"] == "error"


async def test_a_question_asked_while_a_task_runs_waits_for_the_users_next_message(settings, computer, monkeypatch):
    working = asyncio.Event()

    class Hanging(ScriptedModel):  # the task works on for as long as the test needs
        async def ainvoke(self, input, config=None, **kwargs):
            working.set()
            await asyncio.Event().wait()

    async def calls(count: int) -> None:
        while len(main_model.received) < count:
            await asyncio.sleep(0.01)

    _, main_model = use_script(monkeypatch, [], main=[delegate("Open Start."), asking(), AIMessage("Noted.")])
    monkeypatch.setattr(computer_agent, "build_chat_model",
                        lambda _spec, _settings: Hanging(messages=iter([]), received=[], bindings=[]))
    inbox = Inbox()
    run = asyncio.create_task(run_turn(settings, "open start", max_steps=10, computer=computer, inbox=inbox))
    await asyncio.wait_for(working.wait(), 5)

    inbox.put("Which one is it?")
    await asyncio.wait_for(calls(2), 5)
    await asyncio.sleep(0.05)
    assert len(main_model.received) == 2 and not run.done()  # the question ended its turn; the task goes on

    inbox.put("The first")
    await asyncio.wait_for(calls(3), 5)
    assert any(isinstance(m, HumanMessage) and m.text == "The first" for m in main_model.received[2])
    run.cancel()
    await asyncio.gather(run, return_exceptions=True)


async def test_a_question_can_take_several_answers(settings, computer, monkeypatch):
    options = [{"label": "A", "reason": "One."}, {"label": "B", "reason": "Two."}]
    use_script(monkeypatch, [], main=[asking(options=options, multiple=True)])

    result = await run_turn(settings, "Pick for me", max_steps=10, computer=computer)

    (action,) = logged(result, "action", MAIN)
    assert action["status"] == "success" and action["args"]["multiple"] is True


async def test_a_message_logs_when_it_was_sent(settings, computer, monkeypatch):
    use_script(monkeypatch, [], main=[AIMessage("Hello.")])
    inbox = Inbox()
    inbox.put("and Italy?")
    before = inbox.pending()[0].time

    result = await run_turn(settings, "hi", max_steps=10, computer=computer, inbox=inbox, sent=12.5)

    events = events_of(settings, result.run)
    assert events[0]["sent"] == 12.5
    (message,) = [event for event in events if event["type"] == "message"]
    assert message["sent"] == before
