import asyncio
import json
import os

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from computer_use.agent.history import in_call_order, load_conversation, main_messages
from computer_use.agent.middleware import KEEP_SCREENSHOTS, PRUNE_EVERY, prune_screenshots
from computer_use.agent.tools import image_blocks
from computer_use.agent.trajectory import Trajectory
from computer_use.storage import MAIN
from computer_use.storage.files import FileRunStore
from conftest import new_log, read_events
from computer_use.computers import ComputerError
from computer_use.desktop.control import (
    Approval,
    ApprovalFile,
    ControlFile,
    DesktopBusy,
    RunLock,
    hand_over,
    release_input,
)

IMAGE = {"type": "image", "base64": "iVBORw0KGgo=", "mime_type": "image/png"}


async def test_control_file_defaults_to_agent_and_round_trips(tmp_path):
    control = ControlFile(tmp_path / "control.json")
    assert control.read().owner == "agent"
    assert await control.wait_for_agent() is None
    control.write("user", "signing in")
    assert control.read().owner == "user"
    assert control.read().reason == "signing in"


def asked(id="c1", run="r1") -> Approval:
    return Approval(id, run, "left_click", "寄出週報", "003-confirm.png", 1.0)


def test_a_step_awaiting_approval_is_answered_once_by_its_own_id(tmp_path):
    approvals = ApprovalFile(tmp_path / "approval.json")
    assert approvals.read() is None and approvals.pending("r1") is None
    approvals.ask(asked())
    assert approvals.pending("r1") == asked()
    assert approvals.pending("r2") is None
    assert not approvals.decide("c2", "approve")
    assert approvals.decide("c1", "reject", "not now", "cli")
    assert not approvals.decide("c1", "approve")
    assert (approvals.read().decision, approvals.read().note, approvals.read().by) == ("reject", "not now", "cli")
    assert approvals.pending("r1") is None
    approvals.clear("c2")
    assert approvals.read() is not None
    approvals.clear("c1")
    assert approvals.read() is None


async def test_waiting_for_approval_ends_with_an_answer_a_takeover_or_a_rejection(tmp_path, fast_polls):
    approvals, control = ApprovalFile(tmp_path / "approval.json"), ControlFile(tmp_path / "control.json")
    approvals.ask(asked())
    waiting = asyncio.create_task(approvals.wait("c1", control))
    await asyncio.sleep(0.05)
    assert not waiting.done()
    approvals.decide("c1", "approve", by="web")
    assert (await waiting).decision == "approve"

    control.write("user", "taken over by user")
    assert await approvals.wait("c1", control) is None  # taking the desktop answers it too
    control.write("agent")
    approvals.clear("c1")
    assert (await approvals.wait("c1", control)).decision == "reject"


def test_one_run_has_the_desktop_at_a_time_and_says_which(tmp_path):
    first, second = RunLock(tmp_path / "run.lock"), RunLock(tmp_path / "run.lock")
    with first:
        first.name("20261007-120000")
        with pytest.raises(DesktopBusy) as busy, second:
            pass
        assert busy.value.run == "20261007-120000"
        assert second.holder() == {"run": "20261007-120000", "pid": os.getpid()}
    assert second.holder() is None
    with second:
        assert second.holder() == {"pid": os.getpid()}


def test_the_lock_file_of_a_run_that_crashed_does_not_keep_the_desktop_busy(tmp_path):
    lock = RunLock(tmp_path / "run.lock")
    lock.path.write_text(json.dumps({"run": "20261007-120000", "pid": 2**30}))  # no such process
    assert lock.holder() is None
    with lock:
        assert lock.holder() == {"pid": os.getpid()}


def test_prune_removes_the_oldest_screenshots_in_batches_so_the_prompt_prefix_rarely_changes():
    def conversation(screens):
        return [HumanMessage(content=[{"type": "text", "text": str(n)}, IMAGE]) for n in range(screens)]

    def kept(screens):
        return sum(bool(image_blocks(m)) for m in prune_screenshots(conversation(screens), keep=3, every=25))

    assert [kept(n) for n in (2, 3, 27, 28, 52, 53)] == [2, 3, 27, 3, 27, 3]
    # Between batches, a new turn leaves every earlier message as the previous call sent it.
    assert prune_screenshots(conversation(30), 3, 25)[:30] == prune_screenshots(conversation(31), 3, 25)[:30]
    screens = conversation(28)
    assert [bool(image_blocks(m)) for m in prune_screenshots(screens, 3, 25)] == [False] * 25 + [True] * 3
    assert all(image_blocks(m) for m in screens)


async def test_a_continued_conversation_reads_only_the_screenshots_its_next_call_keeps(tmp_path):
    """Loaded for a next turn, a conversation's pruned screenshots are replaced without reading their files, across
    runs and with tool results logged out of call order; its next model call then sends what it would have sent had
    every screenshot been read, now and after the turn adds its own screenshots."""
    store = FileRunStore(tmp_path)
    log = Trajectory(store, first := await store.create())
    log.start("Open Notepad", None, "openai:gpt-6-luna", "openai:gpt-6-luna")
    log.input(HumanMessage("Open Notepad"), "message", MAIN)
    calls = [{"id": f"call_{n}", "name": "computer_use", "args": {"task": str(n)}, "type": "tool_call"} for n in (1, 2)]
    log.input(AIMessage(content="Two tasks.", tool_calls=calls), "model", MAIN)
    for n in (2, 1):  # the second finishes first
        done = ToolMessage(content=[{"type": "text", "text": f"Task {n} done."}, IMAGE], tool_call_id=f"call_{n}")
        log.input(done, "result", MAIN)
    log = Trajectory(store, second := await store.create())
    log.start("Save it", first, "openai:gpt-6-luna", "openai:gpt-6-luna")
    for n in range(26):
        log.input(HumanMessage(content=[{"type": "text", "text": f"Screen {n}."}, IMAGE]), "screen", MAIN)
    everything = in_call_order(
        [m for run in (first, second) for m in await main_messages(store, run, await store.events(run))]
    )
    assert [m.tool_call_id for m in everything if isinstance(m, ToolMessage)] == ["call_1", "call_2"]
    read, get_file = [], store.get_file

    async def counted(run, name):
        read.append(name)
        return await get_file(run, name)

    store.get_file = counted
    loaded = await load_conversation(store, first)

    assert loaded == prune_screenshots(everything, KEEP_SCREENSHOTS, PRUNE_EVERY)
    assert len(read) == KEEP_SCREENSHOTS and sum(bool(image_blocks(m)) for m in loaded) == KEEP_SCREENSHOTS
    for added in range(1, 7):  # the turn's own screenshots, up to past the next batch
        turn = [HumanMessage(content=[IMAGE])] * added
        assert prune_screenshots(loaded + turn, KEEP_SCREENSHOTS, PRUNE_EVERY) == prune_screenshots(
            everything + turn, KEEP_SCREENSHOTS, PRUNE_EVERY
        )


@pytest.mark.parametrize("cause", ["user has control", "disconnected"])
async def test_nothing_reaches_the_computer_while_the_user_has_it_or_it_is_disconnected(cause, executor, control, computer):
    def block(blocked: bool) -> None:
        if cause == "disconnected":
            computer.connected = not blocked
        else:
            control.write("user" if blocked else "agent")

    block(True)
    for name, args in [("left_click", {"coordinate": [10, 10]}), ("screenshot", {})]:
        result = await executor.run(name, args)
        assert not result.ok and cause in result.text and result.frame is None
    block(False)
    assert (await executor.run("left_click", {"coordinate": [10, 10]})).ok
    assert computer.calls == [("click", (10, 10), "left", 1, [])]


async def test_an_action_decided_before_a_takeover_is_not_sent_once_control_is_back(executor, control, computer):
    await executor.observe("Current screen.")
    control.write("user")  # the user takes over while the model decides, and gives control back before it replies
    control.write("agent")

    result = await executor.run("left_click", {"coordinate": [10, 10]})
    assert not result.ok and "had control after your last screenshot" in result.text and result.frame is not None
    assert computer.calls == []
    assert (await executor.run("left_click", {"coordinate": [10, 10]})).ok  # decided again from that screen
    assert computer.calls == [("click", (10, 10), "left", 1, [])]


async def test_a_batch_stops_once_the_user_takes_control(executor, control, computer):
    press = computer.press

    async def press_then_take_over(combos):
        await press(combos)
        control.write("user")

    computer.press = press_then_take_over
    result = await executor.run_batch([("key", {"text": "ctrl+a"}), ("type", {"text": "x"})])
    assert not result.ok and result.frame is None
    assert result.text.startswith(
        "Stopped at action 2 of 2: Not executed: the user has control of the desktop.\n1. Pressed ctrl+a."
    )
    assert computer.calls == [("press", [["ctrl", "a"]])]


DRAG = {"start_coordinate": [10, 10], "coordinate": [200, 200]}


async def test_a_takeover_waits_for_the_action_in_flight_then_lets_go_of_what_is_held(executor, control, computer):
    dragging, dropped = asyncio.Event(), asyncio.Event()

    async def drag(path, modifiers):  # the button is down and the pointer moving until the test drops it
        dragging.set()
        await dropped.wait()
        computer.calls.append(("drag", list(path)))

    computer.drag = drag
    await executor.observe("Current screen.")
    action = asyncio.create_task(executor.run("left_click_drag", DRAG))
    await dragging.wait()
    takeover = asyncio.create_task(hand_over(control, computer, "user", "taken over by user"))
    await asyncio.sleep(0.05)  # it tries the control lock several times meanwhile
    assert not takeover.done() and control.read().owner == "agent" and computer.releases == 0
    dropped.set()

    assert (await takeover).owner == "user" and computer.releases == 1
    assert (await action).ok and computer.calls == [("drag", [(10, 10), (200, 200)])]


async def test_input_is_held_back_when_the_user_takes_over_during_the_screen_check(executor, control, computer):
    await executor.observe("Current screen.")
    screenshot = computer.screenshot

    async def taken_over_meanwhile():  # the screenshot the action is checked against, before it is sent
        control.write("user", "taken over by user")
        return await screenshot()

    computer.screenshot = taken_over_meanwhile
    result = await executor.run("key", {"text": "ctrl+s"})

    assert not result.ok and "user has control" in result.text and computer.calls == []


@pytest.mark.parametrize("ending", ["stopped", "failed"])
async def test_an_action_stopped_or_failed_partway_lets_go_of_keys_and_buttons(ending, executor, computer):
    dragging = asyncio.Event()

    async def drag(path, modifiers):  # the button is down: it stays down unless something lets go of it
        dragging.set()
        if ending == "failed":
            raise ComputerError("xdotool failed: exit code 1")
        await asyncio.Event().wait()

    computer.drag = drag
    await executor.observe("Current screen.")
    action = asyncio.create_task(executor.run("left_click_drag", DRAG))
    if ending == "stopped":
        await dragging.wait()
        action.cancel()
        with pytest.raises(asyncio.CancelledError):
            await action
    else:
        result = await action
        assert not result.ok and "xdotool failed" in result.text

    assert computer.releases == 1


async def test_a_handover_happens_even_when_the_desktop_cannot_be_reached(control, computer):
    async def unreachable():
        raise ComputerError("reading which keys are down failed: the display is gone")

    computer.release_all = unreachable
    assert (await hand_over(control, computer, "user", "taken over by user")).owner == "user"
    assert control.read().owner == "user"


async def test_held_input_is_let_go_of_only_while_its_owner_has_the_desktop(control, computer):
    await release_input(control, computer, "user")  # the agent has it: its input is not the user's to let go of
    control.write("user")
    await release_input(control, computer, "user")
    assert computer.releases == 1


async def test_waiting_for_the_connection_returns_how_long_it_was_down(executor, computer, fast_polls):
    assert await executor.wait_for_connection() is None
    computer.connected = False

    async def reconnect():
        await asyncio.sleep(0.2)
        computer.connected = True

    asyncio.create_task(reconnect())
    assert await executor.wait_for_connection() >= 0.2


async def test_the_screen_seen_is_the_last_full_screenshot_not_a_zoomed_crop(executor):
    observed = await executor.run("screenshot", {})
    zoomed = await executor.run("zoom", {"region": [0, 0, 320, 100]})
    assert executor.shown == observed.frame != zoomed.frame


def test_the_end_event_carries_the_tokens_and_cost_by_kind_in_all_and_by_agent(tmp_path):
    ends = []
    for computer_model in ("openai:gpt-6.1-sol", "openai:unpriced"):
        log = new_log(tmp_path)
        log.uses("openai:gpt-6-luna", MAIN)
        log.uses(computer_model, name="computer")
        log.model(AIMessage(content="saved", usage_metadata={  # the computer agent's
            "input_tokens": 1_000_000, "output_tokens": 50_000, "total_tokens": 1_050_000,
            "input_token_details": {"cache_read": 200_000, "cache_creation": 100_000},
            "output_token_details": {"reasoning": 40_000},
        }))
        log.model(AIMessage(content="It is saved.", usage_metadata={  # the main agent's
            "input_tokens": 100_000, "output_tokens": 10_000, "total_tokens": 110_000,
        }), MAIN)
        log.end("replied", "It is saved.", "replied")
        ends += [event for event in read_events(tmp_path / "runs" / log.run) if event["type"] in ("end", "model")]

    priced, unpriced = [event for event in ends if event["type"] == "end"]
    assert [event.get("model") for event in ends if event["type"] == "model"][:2] == [
        "openai:gpt-6.1-sol", "openai:gpt-6-luna"
    ]
    assert (priced["stop_reason"], priced["computer"], priced["summary"]) == ("replied", "replied", "It is saved.")
    assert priced["usage"] == {"input": 1_100_000, "cached": 200_000, "cache_write": 100_000, "output": 60_000,
                               "reasoning": 40_000}
    # gpt-6.1-sol: 700k plain x $2 + 200k cached x $0.10 + 100k written x $2.50 + 50k output x $10 per million;
    # gpt-6-luna: 100k plain x $0.10 + 10k output x $0.50 per million.
    assert priced["cost"] == pytest.approx({"input": 1.41, "cached": 0.02, "cache_write": 0.25, "output": 0.505})
    assert unpriced["cost"] is None
    # And by agent and model, in the order first used; one without a known price has no cost of its own.
    assert [(each["agent"], each["model"]) for each in priced["agents"]] == [
        ("computer", "openai:gpt-6.1-sol"), ("main", "openai:gpt-6-luna")
    ]
    assert priced["agents"][1]["usage"] == {"input": 100_000, "cached": 0, "cache_write": 0, "output": 10_000,
                                            "reasoning": 0}
    assert priced["agents"][0]["cost"] == pytest.approx({"input": 1.4, "cached": 0.02, "cache_write": 0.25, "output": 0.5})
    assert [each["cost"] is None for each in unpriced["agents"]] == [True, False]
