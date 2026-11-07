"""Isolated command runner with per-conversation folders under /workspace.

Each task runs one command at a time, in its conversation's folder, which the
conversation's tasks share; tasks of one conversation run side by side. Commands
use bash with only PATH, HOME and LANG, in a process group that can be stopped
as a unit. Files persist until the container restarts. The runtime uses HTTP
over SOCKET in a shared volume; without SOCKET, the server listens on PORT.

POST /run   {thread, task, script, seconds} -> {code, output, cut}; code null on timeout
POST /write {thread, path, content}         -> {path, bytes}
POST /stop  {task}                          -> {stopped}
GET /status                                -> {ok: true}

Invalid ids and paths outside the working folder return 400 with {error}."""

import json
import os
import re
import signal
import stat
import socketserver
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

WORKSPACE = Path(os.environ.get("WORKSPACE", "/workspace"))
SOCKET = os.environ.get("SOCKET")
PORT = int(os.environ.get("PORT", "8080"))
# What a command's output keeps: this many bytes from its start and as many from its end.
KEEP = 8000
# The longest a command may run, whatever the runtime asks.
MAX_SECONDS = 600
# The largest request body: a script or a file to write.
MAX_BODY = 8 * 1024 * 1024
# Downloads are bounded independently of command output and uploads.
MAX_FILE = 32 * 1024 * 1024
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")  # a conversation's or a task's

running: dict[str, subprocess.Popen] = {}  # each task's command in progress
lock = threading.Lock()


class Refused(ValueError):
    """A request the runner will not carry out; its message goes back to the agent."""


def folder(thread: str) -> Path:
    """The conversation's working folder, made on first use."""
    if not isinstance(thread, str) or not ID.fullmatch(thread):
        raise Refused("thread must be a conversation id")
    path = WORKSPACE / thread
    path.mkdir(parents=True, exist_ok=True)
    return path


def inside(base: Path, name: str) -> Path:
    """A path in the folder, refusing any that leads out of it."""
    if not isinstance(name, str) or not name:
        raise Refused("path must be a file name in the working folder")
    path = (base / name).resolve()
    if not path.is_relative_to(base.resolve()):
        raise Refused(f"{name} is outside the working folder")
    return path


def clipped(file) -> tuple[str, int]:
    """What a command printed, its middle cut when it is long, and how many bytes were cut."""
    size = file.seek(0, os.SEEK_END)
    file.seek(0)
    if size <= 2 * KEEP:
        return file.read().decode("utf-8", "replace"), 0
    head = file.read(KEEP)
    file.seek(size - KEEP)
    tail = file.read(KEEP)
    cut = size - 2 * KEEP
    text = f"{head.decode('utf-8', 'replace')}\n[... {cut} bytes cut ...]\n{tail.decode('utf-8', 'replace')}"
    return text, cut


def run(thread: str, task: str, script: str, seconds: float) -> dict:
    """Run a script for a task with bash in its conversation's folder until it exits or `seconds` pass."""
    if not isinstance(script, str):
        raise Refused("script must be text")
    if not isinstance(task, str) or not ID.fullmatch(task):
        raise Refused("task must be a task id")
    cwd = folder(thread)
    seconds = min(max(float(seconds), 1.0), MAX_SECONDS)
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(cwd), "LANG": "C.UTF-8"}
    # Output goes to a file, not memory, so a command that prints without end cannot take the runner down with it.
    with tempfile.TemporaryFile() as output:
        with lock:
            if task in running:
                raise Refused("a command of this task is still running")
            process = subprocess.Popen(
                ["bash", "-c", script], cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=output,
                stderr=subprocess.STDOUT, start_new_session=True,
            )
            running[task] = process
        try:
            code = process.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            stop(task)
            process.wait()
            code = None
        finally:
            with lock:
                running.pop(task, None)
        text, cut = clipped(output)
    return {"code": code, "output": text, "cut": cut}


def write(thread: str, path: str, content: str) -> dict:
    """Write a text file in the conversation's folder, replacing any there."""
    if not isinstance(content, str):
        raise Refused("content must be text")
    base = folder(thread)
    target = inside(base, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = content.encode("utf-8")
    target.write_bytes(data)
    return {"path": str(target.relative_to(base.resolve())), "bytes": len(data)}


def stop(task: str) -> bool:
    """Stop the task's command and everything it started; False when none runs."""
    with lock:
        process = running.get(task)
    if process is None:
        return False
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:  # it ended meanwhile
        pass
    return True


def read(thread: str, path: str) -> bytes:
    """Read a regular file, without following symlinks or creating a missing conversation.

    Open each component relative to the preceding directory descriptor so a running command cannot
    swap a checked directory for a symlink between checking and reading it.
    """
    if not isinstance(thread, str) or not ID.fullmatch(thread):
        raise Refused("thread must be a conversation id")
    parts = path.split("/") if isinstance(path, str) else []
    if not parts or any(part in ("", ".", "..") or "\x00" in part for part in parts):
        raise Refused("path must be a file name in the working folder")
    directory = os.open(WORKSPACE, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in [thread, *parts[:-1]]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:  # closed here, whatever it turns out to be: fdopen leaves one it refuses, such as a folder's, open
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise Refused("only regular files can be downloaded")
            with os.fdopen(descriptor, "rb", closefd=False) as file:
                data = file.read(MAX_FILE + 1)
        finally:
            os.close(descriptor)
        if len(data) > MAX_FILE:
            raise Refused(f"the file is over {MAX_FILE} bytes")
        return data
    except FileNotFoundError:
        raise
    except OSError as error:
        raise Refused("file cannot be downloaded") from error
    finally:
        os.close(directory)


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        if url.path == "/files":
            query = parse_qs(url.query)
            try:
                data = read(query.get("thread", [None])[0], query.get("path", [None])[0])
            except FileNotFoundError:
                return self._send(404, {"error": "no such file"})
            except ValueError as error:
                return self._send(400, {"error": str(error)})
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif self.path == "/status":
            self._send(200, {"ok": True})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        handlers = {
            "/run": lambda body: run(body.get("thread"), body.get("task"), body.get("script"), body.get("seconds", 120)),
            "/write": lambda body: write(body.get("thread"), body.get("path"), body.get("content")),
            "/stop": lambda body: {"stopped": stop(body.get("task"))},
        }
        handler = handlers.get(self.path)
        if handler is None:
            return self._send(404, {"error": "not found"})
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self._send(413, {"error": f"the request is over {MAX_BODY} bytes"})
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise Refused("the request must be a JSON object")
            self._send(200, handler(body))
        except (Refused, ValueError) as error:
            self._send(400, {"error": str(error)})

    def log_message(self, format, *args) -> None:  # requests are the runtime's to log
        pass


class UnixHTTPServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


if __name__ == "__main__":
    if SOCKET:
        Path(SOCKET).unlink(missing_ok=True)  # left by the runner's last start
        UnixHTTPServer(SOCKET, Handler).serve_forever()
    else:
        ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
