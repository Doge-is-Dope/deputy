"""Code runner contract: a sandbox where the coding agent's commands and files go, apart from the runtime.

HttpCodeRunner (sandbox.http) talks to the code-runner container over its Unix socket; another sandbox plugs in here."""

from dataclasses import dataclass
from typing import Protocol

from computer_use.computers import Status
from computer_use.config import Settings


class CodeRunnerError(RuntimeError):
    """The code runner could not be reached, or failed."""


@dataclass(frozen=True)
class RunOutput:
    code: int | None  # the exit code; None when the command was stopped after its time
    text: str  # what it printed, stdout and stderr together, its middle cut when long
    cut: int  # how many bytes were cut


class CodeRunner(Protocol):
    """Each conversation (`thread`) has its own working folder in the sandbox. Refused requests raise ValueError;
    connection or server failures raise CodeRunnerError and end the task."""

    async def status(self) -> Status: ...
    async def run(self, thread: str, script: str, seconds: float) -> RunOutput: ...  # a script, with bash
    async def write(self, thread: str, path: str, content: str) -> str: ...  # a file in the working folder
    async def stop(self, thread: str) -> None: ...  # the command running for the conversation, if any
    async def close(self) -> None: ...


def build_code_runner(settings: Settings) -> CodeRunner | None:
    """The code runner the settings name, or None when there is none: the coding agent is then not offered."""
    from computer_use.sandbox.http import HttpCodeRunner

    return HttpCodeRunner(settings.code_runner_url) if settings.code_runner_url else None
