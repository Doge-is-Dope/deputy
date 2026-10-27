"""The code runner over HTTP, normally on the shared Unix socket of the code-runner container."""

import asyncio
import time

import httpx

from computer_use.computers import Status
from computer_use.sandbox import CodeRunnerError, RunOutput

# How long a status read stands, so the settings page, which asks every second or two, does not ask the runner as often.
STATUS_SECONDS = 30.0
# How long to wait for the runner to answer anything but a command, which waits as long as the command may run.
REQUEST_SECONDS = 10.0


class HttpCodeRunner:
    def __init__(self, url: str, transport: httpx.AsyncBaseTransport | None = None):
        self.url = url
        base = url
        if url.startswith("unix://"):
            base = "http://code-runner"
            transport = transport or httpx.AsyncHTTPTransport(uds=url.removeprefix("unix://"))
        self._client = httpx.AsyncClient(base_url=base, transport=transport, timeout=REQUEST_SECONDS)
        self._status: tuple[float, Status] | None = None

    async def status(self) -> Status:
        if self._status is not None and time.monotonic() - self._status[0] < STATUS_SECONDS:
            return self._status[1]
        try:
            await self._request("GET", "/status")
            status = Status(True, "Code runner: connected")
        except CodeRunnerError as error:
            status = Status(False, f"Code runner: not reachable at {self.url} ({error})")
        self._status = (time.monotonic(), status)
        return status

    async def run(self, thread: str, script: str, seconds: float) -> RunOutput:
        """Run a script with bash in the conversation's folder. A task stopped meanwhile stops the command too."""
        try:
            body = await self._request(
                "POST", "/run", {"thread": thread, "script": script, "seconds": seconds}, timeout=seconds + REQUEST_SECONDS
            )
        except asyncio.CancelledError:
            await asyncio.shield(self.stop(thread))
            raise
        return RunOutput(body["code"], body["output"], body["cut"])

    async def write(self, thread: str, path: str, content: str) -> str:
        body = await self._request("POST", "/write", {"thread": thread, "path": path, "content": content})
        return f"Wrote {body['path']} ({body['bytes']} bytes)."

    async def stop(self, thread: str) -> None:
        try:
            await self._request("POST", "/stop", {"thread": thread})
        except CodeRunnerError:  # nothing more to do: it stops itself once the command's time is up
            pass

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, body: dict | None = None, timeout: float | None = None) -> dict:
        try:
            response = await self._client.request(method, path, json=body, timeout=timeout or REQUEST_SECONDS)
        except httpx.HTTPError as error:
            raise CodeRunnerError(f"{type(error).__name__}: {error}") from error
        if response.status_code == 400:
            raise ValueError(response.json().get("error", "refused"))
        if response.status_code != 200:
            raise CodeRunnerError(f"HTTP {response.status_code}: {response.text[:200]}")
        return response.json()

