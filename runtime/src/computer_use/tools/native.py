"""Model-facing commands on the Windows machine itself."""

from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool, tool
from pydantic import Field

from computer_use.native.execution import Commands
from computer_use.tools.common import CallId
from computer_use.tools.desktop import ConsequenceArg, NeedsConfirmationArg, reply


def command_tools(commands: Commands) -> list[BaseTool]:
    @tool
    async def run_command(
        command: Annotated[str, Field(min_length=1, max_length=32000, description="PowerShell, one line or several")],
        timeout: Annotated[int, Field(ge=1, le=600, description="seconds to let it run")] = 30,
        *,
        call_id: CallId,
        needs_confirmation: NeedsConfirmationArg,
        consequence: ConsequenceArg = None,
    ) -> ToolMessage:
        """Run a PowerShell command on this Windows computer, as the signed-in user, and wait for it. Returns its
        exit code, what it printed and the screen after it.

        Use it for what a command does faster or more surely than the mouse: finding, reading, creating, moving and
        renaming files, reading or changing data in bulk, checking that something exists. It starts in the user's
        profile folder, in a new PowerShell each time, so nothing carries over from one call to the next. It is
        stopped when the timeout ends; start what must keep running, such as an app, with Start-Process.
        A command's own report is not proof: when its effect shows on the screen, check it there.
        The same rules apply as to mouse and keyboard: set needs_confirmation as you would for the same change
        made by hand.
        """
        return reply(await commands.run(command, timeout), call_id, "run_command")

    return [run_command]
