import io
import json
import socket

import pytest

from computer_use_cli.client import Client

URL = "http://runtime.test"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """The tests answer every request themselves: none opens a socket."""

    def refuse(*args, **kwargs):
        raise AssertionError("a test opened a socket")

    monkeypatch.setattr(socket.socket, "connect", refuse)


def sse(*events: tuple) -> bytes:
    """A stream of server-sent events: (index, data) for a line of the record, (kind, data) for a named one."""
    out = [": keepalive\n\n"]
    for first, data in events:
        head = f"id: {first}\n" if isinstance(first, int) else f"event: {first}\n"
        out.append(f"{head}data: {json.dumps(data, ensure_ascii=False)}\n\n")
    return "".join(out).encode()


class Interrupted(io.BytesIO):
    """A stream that is cut by Ctrl-C after its first `lines` lines."""

    def __init__(self, data: bytes, lines: int):
        super().__init__(data)
        self.left = lines

    def __iter__(self):
        for line in io.BytesIO(self.getvalue()):
            if self.left == 0:
                raise KeyboardInterrupt
            self.left -= 1
            yield line


class Dropped(io.BytesIO):
    """A stream whose connection drops after its first `lines` lines."""

    def __init__(self, data: bytes, lines: int):
        super().__init__(data)
        self.left = lines

    def __iter__(self):
        for line in io.BytesIO(self.getvalue()):
            if self.left == 0:
                raise ConnectionResetError(54, "Connection reset by peer")
            self.left -= 1
            yield line


class FakeApi:
    """Stands in for the runtime's API: answers each (method, path) with what a test set, in order, and records
    every request it was sent."""

    def __init__(self):
        self.answers: dict[tuple[str, str], list] = {}
        self.requests: list[dict] = []

    def on(self, method: str, path: str, status: int = 200, json_body=None, raw: bytes | None = None, stream=None):
        body = raw if raw is not None else (json.dumps(json_body).encode() if json_body is not None else b"")
        self.answers.setdefault((method, path), []).append((status, stream or (lambda: io.BytesIO(body))))
        return self

    def sent(self, method: str, path: str) -> list[dict]:
        return [request for request in self.requests if (request["method"], request["path"]) == (method, path)]

    def __call__(self, method, url, body, headers):
        path = url.removeprefix(URL)
        self.requests.append({
            "method": method, "path": path, "headers": headers, "body": json.loads(body) if body else None,
        })
        queue = self.answers.get((method, path))
        if not queue:
            raise AssertionError(f"no answer for {method} {path}")
        status, make = queue.pop(0) if len(queue) > 1 else queue[0]
        return status, make()


@pytest.fixture
def api() -> FakeApi:
    return FakeApi()


@pytest.fixture
def client(api) -> Client:
    return Client(URL, send=api, token="")  # whatever CU_AUTH_TOKEN the machine has
