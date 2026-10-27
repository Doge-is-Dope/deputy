"""Names and classifications shared by desktop dispatch, tool schemas and confirmation.

Implementations stay in Executor; these are the fixed actions the model can ask for.
"""

# Button, click count, and the name shown with the result.
CLICKS = {
    "left_click": ("left", 1, "Left click"),
    "right_click": ("right", 1, "Right click"),
    "middle_click": ("middle", 1, "Middle click"),
    "double_click": ("left", 2, "Double click"),
    "triple_click": ("left", 3, "Triple click"),
}

# Observations are separate calls; a batch returns only its final screenshot.
BATCHABLE = (
    *CLICKS, "left_click_drag", "mouse_move", "left_mouse_down", "left_mouse_up", "scroll", "type", "key", "hold_key",
    "wait",
)

# These tools must say whether this particular call needs the user's approval.
CONFIRMABLE = (
    *CLICKS, "left_click_drag", "left_mouse_down", "left_mouse_up", "type", "key", "hold_key", "computer_batch",
)
CONFIRM_FIELDS = ("needs_confirmation", "consequence")

# Explicitly classify the remaining tools too, so a new tool cannot silently miss confirmation handling.
NO_CONFIRMATION = ("screenshot", "zoom", "cursor_position", "mouse_move", "scroll", "wait")

# Keyboard input follows focus rather than a point that can be marked on the screen.
KEYBOARD = ("type", "key", "hold_key")

# The batch is a tool which dispatches these primitive actions, rather than a primitive of its own.
ACTIONS = tuple(name for name in (*CONFIRMABLE, *NO_CONFIRMATION) if name != "computer_batch")
