import http.client
import json
import urllib.request

import pytest

from computer_use_cli.client import ApiError, Client, files_of, parse_sse
from conftest import URL, Dropped, sse


def test_server_sent_events_are_read_with_their_index_and_kind_and_keepalives_said():
    stream = sse((0, {"type": "start"}), ("draft", {"text": "Hel"}), ("delta", {"text": "lo"}), (1, {"type": "end"}),
                 ("done", {})).splitlines(keepends=True)
    events = list(parse_sse(stream))
    assert [(event.kind, event.index) for event in events] == [
        ("keepalive", None), ("line", 0), ("draft", None), ("delta", None), ("line", 1), ("done", None)
    ]
    assert events[3].data == {"text": "lo"}


def test_a_refused_request_raises_with_the_apis_reason(api, client):
    api.on("POST", "/api/runs", 409, {"error": "another run is using the desktop", "reason": "desktop", "run": "r9"})
    with pytest.raises(ApiError) as raised:
        client.start("open start", computer=True)
    assert (raised.value.status, raised.value.body["run"], str(raised.value)) == (
        409, "r9", "another run is using the desktop"
    )


def test_a_message_sends_only_what_was_given(api, client):
    api.on("POST", "/api/runs", 201, {"id": "r1", "thread": "r1"})
    client.start("open start")
    client.start("open start", thread="r0", project="eval", max_steps=5, computer=True,
                 agents={"main": {"model": "openai:gpt-6-luna"}})
    first, second = (request["body"] for request in api.sent("POST", "/api/runs"))
    assert first == {"goal": "open start", "computer": False}
    assert second == {"goal": "open start", "computer": True, "thread": "r0", "project_name": "eval", "max_steps": 5,
                      "agents": {"main": {"model": "openai:gpt-6-luna"}}}


def test_events_after_an_index_ask_for_only_those(api, client):
    api.on("GET", "/api/runs/r1/events", raw=sse((3, {"type": "end"}), ("done", {})))
    assert [event.index for event in client.events("r1", after=2) if event.kind == "line"] == [3]
    assert api.requests[-1]["headers"]["Last-Event-ID"] == "2"


def test_the_files_of_a_run_are_those_its_events_name_once_each():
    events = [
        {"type": "input", "message": {"data": {"content": [{"type": "text"}, {"type": "image", "file": "000-a.png"}]}}},
        {"type": "action", "screenshot": "001-key.png", "message": {"data": {"content": [
            {"type": "image", "file": "001-key.png"}]}}},
        {"type": "confirm", "screenshot": None},
    ]
    assert files_of(events) == ["000-a.png", "001-key.png"]


def test_an_export_writes_the_record_and_the_files_it_names(api, client, tmp_path):
    record = [{"type": "start", "thread": "r1"}, {"type": "action", "screenshot": "001-key.png"},
              {"type": "confirm", "screenshot": "001-confirm.png"}]
    api.on("GET", "/api/runs/r1/events?full=1", raw=sse(*enumerate(record), ("done", {})))
    api.on("GET", "/api/runs/r1/files/001-key.png", raw=b"png bytes")
    api.on("GET", "/api/runs/r1/files/001-confirm.png", 404, {"error": "no such screenshot"})

    events, written = client.export("r1", tmp_path / "run")

    assert events == record and written == ["001-key.png"]
    lines = (tmp_path / "run" / "steps.jsonl").read_text().splitlines()
    assert [json.loads(line) for line in lines] == record
    assert (tmp_path / "run" / "001-key.png").read_bytes() == b"png bytes"


@pytest.mark.parametrize("dropped", [http.client.RemoteDisconnected("Remote end closed connection without response"),
                                     ConnectionResetError(54, "Connection reset by peer"), TimeoutError("timed out")])
def test_a_connection_dropped_before_any_answer_is_said_as_unreachable(monkeypatch, dropped):
    """As a server that is still starting behind a published port: it takes the connection, then drops it."""

    def urlopen(*args, **kwargs):
        raise dropped

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    with pytest.raises(ApiError) as raised:
        Client("http://127.0.0.1:8001").status()
    assert raised.value.status == 0 and "cannot reach the runtime" in str(raised.value)


def test_a_stream_dropped_midway_ends_as_cut_off_for_the_reader_to_ask_again(api, client):
    api.on("GET", "/api/runs/r1/events", stream=lambda: Dropped(sse((0, {"type": "start"}), (1, {"type": "note"})), 5))
    assert [(event.kind, event.index) for event in client.events("r1")] == [("keepalive", None), ("line", 0)]


def test_a_token_goes_with_every_request_and_none_without_one(api, monkeypatch):
    api.on("GET", "/api/status", json_body={})
    Client(URL, send=api, token="s3cret").status()
    monkeypatch.setenv("CU_AUTH_TOKEN", "from-env")
    Client(URL, send=api).status()
    monkeypatch.delenv("CU_AUTH_TOKEN")
    Client(URL, send=api).status()
    assert [request["headers"].get("Authorization") for request in api.sent("GET", "/api/status")] == [
        "Bearer s3cret", "Bearer from-env", None,
    ]
