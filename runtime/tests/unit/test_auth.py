"""Who may use the runtime: each request proves who sent it on its own, by a token or a sign-in proxy's header, or
needs nothing on the loopback address; the runtime keeps no session."""

import asyncio

import httpx
import pytest
from pydantic import SecretStr

import computer_use.serve as serve
from computer_use.auth.base import LOCAL, identity
from computer_use.serve import open_to_anyone, signed_in_link
from computer_use.server import create_app
from conftest import use_script
from langchain_core.messages import AIMessage


def client(settings, computer, address: str = "127.0.0.1") -> httpx.AsyncClient:
    app = create_app(settings, max_steps=10, computer=computer)
    transport = httpx.ASGITransport(app=app, client=(address, 50000))
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_with_no_sign_in_anyone_who_reaches_it_is_the_local_user(settings, computer):
    async with client(settings, computer) as api:
        assert (await api.get("/api/session")).json() == {"id": "local", "name": "Local user", "login": None}
        assert (await api.get("/api/runs")).status_code == 200


async def test_a_token_is_taken_as_a_bearer_or_from_the_cookie_signing_in_sets(settings, computer):
    settings = settings.model_copy(update={"auth": "token", "auth_token": SecretStr("s3cret")})
    async with client(settings, computer) as api:
        refused = await api.get("/api/runs")
        assert (refused.status_code, refused.json()["login"]) == (401, "token")
        assert (await api.get("/api/runs", headers={"Authorization": "Bearer wrong"})).status_code == 401
        assert (await api.get("/api/runs", headers={"Authorization": "Bearer s3cret"})).status_code == 200

        assert (await api.post("/api/login", json={"token": "wrong"})).status_code == 401
        signed_in = await api.post("/api/login", json={"token": "s3cret"})
        assert signed_in.status_code == 204 and "httponly" in signed_in.headers["set-cookie"].lower()
        assert (await api.get("/api/session")).json() == {"id": "local", "name": "Local user", "login": "token"}  # the cookie, alone

        await api.post("/api/logout")
        assert (await api.get("/api/session")).status_code == 401


async def test_a_sign_in_proxys_header_is_believed_only_from_the_proxy(settings, computer):
    settings = settings.model_copy(update={"auth": "proxy", "auth_proxies": "10.0.0.0/8"})
    alice = {"X-Forwarded-User": "alice@example.com"}
    async with client(settings, computer, "10.1.2.3") as api:
        answer = (await api.get("/api/session", headers=alice)).json()
        assert (answer["name"], answer["login"]) == ("alice@example.com", "proxy")
        refused = await api.get("/api/session")
        assert (refused.status_code, refused.json()["login"]) == (401, "proxy")
    async with client(settings, computer, "192.168.1.9") as api:  # anyone else could have set the header
        assert (await api.get("/api/session", headers=alice)).status_code == 401


def test_a_token_runtime_needs_its_token(settings, computer):
    with pytest.raises(ValueError, match="needs a token"):
        create_app(settings.model_copy(update={"auth": "token"}), max_steps=10, computer=computer)


def test_it_will_not_serve_another_address_with_no_sign_in_unless_told_to(settings):
    assert open_to_anyone(settings, "127.0.0.1") is None and open_to_anyone(settings, "localhost") is None
    assert "CU_AUTH" in open_to_anyone(settings, "0.0.0.0")
    told = type(settings)(_env_file=None, auth="none")  # CU_AUTH=none in so many words, as compose.yaml says it
    assert open_to_anyone(told, "0.0.0.0") is None
    token = settings.model_copy(update={"auth": "token", "auth_token": SecretStr("s3cret")})
    assert open_to_anyone(token, "0.0.0.0") is None


def test_a_token_runtime_makes_a_token_each_start_unless_one_is_kept_and_links_the_page_to_it(settings):
    settings = settings.model_copy(update={"auth": "token", "web_url": "http://localhost:5173/"})
    made, link = signed_in_link(settings)
    again, _ = signed_in_link(settings)
    token = made.auth_token.get_secret_value()
    assert link == f"http://localhost:5173/#token={token}" and len(token) >= 40
    assert again.auth_token.get_secret_value() != token
    kept, link = signed_in_link(settings.model_copy(update={"auth_token": SecretStr("s3cret")}))
    assert (kept.auth_token.get_secret_value(), link) == ("s3cret", "http://localhost:5173/#token=s3cret")


def test_an_id_is_safe_in_a_path_the_same_each_time_and_apart_for_each_way_of_signing_in():
    alice = identity("proxy", "alice@example.com")
    assert alice == identity("proxy", "alice@example.com") and alice.name == "alice@example.com"
    assert alice.id != identity("oidc", "alice@example.com").id
    for each in (alice, identity("proxy", "../../etc"), identity("proxy", "a/b c"), LOCAL):
        assert each.id.isalnum()


async def test_a_browser_may_change_things_only_from_the_pages_own_origin(settings, computer):
    async with client(settings, computer) as api:
        for site, status in (("same-site", 403), ("cross-site", 403), ("same-origin", 404), (None, 404)):
            headers = {"Sec-Fetch-Site": site} if site else {}  # none: the command line
            sent = await api.post("/api/runs/nope/stop", headers=headers)
            assert sent.status_code == status, site
        assert (await api.get("/api/runs", headers={"Sec-Fetch-Site": "cross-site"})).status_code == 200


def test_the_server_takes_the_connections_own_address_not_a_forwarded_one(settings, monkeypatch):
    configs = []

    class Server:
        def __init__(self, config):
            configs.append(config)

        async def serve(self):
            pass

    monkeypatch.setattr(serve, "get_settings", lambda: settings)
    monkeypatch.setattr(serve, "create_app", lambda *args: None)
    monkeypatch.setattr(serve.uvicorn, "Server", Server)
    assert serve.main(["--port", "0"]) == 0
    assert configs[0].proxy_headers is False


async def test_each_user_sees_and_changes_only_their_own_conversations(settings, computer, monkeypatch):
    settings = settings.model_copy(update={"auth": "proxy"})
    alice, bob = {"X-Forwarded-User": "alice@example.com"}, {"X-Forwarded-User": "bob@example.com"}
    use_script(monkeypatch, [], main=[AIMessage("Wrote the notes in Notepad.")])
    async with client(settings, computer) as api:
        created = (await api.post("/api/runs", json={"goal": "write the notes"}, headers=alice)).json()
        run, thread = created["id"], created["thread"]
        for _ in range(200):
            if not (await api.get("/api/status", headers=alice)).json()["running"]:
                break
            await asyncio.sleep(0.01)

        assert [each["id"] for each in (await api.get("/api/runs", headers=alice)).json()] == [run]
        assert (await api.get("/api/runs", headers=bob)).json() == []
        assert (await api.get("/api/search", params={"q": "notes"}, headers=bob)).json() == []
        for method, path, body in (
            ("GET", f"/api/runs/{run}/events", None),
            ("POST", f"/api/runs/{run}/stop", None),
            ("PATCH", f"/api/conversations/{thread}", {"title": "mine now"}),
            ("DELETE", f"/api/conversations/{thread}", None),
        ):
            assert (await api.request(method, path, json=body, headers=bob)).status_code == 404, path
        continued = await api.post("/api/runs", json={"goal": "and more", "thread": thread}, headers=bob)
        assert continued.status_code == 404

        assert (await api.delete(f"/api/conversations/{thread}", headers=alice)).status_code == 200
        assert (await api.post(f"/api/conversations/{thread}/restore", headers=bob)).status_code == 404
        assert (await api.post(f"/api/conversations/{thread}/restore", headers=alice)).status_code == 200
