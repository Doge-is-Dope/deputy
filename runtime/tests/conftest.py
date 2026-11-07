import asyncio
import io
import itertools
import json
import os
import socket
import uuid
from pathlib import Path
from functools import cache, partial
from urllib.parse import urlsplit

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, messages_from_dict
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
from computer_use.runner import Runner
from computer_use.agent.background import Background
from computer_use.tools.desktop import desktop_tools
from computer_use.desktop.actions import CONFIRMABLE
from computer_use.agent.trajectory import Trajectory
from computer_use.adapters import build_control
from computer_use.agent.history import in_call_order, with_images
from computer_use.computers import ComputerError, Frame, Status
from computer_use.storage import LOCAL_USER, MAIN, TURN, Runs
from computer_use.files.local import LocalFileStore
from computer_use.storage.files import FileRunStore, FileRuns
from computer_use.sandbox import CodeRunnerError, RunOutput
from computer_use.config import Settings
from computer_use.desktop.control import ControlFile
from computer_use.desktop.executor import Executor

pytest_plugins = ["recording"]  # CU_RECORD_INPUTS: what the scripted models were asked, per test

OBSERVE_CALL = {"type": "tool_call", "name": "screenshot", "args": {}, "id": "call_observe"}


async def restore(store: Runs, run: str, record: dict) -> BaseMessage:
    """A recorded message with its images read back from their files."""
    return await with_images(store, run, messages_from_dict([record])[0])


async def main_messages(store: Runs, run: str) -> list[BaseMessage]:
    """The main agent's recorded messages in one run, in their original order."""
    return [await restore(store, run, event["message"]) for event in await store.events(run)
            if event.get("agent") == MAIN and "message" in event]


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
    Tests marked `model` call a real model API, and those marked `mongo` a database server: they keep the network."""
    if request.node.get_closest_marker("model") or request.node.get_closest_marker("mongo"):
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


@pytest.fixture
def mongo_url():
    """A fresh database on CU_TEST_MONGO_URL (a replica set), dropped after the test."""
    from pymongo import MongoClient

    server = os.environ.get("CU_TEST_MONGO_URL")
    if not server:
        pytest.fail("the mongo tests need CU_TEST_MONGO_URL, e.g. mongodb://localhost:27017/?replicaSet=rs0")
    name = f"test_{uuid.uuid4().hex[:12]}"
    yield urlsplit(server)._replace(path=f"/{name}").geturl()
    with MongoClient(server) as client:
        client.drop_database(name)


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
    monkeypatch.setattr(computer_use.desktop.executor, "RECONNECT_SIGN_IN_SECONDS", 0.01)
    monkeypatch.setattr(computer_use.desktop.screen, "SETTLE_POLL_SECONDS", 0.01)


# The settings of the test at hand, for helpers that take a run's result alone (`logged`).
LAST_SETTINGS: list = [None]


@pytest.fixture(autouse=True)
def no_settle(monkeypatch):
    """Input is answered at once: a test of the wait after an action sets the waits it needs."""
    monkeypatch.setattr(computer_use.desktop.executor, "SETTLE_SECONDS", 0)
    monkeypatch.setattr(computer_use.desktop.screen, "SETTLE_QUIET_SECONDS", 0)
    monkeypatch.setattr(computer_use.desktop.screen, "SETTLE_MAX_SECONDS", 0)


@pytest.fixture(autouse=True)
def remember_settings(request):
    if "settings" in request.fixturenames:
        LAST_SETTINGS[0] = request.getfixturevalue("settings")


# Each store backend a contract test runs on: files, then each database (marked, so left out of plain test runs).
DATABASES = ["", pytest.param("mongo", marks=pytest.mark.mongo)]


@pytest.fixture(params=DATABASES)
def store_settings(request, tmp_path) -> Settings:
    """Settings that pick each store backend in turn, for the `build_*` factories."""
    url = request.getfixturevalue("mongo_url") if request.param == "mongo" else ""
    return Settings(_env_file=None, data_dir=tmp_path, database_url=url)


def file_runs(data_dir: Path) -> FileRunStore:
    """The files store under `data_dir`, with its files beside the records, as the runtime makes it."""
    return FileRunStore(data_dir, LocalFileStore(data_dir))


def runs_dir(data_dir: Path) -> Path:
    """The local user's runs folder in a files store."""
    return data_dir / "users" / LOCAL_USER / "runs"


@pytest.fixture
def store(settings) -> FileRuns:
    return file_runs(settings.data_dir).of(LOCAL_USER)


def runs_of(data_dir: Path, run: str) -> FileRuns:
    """The file store as the user whose run this is sees it, whichever user that was."""
    store = file_runs(data_dir)
    for folder in (data_dir / "users").glob(f"*/runs/{run}"):
        return store.of(folder.parent.parent.name)
    return store.of(LOCAL_USER)


async def listed_runs(client, headers=None) -> list[dict]:
    """Every run the server lists for the asker, newest first: a page of conversations at a time, then each one's
    runs."""
    runs, before = [], None
    while True:
        params = {"limit": "100", **({"before": before} if before else {})}
        page = (await client.get("/api/conversations", params=params, headers=headers)).json()
        for each in page["items"]:
            runs += (await client.get(f"/api/conversations/{each['id']}/runs", headers=headers)).json()
        if page["next"] is None:
            return sorted(runs, key=lambda run: run["started"], reverse=True)
        before = page["next"]


async def listed_sessions(client, headers=None) -> list[dict]:
    """The runs the server lists for the asker that began a session, each with a user's message, newest first."""
    return [run for run in await listed_runs(client, headers) if run["id"] == run["session"]]


def runner_of(settings: Settings, computer, control) -> Runner:
    """A runner of the server's kind, on these."""
    start_turn = partial(main_agent.run_turn, settings, computer=computer, control=control)
    return Runner(file_runs(settings.data_dir), start_turn, title.Titles(settings))


async def run_turn(settings: Settings, message: str, **kwargs) -> main_agent.TurnResult:
    """A turn as `user` (the local user unless given), through the store as they see it."""
    store = file_runs(settings.data_dir).of(kwargs.pop("user", LOCAL_USER))
    kwargs.setdefault("control", build_control(settings))
    return await main_agent.run_turn(settings, message, store=store, **kwargs)


class MemoryFileStore:
    def __init__(self):
        self.kept: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes) -> None:
        self.kept[key] = data

    async def get(self, key: str) -> bytes:
        try:
            return self.kept[key]
        except KeyError:
            raise FileNotFoundError(key) from None

    async def delete_prefix(self, prefix: str) -> None:
        for key in [each for each in self.kept if each.startswith(prefix)]:
            del self.kept[key]


def settings_for(data_dir: Path, database_url: str = "") -> Settings:
    # Ignore any local .env so tests never depend on the developer's machine; no code runner unless a test gives one.
    return Settings(_env_file=None, data_dir=data_dir, database_url=database_url, code_runner_url=None)


@pytest.fixture
def settings(tmp_path) -> Settings:
    return settings_for(tmp_path)


class FakeComputer:
    CODE = "BLUE-HERON-7"

    def __init__(self):
        self.calls: list[tuple] = []
        self.releases = 0  # times every key and button was let go of
        self.closed = False
        self.fail_next: str | None = None
        self.connected = True
        self.screen = lambda: fixture_png(self.CODE)

    async def close(self):
        self.closed = True

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
    bindings: list = []  # bind_tools' tools and keyword arguments, per binding
    disable_streaming: bool = True

    def bind_tools(self, tools, **kwargs):
        self.bindings.append({"tools": tools, **kwargs})
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
    return AIMessage(content="", tool_calls=[tool_call(call_id, "start_task", agent="computer", title="Task", task=task)])


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
    return runs_dir(settings.data_dir) / run


def session_folders(settings, session: str) -> list[Path]:
    """The folders of the logs of the session `session` began: its turns' and its tasks'."""
    folders = []
    for folder in sorted(runs_dir(settings.data_dir).iterdir()):
        events = read_events(folder)
        if events and events[0]["type"] == "start" and events[0].get("session") == session:
            folders.append(folder)
    return folders


def events_of(settings, run: str) -> list[dict]:
    """Everything written from the message that began `run` until the conversation was quiet again: the main
    agent's turns' logs and its tasks', merged in the order written."""
    logged = [(event["time"], order, n, event) for order, folder in enumerate(session_folders(settings, run))
              for n, event in enumerate(read_events(folder))]
    return [event for *_, event in sorted(logged, key=lambda each: each[:3])]


def task_states(settings, run: str) -> list[tuple[str, str]]:
    """Each task of the session `run` began, in time order: (id, "started") as its turn handed it over, then (id, how
    its own log ended: "ended", "stopped" or "error")."""
    states = []
    for folder in session_folders(settings, run):
        events = read_events(folder)
        if events[0]["kind"] == "task":
            states += [(e["time"], events[0]["id"], e["stop_reason"]) for e in events if e["type"] == "end"]
        else:
            states += [(e["time"], e["id"], e["state"]) for e in events if e["type"] == "task"]
    return [(id, state) for _, id, state in sorted(states)]


def task_folder(settings, run: str, id: str) -> Path:
    """The folder of the log of task `id` of the session `run` began."""
    return next(folder for folder in session_folders(settings, run)
                if read_events(folder)[0].get("kind") == "task" and read_events(folder)[0]["id"] == id)


def run_file(settings, run: str, name: str) -> Path:
    """A file written from the message that began `run` on, such as a screenshot an event names."""
    return next((folder / name for folder in session_folders(settings, run) if (folder / name).exists()),
                run_dir(settings, run) / name)


def files_of(settings, run: str) -> set[str]:
    """The names of the files written from the message that began `run` on."""
    return {path.name for folder in session_folders(settings, run) for path in folder.iterdir()
            if path.name != "steps.jsonl"}


def first_run(settings) -> str:
    """The run that began the only conversation there is: its thread."""
    return min(path.name for path in runs_dir(settings.data_dir).iterdir())


def crash_point(settings):
    """How the records are now; calling what this returns puts them back, as a runtime that died here leaves them:
    with nothing a stop writes."""
    kept = {path: path.read_bytes() for path in runs_dir(settings.data_dir).glob("*/steps.jsonl")}

    def died() -> None:
        for path, data in kept.items():
            path.write_bytes(data)

    return died


async def new_log(data_dir: Path) -> Trajectory:
    """A log of a new run in a file store."""
    store = file_runs(data_dir).of(LOCAL_USER)
    return Trajectory(store, await store.create())


def logged(result, kind: str, agent: str | None = None) -> list[dict]:
    """A finished run's logged events of one type, of the computer-use agent (or of the main agent: agent=MAIN)."""
    events = events_of(LAST_SETTINGS[0], result.run)
    return [event for event in events if event["type"] == kind and event.get("agent") == agent]


def computer_use_result(result) -> dict:
    """What came back to the main agent from its first desktop task, shaped as an action event: the runtime's message
    that the task ended (its result's text, its screenshot's file and its artifact), or the start_task call's own
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
    asyncio.run(whole_record(settings.data_dir, finished))


async def whole_record(data_dir: Path, finished) -> None:
    for agent, run, messages in finished:
        store = runs_of(data_dir, run)
        events = await store.events(run)
        if agent == MAIN:
            # Each turn ends with the main agent's messages so far, which its conversation's turns logged up to it; one
            # stopped ends with those up to where it stopped.
            turns = [each.id for each in await store.runs(events[0]["thread"]) if each.kind == TURN and each.id <= run]
            recorded = in_call_order([m for each in turns for m in await main_messages(store, each)])
            replied = any(e["type"] == "end" and e["stop_reason"] == "replied" for e in events)
            assert (recorded == messages) if replied else (recorded[:len(messages)] == messages)
        else:
            # A task's agent's messages are its log's, in order.
            recorded = [await restore(store, run, e["message"]) for e in events
                        if "message" in e and e.get("agent") is None]
            begin = next(n for n, message in enumerate(recorded) if message.id == messages[0].id)
            assert in_call_order(recorded[begin:begin + len(messages)]) == messages


@pytest.fixture
def computer() -> FakeComputer:
    return FakeComputer()


@pytest.fixture
def control(settings) -> ControlFile:
    return ControlFile(settings.control_path)


@pytest.fixture
def executor(computer, control) -> Executor:
    return Executor(computer, control)


@pytest.fixture
async def observe_conversation(executor):
    tools = desktop_tools(executor)
    result = await tools[0].ainvoke(OBSERVE_CALL)
    prompt = "Take a screenshot of the desktop. Then reply with only the fixture code shown on it."
    return tools, [HumanMessage(prompt), AIMessage(content="", tool_calls=[OBSERVE_CALL]), result]


class FakeCodeRunner:
    """Stands in for the code runner: each command's output comes from `answer`, by default "ok" and exit code 0;
    records every command and file, and which task's command it was asked to stop."""

    def __init__(self):
        self.connected = True
        self.commands: list[tuple[str, str]] = []  # (thread, script)
        self.tasks: list[str] = []  # whose each command was
        self.files: dict[str, str] = {}
        self.stops: list[str] = []
        self.answer = lambda script: RunOutput(0, "ok", 0)
        self.closed = False

    async def status(self):
        return Status(self.connected, f"Code runner: {'connected' if self.connected else 'not reachable'}")

    async def run(self, thread, task, script, seconds):
        if not self.connected:
            raise CodeRunnerError("ConnectError: gone")
        self.commands.append((thread, script))
        self.tasks.append(task)
        output = self.answer(script)
        return await output if asyncio.iscoroutine(output) else output

    async def write(self, thread, path, content):
        if path.startswith("/") or ".." in path:
            raise ValueError(f"{path} is outside the working folder")
        self.files[path] = content
        return f"Wrote {path} ({len(content.encode())} bytes)."

    async def stop(self, task):
        self.stops.append(task)

    async def close(self):
        self.closed = True


@pytest.fixture
def code_runner() -> FakeCodeRunner:
    return FakeCodeRunner()
