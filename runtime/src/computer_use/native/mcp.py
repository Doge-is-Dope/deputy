"""The host over MCP on HTTPS, reached with the credentials kept for its desktop. No call is retried."""

import asyncio
import hashlib
import http.client
import json
import os
import re
import ssl
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from computer_use.native import HostError

PROTOCOL = "2025-11-25"
# Lease calls are the host's own, beside MCP: models never see them.
CONTROL = ("control.resume", "control.heartbeat", "control.takeover")
Post = Callable[[str, dict, float], dict]


@dataclass(frozen=True)
class Credentials:
    """What reaches one host: its token, and its certificate's SHA-256 once known."""

    token: str
    fingerprint: str | None = None


class CredentialFile:
    """A desktop's host credentials, kept beside its other shared state so every server of that desktop uses the
    same host. A token set by hand (`token`) is the one used, and the file then remembers only its certificate."""

    def __init__(self, path: Path, token: str | None = None):
        self.path = path
        self.token = token

    def read(self) -> Credentials | None:
        try:
            kept = Credentials(**json.loads(self.path.read_text()))
        except (FileNotFoundError, ValueError, TypeError):
            kept = None
        if self.token is None:
            return kept
        return kept if kept and kept.token == self.token else Credentials(self.token)

    def write(self, credentials: Credentials) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        scratch = self.path.with_suffix(".new")
        with open(os.open(scratch, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as file:
            json.dump(asdict(credentials), file)
        scratch.replace(self.path)


def check_certificate(store: CredentialFile, credentials: Credentials, certificate: bytes) -> None:
    """Refuse a host whose certificate is not the known one. With none known yet, as for a host started by hand,
    the first seen is remembered."""
    seen = hashlib.sha256(certificate).hexdigest()
    if credentials.fingerprint is None:
        store.write(Credentials(credentials.token, seen))
    elif seen != credentials.fingerprint:
        raise HostError(
            "certificate_changed",
            f"The Windows Tools host's certificate is not the known one. If that is expected, delete {store.path}.",
            sent=False,
        )


def https(host: str, port: int, store: CredentialFile) -> Post:
    """Posts JSON to the host, the token sent only once its certificate is the known one."""
    context = ssl.create_default_context()
    # The fingerprint is the check: the host signs its own certificate.
    context.check_hostname, context.verify_mode = False, ssl.CERT_NONE

    def post(path: str, body: dict, timeout: float) -> dict:
        credentials = store.read()
        if credentials is None:
            raise HostError("not_started", "The Windows Tools host has not been started yet.", sent=False)
        connection = http.client.HTTPSConnection(host, port, timeout=timeout, context=context)
        try:
            try:
                connection.connect()
                check_certificate(store, credentials, connection.sock.getpeercert(binary_form=True))
            except OSError as error:
                raise HostError("unreachable", f"The Windows Tools host did not answer: {error}", sent=False) from None
            try:
                connection.request("POST", path, json.dumps(body, ensure_ascii=False).encode(), {
                    "Authorization": f"Bearer {credentials.token}", "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": PROTOCOL,
                })
                response = connection.getresponse()
                text = response.read().decode()
            except (OSError, http.client.HTTPException) as error:
                raise HostError("no_reply", f"The Windows Tools host did not reply: {error}") from None
            if response.status == 401:
                raise HostError("unauthorized", "The Windows Tools host refused the token.", sent=False)
            if response.status not in (200, 202):
                raise HostError("http_error", f"The Windows Tools host answered HTTP {response.status}.")
            return json.loads(text) if text else {}
        finally:
            connection.close()

    return post


class McpChannel:
    def __init__(self, post: Post):
        self.post = post
        self._ready = False
        self._starting = asyncio.Lock()

    async def call(self, method: str, target: dict | None = None, args: dict | None = None, *, timeout: float = 5) -> dict:
        identity = uuid.uuid4().hex
        if method in CONTROL:
            message = {"version": 1, "id": identity, "method": method, "target": target, "args": {}}
            return _result(await self._post("/connector/control", message, timeout))
        await self._initialize(timeout)
        name = "windows_" + re.sub("[A-Z]", lambda upper: "_" + upper[0].lower(), method.replace(".", "_"))
        params: dict = {"name": name, "arguments": args or {}}
        if target is not None:
            params["_meta"] = {"windows-tools/target": target}
        return _result(_reply(await self._rpc("tools/call", params, identity, timeout)).get("structuredContent"))

    async def _initialize(self, timeout: float) -> None:
        async with self._starting:
            if self._ready:
                return
            client = {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": {"name": "computer-use", "version": "1"}}
            try:
                _reply(await self._rpc("initialize", client, uuid.uuid4().hex, timeout))
                await self._post("/mcp", {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, timeout)
            except HostError as error:  # the handshake runs nothing on Windows
                raise HostError(error.code, str(error), sent=False) from None
            self._ready = True

    async def _rpc(self, method: str, params: dict, identity: str, timeout: float) -> dict:
        return await self._post("/mcp", {"jsonrpc": "2.0", "id": identity, "method": method, "params": params}, timeout)

    async def _post(self, path: str, body: dict, timeout: float) -> dict:
        try:
            return await asyncio.to_thread(self.post, path, body, timeout)
        except ValueError:
            raise HostError("protocol_error", "The Windows Tools host's reply was not JSON.") from None


def _reply(message: dict) -> dict:
    if not isinstance(message.get("result"), dict):
        raise HostError("protocol_error", "The Windows Tools host's reply had no result.")
    return message["result"]


def _result(envelope: object) -> dict:
    """What a call returned, from the host's own envelope of result or error."""
    if not isinstance(envelope, dict):
        raise HostError("protocol_error", "The Windows Tools host's reply had no result.")
    if error := envelope.get("error"):
        raise HostError(error.get("code", "error"), error.get("message", "The call failed."), sent=error.get("delivery") != "not_sent")
    if not isinstance(envelope.get("result"), dict):
        raise HostError("protocol_error", "The Windows Tools host's reply had no result.")
    return envelope["result"]
