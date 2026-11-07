"""How a conversation's work starts, stops and carries on: refusals of the task tools, a task stopped among others,
calls a stop left unanswered, tasks the runtime died under, and a result a stop cut off before it was heard."""

import asyncio

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

import computer_use.agent.background as background
import computer_use.agent.coding_agent as coding_agent
from computer_use.agent.background import from_user
from computer_use.storage.files import FileRuns
from computer_use.agent.inbox import Inbox
from computer_use.desktop.control import RunLock
from computer_use.prompts import notes
from computer_use.sandbox import RunOutput
from computer_use.storage import MAIN
from conftest import (
    ScriptedModel,
    delegate,
    logged,
    crash_point,
    events_of,
    first_run,
    run_turn,
    runs_dir,
    sent_while_pressing,
    task_states as states_of,
    tool_call,
    use_script,
)

pytestmark = pytest.mark.usefixtures("the_log_is_the_whole_record")


def coding_script(monkeypatch, replies) -> ScriptedModel:
    model = ScriptedModel(messages=iter(replies), received=[], bindings=[])
    monkeypatch.setattr(coding_agent, "build_chat_model", lambda _spec, _settings: model)
    return model


def actions(result) -> dict[str, dict]:
    """The main agent's calls, by id."""
    return {event["id"]: event for event in logged(result, "action", MAIN)}


def task_events(settings) -> list[dict]:
    """The task events of the first run, if there is one yet."""
    if not runs_dir(settings.data_dir).exists():
        return []
    return [event for event in events_of(settings, first_run(settings)) if event["type"] == "task"]


def task_states(settings) -> list[tuple[str, str]]:
    """How each task started and ended, once there is a conversation."""
    return states_of(settings, first_run(settings)) if runs_dir(settings.data_dir).exists() else []


def task_of(settings, agent: str) -> str:
    """The id of the task handed to `agent`: tasks handed over together are numbered as they start."""
    return next(event["id"] for event in task_events(settings) if event["agent"] == agent)


def runtime_notes(messages) -> list[str]:
    return [m.text for m in messages if isinstance(m, HumanMessage) and not from_user(m)]


async def until(condition, seconds=10):
    for _ in range(int(seconds / 0.01)):
        if condition():
            return
        await asyncio.sleep(0.01)
    raise TimeoutError("the condition never held")


async def test_telling_or_stopping_a_task_that_is_not_running_is_refused(settings, computer, monkeypatch):
    use_script(monkeypatch, [], main=[
        AIMessage(content="", tool_calls=[
            tool_call("m1", "tell_task", task_id="t9", message="Faster."),
            tool_call("m2", "stop_task", task_id="t9"),
        ]),
        AIMessage("There is no such task."),
    ])

    result = await run_turn(settings, "stop t9", max_steps=10, computer=computer)

    done = actions(result)
    assert [(done[id]["status"], done[id]["reason"]) for id in ("m1", "m2")] == [("error", "noTask")] * 2
    assert notes.no_task("t9") in done["m1"]["result"] and result.reply == "There is no such task."


async def test_a_task_past_the_most_at_once_is_refused(settings, computer, code_runner, monkeypatch):
    monkeypatch.setattr(background, "MAX_TASKS", 1)
    inbox, release = Inbox(), asyncio.Event()

    class Releasing(ScriptedModel):  # once it has heard the refusal, the first task may finish
        async def ainvoke(self, input, config=None, **kwargs):
            if len(self.received) == 2:
                release.set()
            return await super().ainvoke(input, config, **kwargs)

    use_script(monkeypatch, [])
    main_model = Releasing(messages=iter([
        AIMessage(content="", tool_calls=[tool_call("m1", "start_task", agent="coding", title="Sum", task="Add 2 and 2.")]),
        AIMessage(content="", tool_calls=[tool_call("m2", "start_task", agent="coding", title="Sum", task="Add 3 and 3.")]),
        AIMessage("One at a time."),
        AIMessage("2 and 2 is 4."),
    ]), received=[], bindings=[])
    monkeypatch.setattr("computer_use.agent.main_agent.build_chat_model", lambda _spec, _settings, **_: main_model)
    coding_script(monkeypatch, [
        AIMessage(content="", tool_calls=[tool_call("k1", "bash", script="echo 4")]), AIMessage("It printed 4."),
    ])

    async def answer(script):  # the user asks for more while it runs
        message = inbox.put("add 3 and 3 too")
        await until(lambda: MAIN in message.read_by)
        await release.wait()
        return RunOutput(0, "4\n", 0)

    code_runner.answer = answer

    result = await run_turn(settings, "add 2 and 2", max_steps=10, computer=computer, code_runner=code_runner,
                            inbox=inbox)

    done = actions(result)
    assert (done["m1"]["status"], done["m2"]["status"], done["m2"]["reason"]) == ("success", "error", "tooManyTasks")
    assert task_states(settings) == [("t1", "started"), ("t1", "ended")] and result.reply == "2 and 2 is 4."


async def test_a_desktop_task_another_process_holds_the_desktop_for_is_refused_by_reason(
    settings, computer, monkeypatch
):
    computer_model, _ = use_script(monkeypatch, [AIMessage("never asked")], main=[
        delegate(), AIMessage("The desktop is busy."),
    ])

    with RunLock(settings.run_lock_path) as other:
        other.name("20261007-120000")
        result = await run_turn(settings, "open start", max_steps=10, computer=computer)

    refused = actions(result)["m1"]
    assert (refused["status"], refused["reason"]) == ("error", "desktopBusy") and computer_model.received == []


async def test_stopping_one_task_leaves_the_other_at_work(settings, computer, code_runner, monkeypatch):
    inbox, cancelled = Inbox(), asyncio.Event()

    class Stopping(ScriptedModel):  # stops the coding task, by the id it started under
        async def ainvoke(self, input, config=None, **kwargs):
            if len(self.received) == 1:
                coding = task_of(settings, "coding")
                self.messages = iter([
                    AIMessage(content="", tool_calls=[tool_call("m3", "stop_task", task_id=coding)]), *self.messages,
                ])
            return await super().ainvoke(input, config, **kwargs)

    use_script(monkeypatch, [
        AIMessage(content="", tool_calls=[tool_call("c1", "key", text="win")]), AIMessage("Opened Start."),
    ])
    main_model = Stopping(messages=iter([
        AIMessage(content="", tool_calls=[
            tool_call("m1", "start_task", agent="computer", title="Start", task="Open Start."),
            tool_call("m2", "start_task", agent="coding", title="Sum", task="Add 2 and 2."),
        ]),
        AIMessage("Stopped the sum."),
        AIMessage("Start is open; the sum was stopped."),
    ]), received=[], bindings=[])
    monkeypatch.setattr("computer_use.agent.main_agent.build_chat_model", lambda _spec, _settings, **_: main_model)
    coding_script(monkeypatch, [AIMessage(content="", tool_calls=[tool_call("k1", "bash", script="sleep 60")])])

    async def answer(script):  # runs until stopped
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    code_runner.answer = answer
    # The user asks to stop the sum while Start opens; Start goes on once the main agent has replied to that.
    sent_while_pressing(computer, inbox, "stop the sum", until=lambda: len(main_model.received) >= 3)

    result = await run_turn(settings, "open start and add 2 and 2", max_steps=10, computer=computer,
                            code_runner=code_runner, inbox=inbox)

    computing, coding = task_of(settings, "computer"), task_of(settings, "coding")
    assert cancelled.is_set() and actions(result)["m3"]["status"] == "success"
    assert task_states(settings)[2:] == [(coding, "stopped"), (computing, "ended")]
    assert ("press", [["win"]]) in computer.calls and result.reply == "Start is open; the sum was stopped."


async def test_a_call_a_stop_cut_off_is_answered_as_unknown_before_the_note_of_the_stopped_task(
    settings, computer, monkeypatch
):
    inbox, pressing, searching = Inbox(), asyncio.Event(), asyncio.Event()

    async def stuck(self, query, limit):  # a search that never returns
        searching.set()
        await asyncio.Event().wait()

    async def press(combos):
        pressing.set()
        inbox.put("which chat was about Start?")
        await asyncio.Event().wait()

    monkeypatch.setattr(FileRuns, "search", stuck)
    computer.press = press
    _, main_model = use_script(monkeypatch, [
        AIMessage(content="", tool_calls=[tool_call("c1", "key", text="win")]),
    ], main=[delegate("Open Start."),
             AIMessage(content="", tool_calls=[tool_call("m2", "search_conversations", query="Start")])])
    run = asyncio.create_task(run_turn(settings, "open start", max_steps=10, computer=computer, inbox=inbox))
    await pressing.wait()
    await searching.wait()  # the search is under way
    run.cancel()
    await asyncio.gather(run, return_exceptions=True)
    thread = first_run(settings)
    _, main_model = use_script(monkeypatch, [], main=[AIMessage("It may or may not have stopped.")])

    await run_turn(settings, "did it stop?", max_steps=10, computer=computer, thread=thread)

    heard = main_model.received[0]
    asked = next(n for n, m in enumerate(heard) if isinstance(m, AIMessage) and m.tool_calls
                 and m.tool_calls[0]["id"] == "m2")
    # The result follows its call, as model APIs require; then the note that the task stopped, then the question.
    answer, note, question = heard[asked + 1:asked + 4]
    assert "The run was stopped, and the background task t1 (computer agent) with it" in note.text
    assert isinstance(answer, ToolMessage) and answer.tool_call_id == "m2" and answer.text == notes.UNKNOWN_RESULT
    assert from_user(question) and question.text == "did it stop?"


async def test_every_task_the_runtime_died_under_is_told_to_the_next_run(settings, computer, code_runner, monkeypatch):
    pressing, running = asyncio.Event(), asyncio.Event()

    async def press(combos):
        pressing.set()
        await asyncio.Event().wait()

    async def answer(script):
        running.set()
        await asyncio.Event().wait()

    computer.press, code_runner.answer = press, answer
    use_script(monkeypatch, [AIMessage(content="", tool_calls=[tool_call("c1", "key", text="win")])], main=[
        AIMessage(content="", tool_calls=[
            tool_call("m1", "start_task", agent="computer", title="Start", task="Open Start."),
            tool_call("m2", "start_task", agent="coding", title="Sum", task="Add 2 and 2."),
        ]),
    ])
    coding_script(monkeypatch, [AIMessage(content="", tool_calls=[tool_call("k1", "bash", script="sleep 60")])])
    run = asyncio.create_task(run_turn(settings, "open start and add 2 and 2", max_steps=10, computer=computer,
                                       code_runner=code_runner))
    await pressing.wait()
    await running.wait()
    died = crash_point(settings)
    run.cancel()
    await asyncio.gather(run, return_exceptions=True)
    died()
    thread = first_run(settings)
    _, main_model = use_script(monkeypatch, [], main=[AIMessage("Both may or may not have finished.")])

    await run_turn(settings, "did they finish?", max_steps=10, computer=computer, code_runner=code_runner,
                   thread=thread)

    heard = runtime_notes(main_model.received[0])
    told = {(agent, f"background task {task_of(settings, agent)} ({agent} agent)") for agent in ("computer", "coding")}
    assert len(heard) == 2 and all(any(said in note for note in heard) for _, said in told)


async def test_a_result_a_stop_cut_off_before_it_was_heard_is_not_told_later(settings, computer, monkeypatch):
    inbox = Inbox()

    class Asking(ScriptedModel):  # the user asks something while the task works, and it then ends
        async def ainvoke(self, input, config=None, **kwargs):
            message = inbox.put("what is the weather?")
            await until(lambda: MAIN in message.read_by)
            return await super().ainvoke(input, config, **kwargs)

    class Hanging(ScriptedModel):  # the answer to that never comes
        async def ainvoke(self, input, config=None, **kwargs):
            if self.received:
                self.received.append(list(input))
                await asyncio.Event().wait()
            return await super().ainvoke(input, config, **kwargs)

    use_script(monkeypatch, [])
    main_model = Hanging(messages=iter([delegate("Open Start.")]), received=[], bindings=[])
    computer_model = Asking(messages=iter([AIMessage("Opened Start.")]), received=[], bindings=[])
    monkeypatch.setattr("computer_use.agent.main_agent.build_chat_model", lambda _spec, _settings, **_: main_model)
    monkeypatch.setattr("computer_use.agent.computer_agent.build_chat_model", lambda _spec, _settings: computer_model)
    run = asyncio.create_task(run_turn(settings, "open start", max_steps=10, computer=computer, inbox=inbox))
    await until(lambda: ("t1", "ended") in task_states(settings) and len(main_model.received) == 2)
    run.cancel()
    await asyncio.gather(run, return_exceptions=True)
    thread = first_run(settings)
    _, main_model = use_script(monkeypatch, [], main=[AIMessage("I don't know if it opened.")])

    await run_turn(settings, "did it open?", max_steps=10, computer=computer, thread=thread)

    # It heard the task run, as the user's question came with its status, but not that it ended or stopped.
    heard = runtime_notes(main_model.received[0])
    assert [note for note in heard if "has ended" in note or "stopped" in note] == []
    assert len(heard) == 1 and "Task t1 (computer agent) is still running" in heard[0]


async def test_stopping_the_reply_leaves_its_tasks_at_work(settings, computer, monkeypatch):
    inbox, opened, asked, done = Inbox(), [], asyncio.Event(), asyncio.Event()

    class Answering(ScriptedModel):  # the reply to the user's question never comes, until stopped
        async def ainvoke(self, input, config=None, **kwargs):
            if len(self.received) == 1:
                self.received.append(list(input))
                asked.set()
                await asyncio.Event().wait()
            return await super().ainvoke(input, config, **kwargs)

    async def press(combos):  # Start opens once the reply was stopped
        inbox.put("what is the weather?")
        await done.wait()

    use_script(monkeypatch, [AIMessage(content="", tool_calls=[tool_call("c1", "key", text="win")]),
                             AIMessage("Opened Start.")])
    main_model = Answering(messages=iter([delegate("Open Start."), AIMessage("Start is open.")]), received=[],
                           bindings=[])
    monkeypatch.setattr("computer_use.agent.main_agent.build_chat_model", lambda _spec, _settings, **_: main_model)
    computer.press = press
    run = asyncio.create_task(run_turn(settings, "open start", max_steps=10, computer=computer, inbox=inbox,
                                       opened=opened.append))
    await asyncio.wait_for(asked.wait(), 10)
    assert opened[0].stop_turn() and task_states(settings) == [("t1", "started")]
    await until(lambda: [e["stop_reason"] for e in events_of(settings, first_run(settings)) if e["type"] == "end"]
                == ["replied", "cancelled"])
    done.set()

    result = await run

    # The task went on and ended; the main agent heard both that its reply was stopped and what the task did.
    assert task_states(settings) == [("t1", "started"), ("t1", "ended")] and result.reply == "Start is open."
    heard = runtime_notes(main_model.received[-1])
    assert any(notes.REPLY_STOPPED_BY_USER in note for note in heard)
    assert any("has ended" in note and "Open Start." in note for note in heard)


async def test_a_task_the_user_stops_is_told_at_the_main_agents_next_call_without_waking_it(
    settings, computer, code_runner, monkeypatch
):
    opened, pressing, done = [], asyncio.Event(), asyncio.Event()

    async def press(combos):
        pressing.set()
        await done.wait()

    async def answer(script):  # runs until stopped
        await asyncio.Event().wait()

    computer.press, code_runner.answer = press, answer
    _, main_model = use_script(monkeypatch, [
        AIMessage(content="", tool_calls=[tool_call("c1", "key", text="win")]), AIMessage("Opened Start."),
    ], main=[
        AIMessage(content="", tool_calls=[
            tool_call("m1", "start_task", agent="computer", title="Start", task="Open Start."),
            tool_call("m2", "start_task", agent="coding", title="Sum", task="Add 2 and 2."),
        ]),
        AIMessage("Start is open; you stopped the sum."),
    ])
    coding_script(monkeypatch, [AIMessage(content="", tool_calls=[tool_call("k1", "bash", script="sleep 60")])])
    run = asyncio.create_task(run_turn(settings, "open start and add 2 and 2", max_steps=10, computer=computer,
                                       code_runner=code_runner, opened=opened.append))
    await pressing.wait()
    coding = next(e["record"] for e in events_of(settings, first_run(settings))
                  if e["type"] == "task" and e["agent"] == "coding")
    assert await opened[0].background.stop_for_user(coding)
    await asyncio.sleep(0.05)
    assert len(main_model.received) == 1  # not woken for it
    done.set()

    result = await run

    told = [note for note in runtime_notes(main_model.received[1]) if "The user stopped" in note]
    assert len(told) == 1 and "(coding agent)" in told[0] and result.reply == "Start is open; you stopped the sum."
    assert sorted(state for _, state in task_states(settings)[2:]) == ["ended", "stopped"]


async def test_a_task_the_user_stopped_as_the_session_went_quiet_is_told_to_the_next_session_as_theirs(
    settings, computer, code_runner, monkeypatch
):
    opened, running = [], asyncio.Event()

    async def answer(script):  # runs until stopped
        running.set()
        await asyncio.Event().wait()

    code_runner.answer = answer
    use_script(monkeypatch, [], main=[
        AIMessage(content="", tool_calls=[tool_call("m1", "start_task", agent="coding", title="Sum", task="Add 2 and 2.")]),
    ])
    coding_script(monkeypatch, [AIMessage(content="", tool_calls=[tool_call("k1", "bash", script="sleep 60")])])
    run = asyncio.create_task(run_turn(settings, "add 2 and 2", max_steps=10, computer=computer,
                                       code_runner=code_runner, opened=opened.append))
    await running.wait()
    (job,) = opened[0].background.jobs.values()
    assert await opened[0].background.stop_for_user(job.record)
    await run  # quiet: nothing woke the main agent to hear of it
    _, main_model = use_script(monkeypatch, [], main=[AIMessage("You stopped the sum.")])

    await run_turn(settings, "what happened to the sum?", max_steps=10, computer=computer, code_runner=code_runner,
                   thread=first_run(settings))

    heard = runtime_notes(main_model.received[0])
    assert len(heard) == 1 and heard[0].endswith(notes.stopped_by_user("t1", "coding", "Add 2 and 2."))


async def test_each_stopped_task_is_told_once_though_every_session_numbers_its_tasks_from_t1(
    settings, computer, code_runner, monkeypatch
):
    opened, running = [], asyncio.Event()

    async def answer(script):  # runs until stopped
        running.set()
        await asyncio.Event().wait()

    code_runner.answer = answer

    async def stopped_by_user(message: str, task: str, thread: str | None = None) -> ScriptedModel:
        """A session whose main agent hands `task` over as t1, which the user stops; what its main agent heard."""
        running.clear()
        _, main_model = use_script(monkeypatch, [], main=[
            AIMessage(content="", tool_calls=[tool_call("m1", "start_task", agent="coding", title="Sum", task=task)]),
        ])
        coding_script(monkeypatch, [AIMessage(content="", tool_calls=[tool_call("k1", "bash", script="sleep 60")])])
        run = asyncio.create_task(run_turn(settings, message, max_steps=10, computer=computer,
                                           code_runner=code_runner, thread=thread, opened=opened.append))
        await running.wait()
        (job,) = opened[-1].background.jobs.values()
        assert await opened[-1].background.stop_for_user(job.record)
        await run
        return main_model

    await stopped_by_user("add 2 and 2", "Add 2 and 2.")
    second = await stopped_by_user("add 3 and 3", "Add 3 and 3.", thread=first_run(settings))
    _, main_model = use_script(monkeypatch, [], main=[AIMessage("You stopped both.")])
    await run_turn(settings, "what happened?", max_steps=10, computer=computer, code_runner=code_runner,
                   thread=first_run(settings))

    assert runtime_notes(second.received[0]) == [f"{notes.FROM_RUNTIME} {notes.stopped_by_user('t1', 'coding', 'Add 2 and 2.')}"]
    assert runtime_notes(main_model.received[0]) == [  # the first heard in the second session, the second now
        f"{notes.FROM_RUNTIME} {notes.stopped_by_user('t1', 'coding', task)}" for task in ("Add 2 and 2.", "Add 3 and 3.")
    ]
