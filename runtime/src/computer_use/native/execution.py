"""One desktop task's commands and browser calls on Windows: sent only while the agent may act, their result told
with the screen after them."""

from collections.abc import Awaitable, Callable
from dataclasses import replace

from computer_use.computers import ComputerError
from computer_use.desktop.executor import ActionResult, Executor
from computer_use.native import HostError
from computer_use.native.lease import Lease

# What a command printed, as the model reads it: its end, where the errors are.
MAX_OUTPUT_CHARACTERS = 12_000
# How much longer than the command's own deadline its reply is waited for.
REPLY_MARGIN_SECONDS = 15
# The host's deadline for one browser call.
BROWSER_SECONDS = 60
# How long the screen is watched for what a command opens to show; it is shown as soon as it has drawn.
PROGRAM_SECONDS = 3.0


def report(result: dict) -> str:
    """How a command ended and what it printed."""
    seconds = f"{result['durationMs'] / 1000:.1f} s"
    match result["state"]:
        case "timed_out":
            first = f"Stopped after {seconds}: the command did not finish in time."
        case "cancelled":
            first = f"Stopped after {seconds}: the desktop changed hands."
        case _ if result.get("error"):
            first = f"The command could not be started: {result['error']}"
        case _:
            first = f"Exit code {result['exitCode']} after {seconds}."
    output = result.get("output") or ""
    cut = len(output) - MAX_OUTPUT_CHARACTERS
    if cut > 0 or result.get("outputTruncated"):
        output = output[-MAX_OUTPUT_CHARACTERS:]
        first += " Only the end of its output is shown."
    return f"{first}\n{output.rstrip()}" if output.strip() else f"{first}\n(no output)"


def page_report(result: dict) -> str:
    """What a browser call returned: its text, the start kept, where a page snapshot begins."""
    text = "\n".join(block["text"] for block in result.get("content", []) if block.get("type") == "text").strip()
    if len(text) > MAX_OUTPUT_CHARACTERS:
        text = text[:MAX_OUTPUT_CHARACTERS] + "\n(Only the start is shown.)"
    if result.get("isError"):
        return f"The browser call failed.\n{text}"
    return text or "Done."


class Commands:
    def __init__(self, lease: Lease, executor: Executor):
        self.lease = lease
        self.executor = executor

    async def run(self, command: str, timeout: int, opens: bool = False) -> ActionResult:
        def send(target: dict) -> Awaitable[dict]:
            args = {"command": command, "timeoutMs": timeout * 1000}
            return self.lease.channel.call("exec.run", target, args, timeout=timeout + REPLY_MARGIN_SECONDS)

        return await self._call(send, report, "the command may have run", opens=opens)

    async def browse(self, name: str, args: dict) -> ActionResult:
        """A browser call's text alone: the screen comes once before the next model call (middleware.desktop), not after
        each of several calls in one reply. A failed call, or one whose outcome is unknown, is a failure."""
        def send(target: dict) -> Awaitable[dict]:
            return self.lease.channel.call_tool(name, target, args, timeout=BROWSER_SECONDS + REPLY_MARGIN_SECONDS)

        unknown = "the browser call may have run, and if the browser closed, its pages are gone"
        return await self._call(send, page_report, unknown, shown=False)

    async def _call(
        self, send: Callable[[dict], Awaitable[dict]], told: Callable[[dict], str], unknown: str, *, shown: bool = True,
        opens: bool = False,
    ) -> ActionResult:
        try:
            if held := await self.executor.held():
                return held
            target = self.lease.target
            if target is None:
                return ActionResult(False, f"Not executed: Windows tools are unavailable right now ({self.lease.problem}).")
            try:
                result = await send(target)
            except HostError as error:
                if not error.sent:
                    return ActionResult(False, f"Not executed: {error}")
                text, failed = f"Outcome unknown: {unknown} ({error}). Check before running it again.", True
            else:
                text, failed = told(result), bool(result.get("isError"))
            # Whatever the call did, the screen the model saw is no longer the one to compare with.
            self.executor.clear_unchanged()
            if not shown:
                self.executor.unshown = True
                return ActionResult(not failed, text)
            try:
                # What a command opens draws after it ends: shown once it has, not a look before.
                shot = await self.executor.settled(PROGRAM_SECONDS) if opens else None
                return replace(await self.executor.observe(text, shot), ok=True)
            except ComputerError as error:
                return ActionResult(True, f"{text}\nNo screenshot: {error}")
        finally:  # an approval covers the one call it was given for
            self.executor.approved = False
