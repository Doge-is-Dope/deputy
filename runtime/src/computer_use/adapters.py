"""Which adapter serves each port, from the settings: the one place that knows them all. The ports know none of their
adapters, which import them."""

from computer_use.computers import Computer
from computer_use.computers.rdp import RdpComputer
from computer_use.config import Settings
from computer_use.desktop.control import ControlFile
from computer_use.desktop.decisions import DecisionsJudge
from computer_use.desktop.judge import ScreenJudge
from computer_use.files import FileStore
from computer_use.files.local import LocalFileStore
from computer_use.memory import MemoryStore
from computer_use.memory.files import FileMemoryStore
from computer_use.memory.mongo import INDEXES as MEMORY_INDEXES, MongoMemoryStore
from computer_use.sandbox import CodeRunner
from computer_use.sandbox.http import HttpCodeRunner
from computer_use.storage import ProjectStore, RunStore
from computer_use.storage.files import FileProjectStore, FileRunStore
from computer_use.storage.mongo import INDEXES as RUN_INDEXES, MongoProjectStore, MongoRunStore, connect


def build_computer(settings: Settings) -> Computer:
    return RdpComputer(settings.display, settings.keyboard_pipe)


def build_control(settings: Settings) -> ControlFile:
    return ControlFile(settings.control_path)


def build_code_runner(settings: Settings) -> CodeRunner | None:
    """The code runner the settings name, or None: the coding agent is then not offered."""
    return HttpCodeRunner(settings.code_runner_url) if settings.code_runner_url else None


def build_screen_judge(settings: Settings) -> ScreenJudge | None:
    """The screen judge, or None: press_while is then not offered."""
    key = settings.openai_api_key
    return DecisionsJudge(key.get_secret_value()) if key else None


def build_file_store(settings: Settings) -> FileStore:
    return LocalFileStore(settings.data_dir)


def build_stores(settings: Settings) -> tuple[RunStore, ProjectStore, MemoryStore]:
    match settings.database:
        case None:
            data_dir = settings.data_dir
            runs = FileRunStore(data_dir, build_file_store(settings))
            return runs, FileProjectStore(data_dir), FileMemoryStore(data_dir)
        case "mongodb":
            database = connect(settings.database_url, RUN_INDEXES | MEMORY_INDEXES)
            runs = MongoRunStore(database, build_file_store(settings))
            return runs, MongoProjectStore(database), MongoMemoryStore(database)
        case other:
            raise ValueError(f"no store for {other}")
