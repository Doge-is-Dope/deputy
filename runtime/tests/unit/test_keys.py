import pytest

from computer_use.desktop.keys import blocked_combo, parse_combos, parse_modifiers


def test_combos_normalize_to_one_set_of_names():
    assert parse_combos("ctrl+S win Super Enter Return alt+F4 PageDown Next Esc ctrl+/") == [
        ["ctrl", "s"], ["win"], ["win"], ["enter"], ["enter"], ["alt", "f4"], ["pagedown"], ["pagedown"],
        ["esc"], ["ctrl", "/"],
    ]
    assert parse_combos("ctrl+shift+comma ctrl+period ctrl+.") == [["ctrl", "shift", ","], ["ctrl", "."], ["ctrl", "."]]
    assert parse_modifiers("Control+Windows") == ["ctrl", "win"]


def test_unknown_or_empty_keys_are_rejected():
    with pytest.raises(ValueError):
        parse_combos("ctrl+banana")
    with pytest.raises(ValueError):
        parse_combos("   ")


@pytest.mark.parametrize("keys", ["super+x", "Windows+X", "ctrl+alt+end", "ctrl+alt+delete"])
def test_session_ending_combos_are_blocked_under_any_spelling(keys):
    assert blocked_combo(parse_combos(keys))


def test_ordinary_input_and_system_tools_are_allowed():
    assert blocked_combo(parse_combos("ctrl+s alt+f4 win+r ctrl+shift+esc")) is None
