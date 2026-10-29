import asyncio

import pytest
from langchain_core.messages import AIMessage

import computer_use.agent.computer_agent as computer_agent
import computer_use.desktop.executor
from computer_use.agent.inbox import Inbox
from computer_use.agent.review import Verdict
from computer_use.storage.files import FileRunStore
from conftest import run_turn
from conftest import read_events, run_dir
from computer_use.config import RunChoices
from computer_use.desktop.control import ApprovalFile, ControlFile
from computer_use.runner import Runner
from conftest import (
    computer_use_result,
    delegate,
    fixture_png,
    handed_back,
    logged,
    run_folder,
    sent_while_pressing,
    telling,
    tool_call,
    use_script,
)

pytestmark = pytest.mark.usefixtures("the_log_is_the_whole_record", "fast_polls")

SEND = {"coordinate": [1180, 92], "needs_confirmation": True, "consequence": "寄出週報給 bob@example.com"}


def asking(call_id="c1", **args) -> AIMessage:
    return AIMessage(content="Sending it.", tool_calls=[tool_call(call_id, "left_click", **(args or SEND))])


def raw_call(call_id, name, **args) -> AIMessage:
    """A turn whose call carries exactly these arguments, unlike tool_call, which adds the flag."""
    return AIMessage(content="", tool_calls=[{"id": call_id, "name": name, "args": args, "type": "tool_call"}])


async def the_user_answers(settings, computer, decision: str, note: str = "", times: int = 1) -> list:
    """The user answering each step the agent asks about, in turn; returns what had reached the computer by then."""
    approvals, answered, sent = ApprovalFile(settings.approval_path), [], []
    for _ in range(times):
        while (pending := approvals.read()) is None or pending.id in answered or pending.decision is not None:
            await asyncio.sleep(0.01)
        sent.append(list(computer.calls))
        answered.append(pending.id)
        assert approvals.decide(pending.id, decision, note, "web")
    return sent


async def test_a_step_runs_only_once_the_user_approves_it(settings, computer, monkeypatch):
    use_script(monkeypatch, [asking(), AIMessage(content="Sent it.")])

    user = asyncio.create_task(the_user_answers(settings, computer, "approve"))
    result = await asyncio.wait_for(run_turn(settings, "寄出週報", max_steps=10, computer=computer), timeout=20)

    assert await user == [[]]
    assert computer.calls == [("click", (1180, 92), "left", 1, [])]
    kinds = ("model", "confirm", "decision", "action")
    events = [event for event in read_events(run_dir(settings, result.run)) if event["type"] in kinds and "agent" not in event]
    assert [event["type"] for event in events] == ["model", "confirm", "decision", "action", "model"]
    confirm, decision = events[1], events[2]
    assert confirm["consequence"] == "寄出週報給 bob@example.com" and confirm["args"] == {"coordinate": [1180, 92]}
    assert (run_dir(settings, result.run) / confirm["screenshot"]).exists()
    assert (decision["outcome"], decision["by"]) == ("approved", "web")
    assert not settings.approval_path.exists()
    assert handed_back(result)["reply"] == "Sent it."
    assert "asked the user to approve: 寄出週報給 bob@example.com" in computer_use_result(result)["result"]


async def test_a_declined_step_never_runs_and_the_agent_hears_why(settings, computer, monkeypatch):
    use_script(monkeypatch, [asking(), AIMessage(content="I did not send it.")])

    user = asyncio.create_task(the_user_answers(settings, computer, "reject", "寄給 Alice，不是 Bob"))
    result = await asyncio.wait_for(run_turn(settings, "寄出週報", max_steps=10, computer=computer), timeout=20)
    await user

    assert computer.calls == []
    (action,) = logged(result, "action")
    assert action["status"] == "error" and "the user declined this step" in action["result"]
    assert "What the user said: 寄給 Alice，不是 Bob" in action["result"]
    (decision,) = logged(result, "decision")
    assert (decision["outcome"], decision["note"]) == ("declined", "寄給 Alice，不是 Bob")
    assert result.computer == "replied"


async def test_taking_the_desktop_answers_a_step_awaiting_approval(settings, computer, monkeypatch):
    use_script(monkeypatch, [asking(), AIMessage(content="The user sent it themselves.")])
    approvals, control = ApprovalFile(settings.approval_path), ControlFile(settings.control_path)

    async def user_does_it():
        while approvals.read() is None:
            await asyncio.sleep(0.01)
        control.write("user", "taken over by user")
        while not any(
            "The user has control" in event.get("text", "") for event in read_events(run_folder(settings))
        ):
            await asyncio.sleep(0.01)
        control.write("agent", "returned by user")

    user = asyncio.create_task(user_does_it())
    result = await asyncio.wait_for(run_turn(settings, "寄出週報", max_steps=10, computer=computer), timeout=20)
    await user

    assert computer.calls == []
    (decision,) = logged(result, "decision")
    (action,) = logged(result, "action")
    assert decision["outcome"] == "took_control" and "took the desktop" in action["result"]
    assert any("Control returned" in note["text"] for note in logged(result, "note"))


async def test_three_declined_steps_end_the_task(settings, computer, monkeypatch):
    use_script(monkeypatch, [asking("c1"), asking("c2"), asking("c3"), AIMessage(content="never reached")])

    user = asyncio.create_task(the_user_answers(settings, computer, "reject", times=3))
    result = await asyncio.wait_for(run_turn(settings, "寄出週報", max_steps=10, computer=computer), timeout=20)
    await user

    assert computer.calls == [] and result.computer == "declined"
    assert "the user declined 3 of its steps" in computer_use_result(result)["result"]
    assert handed_back(result)["reply"] == ""


async def test_a_batch_or_an_unexplained_step_is_refused_without_asking(settings, computer, monkeypatch):
    batch = [{"action": "left_click", "coordinate": [10, 10]}, {"action": "key", "text": "ctrl+enter"}]
    use_script(monkeypatch, [
        AIMessage(content="", tool_calls=[
            tool_call("b1", "computer_batch", actions=batch, needs_confirmation=True, consequence="送出表單"),
        ]),
        AIMessage(content="", tool_calls=[tool_call("k1", "key", text="ctrl+enter", needs_confirmation=True)]),
        AIMessage(content="I could not submit it."),
    ])

    result = await run_turn(settings, "submit the form", max_steps=10, computer=computer)

    assert computer.calls == [] and logged(result, "confirm") == []
    batched, unexplained = logged(result, "action")
    assert "cannot be part of a batch" in batched["result"]
    assert "say in consequence what this step will do" in unexplained["result"]


async def test_a_flag_in_quotes_still_asks_and_a_missing_one_sends_nothing(settings, computer, monkeypatch):
    use_script(monkeypatch, [
        raw_call("c0", "key", text="ctrl+enter"),
        raw_call("c1", "key", text="ctrl+enter", needs_confirmation="true", consequence="送出表單"),
        AIMessage(content="Submitted."),
    ])

    user = asyncio.create_task(the_user_answers(settings, computer, "approve"))
    result = await asyncio.wait_for(run_turn(settings, "submit", max_steps=10, computer=computer), timeout=20)
    await user

    missing, asked = logged(result, "action")
    assert missing["status"] == "error" and "needs_confirmation" in missing["result"]
    assert [decision["outcome"] for decision in logged(result, "decision")] == ["approved"]
    assert asked["status"] == "success" and computer.calls == [("press", [["ctrl", "enter"]])]


async def test_stopping_a_run_while_it_waits_for_approval_sends_nothing(settings, computer, monkeypatch):
    use_script(monkeypatch, [asking()])
    approvals = ApprovalFile(settings.approval_path)

    run = asyncio.create_task(run_turn(settings, "寄出週報", max_steps=10, computer=computer))
    while approvals.read() is None:
        await asyncio.sleep(0.01)
    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run

    assert computer.calls == [] and not settings.approval_path.exists()
    (end,) = [event for event in read_events(run_folder(settings)) if event["type"] == "end"]
    assert end["stop_reason"] == "cancelled"


async def test_a_step_approved_after_the_screen_changed_where_it_lands_is_asked_again(settings, computer, monkeypatch):
    monkeypatch.setattr(computer_use.desktop.executor, "MOVING_WATCH_SECONDS", 0)
    step = {"coordinate": [200, 90], "needs_confirmation": True, "consequence": "刪除 report.txt"}
    use_script(monkeypatch, [asking("c1", **step), asking("c2", **step), AIMessage(content="Deleted.")])
    approvals = ApprovalFile(settings.approval_path)

    async def user():
        while (first := approvals.read()) is None:
            await asyncio.sleep(0.01)
        computer.screen = lambda: fixture_png("Moved")  # something else drew where the click lands
        approvals.decide(first.id, "approve", "", "web")
        while (second := approvals.read()) is None or second.id == first.id:
            await asyncio.sleep(0.01)
        approvals.decide(second.id, "approve", "", "web")

    answering = asyncio.create_task(user())
    result = await asyncio.wait_for(run_turn(settings, "delete it", max_steps=10, computer=computer), timeout=20)
    await answering

    stale, done = logged(result, "action")
    assert stale["status"] == "error" and "the screen changed since your last screenshot" in stale["result"]
    assert done["status"] == "success" and computer.calls == [("click", (200, 90), "left", 1, [])]
    assert len(logged(result, "confirm")) == 2


async def test_an_approved_key_goes_out_though_the_screen_changed_while_it_waited(settings, computer, monkeypatch):
    # Live (2026-10-08): the taskbar's widget turned over and a tooltip came and went while the user decided, and the
    # approved Delete was held back each time, so the agent asked again and again.
    monkeypatch.setattr(computer_use.desktop.executor, "MOVING_WATCH_SECONDS", 0)
    use_script(monkeypatch, [AIMessage(content="", tool_calls=[tool_call("c1", "key", **DELETE)]),
                             AIMessage(content="Deleted it.")])
    approvals = ApprovalFile(settings.approval_path)

    async def user():
        while (pending := approvals.read()) is None:
            await asyncio.sleep(0.01)
        computer.screen = lambda: fixture_png("Moved")
        approvals.decide(pending.id, "approve", "", "web")

    answering = asyncio.create_task(user())
    result = await asyncio.wait_for(run_turn(settings, "delete it", max_steps=10, computer=computer), timeout=20)
    await answering

    assert computer.calls == [("press", [["delete"]])]
    assert len(logged(result, "confirm")) == 1


DELETE = {"text": "Delete", "needs_confirmation": True, "consequence": "把桌面上的 a.txt 刪到資源回收筒"}


def reviewing(monkeypatch, allow: bool) -> list[dict]:
    """Auto review answers every step with `allow`, by a stand-in for the reviewer; returns what it was asked."""
    asked = []

    async def review_step(model, context, step, png, sources):
        asked.append({"context": context, "step": step, "png": png, "sources": sources})
        return Verdict(allow, {"risk": "low", "authorization": "high", "decision": "allow" if allow else "ask",
                               "reason": "a.txt 是這段對話剛建立的", "seconds": 0.1, "usage": {}})

    monkeypatch.setattr(computer_agent, "review_step", review_step)
    return asked


AUTO = RunChoices(approvals="auto")


async def test_auto_review_counts_what_the_user_sends_during_the_task_as_their_words(settings, computer, monkeypatch):
    asked = reviewing(monkeypatch, allow=True)
    told = telling(monkeypatch)
    use_script(monkeypatch, [
        AIMessage(content="", tool_calls=[tool_call("c1", "key", text="win")]),
        AIMessage(content="", tool_calls=[tool_call("c2", "key", **DELETE)]),
        AIMessage(content="Deleted it."),
    ], main=[
        delegate("Tidy the desktop."),
        AIMessage(content="", tool_calls=[tool_call("m2", "tell_task", task_id="t1", message="Also delete a.txt on the desktop.")]),
        AIMessage("Done."),
    ])
    inbox = Inbox()
    sent_while_pressing(computer, inbox, "也刪掉桌面的 a.txt", until=lambda: bool(told))

    await asyncio.wait_for(
        run_turn(settings, "整理桌面", max_steps=10, computer=computer, inbox=inbox, choices=AUTO), 20
    )

    (question,) = asked
    assert "也刪掉桌面的 a.txt" in question["sources"]
    assert "What the main agent told it during this task, with the user's words:" in question["context"]
    assert "- 也刪掉桌面的 a.txt" in question["context"]


async def test_with_auto_review_on_a_step_it_lets_through_goes_ahead_without_the_user(settings, computer, monkeypatch):
    asked = reviewing(monkeypatch, allow=True)
    use_script(monkeypatch, [AIMessage(content="", tool_calls=[tool_call("c1", "key", **DELETE)]),
                             AIMessage(content="Deleted it.")])

    # Nobody answers: the run would wait for ever if it asked the user.
    result = await asyncio.wait_for(
        run_turn(settings, "建立 a.txt 再刪掉", max_steps=10, computer=computer, choices=AUTO), 20
    )

    assert computer.calls == [("press", [["delete"]])]
    kinds = ("confirm", "review", "decision", "action")
    events = [event for event in read_events(run_dir(settings, result.run)) if event["type"] in kinds and "agent" not in event]
    assert [event["type"] for event in events] == ["confirm", "review", "decision", "action"]
    review, decision = events[1], events[2]
    assert review["allow"] and review["reason"] == "a.txt 是這段對話剛建立的"
    assert (decision["outcome"], decision["by"], decision["note"]) == ("approved", "auto", "a.txt 是這段對話剛建立的")
    assert not settings.approval_path.exists()
    (question,) = asked
    assert "建立 a.txt 再刪掉" in question["context"] and "The actions of this task so far" in question["context"]
    assert question["step"].startswith('key {"text": "Delete"') and "刪到資源回收筒" in question["step"]
    assert question["sources"][0] == "建立 a.txt 再刪掉"
    assert "auto review let it through: 把桌面上的 a.txt 刪到資源回收筒" in computer_use_result(result)["result"]


async def test_a_step_auto_review_does_not_let_through_waits_for_the_user(settings, computer, monkeypatch):
    reviewing(monkeypatch, allow=False)
    use_script(monkeypatch, [asking(), AIMessage(content="Sent it.")])

    user = asyncio.create_task(the_user_answers(settings, computer, "approve"))
    result = await asyncio.wait_for(
        run_turn(settings, "寄出週報", max_steps=10, computer=computer, choices=AUTO), timeout=20
    )

    assert await user == [[]]
    review, decision = logged(result, "review")[0], logged(result, "decision")[0]
    assert not review["allow"] and (decision["outcome"], decision["by"]) == ("approved", "web")


async def test_auto_review_turned_off_while_a_run_works_asks_the_user_from_its_next_step(
    settings, computer, monkeypatch
):
    looking, turned_off = asyncio.Event(), asyncio.Event()

    async def review_step(model, context, step, png, sources):  # the user turns it off while it looks at the first
        looking.set()
        await turned_off.wait()
        return Verdict(True, {"risk": "low", "authorization": "high", "decision": "allow", "reason": "使用者要求的",
                              "seconds": 0.1, "usage": {}})

    monkeypatch.setattr(computer_agent, "review_step", review_step)
    use_script(monkeypatch, [AIMessage(content="", tool_calls=[tool_call("c1", "key", **DELETE)]), asking("c2"),
                             AIMessage(content="Sent it.")])
    runner = Runner(settings, computer, FileRunStore(settings.data_dir))
    run = await runner.start("刪掉 a.txt 再寄出週報", 10, choices=AUTO)
    task = runner.runs[run].task

    await asyncio.wait_for(looking.wait(), 20)
    assert runner.choose(run, "ask")
    turned_off.set()
    user = asyncio.create_task(the_user_answers(settings, computer, "approve"))
    await asyncio.wait_for(task, 20)
    await user

    events = list(read_events(run_folder(settings)))
    assert [e["auto_review"] for e in events if e["type"] == "confirm"] == [True, False]
    assert [e["by"] for e in events if e["type"] == "decision"] == ["auto", "web"]
    assert not runner.choose(run, "auto")


async def test_without_auto_review_for_the_run_every_step_waits_for_the_user(settings, computer, monkeypatch):
    asked = reviewing(monkeypatch, allow=True)
    use_script(monkeypatch, [asking("c1"), AIMessage(content="Sent it.")])
    approvals = ApprovalFile(settings.approval_path)

    async def user():
        while (pending := approvals.read()) is None:
            await asyncio.sleep(0.01)
        approvals.decide(pending.id, "approve", "", "web")

    answering = asyncio.create_task(user())
    result = await asyncio.wait_for(run_turn(settings, "寄出週報", max_steps=10, computer=computer), timeout=20)
    await answering

    assert [event["by"] for event in logged(result, "decision")] == ["web"]
    assert asked == []
    assert logged(result, "start")[0]["approvals"] == "ask"
