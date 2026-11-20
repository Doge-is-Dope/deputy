"""Model-facing commands and browser tools on the Windows machine itself."""

import re
from dataclasses import replace
from typing import Annotated

from langchain.tools import ToolRuntime
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool, StructuredTool, tool
from pydantic import Field, TypeAdapter

from computer_use.native.execution import Commands
from computer_use.tools.common import CallId, confirmation
from computer_use.tools.desktop import ConsequenceArg, NeedsConfirmationArg, reply


def command_tools(commands: Commands) -> list[BaseTool]:
    @tool
    async def run_command(
        command: Annotated[str, Field(min_length=1, max_length=32000, description="PowerShell, one line or several")],
        timeout: Annotated[int, Field(ge=1, le=600, description="seconds to let it run")] = 30,
        opens: Annotated[bool, Field(description=(
            "true when it opens a window, an app or a file in its app: the screen is then shown once that has drawn"
        ))] = False,
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
        return reply(await commands.run(command, timeout, opens), call_id, "run_command")

    return [run_command]


# The host's browser tools offered, without the prefix: enough to open, read and act on a page. Those that commit
# nothing take no confirmation. Screenshots, uploads, files and diagnostics are left out: the screen covers them, and
# every listed tool costs each call's input.
BROWSER_PREFIX = "browser_"
READ_ONLY = {"list_pages", "select_page", "take_snapshot", "wait_for"}
OFFERED = READ_ONLY | {
    "new_page", "navigate_page", "click", "fill", "fill_form", "press_key", "type_text", "evaluate_script",
    "handle_dialog",
}
# Opening a page is mostly followed by reading it: its snapshot comes along, which saves the agent a step.
SHOWS_PAGE = {"new_page", "navigate_page"}
SELECTED = re.compile(r"^(\d+): .*\[selected\]$", re.M)
CONFIRM = {
    "needs_confirmation": TypeAdapter(NeedsConfirmationArg).json_schema(),
    "consequence": TypeAdapter(ConsequenceArg).json_schema(),
}


def browser_tools(listed: list[dict], commands: Commands) -> list[BaseTool]:
    """The offered browser tools among those the host lists, called through it."""
    offered = {BROWSER_PREFIX + name for name in OFFERED}
    return [_browser_tool(spec, commands) for spec in listed if spec.get("name") in offered]


def _browser_tool(spec: dict, commands: Commands) -> BaseTool:
    name = spec["name"]
    short = name.removeprefix(BROWSER_PREFIX)
    schema = spec.get("inputSchema", {"type": "object"})
    # No file is written from a page: the tools' file paths are left out.
    properties = {key: value for key, value in schema.get("properties", {}).items() if key != "filePath"}
    required = [key for key in schema.get("required", []) if key in properties]
    confirms = short not in READ_ONLY
    if confirms:
        properties |= CONFIRM
        required = [*required, "needs_confirmation"]
    schema = {**schema, "properties": properties, "required": required}
    shows_page = short in SHOWS_PAGE

    async def call(runtime: ToolRuntime, **args) -> ToolMessage:
        if confirms:
            try:
                confirmation(args)
            except ValueError as error:
                return ToolMessage(f"Not executed: {error}", tool_call_id=runtime.tool_call_id, name=name, status="error")
        # A strict schema has the model write every field: one left out comes as null.
        sent = {
            key: value for key, value in args.items()
            if key not in CONFIRM and not (value is None and key not in required)
        }
        result = await commands.browse(name, sent)
        page = sent.get("pageId") or next(iter(SELECTED.findall(result.text)), None)
        if shows_page and page is not None and result.ok:
            snapshot = await commands.browse(BROWSER_PREFIX + "take_snapshot", {"pageId": int(page)})
            result = replace(result, text=f"{result.text}\n{snapshot.text}")
        return reply(result, runtime.tool_call_id, name)

    description = spec.get("description") or name
    if shows_page:
        description += (" The page's snapshot comes with the result. Web pages only: open a local image, PDF or "
                        "document in its app.")
    return StructuredTool.from_function(
        coroutine=call, name=name, description=description, args_schema=schema, infer_schema=False,
    )
