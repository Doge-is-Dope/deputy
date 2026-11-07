"""The runtime's HTTP API from outside it: what the command line and the eval reach a runtime through.

Only the API and its event format are known here, nothing of the runtime's code, files or folders. The standard
library is enough, so any Python can run it."""

import http.client
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

DEFAULT_URL = "http://127.0.0.1:8000"
# A stream sends a keepalive every 15 s, so a read that waits this long means the server is gone.
READ_SECONDS = 60
# How often a session in progress is looked at for its next log, while none of its logs streams.
POLL_SECONDS = 0.5


class ApiError(RuntimeError):
    """The API refused a request (its status and JSON body), or could not be reached (status 0)."""

    def __init__(self, status: int, body: dict | None, message: str):
        super().__init__(message)
        self.status = status
        self.body = body or {}


@dataclass(frozen=True)
class Event:
    """One server-sent event: a line of the run's record ("line", with its index), "draft", "delta", "done", or
    "keepalive", which the server sends while nothing happens, so a reader can check the time."""

    kind: str
    data: dict
    index: int | None = None


# send(method, url, body, headers) -> (status, response stream). Tests pass their own, so they open no sockets.
Send = Callable[[str, str, bytes | None, dict[str, str]], tuple[int, BinaryIO]]


def urllib_send(method: str, url: str, body: bytes | None, headers: dict[str, str]) -> tuple[int, BinaryIO]:
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        response = urllib.request.urlopen(request, timeout=READ_SECONDS)
    except urllib.error.HTTPError as error:  # a response all the same: its body says why
        return error.code, error
    except (urllib.error.URLError, http.client.HTTPException, OSError) as error:  # refused, reset, timed out
        raise ApiError(0, None, f"cannot reach the runtime at {url}: {getattr(error, 'reason', None) or error}") from None
    return response.status, response


def parse_sse(lines: Iterable[bytes]) -> Iterator[Event]:
    """Server-sent events from the lines of a stream; a comment is a keepalive."""
    kind, index, data = None, None, []
    for raw in lines:
        line = raw.decode("utf-8").rstrip("\r\n")
        if not line:
            if data:
                yield Event(kind or "line", json.loads("\n".join(data)), index)
            kind, index, data = None, None, []
        elif line.startswith(":"):
            yield Event("keepalive", {})
        else:
            field, _, value = line.partition(":")
            value = value.removeprefix(" ")
            if field == "event":
                kind = value
            elif field == "id":
                index = int(value)
            elif field == "data":
                data.append(value)


def files_of(events: Iterable[dict]) -> list[str]:
    """The files a run's events name, in the order first named: screenshots of actions and approvals, and the
    images in recorded messages."""
    names: list[str] = []
    for event in events:
        found = [event.get("screenshot")]
        content = event.get("message", {}).get("data", {}).get("content")
        if isinstance(content, list):
            found += [block.get("file") for block in content if isinstance(block, dict)]
        for name in found:
            if isinstance(name, str) and name not in names:
                names.append(name)
    return names


class Client:
    def __init__(self, url: str | None = None, send: Send = urllib_send, token: str | None = None):
        self.url = (url or os.environ.get("CU_API_URL") or DEFAULT_URL).rstrip("/")
        self._send = send
        # A runtime that takes a token (CU_AUTH=token) is sent it with every request, from the variable it reads too.
        self.token = token if token is not None else os.environ.get("CU_AUTH_TOKEN") or None

    def _open(self, method: str, path: str, body: dict | None = None, headers: dict[str, str] | None = None):
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        sent = ({"Content-Type": "application/json"} if data is not None else {}) | (headers or {})
        if self.token:
            sent["Authorization"] = f"Bearer {self.token}"
        status, stream = self._send(method, self.url + path, data, sent)
        if status >= 400:
            text = stream.read()
            stream.close()
            try:
                answer = json.loads(text)
            except ValueError:
                answer = None
            answer = answer if isinstance(answer, dict) else None
            raise ApiError(status, answer, (answer or {}).get("error") or f"HTTP {status}")
        return stream

    def _json(self, method: str, path: str, body: dict | None = None):
        stream = self._open(method, path, body)
        try:
            text = stream.read()
        finally:
            stream.close()
        return json.loads(text) if text else None

    def _bytes(self, path: str) -> bytes:
        stream = self._open("GET", path)
        try:
            return stream.read()
        finally:
            stream.close()

    def status(self) -> dict:
        return self._json("GET", "/api/status")

    def conversations(self, limit: int) -> list[dict]:
        """The most recently active conversations, `limit` at most, each with its latest run ("latest")."""
        return self._json("GET", f"/api/conversations?limit={limit}")["items"]

    def start(
        self, goal: str, *, thread: str | None = None, project: str | None = None, max_steps: int | None = None,
        computer: bool = False, agents: dict[str, dict[str, str]] | None = None,
    ) -> dict:
        """Send a message: a new run ({"id", "thread"}), or one handed to its conversation's run in progress (with
        "message"). `computer` sends it to the desktop; `agents` chooses each agent's model and effort; `project` names
        the project a new conversation is begun in, which the runtime makes if there is none by that name."""
        body = {"goal": goal, "computer": computer}
        for key, value in (("thread", thread), ("project_name", project), ("max_steps", max_steps), ("agents", agents)):
            if value is not None:
                body[key] = value
        return self._json("POST", "/api/runs", body)

    def events(self, run: str, after: int = -1, full: bool = False) -> Iterator[Event]:
        """The run's events after index `after`, as they come, until it ends ("done"); `full` keeps the model messages
        the stream otherwise leaves out. A stream that ends without "done" was cut off: ask again from the last index
        seen."""
        headers = {"Last-Event-ID": str(after)} if after >= 0 else None
        stream = self._open("GET", f"/api/runs/{_quoted(run)}/events{'?full=1' if full else ''}", headers=headers)
        try:
            for event in parse_sse(stream):
                yield event
                if event.kind == "done":
                    return
        except (http.client.HTTPException, OSError):  # dropped: as cut off, so the caller asks again
            return
        finally:
            stream.close()

    def record(self, run: str) -> list[dict]:
        """A run's events so far, as its record keeps them."""
        return [event.data for event in self.events(run, full=True) if event.kind == "line"]

    def start_of(self, run: str) -> dict:
        """A run's first event, which says its conversation and message, without waiting for it to end."""
        events = self.events(run)
        try:
            return next(event.data for event in events if event.kind == "line")
        finally:
            events.close()

    def runs(self, thread: str) -> list[dict]:
        """A conversation's logs, oldest first: its turns' and its tasks', each with its session."""
        return self._json("GET", f"/api/conversations/{_quoted(thread)}/runs")

    def stop(self, thread: str) -> None:
        """Stop the conversation's session in progress: the main agent's turn and every task."""
        self._json("POST", f"/api/conversations/{_quoted(thread)}/stop", {})

    def stop_run(self, run: str) -> None:
        """Stop one log in progress: an agent's task (the others and the main agent go on), or the main agent's turn
        (its reply; the tasks go on). ApiError 409 when it is not in progress."""
        self._json("POST", f"/api/runs/{_quoted(run)}/stop", {})

    def control(self, owner: str) -> dict:
        """Give the desktop to "user" or "agent"."""
        return self._json("POST", "/api/control", {"owner": owner, "by": "cli"})

    def answer(self, id: str, decision: str, note: str = "", by: str = "cli") -> dict:
        """Answer the step awaiting approval: "approve", or "reject" with an optional note."""
        return self._json("POST", "/api/approval", {"id": id, "decision": decision, "message": note, "by": by})

    def screen(self) -> bytes:
        """The desktop's screen now, as a PNG."""
        return self._bytes("/api/screen")

    def file(self, run: str, name: str) -> bytes:
        return self._bytes(f"/api/runs/{_quoted(run)}/files/{_quoted(name)}")

    def export(self, run: str, folder: Path) -> tuple[list[dict], list[str]]:
        """Write a run's record and its files to `folder`, as steps.jsonl beside its screenshots: its events and the
        names of the files written. A file the run names but the runtime does not have is left out."""
        events = self.record(run)
        folder.mkdir(parents=True, exist_ok=True)
        lines = "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events)
        (folder / "steps.jsonl").write_text(lines, encoding="utf-8")
        written = []
        for name in files_of(events):
            try:
                (folder / name).write_bytes(self.file(run, name))
            except ApiError as error:
                if error.status != 404:
                    raise
                continue
            written.append(name)
        return events, written

    def export_session(self, run: str, folder: Path) -> tuple[list[dict], list[str]]:
        """Write every log of the session `run` began to `folder`, each in a folder of its own named by its id: the
        events of all of them and the names of the files written."""
        thread = self.start_of(run)["thread"]
        events, written = [], []
        for log in [each["id"] for each in self.runs(thread) if each.get("session") == run]:
            logged, files = self.export(log, folder / log)
            events += logged
            written += [f"{log}/{name}" for name in files]
        return events, written


class Follow:
    """What a session logs until it is quiet: the main agent's turns and the tasks they hand over, given by the id of
    its first turn (`run`). Each log is followed to its end, then the next, in the order they began, so a turn's lines
    come together; a stream cut off goes on from its last line, and so does `lines` called again after an
    interrupt."""

    def __init__(self, client: Client, run: str, sleep: Callable[[float], None] = time.sleep):
        self.client, self.run, self.sleep = client, run, sleep
        self.thread: str | None = None  # its conversation, once its first line says it
        self.logs = [run]  # in the order they began
        self.seen: dict[str, int] = {}  # each log's last line so far
        self.ended: set[str] = set()

    def lines(self) -> Iterator[tuple[str, dict]]:
        """Each line as it comes, with the id of its log."""
        while True:
            log = next((each for each in self.logs if each not in self.ended), None)
            if log is None:
                if not self.more():
                    return
                continue
            for event in self.client.events(log, self.seen.get(log, -1)):
                if event.kind == "line":
                    self.seen[log] = event.index if event.index is not None else self.seen.get(log, -1) + 1
                    if event.data.get("type") == "start" and self.thread is None:
                        self.thread = event.data["thread"]
                    yield log, event.data
                elif event.kind == "done":
                    self.ended.add(log)

    def more(self) -> bool:
        """Whether the session began a log not followed yet; while it is in progress without one, it is looked at
        again."""
        while True:
            going = any(each.get("run") == self.run for each in self.client.status().get("running", []))
            found = sorted(
                each["id"] for each in (self.client.runs(self.thread) if self.thread else [])
                if each.get("session") == self.run and each["id"] not in self.logs
            )
            if found:
                self.logs += found
                return True
            if not going:
                return False
            self.sleep(POLL_SECONDS)


def _quoted(part: str) -> str:
    return urllib.parse.quote(part, safe="")
