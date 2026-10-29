import asyncio
import copy
import io
import itertools
import json
import socket
import time
from datetime import datetime
from pathlib import Path
from functools import cache

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.runnables import RunnableLambda
from PIL import Image, ImageDraw, ImageFont

import computer_use.agent.main_agent as main_agent
import computer_use.agent.computer_agent as computer_agent
import computer_use.agent.subagent as subagent
import computer_use.agent.title as title
import computer_use.desktop.control
import computer_use.desktop.executor
import computer_use.desktop.screen
from computer_use.agent.background import Background
from computer_use.agent.tools import desktop_tools
from computer_use.desktop.actions import CONFIRMABLE
from computer_use.agent.trajectory import Trajectory
from computer_use.agent.history import in_call_order, main_messages, restore
from computer_use.computers import ComputerError, Frame, Status
from computer_use.storage import LISTED, LOCAL_USER, MAIN, MAX_HITS, Hit, said, snippet, summarize, supported
from computer_use.storage.files import FileRunStore
from computer_use.sandbox import CodeRunnerError, RunOutput
from computer_use.config import Settings
from computer_use.desktop.control import ControlFile
from computer_use.desktop.executor import Executor

OBSERVE_CALL = {"type": "tool_call", "name": "screenshot", "args": {}, "id": "call_observe"}


@cache
def fixture_png(code: str) -> bytes:
    """A 1280x800 screen with a code drawn only in the image, never in any text."""
    image = Image.new("RGB", (1280, 800), "white")
    ImageDraw.Draw(image).text((24, 70), f"Fixture code: {code}", font=ImageFont.load_default(size=36), fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def no_network(request, monkeypatch):
    """Tests run as in CI, which may be a cloud sandbox: opening an IPv4 or IPv6 socket fails, loopback included.
    Tests marked `model` call a real model API and keep the network."""
    if request.node.get_closest_marker("model"):
        return
    real = socket.socket.__init__

    def offline(*args, **kwargs):
        raise RuntimeError("tests run without a network: fake the transport instead")

    def guarded(self, family=-1, type=-1, proto=-1, fileno=None):
        if fileno is None and family in (-1, socket.AF_INET, socket.AF_INET6):  # -1 opens an IPv4 socket
            offline()
        real(self, family, type, proto, fileno)

    monkeypatch.setattr(socket.socket, "__init__", guarded)
    monkeypatch.setattr(socket, "getaddrinfo", offline)


SCRIPTED_TITLE = "Scripted title"


@pytest.fixture(autouse=True)
def scripted_titles(monkeypatch):
    """Every conversation is named SCRIPTED_TITLE at once (agent.title), by a model that answers nothing else; a test
    of the naming itself puts its own model in `title.build_chat_model`."""
    model = ScriptedModel(messages=itertools.repeat(AIMessage(json.dumps({"title": SCRIPTED_TITLE}))), received=[], bindings=[])
    monkeypatch.setattr(title, "build_chat_model", lambda _spec, _settings, **_: model)


@pytest.fixture
def fast_polls(monkeypatch):
    monkeypatch.setattr(computer_use.desktop.control, "POLL_SECONDS", 0.01)
    monkeypatch.setattr(computer_use.desktop.control, "APPROVAL_POLL_SECONDS", 0.01)
    monkeypatch.setattr(computer_use.desktop.executor, "RECONNECT_POLL_SECONDS", 0.01)
    monkeypatch.setattr(computer_use.desktop.screen, "SETTLE_POLL_SECONDS", 0.01)


# The settings of the test at hand, for helpers that take a run's result alone (`logged`).
LAST_SETTINGS: list = [None]


@pytest.fixture(autouse=True)
def remember_settings(request):
    if "settings" in request.fixturenames:
        LAST_SETTINGS[0] = request.getfixturevalue("settings")


@pytest.fixture
def store(settings) -> FileRunStore:
    return FileRunStore(settings.data_dir)


async def run_turn(settings: Settings, message: str, **kwargs) -> main_agent.TurnResult:
    return await main_agent.run_turn(settings, message, store=FileRunStore(settings.data_dir), **kwargs)


class MemoryRunStore:
    def __init__(self):
        self.listed: dict[str, list[dict]] = {}
        self.deleted: dict[str, list[dict]] = {}
        self.files: dict[str, dict[str, bytes]] = {}
        self._revision = 0
        self._created = 0

    async def create(self) -> str:
        self._created += 1
        run = f"{datetime.now():%Y%m%d-%H%M%S}-{self._created:03d}"
        self.listed[run] = []
        self.files[run] = {}
        self._revision += 1
        return run

    def _events(self, run: str) -> list[dict]:
        return self.listed.get(run) if run in self.listed else self.deleted.get(run, [])

    def append(self, run: str, event: dict) -> tuple[int, dict]:
        events = self._events(run)
        event = {"time": time.time(), **event}
        events.append(event)
        if event["type"] in LISTED:
            self._revision += 1
        return len(events) - 1, event

    def put_file(self, run: str, name: str, data: bytes) -> None:
        self.files.setdefault(run, {})[name] = data

    def has_file(self, run: str, name: str) -> bool:
        return name in self.files.get(run, {})

    async def events(self, run: str, after: int = -1) -> list[dict]:
        return copy.deepcopy(self._events(run)[after + 1:])

    def count(self, run: str) -> int:
        return len(self._events(run))

    async def get_file(self, run: str, name: str) -> bytes:
        try:
            return self.files[run][name]
        except KeyError:
            raise FileNotFoundError(name) from None

    async def summaries(self):
        items = [summarize(run, events) for run, events in self.listed.items() if supported(events)]
        return sorted(items, key=lambda item: item.started, reverse=True)

    async def conversation(self, thread: str, deleted: bool = False, user: str | None = None) -> list[str]:
        place = self.deleted if deleted else self.listed
        return sorted(
            run for run, events in place.items()
            if supported(events) and events[0]["thread"] == thread
            and user in (None, events[0].get("user", LOCAL_USER))
        )

    async def delete(self, thread: str) -> list[str]:
        runs = await self.conversation(thread)
        for run in runs:
            self.deleted[run] = self.listed.pop(run)
        self._revision += bool(runs)
        return runs

    async def restore(self, thread: str) -> list[str]:
        runs = await self.conversation(thread, deleted=True)
        for run in runs:
            self.listed[run] = self.deleted.pop(run)
        self._revision += bool(runs)
        return runs

    async def search(self, query: str, user: str, limit: int = MAX_HITS) -> list[Hit]:
        hits: list[Hit] = []
        for summary in await self.summaries():
            if len(hits) < limit and summary.user == user and all(hit.thread != summary.thread for hit in hits):
                if found := snippet(said(self.listed[summary.id]), query):
                    hits.append(Hit(summary.thread, found))
        return hits

    async def revision(self) -> int:
        return self._revision


@pytest.fixture
def settings(tmp_path) -> Settings:
    # Ignore any local .env so tests never depend on the developer's machine; no code runner unless a test gives one.
    return Settings(
        _env_file=None, data_dir=tmp_path, code_runner_url=None, settle_seconds=0, settle_quiet_seconds=0,
        settle_max_seconds=0,
    )


class FakeComputer:
    CODE = "BLUE-HERON-7"

    def __init__(self):
        self.calls: list[tuple] = []
        self.releases = 0  # times every key and button was let go of
        self.fail_next: str | None = None
        self.connected = True
        self.screen = lambda: fixture_png(self.CODE)

    async def status(self):
        return Status(self.connected, f"Test session: {'connected' if self.connected else 'DISCONNECTED'}")

    async def screenshot(self):
        return Frame.of(self.screen())

    async def image(self):
        return Image.open(io.BytesIO(self.screen())).convert("RGB")

    async def _record(self, *call) -> None:
        if self.fail_next:
            message, self.fail_next = self.fail_next, None
            raise ComputerError(message)
        self.calls.append(call)

    async def click(self, point, button, count, modifiers):
        await self._record("click", point, button, count, list(modifiers))

    async def drag(self, path, modifiers):
        await self._record("drag", list(path), list(modifiers))

    async def move(self, point, settle=True):
        if settle:
            await self._record("move", point)
        else:
            await self._record("move", point, "unsettled")

    async def mouse_button(self, down, button="left"):
        if button == "left":
            await self._record("mouse_button", down)
        else:
            await self._record("mouse_button", down, button)

    async def scroll(self, point, direction, amount, modifiers):
        await self._record("scroll", point, direction, amount, list(modifiers))

    async def type_text(self, text):
        await self._record("type_text", text)

    async def press(self, combos):
        await self._record("press", [list(combo) for combo in combos])

    async def hold(self, combo, seconds):
        await self._record("hold", list(combo), seconds)

    async def key_state(self, key, down):
        await self._record("key_state", key, down)

    async def release_all(self):
        self.releases += 1

    async def next_change(self, seen, timeout):
        await asyncio.sleep(0)  # the fake screen always counts as changed
        return seen + 1

    async def cursor_position(self):
        return 640, 400


class ScriptedModel(GenericFakeChatModel):
    """Sends its replies in turn; records what each call was asked with: the messages and the binding's settings.
    Not streamed, even by the main agent's stream (agent.main_agent): this fake streams a reply's text only, without its tool
    calls."""

    received: list = []  # the messages of each call
    bindings: list = []  # bind_tools' keyword arguments, per binding
    disable_streaming: bool = True

    def bind_tools(self, tools, **kwargs):
        self.bindings.append(kwargs)
        return self

    def with_structured_output(self, schema, **kwargs):
        self.bindings.append(kwargs)

        async def parse(messages):
            raw = await self.ainvoke(messages)
            try:
                return {"raw": raw, "parsed": schema.model_validate_json(raw.text), "parsing_error": None}
            except ValueError as error:
                return {"raw": raw, "parsed": None, "parsing_error": error}

        return RunnableLambda(parse)

    async def ainvoke(self, input, config=None, **kwargs):
        self.received.append(list(input))
        return await super().ainvoke(input, config, **kwargs)


class StreamingModel(ScriptedModel):
    """A scripted model that streams, as the main agent's does: each reply's text a few characters at a time, `pause`
    seconds apart, then its tool calls."""

    disable_streaming: bool = False
    pause: float = 0.0

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        reply = next(self.messages)
        reply = AIMessage(reply) if isinstance(reply, str) else reply
        pieces = [AIMessageChunk(content=reply.text[at:at + 3]) for at in range(0, len(reply.text), 3)]
        pieces += [
            AIMessageChunk(content="", tool_call_chunks=[
                {"name": call["name"], "args": json.dumps(call["args"]), "id": call["id"], "index": index}
            ])
            for index, call in enumerate(reply.tool_calls)
        ]
        pieces = pieces or [AIMessageChunk(content="")]
        pieces[-1].chunk_position = "last"
        for piece in pieces:
            await asyncio.sleep(self.pause)
            yield ChatGenerationChunk(message=piece)


def tool_call(call_id, name, **args):
    """A model's tool call; an input action says it needs no approval unless the test says otherwise."""
    if name in CONFIRMABLE:
        args = {"needs_confirmation": False, **args}
    return {"id": call_id, "name": name, "args": args, "type": "tool_call"}


def delegate(task="Do it.", call_id="m1") -> AIMessage:
    return AIMessage(content="", tool_calls=[tool_call(call_id, "computer_use", title="Task", task=task)])


def use_script(monkeypatch, replies, main=None) -> tuple[ScriptedModel, ScriptedModel]:
    """Runs get a computer-use model that sends these replies in turn, across every task of a run, and a main agent
    that sends `main` (by default: hand the task over, and reply "Done." once it has ended). Returns both
    models, which record what they were asked."""
    computer_model = ScriptedModel(messages=iter(replies), received=[], bindings=[])
    main_model = ScriptedModel(
        messages=iter(main or [delegate(), AIMessage("Done.")]), received=[], bindings=[]
    )
    monkeypatch.setattr(computer_agent, "build_chat_model", lambda _spec, _settings: computer_model)
    monkeypatch.setattr(main_agent, "build_chat_model", lambda _spec, _settings, **_: main_model)
    return computer_model, main_model


def sent_while_pressing(computer, inbox, *texts: str | None, until=None) -> None:
    """Each key press on the desktop has the user send the next of these (None: nothing), as if they wrote while it
    ran. A press that sends one goes on once the main agent has read it, or, with `until`, once that says so."""
    pressed, waiting = computer.press, list(texts)

    async def press(combos):
        if waiting and (text := waiting.pop(0)) is not None:
            message = inbox.put(text)
            done = until or (lambda: MAIN in message.read_by)
            for _ in range(1000):
                if done():
                    break
                await asyncio.sleep(0.01)
        await pressed(combos)

    computer.press = press


def telling(monkeypatch) -> list[str]:
    told, tell = [], Background.tell

    def recorded(self, id, text):
        told.append(text)
        tell(self, id, text)

    monkeypatch.setattr(Background, "tell", recorded)
    return told


def read_events(folder: Path) -> list[dict]:
    try:
        text = (folder / "steps.jsonl").read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    return [json.loads(line) for line in text.split("\n")[:-1] if line]


def run_dir(settings, run: str) -> Path:
    return settings.data_dir / "runs" / run


def new_log(data_dir: Path) -> Trajectory:
    """A log of a new run in a file store, for tests outside an event loop."""
    store = FileRunStore(data_dir)
    return Trajectory(store, asyncio.run(store.create()))


def logged(result, kind: str, agent: str | None = None) -> list[dict]:
    """A finished run's logged events of one type, of the computer-use agent (or of the main agent: agent=MAIN)."""
    events = read_events(run_dir(LAST_SETTINGS[0], result.run))
    return [event for event in events if event["type"] == kind and event.get("agent") == agent]


def computer_use_result(result) -> dict:
    """What came back to the main agent from its first desktop task, shaped as an action event: the runtime's message
    that the task ended (its result's text, its screenshot's file and its artifact), or the computer_use call's own
    result when the task never started."""
    for event in logged(result, "input", MAIN):
        data = event["message"]["data"]
        runtime = data.get("additional_kwargs", {}).get("runtime", {})
        if runtime.get("event") == "task_ended":
            blocks = data["content"][1:]  # after the runtime's line saying the task ended
            text = "\n".join(block["text"] for block in blocks if block.get("type") == "text")
            shot = next((block["file"] for block in blocks if block.get("type") == "image"), None)
            return {"status": "success", "result": text, "screenshot": shot,
                    "message": {"data": {"artifact": runtime["artifact"]}}}
    return logged(result, "action", MAIN)[0]


def handed_back(result) -> dict:
    return computer_use_result(result)["message"]["data"]["artifact"]


def run_folder(settings):
    (folder,) = (settings.data_dir / "runs").iterdir()
    return folder


@pytest.fixture
def the_log_is_the_whole_record(settings, monkeypatch):
    """Every run in a test using this also checks that its log is the record. The main agent's messages read back
    from the conversation's logs are exactly the ones its graph ended with, images included; and each computer-use
    task's messages are in the log, in order, exactly as its graph ended with them."""
    finished = []

    def watched(module, agent):
        real = module.create_agent

        def create_agent(*args, **kwargs):
            graph = real(*args, **kwargs)
            invoke, stream = graph.ainvoke, graph.astream

            async def ainvoke(value, config, **rest):
                state = await invoke(value, config, **rest)
                finished.append((agent, config["metadata"]["run"], state["messages"]))
                return state

            async def astream(value, config, **rest):  # the main agent's, streamed: its last state is what it ends with
                state = None
                async for item in stream(value, config, **rest):
                    if item[0] == "values":
                        state = item[1]
                    yield item
                finished.append((agent, config["metadata"]["run"], state["messages"]))

            graph.ainvoke, graph.astream = ainvoke, astream
            return graph

        monkeypatch.setattr(module, "create_agent", create_agent)

    watched(main_agent, MAIN)
    watched(subagent, None)
    yield
    asyncio.run(whole_record(FileRunStore(settings.data_dir), finished))


async def whole_record(store, finished) -> None:
    for index, (agent, run, messages) in enumerate(finished):
        events = await store.events(run)
        if agent == MAIN:
            # A run's main agent takes turns: each ends with the messages so far, and the last of a run that replied with
            # all of them (one stopped meanwhile logs that its task stopped too).
            runs = [each for each in await store.conversation(events[0]["thread"]) if each <= run]
            recorded = in_call_order(
                [m for each in runs for m in await main_messages(store, each, await store.events(each))]
            )
            later = any(each[:2] == (MAIN, run) for each in finished[index + 1:])
            replied = any(e["type"] == "end" and e["stop_reason"] == "replied" for e in events)
            assert (recorded == messages) if replied and not later else (recorded[:len(messages)] == messages)
        else:
            # Its task's own: tasks at work at once write between each other's lines.
            own = [e for e in events if "message" in e and e.get("agent") is None]
            task = next(e.get("task") for e in own if e["message"]["data"]["id"] == messages[0].id)
            recorded = [await restore(store, run, e["message"]) for e in own if e.get("task") == task]
            begin = next(n for n, message in enumerate(recorded) if message.id == messages[0].id)
            assert in_call_order(recorded[begin:begin + len(messages)]) == messages


@pytest.fixture
def computer() -> FakeComputer:
    return FakeComputer()


@pytest.fixture
def control(settings) -> ControlFile:
    return ControlFile(settings.control_path)


@pytest.fixture
def executor(computer, control, settings) -> Executor:
    return Executor(computer, control, settings)


@pytest.fixture
async def observe_conversation(executor):
    tools = desktop_tools(executor)
    result = await tools[0].ainvoke(OBSERVE_CALL)
    prompt = "Take a screenshot of the desktop. Then reply with only the fixture code shown on it."
    return tools, [HumanMessage(prompt), AIMessage(content="", tool_calls=[OBSERVE_CALL]), result]


class FakeCodeRunner:
    """Stands in for the code runner: each command's output comes from `answer`, by default "ok" and exit code 0;
    records every command and file, and whether it was asked to stop one."""

    def __init__(self):
        self.connected = True
        self.commands: list[tuple[str, str]] = []  # (thread, script)
        self.files: dict[str, str] = {}
        self.stops: list[str] = []
        self.answer = lambda script: RunOutput(0, "ok", 0)
        self.closed = False

    async def status(self):
        return Status(self.connected, f"Code runner: {'connected' if self.connected else 'not reachable'}")

    async def run(self, thread, script, seconds):
        if not self.connected:
            raise CodeRunnerError("ConnectError: gone")
        self.commands.append((thread, script))
        output = self.answer(script)
        return await output if asyncio.iscoroutine(output) else output

    async def write(self, thread, path, content):
        if path.startswith("/") or ".." in path:
            raise ValueError(f"{path} is outside the working folder")
        self.files[path] = content
        return f"Wrote {path} ({len(content.encode())} bytes)."

    async def stop(self, thread):
        self.stops.append(thread)

    async def close(self):
        self.closed = True


@pytest.fixture
def code_runner() -> FakeCodeRunner:
    return FakeCodeRunner()
