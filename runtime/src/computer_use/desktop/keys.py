"""Normalize key combos and reject restricted agent input.

Backends and the deny list use the same normalized names, so alternate spellings
cannot bypass the check."""

import re

ALIASES = {
    "ctrl": "ctrl",
    "control": "ctrl",
    "alt": "alt",
    "shift": "shift",
    "win": "win",
    "windows": "win",
    "super": "win",
    "meta": "win",
    "cmd": "win",
    "enter": "enter",
    "return": "enter",
    "esc": "esc",
    "escape": "esc",
    "tab": "tab",
    "space": "space",
    "backspace": "backspace",
    "delete": "delete",
    "del": "delete",
    "insert": "insert",
    "up": "up",
    "down": "down",
    "left": "left",
    "right": "right",
    "home": "home",
    "end": "end",
    "pageup": "pageup",
    "page_up": "pageup",
    "prior": "pageup",
    "pagedown": "pagedown",
    "page_down": "pagedown",
    "next": "pagedown",
}

# Punctuation keys go by their character; models also write the X keysym name.
PUNCTUATION = {
    "slash": "/",
    "backslash": "\\",
    "minus": "-",
    "equal": "=",
    "comma": ",",
    "period": ".",
    "semicolon": ";",
    "apostrophe": "'",
    "grave": "`",
    "bracketleft": "[",
    "bracketright": "]",
}

MODIFIERS = {"ctrl", "alt", "shift", "win"}

# Combos that can end the session the agent works in: the security screen (sign out, lock) and the power user menu
# (shut down, sign out). Apps and scripts are allowed: the Run dialog, Command Prompt and PowerShell are not here.
BLOCKED = {
    frozenset({"win", "x"}): "the power user menu",
    frozenset({"ctrl", "alt", "delete"}): "the security screen",
    frozenset({"ctrl", "alt", "end"}): "the security screen",
}


def normalize_key(token: str) -> str:
    key = token.strip()
    lowered = key.lower()
    if lowered in ALIASES:
        return ALIASES[lowered]
    if lowered[:1] == "f" and lowered[1:].isdigit() and 1 <= int(lowered[1:]) <= 24:
        return f"f{int(lowered[1:])}"
    if key in PUNCTUATION.values():
        return key
    if lowered in PUNCTUATION:
        return PUNCTUATION[lowered]
    if len(key) == 1 and key.isalnum():
        return lowered
    raise ValueError(f"Unknown key {token!r}")


def parse_combos(keys: str) -> list[list[str]]:
    """Parse "ctrl+a Delete" into [["ctrl", "a"], ["delete"]]."""
    combos = [[normalize_key(part) for part in chunk.split("+") if part] for chunk in keys.split()]
    combos = [combo for combo in combos if combo]
    if not combos:
        raise ValueError("No keys given")
    return combos


def parse_modifiers(text: str | None) -> list[str]:
    """Parse the keys held during a click or scroll, e.g. "shift" or "ctrl+shift"."""
    if not text:
        return []
    keys = [normalize_key(part) for part in re.split(r"[+\s]+", text) if part]
    if not keys or any(key not in MODIFIERS for key in keys):
        raise ValueError(f"Hold only ctrl, alt, shift or win during a click or scroll, got {text!r}")
    return keys


def blocked_combo(combos: list[list[str]]) -> str | None:
    for combo in combos:
        target = BLOCKED.get(frozenset(combo))
        if target:
            return f"{'+'.join(combo)} opens {target}"
    return None
