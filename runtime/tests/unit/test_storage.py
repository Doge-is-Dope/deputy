"""Every run store keeps the record the same way: the contract FileRunStore and MemoryRunStore both meet."""

import json

import pytest

from computer_use.storage import FORMAT
from computer_use.storage.files import FileRunStore
from conftest import MemoryRunStore


@pytest.fixture(params=["files", "memory"])
def store(request, tmp_path):
    return FileRunStore(tmp_path) if request.param == "files" else MemoryRunStore()


def start(thread: str, goal: str = "open start", version: int = FORMAT, at: float | None = None) -> dict:
    """A start event; `at` fixes its time, which the store would otherwise set (two runs can start within a tick)."""
    return {"type": "start", "v": version, "thread": thread, "goal": goal, **({"time": at} if at else {})}


async def test_appends_are_numbered_in_order_and_read_back_from_any_index(store):
    run = await store.create()
    assert await store.events(run) == [] and store.count(run) == 0
    indexes = [store.append(run, event)[0] for event in (start(run), {"type": "note", "text": "hi"}, {"type": "end"})]
    assert indexes == [0, 1, 2] and store.count(run) == 3
    events = await store.events(run)
    assert [event["type"] for event in events] == ["start", "note", "end"] and all("time" in event for event in events)
    assert [event["type"] for event in await store.events(run, after=0)] == ["note", "end"]
    assert await store.events("nope") == [] and store.count("nope") == 0


async def test_runs_are_unique_and_sort_by_when_they_started(store):
    first, second = await store.create(), await store.create()
    assert first != second and first < second


async def test_only_records_in_the_current_format_are_listed_and_a_conversation_is_its_runs_oldest_first(store):
    first, second, old = await store.create(), await store.create(), await store.create()
    store.append(first, start(first, at=1))
    store.append(second, start(first, "and notepad", at=2))
    store.append(old, start(old, version=3))
    listed = await store.summaries()
    assert [(each.id, each.thread, each.goal) for each in listed] == [(second, first, "and notepad"), (first, first, "open start")]
    assert listed[0].ended is None and listed[0].title is None and listed[0].actions == 0
    assert await store.conversation(first) == [first, second] and await store.conversation(old) == []


async def test_a_summary_reads_the_title_project_actions_and_end_off_the_events(store):
    run = await store.create()
    store.append(run, start(run) | {"project": "eval"})
    store.append(run, {"type": "title", "text": "Opening Start"})
    store.append(run, {"type": "action", "n": 1})
    store.append(run, {"type": "action", "agent": "main", "n": 1})
    store.append(run, {"type": "end", "stop_reason": "error"})
    (summary,) = await store.summaries()
    assert (summary.title, summary.project, summary.actions, summary.failed) == ("Opening Start", "eval", 1, True)
    assert summary.ended is not None and summary.ended >= summary.started


async def test_files_are_kept_by_name_and_a_name_given_twice_replaces(store):
    run = await store.create()
    assert not store.has_file(run, "001-key.png")
    store.put_file(run, "001-key.png", b"one")
    store.put_file(run, "001-key.png", b"two")
    assert store.has_file(run, "001-key.png") and await store.get_file(run, "001-key.png") == b"two"
    with pytest.raises(FileNotFoundError):
        await store.get_file(run, "002-key.png")


async def test_deleting_a_conversation_takes_its_runs_out_of_the_list_and_restoring_brings_them_back(store):
    first, second = await store.create(), await store.create()
    store.append(first, start(first, at=1))
    store.append(second, start(first, at=2))
    assert await store.delete(first) == [first, second]
    assert await store.summaries() == [] and await store.conversation(first) == []
    assert await store.conversation(first, deleted=True) == [first, second]
    assert await store.delete(first) == [] and await store.restore("nope") == []
    assert await store.restore(first) == [first, second]
    assert [each.id for each in await store.summaries()] == [second, first]


async def test_the_revision_moves_with_the_list_and_not_with_a_runs_other_events(store):
    seen = [await store.revision()]
    run = await store.create()
    seen.append(await store.revision())
    for event in (start(run), {"type": "title", "text": "Start"}, {"type": "project", "name": "eval"}, {"type": "end"}):
        store.append(run, event)
        seen.append(await store.revision())
    assert seen == sorted(seen) and len(set(seen)) == len(seen)
    store.append(run, {"type": "note", "text": "quiet"})
    assert await store.revision() == seen[-1]
    await store.delete(run)
    assert await store.revision() > seen[-1]


async def test_the_file_store_leaves_out_a_line_cut_off_by_a_crash_and_sees_another_processs_appends(tmp_path):
    store, other = FileRunStore(tmp_path), FileRunStore(tmp_path)
    run = await store.create()
    store.append(run, start(run))
    other.append(run, {"type": "title", "text": "By the server"})  # as another process, e.g. the server naming it
    assert store.count(run) == 2 and store.append(run, {"type": "end"})[0] == 2
    with (tmp_path / "runs" / run / "steps.jsonl").open("a", encoding="utf-8") as file:
        file.write(json.dumps({"type": "note", "text": "cut off"}))
    assert [event["type"] for event in await store.events(run)] == ["start", "title", "end"]
    assert store.count(run) == 3


async def test_a_search_finds_conversations_by_what_the_user_and_the_main_agent_said(store):
    first, second, third = await store.create(), await store.create(), await store.create()
    store.append(first, start(first, "Open Notepad", at=1))
    store.append(first, {"type": "model", "agent": "main", "text": "Saved notes.txt on the desktop.", "tool_calls": []})
    store.append(second, start(second, "open the calculator", at=2))
    store.append(second, {"type": "message", "id": "m1", "text": "and then notepad"})
    store.append(third, start(third, "tidy up", at=3))
    # Not what the user and the main agent said: a subagent's words and a tool's result.
    store.append(third, {"type": "model", "text": "notepad is open", "tool_calls": []})
    store.append(third, {"type": "action", "tool": "computer", "result": "notepad", "n": 1})
    assert [(hit.thread, hit.snippet) for hit in await store.search("NOTEPAD", "local")] == [
        (second, "and then notepad"), (first, "Open Notepad"),
    ]
    assert [hit.thread for hit in await store.search("notes.txt", "local")] == [first]
    assert [hit.thread for hit in await store.search("notepad", "local", limit=1)] == [second]
    assert await store.search("記事本", "local") == []


async def test_a_search_finds_a_conversation_once_by_its_latest_match_and_not_once_deleted(store):
    first, second = await store.create(), await store.create()
    store.append(first, start(first, "打開記事本", at=1))
    store.append(second, start(first, "再打開記事本存檔", at=2))
    assert [(hit.thread, hit.snippet) for hit in await store.search("記事本", "local")] == [(first, "再打開記事本存檔")]
    await store.delete(first)
    assert await store.search("記事本", "local") == []


async def test_a_hits_snippet_is_the_words_around_the_match_on_one_line(store):
    run = await store.create()
    words = "a" * 30 + " the\n\nkey " + "b" * 100
    store.append(run, start(run, words))
    (hit,) = await store.search("key", "local")
    assert hit.snippet == "…" + "a" * 14 + " the key " + "b" * 79 + "…"


async def test_a_conversation_and_its_search_are_its_users_alone(store):
    alices, bobs, old = await store.create(), await store.create(), await store.create()
    store.append(alices, start(alices, "alice's notepad", at=1) | {"user": "alice"})
    store.append(bobs, start(bobs, "bob's notepad", at=2) | {"user": "bob"})
    store.append(old, start(old, "an old notepad", at=3))  # from before runs said whose: the local user's
    assert {each.id: each.user for each in await store.summaries()} == {alices: "alice", bobs: "bob", old: "local"}
    assert await store.conversation(alices, user="alice") == [alices]
    assert await store.conversation(alices, user="bob") == []
    assert [hit.thread for hit in await store.search("notepad", "bob")] == [bobs]
    assert [hit.thread for hit in await store.search("notepad", "local")] == [old]
    await store.delete(alices)
    assert await store.conversation(alices, deleted=True, user="bob") == []
    assert await store.conversation(alices, deleted=True, user="alice") == [alices]
