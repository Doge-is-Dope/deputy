"""Runtime settings, read from environment variables or `.env`; and the choices a user sends with each run."""

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CU_", env_file=".env", extra="ignore", validate_by_name=True)

    # Also used for step review. Per-run choices override these.
    main_model: str = "openai:gpt-6.1-terra"
    main_effort: str = "medium"
    # Empty values inherit the main agent.
    computer_model: str = "openai:gpt-6.1-terra"
    computer_effort: str = "medium"
    # Independent title model; empty uses agent.title.MODEL.
    title_model: str = ""

    # Provider keys keep their usual names; `.env` is not exported to os.environ.
    anthropic_api_key: SecretStr | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    openai_api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")

    # "none" on the loopback address only, "token" (CU_AUTH_TOKEN), or "proxy": a sign-in proxy names the user in
    # auth_header, believed only from auth_proxies.
    auth: Literal["none", "token", "proxy"] = "none"
    auth_token: SecretStr | None = None
    auth_header: str = "X-Forwarded-User"
    auth_proxies: str = "127.0.0.1/32,::1/128"

    data_dir: Path = Path("data")
    # Runs, projects and memories: empty for files under data_dir, else a database URL whose scheme picks the store.
    database_url: str = ""
    # Shared-volume Unix socket; no coding agent when unset or unreachable.
    code_runner_url: str | None = "unix:///run/code-runner/runner.sock"

    # The RDP backend: the X display showing the session (rdp-entrypoint.sh reads the same RDP_* variables, and
    # sizes the screen with RDP_SCREEN_WIDTH and RDP_SCREEN_HEIGHT; the runtime reads the size off screenshots).
    display: str = Field(default=":1", validation_alias="RDP_DISPLAY")
    keyboard_pipe: Path = Field(default=Path("/tmp/rdp-keyboard"), validation_alias="RDP_KEYBOARD_PIPE")

    web_url: str = "http://localhost:5173"
    # A TURN server the browser relays the live view through when it cannot reach the runtime's own addresses,
    # as from the Mac into a Docker container, e.g. "turn:localhost:3478?transport=tcp".
    turn_url: str | None = None
    turn_password: SecretStr | None = None  # for the user "live"; entrypoint.sh makes a new one each start

    @field_validator("database_url")
    @classmethod
    def _known_database(cls, url: str) -> str:
        database_of(url)
        return url

    @property
    def database(self) -> "Database | None":
        return database_of(self.database_url)

    @property
    def control_path(self) -> Path:
        return self.data_dir / "control.json"

    @property
    def run_lock_path(self) -> Path:
        return self.data_dir / "run.lock"

    @property
    def approval_path(self) -> Path:
        return self.data_dir / "approval.json"


Database = Literal["mongodb"]
DATABASES: dict[str, Database] = {"mongodb": "mongodb", "mongodb+srv": "mongodb"}


def database_of(url: str) -> Database | None:
    """The URL's database, None for files; ValueError for an unsupported scheme."""
    if not url:
        return None
    scheme = url.partition("://")[0]
    if scheme not in DATABASES:
        raise ValueError(f"no store for {scheme}:// (supported: {', '.join(DATABASES)})")
    return DATABASES[scheme]


Approvals = Literal["ask", "auto"]
APPROVALS: tuple[Approvals, ...] = ("ask", "auto")


# A subagent's model or effort that takes the main agent's, whatever it is when the task starts.
FOLLOW = "follow"


@dataclass(frozen=True)
class Choice:
    """An agent's model, as "provider:model", and reasoning effort."""

    model: str
    effort: str


@dataclass(frozen=True)
class RunChoices:
    """Per-message choices held by the browser.

    Missing choices use Settings; FOLLOW inherits the main agent. Model changes apply to the next run; approval
    changes apply to its next flagged step. Memory is off unless sent: a run from the command line or an eval neither
    learns nor follows what the user taught on the page."""

    agents: dict[str, dict[str, str]] = field(default_factory=dict)
    approvals: Approvals = "ask"
    locale: str | None = None
    timezone: str | None = None  # IANA, e.g. "Asia/Taipei"
    learn: bool = False  # the main agent may remember rules from the user's corrections
    recall: bool = False  # the run is told what it remembers, and hands rules over


@lru_cache
def get_settings() -> Settings:
    return Settings()
