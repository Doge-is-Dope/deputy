"""The whole loop with scripted models: main agent -> computer_use -> computer-use agent -> guards -> tool -> executor
-> computer -> screenshot -> computer-use agent -> ... -> the main agent's reply."""

import asyncio
import json

import pytest
from langchain_core.messages import AIMessage

import computer_use.agent.main_agent as main_agent
from computer_use.prompts import notes
from computer_use.prompts.computer import SYSTEM_PROMPT, system_prompt
import computer_use.desktop.executor
from computer_use.agent.inbox import Inbox
from computer_use.agent.history import tasks
from conftest import run_turn
from conftest import read_events, run_dir
from computer_use.computers import ComputerError
from computer_use.desktop.control import ControlFile, DesktopBusy, RunLock
from conftest import (
    ScriptedModel,
    computer_use_result,
    delegate,
    fixture_png,
    handed_back,
    logged,
    run_folder,
    telling,
    tool_call,
    use_script,
)

pytestmark = pytest.mark.usefixtures("the_log_is_the_whole_record")


def notes_so_far(settings) -> list[str]:
    logs = list((settings.data_dir / "runs").glob("*/steps.jsonl"))
    return [event["text"] for event in read_events(logs[0].parent) if event["type"] == "note"] if logs else []


async def test_loop_executes_every_allowed_tool_call_of_a_turn(settings, computer, monkeypatch):
    use_script(monkeypatch, [
        AIMessage(content="Open Start.", tool_calls=[tool_call("c1", "key", text="win")]),
        AIMessage(content="", tool_calls=[
            tool_call("c2", "type", text="notepad"),
            tool_call("c3", "key", text="enter"),
        ]),
        AIMessage(content="", tool_calls=[tool_call("c4", "key", text="ctrl+alt+delete")]),  # blocked input
        AIMessage(content="", tool_calls=[tool_call("c5", "left_click", coordinate=[5000, 10])]),
        AIMessage(content="", tool_calls=[tool_call("c6", "type", text="會議紀錄")]),
        AIMessage(content="Typed the note."),
        AIMessage(content="never reached"),
    ])

    result = await run_turn(settings, "type a note", max_steps=10, computer=computer)

    assert (result.reply, result.computer) == ("Done.", "replied")
    assert handed_back(result)["reply"] == "Typed the note."
    # The two calls of one turn run at once, in no promised order.
    assert computer.calls[0] == ("press", [["win"]]) and computer.calls[3] == ("type_text", "會議紀錄")
    assert sorted(computer.calls[1:3]) == [("press", [["enter"]]), ("type_text", "notepad")]
    actions = {event["id"]: event for event in logged(result, "action")}
    assert {call_id: event["status"] for call_id, event in actions.items()} == {
        "c1": "success", "c2": "success", "c3": "success", "c4": "error", "c5": "error", "c6": "success",
    }
    assert "the security screen" in actions["c4"]["result"]
    assert "outside" in actions["c5"]["result"]
    for event in actions.values():
        if event["status"] == "success":
            assert (run_dir(settings, result.run) / event["screenshot"]).exists()
    assert '1. Open Start. -> key {"text": "win"} -> success' in computer_use_result(result)["result"]


async def test_loop_runs_a_batch_as_one_tool_call(settings, computer, monkeypatch):
    use_script(monkeypatch, [
        AIMessage(content="Fill in the form.", tool_calls=[tool_call("b1", "computer_batch", actions=[
            {"action": "left_click", "coordinate": [100, 100]},
            {"action": "type", "text": "Ada"},
            {"action": "key", "text": "tab"},
            {"action": "type", "text": "Lovelace"},
        ])]),
        AIMessage(content="Filled it in."),
    ])

    result = await run_turn(settings, "fill in the form", max_steps=10, computer=computer)

    assert result.computer == "replied"
    assert computer.calls == [
        ("click", (100, 100), "left", 1, []), ("type_text", "Ada"), ("press", [["tab"]]), ("type_text", "Lovelace"),
    ]
    (batch,) = logged(result, "action")
    assert (batch["tool"], batch["status"]) == ("computer_batch", "success")
    assert "\n4. Typed 8 characters." in batch["result"] and (run_dir(settings, result.run) / batch["screenshot"]).exists()
    handback = computer_use_result(result)["result"]
    assert "4. Typed 8 characters." in handback
    assert "Earlier screen before action 1" in handback


async def test_handoff_images_use_task_action_numbers_after_an_earlier_delegation(settings, computer, monkeypatch):
    use_script(monkeypatch, [
        AIMessage(content="", tool_calls=[tool_call("c1", "type", text="Draft")]),
        AIMessage(content="Typed the draft."),
        AIMessage(content="", tool_calls=[tool_call("c2", "key", text="ctrl+a")]),
        AIMessage(content="", tool_calls=[tool_call("c3", "type", text="Final")]),
        AIMessage(content="Replaced the draft."),
    ], main=[
        delegate("Type the draft.", "m1"), delegate("Replace it with Final.", "m2"), AIMessage("Done."),
    ])

    result = await run_turn(settings, "type Draft, then replace it with Final", max_steps=10, computer=computer)

    assert [event["n"] for event in logged(result, "action")] == [1, 2, 3]
    handoffs = [
        event["message"]["data"] for event in logged(result, "input", "main")
        if event["message"]["data"].get("additional_kwargs", {}).get("runtime", {}).get("event") == "task_ended"
    ]
    assert len(handoffs) == 2
    blocks = handoffs[-1]["content"]
    text = "\n".join(block["text"] for block in blocks if block.get("type") == "text")
    assert "Its actions (2):" in text and '2. type {"text": "Final"}' in text
    assert "Earlier screen before action 2" in text
    assert "Earlier screen before action 3" not in text
    assert sum(block.get("type") == "image" for block in blocks) == 2  # this task's historical and final screens


async def test_loop_ends_at_the_step_limit_instead_of_crashing(settings, computer, monkeypatch):
    # Long enough that a recursion limit below the graph's real size would raise first.
    use_script(monkeypatch, [
        AIMessage(content="", tool_calls=[tool_call(f"c{n}", "key", text="a")]) for n in range(30)
    ])
    # Every key press draws a new number, a visible change, so pressing the same key is not being stuck.
    computer.screen = lambda: fixture_png(str(len(computer.calls)))

    result = await run_turn(settings, "keep going", max_steps=20, computer=computer)

    assert len(computer.calls) == 20
    assert len(logged(result, "action")) == 20
    assert result.computer == "step_limit"
    assert [(event["stop_reason"], event["computer"]) for event in logged(result, "end")] == [("replied", "step_limit")]
    handback = computer_use_result(result)["result"]
    assert "the runtime stopped it after 20 model calls" in handback
    # The model call limit closes the transcript with its own message, which is not the agent's reply.
    assert handed_back(result)["reply"] == ""
    assert "Its final message (a claim, not evidence): (none)" in handback
    assert "Model call limits exceeded" not in handback


async def test_a_reply_on_the_last_allowed_call_is_a_reply_not_the_step_limit(settings, computer, monkeypatch):
    use_script(monkeypatch, [
        AIMessage(content="", tool_calls=[tool_call("c1", "key", text="a")]),
        AIMessage(content="Pressed a."),
    ])

    result = await run_turn(settings, "press a", max_steps=2, computer=computer)

    assert (handed_back(result)["reply"], result.computer) == ("Pressed a.", "replied")
    assert "the runtime stopped it" not in computer_use_result(result)["result"]


async def test_loop_asks_for_another_way_then_stops_when_actions_change_nothing(settings, computer, monkeypatch):
    # The fake screen never changes, like a panel that does not open however often the key is pressed.
    use_script(monkeypatch, [
        AIMessage(content="", tool_calls=[tool_call(f"c{n}", "key", text="win")]) for n in range(10)
    ])

    result = await run_turn(settings, "open start", max_steps=20, computer=computer)

    # The runtime stopped it, so it has no reply: the runtime's own words are not passed off as the agent's.
    assert handed_back(result)["reply"] == ""
    assert result.computer == "stuck"
    assert "its last actions did not change the screen" in computer_use_result(result)["result"]
    assert len(computer.calls) == 6
    results = [event["result"] for event in logged(result, "action")]
    assert "did not change the screen" not in results[1]
    assert "Your last 3 actions did not change the screen" in results[2]


async def test_only_the_same_action_repeating_without_effect_stops_a_run(settings, computer, monkeypatch):
    # Different keys, none of which changes the screen: the model is told to try another way, but trying is not
    # being stuck.
    use_script(monkeypatch, [
        *(AIMessage(content="", tool_calls=[tool_call(f"c{n}", "key", text=key)]) for n, key in enumerate("ab" * 4)),
        AIMessage(content="Nothing worked."),
    ])

    result = await run_turn(settings, "try things", max_steps=20, computer=computer)

    assert len(computer.calls) == 8 and result.computer != "stuck"
    results = [event["result"] for event in logged(result, "action")]
    assert "Your last 3 actions did not change the screen" in results[2]


async def test_loop_does_not_act_on_a_screen_that_changed_while_the_model_decided(settings, computer, monkeypatch):
    use_script(monkeypatch, [
        AIMessage(content="", tool_calls=[tool_call("c1", "key", text="ctrl+s")]),
        AIMessage(content="", tool_calls=[tool_call("c2", "key", text="ctrl+s")]),
        AIMessage(content="Saved."),
    ])
    monkeypatch.setattr(computer_use.desktop.executor, "MOVING_WATCH_SECONDS", 0)
    screens = iter([fixture_png("Loading"), fixture_png("Notepad")])
    # The first observation shows the app loading; it has finished by the time the model acts.
    computer.screen = lambda: next(screens, fixture_png("Notepad"))

    result = await run_turn(settings, "save", max_steps=10, computer=computer)

    assert computer.calls == [("press", [["ctrl", "s"]])]  # only the second, decided on the current screen
    first, second = logged(result, "action")
    assert first["status"] == "error" and "screen changed since your last screenshot" in first["result"]
    assert first["screenshot"] and second["status"] == "success"


async def test_the_log_records_tokens_per_model_call_and_in_total(settings, computer, monkeypatch):
    settings.computer_model = "openai:gpt-6-luna"
    use_script(monkeypatch, [
        AIMessage(content="", tool_calls=[tool_call("c1", "key", text="ctrl+s")], usage_metadata={
            "input_tokens": 1000, "output_tokens": 50, "total_tokens": 1050,
            "input_token_details": {"cache_read": 600}, "output_token_details": {"reasoning": 30},
        }),
        AIMessage(content="Saved.", usage_metadata={"input_tokens": 1200, "output_tokens": 20, "total_tokens": 1220}),
    ])

    result = await run_turn(settings, "save", max_steps=10, computer=computer)

    assert [event["usage"] for event in logged(result, "model")] == [
        {"input": 1000, "cached": 600, "cache_write": 0, "output": 50, "reasoning": 30},
        {"input": 1200, "cached": 0, "cache_write": 0, "output": 20, "reasoning": 0},
    ]
    # gpt-6-luna list prices: 1,600 plain input x $0.10 + 600 cached x $0.01 + 70 output x $0.50 per million.
    summary = logged(result, "note")[-1]["text"]
    for number in ["4 model calls", "2 by the main agent", "2,200 input", "600 cached", "70 output", "30 reasoning",
                   "$0.0002"]:
        assert number in summary


async def test_loop_waits_while_the_user_has_control(settings, computer, monkeypatch, fast_polls):
    use_script(monkeypatch, [
        AIMessage(content="", tool_calls=[tool_call("h1", "request_takeover", reason="sign in")]),
        AIMessage(content="", tool_calls=[tool_call("c1", "key", text="ctrl+s")]),
        AIMessage(content="Saved after the user signed in."),
    ])
    control = ControlFile(settings.control_path)

    async def user_returns_control():
        # Once the agent waits for it: returned sooner, the agent's next step is refused as decided from an older screen.
        while "The user has control." not in "".join(
            path.read_text() for path in (settings.data_dir / "runs").glob("*/steps.jsonl")
        ):
            await asyncio.sleep(0.05)
        assert computer.calls == []
        control.write("agent")

    user = asyncio.create_task(user_returns_control())
    result = await asyncio.wait_for(run_turn(settings, "save", max_steps=10, computer=computer), timeout=20)
    await user

    assert (handed_back(result)["reply"], result.computer) == ("Saved after the user signed in.", "replied")
    assert computer.calls == [("press", [["ctrl", "s"]])]
    assert any("Control returned" in note["text"] for note in logged(result, "note"))


async def test_what_the_main_agent_tells_a_task_while_the_user_has_the_desktop_comes_with_the_fresh_screen(
    settings, computer, monkeypatch, fast_polls
):
    told = telling(monkeypatch)
    computer_model, _ = use_script(monkeypatch, [
        AIMessage(content="", tool_calls=[tool_call("h1", "request_takeover", reason="sign in")]),
        AIMessage(content="Signed in."),
    ], main=[
        delegate("Sign in."),
        AIMessage(content="", tool_calls=[tool_call("m2", "tell_task", task_id="t1", message="The user says they have signed in.")]),
        AIMessage("Got it."),
        AIMessage("Signed in."),
    ])
    control, inbox = ControlFile(settings.control_path), Inbox()

    async def user_writes_then_returns_control():
        while control.read().owner != "user":
            await asyncio.sleep(0.05)
        inbox.put("I signed in already")
        while not told:  # the main agent answers at once, while the task waits for the desktop
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.2)
        control.write("agent")

    user = asyncio.create_task(user_writes_then_returns_control())
    await asyncio.wait_for(run_turn(settings, "save", max_steps=10, computer=computer, inbox=inbox), timeout=20)
    await user

    note = computer_model.received[1][-1]
    text, image = note.content
    assert text["text"].startswith("From the main agent, while you work.")
    assert "The user says they have signed in." in text["text"] and "- I signed in already" in text["text"]
    assert "\n\nThe user had control for " in text["text"] and image["type"] == "image"


async def test_a_run_never_takes_the_desktop_from_the_user(settings, computer, monkeypatch, fast_polls):
    use_script(monkeypatch, [
        AIMessage(content="", tool_calls=[tool_call("c1", "key", text="ctrl+s")]),
        AIMessage(content="Saved."),
    ])
    control = ControlFile(settings.control_path)
    control.write("user", "editing a slide")

    async def user_returns_control():
        while not any("The user has control" in text for text in notes_so_far(settings)):
            await asyncio.sleep(0.01)
        assert control.read().reason == "editing a slide" and computer.calls == []
        control.write("agent", "returned by user")

    user = asyncio.create_task(user_returns_control())
    result = await asyncio.wait_for(run_turn(settings, "save", max_steps=10, computer=computer), timeout=20)
    await asyncio.wait_for(user, timeout=5)  # times out if the task never waited for the user

    assert handed_back(result)["reply"] == "Saved." and computer.calls == [("press", [["ctrl", "s"]])]


async def test_a_run_lets_go_of_what_the_agent_still_held_when_it_ends(settings, computer, monkeypatch):
    use_script(monkeypatch, [
        AIMessage(content="", tool_calls=[tool_call("c1", "left_mouse_down")]),
        AIMessage(content="Pressed it."),
    ])

    await run_turn(settings, "press the button", max_steps=10, computer=computer)

    assert computer.calls == [("mouse_button", True)] and computer.releases == 1


async def test_a_message_for_the_desktop_does_not_start_while_another_run_has_it(settings, computer, control, monkeypatch):
    use_script(monkeypatch, [AIMessage(content="never asked")])
    control.write("user", "taken over by user")

    with RunLock(settings.run_lock_path) as other:
        other.name("20261007-120000")
        with pytest.raises(DesktopBusy) as busy:
            await run_turn(
                settings, "open start", max_steps=10, computer=computer, force_computer=True, take_control=True
            )

    assert busy.value.run == "20261007-120000"
    assert not (settings.data_dir / "runs").exists() and computer.calls == []
    assert control.read().owner == "user"  # not handed to the agent: the other run would have carried on


async def test_other_messages_go_on_while_another_run_has_the_desktop(settings, computer, monkeypatch):
    with RunLock(settings.run_lock_path) as other:
        other.name("20261007-120000")
        use_script(monkeypatch, [], main=[AIMessage("Paris.")])
        answered = await run_turn(settings, "capital of France?", max_steps=10, computer=computer)
        computer_model, _ = use_script(monkeypatch, [AIMessage(content="never asked")], main=[
            delegate(), AIMessage("Another conversation is using the desktop; try again when it is done."),
        ])
        refused = await run_turn(settings, "open start", max_steps=10, computer=computer)
        assert RunLock(settings.run_lock_path).holder()["run"] == "20261007-120000"

    assert (answered.reply, answered.computer) == ("Paris.", None)
    assert refused.computer is None and computer_model.received == []
    assert computer.calls == [] and computer.releases == 0
    handed = computer_use_result(refused)
    assert handed["status"] == "error" and handed["result"] == notes.DESKTOP_BUSY
    assert tasks(read_events(run_dir(settings, refused.run))) == []
    end = logged(refused, "end")[0]
    assert (end["stop_reason"], end["computer"]) == ("replied", None)


async def test_a_run_takes_the_desktop_when_it_first_uses_it_and_lets_go_at_the_end(settings, computer, monkeypatch):
    holders = []

    async def release_all():  # what the run left down is let go of while the run still has the desktop
        holders.append(RunLock(settings.run_lock_path).holder())

    computer.release_all = release_all
    lock = RunLock(settings.run_lock_path)
    use_script(monkeypatch, [AIMessage(content="Opened Start.")])

    result = await run_turn(settings, "open start", max_steps=10, computer=computer)

    assert [holder["run"] for holder in holders] == [result.run]
    assert lock.holder() is None
    started = asyncio.Event()

    async def press(combos):  # never finishes: the run is stopped during it
        started.set()
        await asyncio.Event().wait()

    computer.press = press
    use_script(monkeypatch, [AIMessage(content="", tool_calls=[tool_call("c1", "key", text="win")])])
    run = asyncio.create_task(run_turn(settings, "open start", max_steps=10, computer=computer))
    await started.wait()
    assert lock.holder()["run"] != result.run
    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run
    assert lock.holder() is None


async def test_a_message_for_the_desktop_gets_it_from_the_user_once_the_run_has_it(settings, computer, control, monkeypatch):
    use_script(monkeypatch, [AIMessage(content="Opened Start.")])
    control.write("user", "taken over by user")

    result = await run_turn(
        settings, "@Computer open start", max_steps=10, computer=computer, force_computer=True, take_control=True
    )

    assert (result.computer, control.read().owner) == ("replied", "agent")
    assert not [note for note in logged(result, "note") if "The user has control" in note["text"]]


async def test_a_stopped_run_still_ends_its_log_and_frees_the_desktop(settings, computer, monkeypatch):
    pressing = asyncio.Event()

    async def press(combos):  # never finishes: the run is stopped during it
        pressing.set()
        await asyncio.Event().wait()

    computer.press = press
    use_script(monkeypatch, [AIMessage(content="", tool_calls=[tool_call("c1", "key", text="win")])])
    run = asyncio.create_task(run_turn(settings, "open start", max_steps=10, computer=computer))
    await pressing.wait()
    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run

    folder = run_folder(settings)
    ends = [event for event in read_events(folder) if event["type"] == "end"]
    assert [(end["stop_reason"], end["summary"], end["computer"]) for end in ends] == [("cancelled", "", None)]
    assert "error" not in ends[0] and "usage" in ends[0]
    assert RunLock(settings.run_lock_path).holder() is None


async def test_a_desktop_that_cannot_be_used_is_told_to_the_main_agent_which_replies(settings, computer, monkeypatch):
    computer_model, _ = use_script(monkeypatch, [AIMessage(content="never asked")], main=[
        AIMessage(content="", tool_calls=[tool_call("m1", "computer_use", title="Task", task="Open Start.")]),
        AIMessage("The desktop can't be reached right now."),
    ])

    def gone():
        raise ComputerError("the display is gone")

    computer.screen = gone
    result = await run_turn(settings, "open start", max_steps=10, computer=computer)

    assert (result.reply, result.computer) == ("The desktop can't be reached right now.", "error")
    assert computer_model.received == []
    handback = computer_use_result(result)
    assert handback["status"] == "success" and "the desktop could not be seen or used" in handback["result"]
    assert "No screenshot: the display is gone" in handback["result"]
    assert "Stopped: the desktop could not be used: the display is gone" in [n["text"] for n in logged(result, "note")]
    end = logged(result, "end")[0]
    assert (end["stop_reason"], end["computer"]) == ("replied", "error") and "error" not in end


async def test_a_run_whose_main_agent_fails_ends_its_log_with_the_error(settings, computer, monkeypatch):
    class Broken(ScriptedModel):
        async def ainvoke(self, input, config=None, **kwargs):
            raise RuntimeError("the model API is down")

    use_script(monkeypatch, [])
    monkeypatch.setattr(main_agent, "build_chat_model", lambda _spec, _settings, **_: Broken(messages=iter([])))
    with pytest.raises(RuntimeError):
        await run_turn(settings, "open start", max_steps=10, computer=computer)

    folder = run_folder(settings)
    end = read_events(folder)[-1]
    assert (end["type"], end["stop_reason"], end["error"]) == ("end", "error", "RuntimeError: the model API is down")
    assert end["error_code"] == "E-UNKNOWN"
    assert RunLock(settings.run_lock_path).holder() is None


async def test_loop_waits_while_the_desktop_is_disconnected(settings, computer, monkeypatch, fast_polls):
    use_script(monkeypatch, [
        AIMessage(content="", tool_calls=[tool_call("c1", "key", text="ctrl+a")]),
        AIMessage(content="", tool_calls=[tool_call("c2", "key", text="ctrl+s")]),
        AIMessage(content="Saved."),
    ])
    press = computer.press

    async def press_then_drop(combos):
        await press(combos)
        if len(computer.calls) == 1:
            computer.connected = False

    monkeypatch.setattr(computer, "press", press_then_drop)

    async def session_comes_back():
        while computer.connected:
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.2)
        assert computer.calls == [("press", [["ctrl", "a"]])]  # nothing is sent while disconnected
        computer.connected = True

    session = asyncio.create_task(session_comes_back())
    result = await asyncio.wait_for(run_turn(settings, "save", max_steps=10, computer=computer), timeout=20)
    await session

    assert handed_back(result)["reply"] == "Saved."
    assert computer.calls == [("press", [["ctrl", "a"]]), ("press", [["ctrl", "s"]])]
    notes = [note["text"] for note in logged(result, "note")]
    assert any(note.startswith("The desktop is disconnected;") for note in notes)
    assert any(note.startswith("The desktop reconnected after") for note in notes)
    assert any("disconnected for" in json.dumps(event) for event in logged(result, "input"))


async def test_a_run_stops_when_the_desktop_does_not_reconnect(settings, computer, monkeypatch, fast_polls):
    monkeypatch.setattr(computer_use.desktop.executor, "RECONNECT_LIMIT_SECONDS", 0.05)
    use_script(monkeypatch, [
        AIMessage(content="", tool_calls=[tool_call("c1", "key", text="ctrl+a")]),
        AIMessage(content="never asked"),
    ])
    press = computer.press

    async def press_then_drop(combos):
        await press(combos)
        computer.connected = False

    monkeypatch.setattr(computer, "press", press_then_drop)
    result = await run_turn(settings, "select all", max_steps=10, computer=computer)

    assert result.computer == "disconnected"
    assert handed_back(result)["reply"] == ""
    assert "the desktop did not reconnect in time" in computer_use_result(result)["result"]
    assert "Stopped: the desktop did not reconnect within 0.05 seconds." in [n["text"] for n in logged(result, "note")]
    timeout = next(note for note in logged(result, "note") if note["code"] == "gone")
    assert timeout["data"] == {"seconds": 0.05}


async def test_a_desktop_that_is_gone_ends_the_task_even_while_the_user_has_control(
    settings, computer, monkeypatch, fast_polls
):
    monkeypatch.setattr(computer_use.desktop.executor, "RECONNECT_LIMIT_SECONDS", 0.05)
    use_script(monkeypatch, [AIMessage(content="never asked")])
    control = ControlFile(settings.control_path)
    control.write("user", "taken over by user")
    status = computer.status
    asked = []

    async def dropping():  # connected as the task is handed over, gone once it starts
        computer.connected = not asked
        asked.append(True)
        return await status()

    monkeypatch.setattr(computer, "status", dropping)

    # Times out if the task waits for the user to hand back a desktop that is gone.
    result = await asyncio.wait_for(run_turn(settings, "save", max_steps=10, computer=computer), timeout=5)

    assert result.computer == "disconnected" and computer.calls == []
    codes = [note["code"] for note in logged(result, "note")]
    assert "userControl" not in codes and codes.index("disconnected") < codes.index("gone")
    assert control.read().owner == "user"


async def test_a_desktop_task_is_refused_at_once_while_the_desktop_is_down(settings, computer, monkeypatch):
    computer_model, main_model = use_script(monkeypatch, [AIMessage(content="never asked")], main=[
        delegate("Open Start."), AIMessage("The desktop is not connected."),
    ])
    computer.connected = False

    # Times out if the task waits the minute it gives a desktop that drops while it works.
    result = await asyncio.wait_for(run_turn(settings, "open start", max_steps=10, computer=computer), 5)

    assert result.reply == "The desktop is not connected." and result.computer is None
    assert computer_model.received == [] and computer.calls == []
    refused = computer_use_result(result)
    assert refused["status"] == "error" and refused["reason"] == "disconnected"
    assert refused["result"].startswith("Not executed: the desktop is not connected (Test session: DISCONNECTED)")
    assert RunLock(settings.run_lock_path).holder() is None


@pytest.mark.parametrize(
    ("locale", "language"), [("zh-Hant", "Traditional Chinese"), ("en", "English"), ("ja", "ja")]
)
def test_the_prompt_names_the_language_the_user_reads(locale, language):
    assert system_prompt(locale) == (
        f"{SYSTEM_PROMPT}\nThe user reads {language}: write anything you say to them in {language}."
    )


def test_the_prompt_asks_for_updates_only_as_a_task_starts_and_its_phases_change():
    """OpenAI's wording for updates in long tool-heavy tasks (Prompting guidance for GPT-5.6 Sol); without it the agent
    said nothing in 60 of 60 steps (2026-10-19)."""
    assert "send a one- or two-sentence user-visible update that states the first step" in SYSTEM_PROMPT
    assert "routine steps need no narration" not in SYSTEM_PROMPT
    assert system_prompt(None) == SYSTEM_PROMPT
