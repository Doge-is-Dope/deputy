import asyncio
import json
import threading

import pytest

from computer_use.config import Settings
from computer_use.files.local import LocalFileStore
from computer_use.adapters import build_stores
from computer_use.storage import ALL, FORMAT, TASK, TURN
from computer_use.storage.files import FileRunStore, FileRuns
from conftest import MemoryFileStore, file_runs, runs_dir


@pytest.fixture
async def stores(store_settings):
    """A store of each backend, as the runtime builds it, whose views the tests take: the local user's, or any
    user's."""
    store, _, _ = build_stores(store_settings)
    yield store
    await store.close()


@pytest.fixture
def store(stores):
    return stores.of("local")


def start(thread: str, goal: str = "open start", version: int = FORMAT, at: float | None = None) -> dict:
    """A start event; `at` fixes its time, which the store would otherwise set (two runs can start within a tick)."""
    return {"type": "start", "v": version, "kind": TURN, "thread": thread, "session": thread, "goal": goal,
            **({"time": at} if at else {})}


async def test_appends_keep_their_order_and_read_back_from_any_index(store):
    run = await store.create()
    assert await store.events(run) == []
    appended = [store.append(run, event) for event in (start(run), {"type": "note", "text": "hi"}, {"type": "end"})]
    assert await store.events(run) == appended and all("time" in event for event in appended)
    assert [event["type"] for event in await store.events(run, after=0)] == ["note", "end"]
    assert await store.events("nope") == []
    await store.flush(run)
    await store.flush("nope")


async def test_runs_are_unique_and_sort_by_when_they_started(store):
    first, second = await store.create(), await store.create()
    assert first != second and first < second and len(first) == 32


async def test_only_records_in_the_current_format_are_listed_and_a_conversation_is_its_runs_oldest_first(store):
    first, second, old = await store.create(), await store.create(), await store.create()
    store.append(first, start(first, at=1))
    store.append(second, start(first, "and notepad", at=2))
    store.append(old, start(old, version=3))
    listed = await store.runs(first)
    assert [(each.id, each.thread, each.goal) for each in listed] == [(first, first, "open start"), (second, first, "and notepad")]
    assert listed[0].ended is None and listed[0].title is None and listed[0].actions == 0
    assert await store.runs(old) == [] and [each.id for each in (await store.conversations()).items] == [first]


async def test_a_conversations_tasks_are_listed_with_its_runs_but_never_fold_into_it_nor_are_searched(store):
    turn, task, later = await store.create(), await store.create(), await store.create()
    store.append(turn, start(turn, at=1))
    store.append(task, start(turn, "Type the secret brief.", at=2) | {"kind": TASK})
    store.append(task, {"type": "title", "text": "Typing"})
    store.append(later, start(turn, "", at=3))
    listed = await store.runs(turn)
    assert [(each.id, each.kind) for each in listed] == [(turn, TURN), (task, TASK), (later, TURN)]
    (conversation,) = (await store.conversations()).items
    assert (conversation.goal, conversation.title, conversation.latest.id) == ("open start", None, later)
    assert await store.search("secret brief") == []


async def test_a_summary_reads_the_title_project_actions_and_end_off_the_events(store):
    run = await store.create()
    store.append(run, start(run) | {"project": "p1"})
    store.append(run, {"type": "title", "text": "Opening Start"})
    store.append(run, {"type": "action", "n": 1})
    store.append(run, {"type": "action", "agent": "main", "n": 1})
    store.append(run, {"type": "end", "stop_reason": "error"})
    (summary,) = await store.runs(run)
    assert (summary.title, summary.project, summary.actions, summary.failed) == ("Opening Start", "p1", 1, True)
    assert summary.ended is not None and summary.ended >= summary.started


async def test_files_are_kept_by_name_and_a_name_given_twice_replaces(store):
    run = await store.create()
    await store.put_file(run, "001-key.png", b"one")
    await store.put_file(run, "001-key.png", b"two")
    await store.put_file(run, "thumbs/160/001-key.png.webp", b"small")
    assert await store.get_file(run, "001-key.png") == b"two"
    assert await store.get_file(run, "thumbs/160/001-key.png.webp") == b"small"
    with pytest.raises(FileNotFoundError):
        await store.get_file(run, "002-key.png")


async def test_the_file_store_keeps_a_runs_files_beside_its_record(tmp_path):
    store = file_runs(tmp_path).of("local")
    run = await store.create()
    store.append(run, start(run))
    await store.put_file(run, "001-key.png", b"png")
    assert sorted(path.name for path in (runs_dir(tmp_path) / run).iterdir()) == [
        "001-key.png", "steps.jsonl",
    ]


async def test_a_run_store_keeps_its_files_in_the_files_store_it_is_given(tmp_path):
    files = MemoryFileStore()
    store = FileRunStore(tmp_path, files).of("alice")
    run = await store.create()
    store.append(run, start(run))
    await store.put_file(run, "001-key.png", b"png")
    assert files.kept == {f"users/alice/runs/{run}/001-key.png": b"png"}
    await store.delete(run)
    assert files.kept == {}


async def test_deleting_a_conversation_erases_its_runs_records_and_files(store):
    first, second, other = await store.create(), await store.create(), await store.create()
    store.append(first, start(first, at=1))
    store.append(second, start(first, at=2))
    store.append(other, start(other, at=3))
    await store.put_file(first, "001-key.png", b"png")
    await store.put_file(other, "001-key.png", b"kept")
    assert await store.delete(first) == [first, second]
    assert [each.id for each in (await store.conversations()).items] == [other] and await store.runs(first) == []
    assert await store.events(first) == [] and await store.events(second) == []
    assert await store.get_file(other, "001-key.png") == b"kept"
    with pytest.raises(FileNotFoundError):
        await store.get_file(first, "001-key.png")
    assert await store.delete(first) == [] and await store.delete("nope") == []


async def test_conversations_fold_their_runs_and_list_most_recently_active_first(store):
    first, second, third = await store.create(), await store.create(), await store.create()
    store.append(first, start(first, "open notepad", at=1) | {"project": "p1"})
    store.append(first, {"type": "title", "text": "Notepad"})
    store.append(second, start(second, "tidy up", at=2))
    store.append(third, start(first, "and save", at=3))
    store.append(third, {"type": "title", "text": "Notepad notes", "by": "user"})
    everything = (await store.conversations()).items
    assert [(each.id, each.title, each.goal, each.project, each.last, each.latest.id) for each in everything] == [
        (first, "Notepad notes", "open notepad", "p1", 3, third), (second, None, "tidy up", None, 2, second),
    ]
    assert [each.id for each in (await store.conversations(project="p1")).items] == [first]
    assert [each.id for each in (await store.conversations(project=None)).items] == [second]
    assert (await store.conversations(project="p2")).items == []


async def test_a_page_of_conversations_continues_from_the_one_before_by_its_cursor(store):
    threads = []
    for n in range(1, 8):
        run = await store.create()
        store.append(run, start(run, f"task {n}", at=n))
        threads.append(run)
    newest_first = threads[::-1]
    first = await store.conversations(limit=3)
    assert [each.id for each in first.items] == newest_first[:3] and first.next is not None
    second = await store.conversations(before=first.next, limit=3)
    assert [each.id for each in second.items] == newest_first[3:6] and second.next is not None
    third = await store.conversations(before=second.next, limit=3)
    assert [each.id for each in third.items] == newest_first[6:] and third.next is None
    # A conversation active since does not move the page: the cursor is a place, not an offset.
    run = await store.create()
    store.append(run, start(run, "task 8", at=8))
    assert [each.id for each in (await store.conversations(before=first.next, limit=3)).items] == newest_first[3:6]
    assert len((await store.conversations(limit=1000)).items) == 8 and (await store.conversations(limit=0)).next is not None
    with pytest.raises(ValueError):
        await store.conversations(before="not a cursor")
    with pytest.raises(ValueError):
        await store.conversations(before="eyJ4IjogMX0=")  # JSON, not a place


async def test_the_revision_moves_with_the_list_and_not_with_a_runs_other_events(store):
    seen = [await store.revision()]
    run = await store.create()
    seen.append(await store.revision())
    for event in (start(run), {"type": "title", "text": "Start"}, {"type": "project", "project": "p1"}, {"type": "end"}):
        store.append(run, event)
        seen.append(await store.revision())
    assert seen == sorted(seen) and len(set(seen)) == len(seen)
    store.append(run, {"type": "note", "text": "quiet"})
    assert await store.revision() == seen[-1]
    await store.delete(run)
    assert await store.revision() > seen[-1]


async def test_another_processs_appends_are_numbered_in_turn(stores, store_settings):
    other_store, _, _ = build_stores(store_settings)  # as another process on the same data, e.g. the page's server
    store, other = stores.of("local"), other_store.of("local")
    run = await store.create()
    store.append(run, start(run))
    await store.flush(run)  # what another process reads
    other.append(run, {"type": "title", "text": "By the server"})
    await other.flush(run)
    store.append(run, {"type": "end"})
    await store.flush(run)
    assert [event["type"] for event in await other.events(run)] == ["start", "title", "end"]
    assert [each.title for each in await store.runs(run)] == ["By the server"]
    await other_store.close()


async def test_the_file_store_leaves_out_a_line_cut_off_by_a_crash(tmp_path):
    store = file_runs(tmp_path).of("local")
    run = await store.create()
    store.append(run, start(run))
    with (runs_dir(tmp_path) / run / "steps.jsonl").open("a", encoding="utf-8") as file:
        file.write(json.dumps({"type": "note", "text": "cut off"}))
    assert [event["type"] for event in await store.events(run)] == ["start"]


async def projections(store, user: str = "local") -> tuple[list[dict], list[dict]]:
    """A user's run and conversation documents, in a fixed order."""
    runs = await store.db.runs.find({"user": user}, {"_id": 0}).sort("run").to_list()
    conversations = await store.db.conversations.find({"user": user}, {"_id": 0}).sort("thread").to_list()
    return runs, conversations


async def every_kind_of_run(runs) -> tuple[str, str, str]:
    """Appends runs that touch every projected field: a conversation of two runs, titled by the runtime and then the
    user, moved into a project; desktop and main agent actions; an end in error; a run in an old format."""
    first, second, other, old = [await runs.create() for _ in range(4)]
    runs.append(first, start(first, "open notepad", at=1) | {"project": "p1"})
    runs.append(first, {"type": "title", "text": "Notepad"})
    runs.append(first, {"type": "action", "n": 1})
    runs.append(first, {"type": "action", "agent": "main", "n": 1})
    runs.append(first, {"type": "end", "stop_reason": "reply"})
    runs.append(second, start(first, "and save", at=3))
    runs.append(second, {"type": "title", "text": "Notes", "by": "user"})
    runs.append(second, {"type": "title", "text": "Later by the runtime"})
    runs.append(first, {"type": "project", "project": "p2", "by": "user"})
    runs.append(other, start(other, "tidy up", at=2))
    runs.append(other, {"type": "end", "stop_reason": "error"})
    runs.append(old, start(old, version=3))
    for run in (first, second, other, old):
        await runs.flush(run)  # the tests read the documents
    return first, second, other


@pytest.fixture
async def mongo_store(tmp_path, mongo_url):
    store, _, _ = build_stores(Settings(_env_file=None, data_dir=tmp_path, database_url=mongo_url))
    yield store
    await store.close()


@pytest.mark.mongo
async def test_rebuilding_from_the_events_makes_the_documents_the_appends_made(mongo_store):
    store = mongo_store
    runs = store.of("local")
    await every_kind_of_run(runs)
    appended, revision = await projections(store), await runs.revision()
    assert [len(each) for each in appended] == [3, 2]
    assert await store.rebuild("local") == (3, 2)
    assert await projections(store) == appended and await runs.revision() > revision


@pytest.mark.mongo
async def test_rows_and_conversations_an_older_format_left_are_not_read(mongo_store):
    runs = mongo_store.of("local")
    run = await runs.create()
    runs.append(run, start(run, at=1))
    await runs.flush(run)
    # As an older format's server left them: no format of their own, and a row without the fields this one keeps.
    await mongo_store.db.runs.insert_one({"user": "local", "run": "old", "thread": "old", "goal": "old goal",
                                          "started": 0, "ended": None, "failed": False, "actions": 0})
    await mongo_store.db.conversations.insert_one({"user": "local", "thread": "old", "project": None, "title": None,
                                                   "goal": "old goal", "last": 2, "latest": "old"})
    assert [each.id for each in (await runs.conversations()).items] == [run]
    assert await runs.runs("old") == [] and await runs.search("old goal") == []


@pytest.mark.mongo
async def test_rebuilding_repairs_one_users_documents_and_leaves_the_others(mongo_store):
    store = mongo_store
    first, second, other = await every_kind_of_run(store.of("local"))
    await every_kind_of_run(store.of("bob"))
    right = await projections(store)
    # As a crash leaves them: a conversation never written, a count behind, documents of a run whose events are gone.
    await store.db.conversations.delete_one({"user": "local", "thread": other})
    await store.db.runs.update_one({"user": "local", "run": first}, {"$set": {"actions": 7}})
    await store.db.runs.insert_one({"user": "local", "run": "gone", "thread": "gone", "started": 0})
    await store.db.conversations.insert_one({"user": "local", "thread": "gone", "last": 0, "latest": "gone"})
    await store.db.runs.update_one({"user": "bob", "run": {"$exists": True}}, {"$set": {"goal": "bob's own"}})
    bobs = await projections(store, "bob")
    assert await store.users() == ["bob", "local"]
    await store.rebuild("local")
    assert await projections(store) == right and await projections(store, "bob") == bobs
    assert [each.id for each in (await store.of("local").conversations()).items] == [first, other]


@pytest.mark.mongo
def test_rebuilding_one_user_from_the_command_line(tmp_path, mongo_url, capsys):
    from computer_use.storage.rebuild import main

    settings = Settings(_env_file=None, database_url=mongo_url, data_dir=tmp_path)

    async def broken(user):
        store, _, _ = build_stores(settings)
        await every_kind_of_run(store.of(user))
        await store.db.conversations.delete_many({"user": user})
        await store.close()

    asyncio.run(broken("alice"))
    asyncio.run(broken("bob"))
    assert main(["--user", "alice"], settings) == 0
    assert capsys.readouterr().out == "alice: 3 runs, 2 conversations\n"

    async def listed(user):
        store, _, _ = build_stores(settings)
        try:
            return len((await store.of(user).conversations()).items)
        finally:
            await store.close()

    assert asyncio.run(listed("alice")) == 2 and asyncio.run(listed("bob")) == 0


def test_a_files_store_has_nothing_to_rebuild(tmp_path, capsys):
    from computer_use.storage.rebuild import main

    assert main([], Settings(_env_file=None, data_dir=tmp_path, database_url="")) == 0
    assert "nothing to rebuild" in capsys.readouterr().out


async def test_the_file_store_parses_records_off_the_event_loop(tmp_path, monkeypatch):
    store, parsed_on = file_runs(tmp_path).of("local"), set()
    parse = FileRuns._parse
    monkeypatch.setattr(FileRuns, "_parse", staticmethod(
        lambda text, after=-1: parsed_on.add(threading.get_ident()) or parse(text, after)))
    run = await store.create()
    store.append(run, start(run, goal="open paint"))
    assert await store.events(run) and (await store.conversations()).items and await store.search("paint")
    assert parsed_on and threading.get_ident() not in parsed_on


async def test_the_file_store_scans_once_for_the_lists_asked_for_at_once(tmp_path, monkeypatch):
    store, scans = file_runs(tmp_path).of("local"), []
    summarize = FileRuns._summarize
    monkeypatch.setattr(FileRuns, "_summarize", lambda self: scans.append(1) or summarize(self))
    run = await store.create()
    store.append(run, start(run) | {"project": "p1"})
    await asyncio.gather(*(store.conversations(project) for project in (ALL, None, "p1", "p2")))
    assert len(scans) == 1
    store.append(run, {"type": "title", "text": "Renamed"})
    assert (await store.conversations("p1")).items[0].title == "Renamed" and len(scans) == 2


@pytest.mark.mongo
async def test_a_failed_write_is_logged_the_runs_others_go_on_and_its_flush_raises_it_once(
    mongo_store, monkeypatch, caplog,
):
    from pymongo.asynchronous.collection import AsyncCollection
    from pymongo.errors import AutoReconnect

    insert = AsyncCollection.insert_one

    async def flaky(self, document, *args, **kwargs):
        if document.get("event", {}).get("text") == "lost":
            raise AutoReconnect("down")
        return await insert(self, document, *args, **kwargs)

    monkeypatch.setattr(AsyncCollection, "insert_one", flaky)
    runs = mongo_store.of("local")
    run, other = await runs.create(), await runs.create()
    for event in (start(run), {"type": "note", "text": "lost"}, {"type": "end"}):
        runs.append(run, event)  # never raises: the agents append from callbacks
    runs.append(other, start(other))
    with pytest.raises(AutoReconnect):
        await runs.flush(run)
    await runs.flush(run)  # told once
    assert "down" in caplog.text
    assert [event["type"] for event in await runs.events(run)] == ["start", "end"]
    assert [event["type"] for event in await runs.events(other)] == ["start"]


@pytest.mark.mongo
async def test_a_conversation_whose_runs_are_gone_leaves_the_pages_after_it(mongo_store):
    runs = mongo_store.of("local")
    threads = []
    for at in (1, 2, 4):
        thread = await runs.create()
        runs.append(thread, start(thread, at=at))
        await runs.flush(thread)
        threads.append(thread)
    # As a crash between a delete's steps leaves it: listed, with its runs gone.
    await mongo_store.db.conversations.insert_one(
        {"user": "local", "thread": "f" * 32, "project": None, "title": None, "goal": "gone", "last": 3, "latest": "f" * 32},
    )
    seen, before = [], None
    while True:
        page = await runs.conversations(before=before, limit=1)
        seen += [each.id for each in page.items]
        if (before := page.next) is None:
            break
    assert seen == threads[::-1]


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
    assert [(hit.conversation.id, hit.snippet) for hit in await store.search("NOTEPAD")] == [
        (second, "and then notepad"), (first, "Open Notepad"),
    ]
    assert [hit.conversation.id for hit in await store.search("notes.txt")] == [first]
    # By its title alone, with no snippet (a first message is among its words, so it has one).
    store.append(first, {"type": "title", "text": "Desktop jottings"})
    assert [(hit.conversation.id, hit.snippet) for hit in await store.search("jottings")] == [(first, None)]
    assert [hit.conversation.id for hit in await store.search("notepad", limit=1)] == [second]
    assert await store.search("記事本") == []


async def test_a_search_finds_a_conversation_once_by_its_latest_match_and_not_once_deleted(store):
    first, second = await store.create(), await store.create()
    store.append(first, start(first, "打開記事本", at=1))
    store.append(second, start(first, "再打開記事本存檔", at=2))
    assert [(hit.conversation.id, hit.snippet) for hit in await store.search("記事本")] == [(first, "再打開記事本存檔")]
    await store.delete(first)
    assert await store.search("記事本") == []


async def test_a_hits_snippet_is_the_words_around_the_match_on_one_line(store):
    run = await store.create()
    words = "a" * 30 + " the\n\nkey " + "b" * 100
    store.append(run, start(run, words))
    (hit,) = await store.search("key")
    assert hit.snippet == "…" + "a" * 14 + " the key " + "b" * 79 + "…"


async def test_a_users_view_reaches_none_of_another_users_runs(stores):
    """Every way of reading: through Bob's view, Alice's run is as missing as one that never was."""
    alice, bob = stores.of("alice"), stores.of("bob")
    assert stores.of("alice") is alice and alice.user == "alice"
    run = await alice.create()
    alice.append(run, start(run, "alice's notepad") | {"user": "alice"})
    await alice.put_file(run, "001-key.png", b"png")
    assert [each.id for each in (await alice.conversations()).items] == [run]
    assert [each.id for each in await alice.runs(run)] == [run] and [hit.conversation.id for hit in await alice.search("notepad")] == [run]

    assert (await bob.conversations()).items == [] and await bob.runs(run) == [] and await bob.search("notepad") == []
    assert await bob.events(run) == []
    with pytest.raises(FileNotFoundError):
        await bob.get_file(run, "001-key.png")
    assert await bob.delete(run) == [] and [each.id for each in await alice.runs(run)] == [run]
    assert await bob.revision() == 0 < await alice.revision()


async def test_a_store_takes_only_user_ids_as_views(stores):
    with pytest.raises(ValueError):
        stores.of("../alice")


@pytest.fixture(params=["local", "memory"])
def files(request, tmp_path):
    return LocalFileStore(tmp_path) if request.param == "local" else MemoryFileStore()


async def test_a_files_store_keeps_each_key_and_replaces_one_given_twice(files):
    await files.put("users/a/runs/r1/001-key.png", b"one")
    await files.put("users/a/runs/r1/001-key.png", b"two")
    await files.put("users/a/runs/r1/thumbs/160/001-key.png.webp", b"small")
    assert await files.get("users/a/runs/r1/001-key.png") == b"two"
    assert await files.get("users/a/runs/r1/thumbs/160/001-key.png.webp") == b"small"
    for missing in ("users/a/runs/r1/002-key.png", "users/a/runs/r1", "users/a/runs/r2/001-key.png"):
        with pytest.raises(FileNotFoundError):
            await files.get(missing)


async def test_a_files_store_erases_a_prefix_and_nothing_beside_it(files):
    for key in ("users/a/runs/r1/001-key.png", "users/a/runs/r1/thumbs/160/001-key.png.webp",
                "users/a/runs/r10/001-key.png", "users/b/runs/r1/001-key.png"):
        await files.put(key, b"png")
    await files.delete_prefix("users/a/runs/r1/")
    await files.delete_prefix("users/a/runs/gone/")
    with pytest.raises(FileNotFoundError):
        await files.get("users/a/runs/r1/001-key.png")
    with pytest.raises(FileNotFoundError):
        await files.get("users/a/runs/r1/thumbs/160/001-key.png.webp")
    assert await files.get("users/a/runs/r10/001-key.png") == await files.get("users/b/runs/r1/001-key.png") == b"png"


async def test_the_local_files_store_takes_no_key_out_of_its_folder(tmp_path):
    files = LocalFileStore(tmp_path / "data")
    for key in ("../outside.png", "/etc/passwd", "users/a/../../outside.png", ""):
        with pytest.raises(ValueError):
            await files.put(key, b"x")
    with pytest.raises(ValueError):
        await files.delete_prefix("users/a/runs/r1")  # only a folder, ending in "/"


@pytest.fixture
async def projects(store_settings):
    _, store, _ = build_stores(store_settings)
    yield store
    await store.close()


async def test_projects_are_each_users_own_and_a_name_names_one(projects):
    made = await projects.create("alice", "  客戶  報價 ")
    assert made.name == "客戶 報價" and await projects.create("alice", "客戶 報價") == made
    bobs = await projects.create("bob", "客戶 報價")
    assert bobs.id != made.id and await projects.get("bob", made.id) is None
    assert [each.id for each in await projects.list("alice")] == [made.id]


async def test_a_renamed_project_keeps_its_id_unless_the_name_is_taken(projects):
    first, second = await projects.create("local", "a"), await projects.create("local", "b")
    assert (await projects.rename("local", first.id, "c")).id == first.id
    with pytest.raises(ValueError):
        await projects.rename("local", first.id, "b")
    assert await projects.rename("local", "nope", "d") is None
    assert await projects.delete("local", second.id) and not await projects.delete("local", second.id)
    assert [each.name for each in await projects.list("local")] == ["c"]
    assert await projects.get("local", second.id) is None and await projects.rename("local", second.id, "e") is None


async def test_a_deleted_projects_name_is_free_again(projects):
    first = await projects.create("local", "a")
    await projects.delete("local", first.id)
    assert (await projects.create("local", "a")).id != first.id


async def test_a_project_store_takes_only_user_ids(projects):
    with pytest.raises(ValueError):
        await projects.create("../x", "a")


async def test_projects_are_kept_between_processes(projects, store_settings):
    made = await projects.create("local", "a")
    _, other, _ = build_stores(store_settings)
    assert await other.list("local") == [made]
    await other.close()
