"""What every scripted model was asked in each test, for comparing two versions of the runtime. With CU_RECORD_INPUTS
set to a folder, each test writes there one file of its models' calls, normalised so that ids, times and temporary
paths do not count; tests/compare_inputs.py compares two such folders."""

import base64
import hashlib
import json
import os
import re
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool

FOLDER = os.environ.get("CU_RECORD_INPUTS")

# What differs from one run of the same test to the next.
VOLATILE = [
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"), "<uuid>"),
    (re.compile(r"\b[0-9a-f]{32}\b"), "<id>"),
    (re.compile(r"runtime-[0-9a-f]{12}"), "runtime-<id>"),
    (re.compile(r"\b\d+m\d{2}s\b"), "<duration>"),
    (re.compile(r"Today is [^.]+\."), "Today is <date>."),
    (re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?([+-]\d{2}:\d{2}|Z)?"), "<time>"),
    (re.compile(r"/[^\s\"']*pytest-of-[^\s\"']*"), "<tmp>"),
]
TASK_ID = re.compile(r"\bt(\d+)\b")


def stable(text: str) -> str:
    for pattern, replacement in VOLATILE:
        text = pattern.sub(replacement, text)
    return text


def digest(data) -> str:
    raw = data if isinstance(data, bytes) else str(data).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def block(part) -> str:
    if isinstance(part, str):
        return stable(part)
    kind = part.get("type")
    if kind == "text":
        return stable(part.get("text", ""))
    if kind == "image_url":
        return f"<image {digest(part['image_url']['url'])}>"
    if kind == "image":
        data = part.get("base64") or part.get("data") or part.get("url") or part.get("source", {}).get("data", "")
        return f"<image {digest(base64.b64decode(data) if isinstance(data, str) and len(data) > 200 else data)}>"
    return stable(json.dumps(part, sort_keys=True, default=str))


def message(m: BaseMessage) -> dict:
    content = m.content if isinstance(m.content, list) else [m.content]
    shown = {"type": m.type, "content": [block(part) for part in content if part != ""]}
    if isinstance(m, AIMessage) and m.tool_calls:
        shown["tool_calls"] = [
            {"name": c["name"], "args": stable(json.dumps(c["args"], sort_keys=True)), "id": stable(c["id"] or "")}
            for c in m.tool_calls
        ]
    if isinstance(m, ToolMessage):
        shown |= {"tool_call_id": stable(m.tool_call_id), "status": m.status, "name": m.name}
    if runtime := m.additional_kwargs.get("runtime"):
        shown["runtime"] = runtime.get("event")
    return shown


def binding(bound: dict) -> dict:
    tools = []
    for tool in bound.get("tools", []):
        try:
            tools.append(convert_to_openai_tool(tool))
        except Exception:  # a provider's own tool, as a dict already or of a kind the converter does not know
            tools.append(tool if isinstance(tool, dict) else repr(tool))
    rest = {key: value for key, value in bound.items() if key != "tools"}
    return {"tools": stable(json.dumps(tools, sort_keys=True, default=str)),
            "rest": stable(json.dumps(rest, sort_keys=True, default=str))}


def conversation(messages: list[BaseMessage]) -> str:
    """Which conversation a call belongs to: its system prompt's start and its first other message's."""
    system = next((m.text for m in messages if m.type == "system"), "")
    first = next((m.text for m in messages if m.type != "system"), "")
    return stable(f"{system[:60]} | {first[:120]}")


def numbered(calls: list[list[dict]]) -> list[list[dict]]:
    """Task ids renumbered in the order they first appear: tasks handed over together are numbered as they start,
    which depends on scheduling, not on what the model was asked."""
    order: dict[str, str] = {}

    def rename(match):
        return order.setdefault(match.group(0), f"t<{len(order) + 1}>")

    text = json.dumps(calls)
    return json.loads(TASK_ID.sub(rename, text))


@pytest.fixture(autouse=True)
def record_inputs(request, monkeypatch):
    if not FOLDER:
        yield
        return
    from conftest import ScriptedModel

    made: list = []
    init = ScriptedModel.__init__

    def tracked(self, *args, **kwargs):
        init(self, *args, **kwargs)
        made.append(self)

    monkeypatch.setattr(ScriptedModel, "__init__", tracked)
    yield
    groups: dict[str, list] = {}
    for model in made:
        for call in model.received:
            groups.setdefault(conversation(call), []).append([message(m) for m in call])
    record = {
        "calls": {key: numbered(calls) for key, calls in sorted(groups.items())},
        "bindings": sorted(json.dumps(binding(b), sort_keys=True) for model in made for b in model.bindings),
    }
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", request.node.nodeid)
    Path(FOLDER).mkdir(parents=True, exist_ok=True)
    (Path(FOLDER) / f"{name}.json").write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")
