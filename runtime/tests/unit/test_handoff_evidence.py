from computer_use.agent.history import action_lines, text_entry_screens


def action(number, tool, args, result="", screenshot=None, status="success"):
    return {"type": "action", "n": number, "tool": tool, "args": args,
            "result": result, "screenshot": screenshot, "status": status}


def test_partial_batch_handoff_keeps_completed_and_unsent_steps():
    event = action(1, "computer_batch", {"actions": [
        {"action": "type", "text": "report.txt"}, {"action": "left_click", "coordinate": [10, 10]},
        {"action": "key", "text": "enter"},
    ]}, "Stopped at action 2 of 3: screen changed.\n1. Typed 10 characters.\n"
        "Action 3 was not sent.\nScreen 1280x800; connected.", status="error")
    summary = action_lines([event])[0]
    assert "Stopped at action 2 of 3" in summary
    assert "1. Typed 10 characters." in summary
    assert "Action 3 was not sent." in summary
    assert "Screen 1280x800" not in summary


def test_successful_batch_handoff_includes_last_step_result():
    event = action(1, "computer_batch", {"actions": [
        {"action": "type", "text": "report.txt"}, {"action": "left_click", "coordinate": [10, 10]},
    ]}, "1. Typed 10 characters.\n2. Left click at (10, 10).\nScreen 1280x800; connected.")
    assert "2. Left click at (10, 10)." in action_lines([event])[0]


def test_checkpoints_keep_pre_entry_full_screens_not_zoom_or_main_images():
    events = [
        {"type": "input", "message": {"data": {"content": [
            {"type": "image", "file": "initial.png"},
        ]}}},
        action(1, "type", {"text": "content"}, screenshot="document.png"),
        action(2, "key", {"text": "F12"}, screenshot="save-dialog.png"),
        action(3, "zoom", {"region": [0, 0, 10, 10]}, screenshot="crop.png"),
        {"type": "input", "agent": "main", "message": {"data": {"content": [
            {"type": "image", "file": "other-task.png"},
        ]}}},
        action(4, "computer_batch", {"actions": [
            {"action": "type", "text": "report.txt"}, {"action": "key", "text": "enter"},
        ]}, screenshot="saved.png"),
    ]
    assert text_entry_screens(events) == [(1, "initial.png"), (4, "save-dialog.png")]
    assert text_entry_screens(events, limit=1) == [(4, "save-dialog.png")]
    assert text_entry_screens(events, limit=0) == []
