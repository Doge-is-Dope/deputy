"""Starting the host on the machine a desktop shows, and the way to do it over RDP."""

import asyncio
import ipaddress
import os
import subprocess
from typing import Protocol

from computer_use.computers import Computer, ComputerError
from computer_use.native import HostError

# How the token and the certificate's fingerprint cross the clipboard, as the host reads and writes them.
TOKEN_PREFIX = "windows-tools-token:"
FINGERPRINT_PREFIX = "windows-tools-fingerprint:"
# The Run dialog takes no more.
RUN_LIMIT = 259
# Windows draws the Run dialog before it takes keys.
RUN_OPENS_SECONDS = 1.5
# The host answers in under a second; a machine busy starting it gets longer.
ANSWER_SECONDS = 20.0
ANSWER_POLL_SECONDS = 0.3


class Launcher(Protocol):
    """Starts the host where the desktop is, handing it `token` over a channel already trusted; returns the SHA-256
    of the certificate the host made for this run. Another backend for the desktop brings another launcher."""

    async def start(self, token: str) -> str: ...


class Clipboard(Protocol):
    async def put(self, text: str) -> None: ...
    async def get(self) -> str: ...


class XClipboard:
    """The X clipboard an RDP client shares with Windows."""

    def __init__(self, display: str):
        self.environment = {**os.environ, "DISPLAY": display}

    async def put(self, text: str) -> None:
        await asyncio.to_thread(self._run, ["xclip", "-selection", "clipboard", "-i"], text)

    async def get(self) -> str:
        return await asyncio.to_thread(self._run, ["timeout", "5", "xclip", "-selection", "clipboard", "-o"], None)

    def _run(self, command: list[str], text: str | None) -> str:
        # xclip stays behind to serve what it was given, holding any pipe it inherited: only a read is captured.
        putting = text is not None
        try:
            done = subprocess.run(
                command, input=text.encode() if putting else None, env=self.environment, timeout=10,
                stdout=subprocess.DEVNULL if putting else subprocess.PIPE, stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise HostError("clipboard", f"The clipboard could not be used: {error}", sent=False) from None
        return "" if putting else done.stdout.decode("utf-8", "replace")


class RdpLauncher:
    """Starts the host from the Run dialog, with no window. The token goes by the clipboard, never typed: the Run
    dialog remembers what is typed into it."""

    def __init__(self, computer: Computer, clipboard: Clipboard, path: str, address: str, port: int):
        self.computer = computer
        self.clipboard = clipboard
        self.command = f'conhost.exe --headless "{path}" --attach {address} {port}'
        try:
            ipaddress.IPv4Address(address)
            usable = '"' not in path and len(self.command) <= RUN_LIMIT
        except ValueError:
            usable = False
        if not usable:
            raise ValueError(
                "Windows Tools needs the host's own IPv4 address (WINDOWS_TOOLS_HOST, else RDP_HOST) and a path "
                "to its program short enough for the Run dialog."
            )

    async def start(self, token: str) -> str:
        await self.clipboard.put(TOKEN_PREFIX + token)
        try:
            await self.computer.press([["win", "r"]])
            await asyncio.sleep(RUN_OPENS_SECONDS)
            await self.computer.type_text(self.command)
            await self.computer.press([["enter"]])
        except ComputerError as error:
            raise HostError("desktop", f"The Windows Tools host could not be started: {error}", sent=False) from None
        loop = asyncio.get_running_loop()
        until = loop.time() + ANSWER_SECONDS
        while loop.time() < until:
            answer = (await self.clipboard.get()).strip()
            if answer.startswith(FINGERPRINT_PREFIX):
                await self.clipboard.put("")  # nothing of the exchange stays on the clipboard
                return answer.removeprefix(FINGERPRINT_PREFIX)
            await asyncio.sleep(ANSWER_POLL_SECONDS)
        await self.clipboard.put("")
        raise HostError("not_started", "The Windows Tools host did not answer after it was started.", sent=False)
