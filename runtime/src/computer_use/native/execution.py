"""One desktop task's commands on Windows: sent only while the agent may act, their result told with the screen
after them."""

from dataclasses import replace

from computer_use.computers import ComputerError
from computer_use.desktop.executor import ActionResult, Executor
from computer_use.native import HostError
from computer_use.native.lease import Lease

# What a command printed, as the model reads it: its end, where the errors are.
MAX_OUTPUT_CHARACTERS = 12_000
# How much longer than the command's own deadline its reply is waited for.
REPLY_MARGIN_SECONDS = 15


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


class Commands:
    def __init__(self, lease: Lease, executor: Executor):
        self.lease = lease
        self.executor = executor

    async def run(self, command: str, timeout: int) -> ActionResult:
        try:
            if held := await self.executor.held():
                return held
            target = self.lease.target
            if target is None:
                return ActionResult(False, f"Not executed: commands are unavailable right now ({self.lease.problem}).")
            try:
                result = await self.lease.channel.call(
                    "exec.run", target, {"command": command, "timeoutMs": timeout * 1000},
                    timeout=timeout + REPLY_MARGIN_SECONDS,
                )
            except HostError as error:
                if not error.sent:
                    return ActionResult(False, f"Not executed: {error}")
                text = f"Outcome unknown: the command may have run ({error}). Check before running it again."
            else:
                text = report(result)
            # Whatever the command did, the screen the model saw is no longer the one to compare with.
            self.executor.clear_unchanged()
            try:
                return replace(await self.executor.observe(text), ok=True)
            except ComputerError as error:
                return ActionResult(True, f"{text}\nNo screenshot: {error}")
        finally:  # an approval covers the one call it was given for
            self.executor.approved = False
