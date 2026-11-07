"""Code runner contract: a sandbox where the coding agent's commands and files go, apart from the runtime.

HttpCodeRunner (sandbox.http) talks to the code-runner container over its Unix socket; another sandbox plugs in here."""

from dataclasses import dataclass
from typing import Protocol


class CodeRunnerError(RuntimeError):
    """The code runner could not be reached, or failed."""


@dataclass(frozen=True)
class Status:
    connected: bool
    detail: str = ""


@dataclass(frozen=True)
class RunOutput:
    code: int | None  # the exit code; None when the command was stopped after its time
    text: str  # what it printed, stdout and stderr together, its middle cut when long
    cut: int  # how many bytes were cut


class CodeRunner(Protocol):
    """Each conversation (`thread`) has its own working folder in the sandbox, which its tasks share; each task runs
    its commands on its own, one at a time, so tasks of one conversation run side by side. Refused requests raise
    ValueError; connection or server failures raise CodeRunnerError and end the task."""

    async def status(self) -> Status: ...
    async def run(self, thread: str, task: str, script: str, seconds: float) -> RunOutput: ...  # a script, with bash
    async def write(self, thread: str, path: str, content: str) -> str: ...  # a file in the working folder
    async def read(self, thread: str, path: str) -> bytes: ...  # FileNotFoundError when missing
    async def stop(self, task: str) -> None: ...  # the task's command running, if any
    async def close(self) -> None: ...
