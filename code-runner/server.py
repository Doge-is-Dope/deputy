"""Isolated command runner with per-conversation folders under /workspace.

Commands use bash with only PATH, HOME and LANG, in a process group that can be
stopped as a unit. Files persist until the container restarts. The runtime uses
HTTP over SOCKET in a shared volume; without SOCKET, the server listens on PORT.

POST /run   {thread, script, seconds} -> {code, output, cut}; code null on timeout
POST /write {thread, path, content}   -> {path, bytes}
POST /stop  {thread}                  -> {stopped}
GET /status                          -> {ok: true}

Invalid threads and paths outside the working folder return 400 with {error}."""

import json
import os
import re
import signal
import socketserver
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WORKSPACE = Path(os.environ.get("WORKSPACE", "/workspace"))
SOCKET = os.environ.get("SOCKET")
PORT = int(os.environ.get("PORT", "8080"))
# What a command's output keeps: this many bytes from its start and as many from its end.
KEEP = 8000
# The longest a command may run, whatever the runtime asks.
MAX_SECONDS = 600
# The largest request body: a script or a file to write.
MAX_BODY = 8 * 1024 * 1024
THREAD = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")

running: dict[str, subprocess.Popen] = {}  # each conversation's command in progress
lock = threading.Lock()


class Refused(ValueError):
    """A request the runner will not carry out; its message goes back to the agent."""


def folder(thread: str) -> Path:
    """The conversation's working folder, made on first use."""
    if not isinstance(thread, str) or not THREAD.fullmatch(thread):
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


def run(thread: str, script: str, seconds: float) -> dict:
    """Run a script with bash in the conversation's folder until it exits or `seconds` pass."""
    if not isinstance(script, str):
        raise Refused("script must be text")
    cwd = folder(thread)
    seconds = min(max(float(seconds), 1.0), MAX_SECONDS)
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(cwd), "LANG": "C.UTF-8"}
    # Output goes to a file, not memory, so a command that prints without end cannot take the runner down with it.
    with tempfile.TemporaryFile() as output:
        with lock:
            if thread in running:
                raise Refused("a command of this conversation is still running")
            process = subprocess.Popen(
                ["bash", "-c", script], cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=output,
                stderr=subprocess.STDOUT, start_new_session=True,
            )
            running[thread] = process
        try:
            code = process.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            stop(thread)
            process.wait()
            code = None
        finally:
            with lock:
                running.pop(thread, None)
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


def stop(thread: str) -> bool:
    """Stop the conversation's command and everything it started; False when none runs."""
    with lock:
        process = running.get(thread)
    if process is None:
        return False
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:  # it ended meanwhile
        pass
    return True


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path == "/status":
            self._send(200, {"ok": True})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        handlers = {
            "/run": lambda body: run(body.get("thread"), body.get("script"), body.get("seconds", 120)),
            "/write": lambda body: write(body.get("thread"), body.get("path"), body.get("content")),
            "/stop": lambda body: {"stopped": stop(body.get("thread"))},
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
