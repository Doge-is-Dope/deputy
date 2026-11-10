"""Model-facing desktop tools, batches and takeover requests.

Input actions return a fresh screenshot; execution.approvals holds the calls flagged for approval."""

import json
from collections.abc import Callable
from typing import Annotated, Any, Literal

from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool, ToolException, tool
from pydantic import BaseModel, ConfigDict, Field, ValidationError, WithJsonSchema, create_model

from computer_use.desktop.actions import BATCHABLE, CLICKS
from computer_use.computers import Computer
from computer_use.desktop.control import Control, hand_over
from computer_use.desktop.executor import ActionResult, Executor
from computer_use.events import CONFIRM_FIELDS
from computer_use.tools.common import CallId, image_block

def content(result: ActionResult) -> str | list[dict]:
    if result.frame is None:
        return result.text
    return [{"type": "text", "text": result.text}, image_block(result.frame.png)]


def reply(result: ActionResult, call_id: str, name: str) -> ToolMessage:
    """The result as a tool message; its reason rides in the artifact, outside the text the model reads."""
    return ToolMessage(
        content=content(result), tool_call_id=call_id, name=name,
        status="success" if result.ok else "error", artifact={"reason": result.reason},
    )


# Coordinates are lists so every provider's function calling accepts the schema.
PointArg = Annotated[list[int], Field(min_length=2, max_length=2, description="[x, y] in full-screen screenshot pixels from the top-left")]
RegionArg = Annotated[list[int], Field(min_length=4, max_length=4, description="[x0, y0, x1, y1] in full-screen screenshot pixels from the top-left")]
ModifiersArg = Annotated[str | None, Field(description='Keys held during the action, e.g. "shift" or "ctrl+shift"')]

NeedsConfirmationArg = Annotated[bool, Field(description=(
    "true only on the step that commits something the user must approve first (see your instructions); "
    "false on every other step"
))]
ConsequenceArg = Annotated[str | None, Field(description=(
    "Required when needs_confirmation is true: what this step will do, as one short phrase in the user's language "
    "that starts with the action: what, to whom or where, and any amount. Otherwise omit."
))]


def batch_steps(schemas: dict[str, type[BaseModel]]) -> dict[str, type[BaseModel]]:
    """Each batchable action's own arguments, refusing any other: a batch says once whether it needs approval."""
    return {
        name: create_model(name, __config__=ConfigDict(extra="forbid"), **{
            key: (field.annotation, field) for key, field in schemas[name].model_fields.items() if key not in CONFIRM_FIELDS
        })
        for name in BATCHABLE
    }


def batch_step_schema(steps: dict[str, type[BaseModel]]) -> dict:
    """A batch step as one object per kind of action, with only that action's arguments. OpenAI makes tool schemas
    strict, which has the model write every field an object has: one object shared by all actions filled each step
    with nulls, a third of the computer agent's output (2026-11-01). Actions taking the same arguments share one."""
    kinds: dict[str, tuple[list[str], dict]] = {}
    for name, step in steps.items():
        schema = step.model_json_schema()
        schema["properties"] = {
            key: {k: v for k, v in field.items() if k != "title"} for key, field in schema["properties"].items()
        }
        schema.pop("title")
        kinds.setdefault(json.dumps(schema, sort_keys=True), ([], schema))[0].append(name)
    return {"anyOf": [
        {**schema, "properties": {"action": {"type": "string", "enum": names}, **schema["properties"]},
         "required": ["action", *schema.get("required", [])]}
        for names, schema in kinds.values()
    ]}


def desktop_tools(executor: Executor) -> list[BaseTool]:
    """Anthropic's computer use actions (computer_toolset_20260801) as ordinary function tools, and a batch of them."""

    async def run(name: str, call_id: str, **args) -> ToolMessage:
        return reply(await executor.run(name, args), call_id, name)

    @tool
    async def screenshot(*, call_id: CallId) -> ToolMessage:
        """Take a screenshot of the Windows desktop."""
        return await run("screenshot", call_id)

    @tool
    async def zoom(region: RegionArg, *, call_id: CallId) -> ToolMessage:
        """Show a region of the screen enlarged, to read small text or icons.

        Coordinates in the enlarged image are not screen coordinates; act with the full screenshot's.
        """
        return await run("zoom", call_id, region=region)

    # The input tools take needs_confirmation and consequence for `execution.approvals`, after their own arguments; neither
    # reaches the executor.
    def click_tool(name: str, what: str) -> BaseTool:
        async def click(
            coordinate: PointArg | None = None,
            text: ModifiersArg = None,
            *,
            call_id: CallId,
            needs_confirmation: NeedsConfirmationArg,
            consequence: ConsequenceArg = None,
        ) -> ToolMessage:
            return await run(name, call_id, coordinate=coordinate, text=text)

        click.__doc__ = f"{what} at coordinate, or where the pointer is if omitted. Returns the screen after it."
        return tool(name)(click)

    @tool
    async def left_click_drag(
        start_coordinate: PointArg,
        coordinate: PointArg,
        text: ModifiersArg = None,
        *,
        call_id: CallId,
        needs_confirmation: NeedsConfirmationArg,
        consequence: ConsequenceArg = None,
    ) -> ToolMessage:
        """Press the left button at start_coordinate, move to coordinate and release. Returns the screen after it."""
        return await run("left_click_drag", call_id, start_coordinate=start_coordinate, coordinate=coordinate, text=text)

    @tool
    async def mouse_move(coordinate: PointArg, *, call_id: CallId) -> ToolMessage:
        """Move the pointer without clicking, e.g. to show a tooltip or a hover menu. Returns the screen after it."""
        return await run("mouse_move", call_id, coordinate=coordinate)

    @tool
    async def left_mouse_down(
        *, call_id: CallId, needs_confirmation: NeedsConfirmationArg, consequence: ConsequenceArg = None,
    ) -> ToolMessage:
        """Press and hold the left button where the pointer is. Release it with left_mouse_up."""
        return await run("left_mouse_down", call_id)

    @tool
    async def left_mouse_up(
        *, call_id: CallId, needs_confirmation: NeedsConfirmationArg, consequence: ConsequenceArg = None,
    ) -> ToolMessage:
        """Release the left button where the pointer is."""
        return await run("left_mouse_up", call_id)

    @tool
    async def cursor_position(*, call_id: CallId) -> ToolMessage:
        """Report where the pointer is, in screenshot pixels."""
        return await run("cursor_position", call_id)

    @tool
    async def scroll(
        scroll_direction: Literal["up", "down", "left", "right"],
        scroll_amount: Annotated[int, Field(ge=1, le=20, description="wheel clicks")] = 3,
        coordinate: PointArg | None = None,
        text: ModifiersArg = None,
        *,
        call_id: CallId,
    ) -> ToolMessage:
        """Turn the mouse wheel at coordinate, or where the pointer is if omitted. Returns the screen after it."""
        return await run(
            "scroll", call_id, scroll_direction=scroll_direction, scroll_amount=scroll_amount, coordinate=coordinate, text=text
        )

    async def type_(
        text: Annotated[str, Field(min_length=1)],
        *,
        call_id: CallId,
        needs_confirmation: NeedsConfirmationArg,
        consequence: ConsequenceArg = None,
    ) -> ToolMessage:
        """Type text into the focused field; a newline presses Enter and may submit the form or run a command.

        If Enter needs approval, send the text first, then use key for that Enter in a separate approved call.
        Returns the screen after typing.
        """
        return await run("type", call_id, text=text)

    @tool
    async def key(
        text: str,
        repeat: Annotated[int, Field(ge=1, le=100)] = 1,
        *,
        call_id: CallId,
        needs_confirmation: NeedsConfirmationArg,
        consequence: ConsequenceArg = None,
    ) -> ToolMessage:
        """Press a key or combo, e.g. "Return", "ctrl+s", "win+s", "alt+f4"; several can be separated by spaces.

        Several combos run in order without intermediate observations. Separate them when a later combo needs
        new screen information or approval. Returns the screen after the keys.
        """
        return await run("key", call_id, text=text, repeat=repeat)

    @tool
    async def hold_key(
        text: str,
        duration: Annotated[float, Field(gt=0, le=10, description="seconds")],
        *,
        call_id: CallId,
        needs_confirmation: NeedsConfirmationArg,
        consequence: ConsequenceArg = None,
    ) -> ToolMessage:
        """Hold a key or combo down for duration seconds, then release it. Returns the screen after it."""
        return await run("hold_key", call_id, text=text, duration=duration)

    @tool
    async def wait(
        duration: Annotated[float, Field(ge=0.5, le=60, description="seconds")] = 2.0, *, call_id: CallId,
    ) -> ToolMessage:
        """Pause for duration seconds, then return a screenshot, e.g. while an interface loads."""
        return await run("wait", call_id, duration=duration)

    tools = [
        screenshot,
        zoom,
        *(click_tool(name, what) for name, (_, _, what) in CLICKS.items()),
        left_click_drag,
        mouse_move,
        left_mouse_down,
        left_mouse_up,
        cursor_position,
        scroll,
        tool("type")(type_),
        key,
        hold_key,
        wait,
    ]
    steps = batch_steps({each.name: each.tool_call_schema for each in tools})
    Step = Annotated[dict[str, Any], WithJsonSchema(batch_step_schema(steps))]

    @tool
    async def computer_batch(
        actions: Annotated[list[Step], Field(min_length=1)],
        *,
        call_id: CallId,
        needs_confirmation: NeedsConfirmationArg,
        consequence: ConsequenceArg = None,
    ) -> ToolMessage:
        """Run actions determined from the current observation, then return the results and final screenshot.

        Use this when the actions' effects are predictable from the current observation, such as clicking a visible
        empty document and typing text. Each item uses its action's arguments and full-screen coordinates.
        Actions run in order with settling between inputs, and stop at the first failure or blocked action.
        If a later action depends on confirming an earlier result, end the batch before that later action.
        A wait allows time to pass but gives you no intermediate screenshot within the batch. The final screenshot
        already waits for the screen to settle, so end a batch with a wait only when something slower, such as an app
        starting, must finish first.
        Include only actions that need no approval and set needs_confirmation to false. Send any action needing
        approval in a separate call. If the batch stops partway, inspect its results and screen before continuing;
        do not repeat actions already completed.
        """
        valid = []
        for number, step in enumerate(actions, 1):
            name = step.get("action")
            if name not in steps:
                raise ToolException(f"Nothing was sent: action {number} of {len(actions)}: {name!r} cannot be batched")
            # The arguments a step leaves out come as null under a strict schema.
            given = {key: value for key, value in step.items() if key != "action" and value is not None}
            try:
                valid.append((name, steps[name].model_validate(given).model_dump()))
            except ValidationError as error:
                problems = "; ".join(f"{'.'.join(map(str, each['loc']))}: {each['msg']}" for each in error.errors())
                message = f"Nothing was sent: action {number} of {len(actions)} ({name}): {problems}"
                raise ToolException(message) from error
        return reply(await executor.run_batch(valid), call_id, "computer_batch")

    tools.append(computer_batch)

    @tool
    async def press_while(
        text: str,
        condition: Annotated[str, Field(min_length=1)],
        max_presses: Annotated[int, Field(ge=1, le=50)] = 20,
        *,
        call_id: CallId,
        needs_confirmation: NeedsConfirmationArg,
        consequence: ConsequenceArg = None,
    ) -> ToolMessage:
        """Press a key again and again while a condition still holds on the screen, with no model call between presses.

        Before each press a fast check judges the current screen against the condition, a statement describing the
        screen on which another press is still wanted, e.g. pagedown while "The table does not show the row for
        invoice 1042 yet". It stops when the condition no longer holds, after max_presses, or when a press leaves the
        screen unchanged. Use it to move through many screens that each take the same key; decide yourself where a
        choice is to be made. Returns how many presses were sent and the screen after them.
        """
        return await run("press_while", call_id, text=text, condition=condition, max_presses=max_presses)

    if executor.judge:
        tools.append(press_while)
    for each in tools:
        each.handle_tool_error = True  # rejected input and computer errors reach the model as failed tool results
    return tools


def takeover_tool(control: Control, computer: Computer, on_request: Callable[[str], None]) -> BaseTool:
    @tool
    async def request_takeover(reason: str) -> str:
        """Ask the user to take over the desktop for something only they should do: typing a password or a sign-in
        code, a CAPTCHA, an administrator prompt, payment details, getting past a browser or site safety barrier such
        as a certificate warning. You get the current screen back when they return control."""
        await hand_over(control, computer, "user", reason)
        on_request(reason)
        return "The user now has control. You will get the current screen when they return it."

    return request_takeover
