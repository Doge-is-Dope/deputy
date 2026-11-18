"""The host over MCP on HTTPS, reached as one URL says. No call is retried."""

import asyncio
import hashlib
import http.client
import json
import re
import ssl
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from computer_use.native import HostError

PROTOCOL = "2025-11-25"
# Lease calls are the host's own, beside MCP: models never see them.
CONTROL = ("control.resume", "control.heartbeat", "control.takeover")
Post = Callable[[str, dict, float], dict]
URL_SHAPE = "https://<token>@<address>:<port>/<certificate SHA-256>"


@dataclass(frozen=True)
class Connection:
    """How to reach one host: where it listens, its token, and its certificate's SHA-256."""

    address: str
    port: int
    token: str
    fingerprint: str

    @classmethod
    def from_url(cls, url: str) -> "Connection":
        """The host's line, as `URL_SHAPE`; the port is 8767 when left out."""
        parts = urlsplit(url.strip())
        fingerprint = parts.path.strip("/").lower()
        if parts.scheme != "https" or not parts.hostname or not parts.username or not re.fullmatch("[0-9a-f]{64}", fingerprint):
            raise ValueError(f"WINDOWS_TOOLS_URL must be {URL_SHAPE}.")
        return cls(parts.hostname, parts.port or 8767, unquote(parts.username), fingerprint)


def check_certificate(connection: Connection, certificate: bytes) -> None:
    """Refuse a host whose certificate is not the one its URL names, before the token goes to it."""
    if hashlib.sha256(certificate).hexdigest() != connection.fingerprint:
        raise HostError(
            "certificate_changed",
            "The Windows Tools host's certificate is not the one in WINDOWS_TOOLS_URL. If the host was set up again, "
            "put its new line in WINDOWS_TOOLS_URL.",
            sent=False,
        )


def https(connection: Connection) -> Post:
    """Posts JSON to the host, the token sent only once its certificate is the one named."""
    context = ssl.create_default_context()
    # The fingerprint is the check: the host signs its own certificate.
    context.check_hostname, context.verify_mode = False, ssl.CERT_NONE

    def post(path: str, body: dict, timeout: float) -> dict:
        client = http.client.HTTPSConnection(connection.address, connection.port, timeout=timeout, context=context)
        try:
            try:
                client.connect()
                check_certificate(connection, client.sock.getpeercert(binary_form=True))
            except OSError as error:
                raise HostError("unreachable", (
                    f"The Windows Tools host did not answer: {error}. Sign in to Windows as its account and allow port "
                    f"{connection.port}; if the computer's address changed, run the installer again and put its new "
                    "line in WINDOWS_TOOLS_URL."
                ), sent=False) from None
            try:
                client.request("POST", path, json.dumps(body, ensure_ascii=False).encode(), {
                    "Authorization": f"Bearer {connection.token}", "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": PROTOCOL,
                })
                response = client.getresponse()
                text = response.read().decode()
            except (OSError, http.client.HTTPException) as error:
                raise HostError("no_reply", f"The Windows Tools host did not reply: {error}") from None
            if response.status == 401:
                raise HostError("unauthorized", (
                    "The Windows Tools host refused the token in WINDOWS_TOOLS_URL. Copy the installer's line into it "
                    "again."
                ), sent=False)
            if response.status not in (200, 202):
                raise HostError("http_error", f"The Windows Tools host answered HTTP {response.status}.")
            message = json.loads(text) if text else {}
            if not isinstance(message, dict):
                raise HostError("protocol_error", "The Windows Tools host did not reply with a JSON object.")
            return message
        finally:
            client.close()

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
        if not isinstance(error, dict) or not isinstance(error.get("code"), str):
            raise HostError("protocol_error", "The Windows Tools host's error had no code.")
        raise HostError(error["code"], error.get("message", "The call failed."), sent=error.get("delivery") != "not_sent")
    if not isinstance(envelope.get("result"), dict):
        raise HostError("protocol_error", "The Windows Tools host's reply had no result.")
    return envelope["result"]
