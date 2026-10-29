import httpx
import pytest
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from computer_use.memory import Memory, Source
from computer_use.memory.context import recall
from computer_use.memory.files import FileMemoryStore
from computer_use.memory.prompts import handed
from computer_use.memory.routes import memory_routes
from computer_use.memory.tools import memory_tools


def memory(id: str = "m1", user: str = "local", project: str | None = None, at: float = 1.0) -> Memory:
    return Memory(id, user, project, "用內網查報表", "Google 上的是舊版", "查公司報表時", Source("t1", "r1", "steer"),
                  at, at)


async def test_a_memory_is_kept_as_written_and_listed_oldest_first(tmp_path):
    store = FileMemoryStore(tmp_path)
    await store.save(memory("m2", at=2.0))
    await store.save(written := memory("m1", project="p1", at=1.0))
    assert [each.id for each in await store.list("local")] == ["m1", "m2"]
    assert await FileMemoryStore(tmp_path).get("local", "m1") == written
    assert (tmp_path / "users/local/memory/m1.md").read_text().endswith("---\n用內網查報表\n")


async def test_editing_forgetting_and_counting_uses(tmp_path):
    store = FileMemoryStore(tmp_path)
    await store.save(memory())
    changed = await store.update("local", "m1", text="改用 VPN", uses="9")
    assert changed.text == "改用 VPN" and changed.uses == 0 and changed.updated > changed.created
    await store.used("local", ["m1", "gone"])
    assert (await store.get("local", "m1")).uses == 1
    assert await store.update("local", "gone", text="x") is None
    assert await store.delete("local", "m1") and not await store.delete("local", "m1")
    await store.save(memory("a"))
    await store.save(memory("b"))
    assert await store.reset("local") == 2 and await store.list("local") == []


async def test_memories_are_each_users_own_and_names_cannot_leave_their_folder(tmp_path):
    store = FileMemoryStore(tmp_path)
    await store.save(memory(user="alice"))
    assert await store.list("bob") == [] and await store.get("bob", "m1") is None
    assert await store.get("alice", "../m1") is None and not await store.delete("alice", "../../x")
    with pytest.raises(ValueError):
        await store.list("../alice")
    with pytest.raises(ValueError):
        await store.save(memory(id="../x"))


async def test_remember_writes_a_rule_and_replaces_one_in_place(tmp_path):
    store = FileMemoryStore(tmp_path)
    remember, forget = memory_tools(store, "local", "p1", "t1", "r1")
    args = {"rule": " 用 內網 ", "why": "舊版", "applies": "報表", "scope": "project", "learned_from": "decline"}
    reply = await remember.ainvoke(args)
    (saved,) = await store.list("local")
    assert reply == f"Remembered as {saved.id}."
    assert (saved.text, saved.project, saved.source) == ("用 內網", "p1", Source("t1", "r1", "decline"))
    await remember.ainvoke(args | {"rule": "用 VPN", "scope": "personal", "replaces": saved.id})
    (replaced,) = await store.list("local")
    assert (replaced.id, replaced.created, replaced.text, replaced.project) == (saved.id, saved.created, "用 VPN", None)
    assert "no rule nope" in await remember.ainvoke(args | {"replaces": "nope"})
    assert await forget.ainvoke({"id": saved.id}) == f"Forgot {saved.id}." and await store.list("local") == []


async def test_a_rule_for_the_project_needs_a_conversation_in_one(tmp_path):
    store = FileMemoryStore(tmp_path)
    remember, _ = memory_tools(store, "local", None, "t1", "r1")
    args = {"rule": "x", "why": "y", "applies": "z", "scope": "project", "learned_from": "said"}
    assert (await remember.ainvoke(args)).startswith("Not remembered") and await store.list("local") == []


async def test_a_run_recalls_the_users_own_rules_and_its_projects_only(tmp_path):
    store = FileMemoryStore(tmp_path)
    for each in (memory("own", at=1), memory("mine", project="p1", at=2), memory("other", project="p2", at=3)):
        await store.save(each)
    recalled = await recall(store, "local", "p1")
    assert [each.id for each in recalled.memories] == ["own", "mine"]
    assert "[mine] 用內網查報表" in recalled.prompt() and "[other]" not in recalled.prompt()
    assert [each.id for each in await recalled.use(["other", "mine"])] == ["mine"]
    assert (await store.get("local", "mine")).uses == 1 and (await store.get("local", "other")).uses == 0
    assert "用內網查報表 (why: Google 上的是舊版" in handed(recalled.chosen(["own"]))
    assert handed(recalled.chosen(["other"])) == "" and (await recall(store, "bob", None)).prompt() == ""


@pytest.fixture
async def client(tmp_path):
    store = FileMemoryStore(tmp_path)
    await store.save(memory("m1"))
    await store.save(memory("b1", user="bob"))

    async def error(request, exc: HTTPException):
        return JSONResponse({"error": exc.detail}, exc.status_code)

    app = Starlette(routes=memory_routes(store, lambda request: request.headers.get("x-user", "local")),
                    exception_handlers={HTTPException: error})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def test_the_page_lists_edits_forgets_and_puts_back_a_users_memories(client):
    (listed,) = (await client.get("/api/memory")).json()
    assert listed["id"] == "m1" and listed["source"]["kind"] == "steer"
    changed = await client.patch("/api/memory/m1", json={"text": "  改用 VPN ", "uses": 9})
    assert changed.json()["text"] == "改用 VPN" and changed.json()["uses"] == 0
    assert (await client.patch("/api/memory/m1", json={"text": " "})).status_code == 400
    assert (await client.patch("/api/memory/b1", json={"text": "x"})).status_code == 404
    kept = changed.json()
    assert (await client.delete("/api/memory/m1")).status_code == 200
    assert (await client.put("/api/memory/m1", json=kept | {"user": "bob"})).status_code == 201
    assert (await client.get("/api/memory")).json() == [kept]
    assert (await client.put("/api/memory/m2", json={"text": "x"})).status_code == 400
    assert (await client.delete("/api/memory")).json() == {"deleted": 1}
    assert [each["id"] for each in (await client.get("/api/memory", headers={"x-user": "bob"})).json()] == ["b1"]
