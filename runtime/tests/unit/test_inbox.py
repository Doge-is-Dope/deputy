from computer_use.agent.inbox import SUBAGENT, Inbox
from computer_use.storage import MAIN
from conftest import new_log, read_events


def test_each_agent_reads_every_message_once_in_order():
    inbox = Inbox()
    first, second = inbox.put("and Italy?"), inbox.put("and Spain?")

    assert [message.text for message in inbox.take(SUBAGENT)] == ["and Italy?", "and Spain?"]
    assert inbox.take(SUBAGENT) == []
    assert inbox.take(MAIN) == [first, second]
    assert inbox.read(SUBAGENT) == [first, second] and inbox.pending() == []


def test_a_message_waits_until_an_agent_reads_it():
    inbox = Inbox()
    read = inbox.put("open notepad")
    inbox.take(SUBAGENT)
    waiting = inbox.put("in dark mode")

    assert inbox.pending() == [waiting]
    assert inbox.take(MAIN) == [read, waiting] and inbox.pending() == []


def test_a_message_is_logged_once_when_an_agent_first_reads_it(tmp_path):
    inbox = Inbox()
    inbox.log = new_log(tmp_path)
    message = inbox.put("and Italy?")

    inbox.take(SUBAGENT)
    inbox.take(MAIN)

    logged = [event for event in read_events(tmp_path / "runs" / inbox.log.run) if event["type"] == "message"]
    assert [(event["id"], event["text"]) for event in logged] == [(message.id, "and Italy?")]


def test_a_message_can_be_taken_back_until_an_agent_reads_it():
    inbox = Inbox()
    read, unread = inbox.put("open notepad"), inbox.put("in dark mode")
    inbox.take(SUBAGENT)
    late = inbox.put("never mind")

    assert not inbox.withdraw(read.id) and not inbox.withdraw("no such message")
    assert inbox.withdraw(late.id) and not inbox.withdraw(late.id)
    assert inbox.pending() == [] and inbox.take(MAIN) == [read, unread]


def test_an_ended_run_takes_no_more_and_hands_back_what_the_main_agent_did_not_read():
    inbox = Inbox()
    inbox.put("read by both")
    inbox.take(MAIN)
    only_the_desktop = inbox.put("read by the computer-use agent only")
    inbox.take(SUBAGENT)
    nobody = inbox.put("read by nobody")

    assert inbox.close() == [only_the_desktop, nobody]
    assert inbox.put("too late") is None
