"""Runtime settings, read from environment variables or `.env`; and the choices a user sends with each run."""

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CU_", env_file=".env", extra="ignore", validate_by_name=True)

    # Default main model and effort; also used for step review. Per-run choices override these.
    main_model: str = "openai:gpt-6.1-terra"
    main_effort: str = "medium"
    # Desktop defaults (CU_MODEL/CU_EFFORT); empty values inherit the main agent.
    computer_model: str = Field(default="openai:gpt-6.1-terra", validation_alias="CU_MODEL")
    computer_effort: str = Field(default="medium", validation_alias="CU_EFFORT")
    # Independent title model; empty uses agent.title.MODEL.
    title_model: str = ""

    # Provider keys keep their usual names; `.env` is not exported to os.environ.
    anthropic_api_key: SecretStr | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    openai_api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")

    # Who may use the runtime (computer_use.auth): "none" on the loopback address only, "token" (CU_AUTH_TOKEN), or
    # "proxy": a sign-in proxy names the user in auth_header, believed only from the addresses in auth_proxies.
    auth: Literal["none", "token", "proxy"] = "none"
    auth_token: SecretStr | None = None
    auth_header: str = "X-Forwarded-User"
    auth_proxies: str = "127.0.0.1/32,::1/128"  # comma-separated networks

    data_dir: Path = Path("data")
    # Shared-volume Unix socket; omit the coding agent when unset or unreachable.
    code_runner_url: str | None = "unix:///run/code-runner/runner.sock"

    # The RDP backend: the X display showing the session (entrypoint.sh reads the same RDP_* variables, and
    # sizes the screen with RDP_SCREEN_WIDTH and RDP_SCREEN_HEIGHT; the runtime reads the size off screenshots).
    display: str = Field(default=":1", validation_alias="RDP_DISPLAY")
    keyboard_pipe: Path = Field(default=Path("/tmp/rdp-keyboard"), validation_alias="RDP_KEYBOARD_PIPE")
    # After an action, wait until its effect has drawn and the screen has been still for settle_quiet_seconds,
    # at most settle_max_seconds. If nothing visible changes, stop waiting after settle_seconds.
    settle_seconds: float = 1.5
    settle_quiet_seconds: float = 0.5
    settle_max_seconds: float = 3.0

    # The web page where the user watches and takes over, printed for them to open.
    web_url: str = "http://localhost:5173"
    # A TURN server the browser relays the live view through when it cannot reach the runtime's own addresses,
    # as from the Mac into a Docker container, e.g. "turn:localhost:3478?transport=tcp".
    turn_url: str | None = None
    turn_password: SecretStr | None = None  # for the user "live"; entrypoint.sh makes a new one each start

    # The desktop's control file, run lock and step awaiting approval (see `desktop.control`); a second desktop would
    # get its own set.
    @property
    def control_path(self) -> Path:
        return self.data_dir / "control.json"

    @property
    def run_lock_path(self) -> Path:
        return self.data_dir / "run.lock"

    @property
    def approval_path(self) -> Path:
        return self.data_dir / "approval.json"


# Ask for each flagged step, or review it first (agent.review).
Approvals = Literal["ask", "auto"]
APPROVALS: tuple[Approvals, ...] = ("ask", "auto")


# A subagent's model or effort chosen to be the main agent's, whatever that is when its task starts.
FOLLOW = "follow"


@dataclass(frozen=True)
class Choice:
    """An agent's model, as "provider:model", and reasoning effort."""

    model: str
    effort: str


@dataclass(frozen=True)
class RunChoices:
    """Per-message choices held by the browser: models, efforts, approvals, locale and time zone, and memory.

    Missing choices use Settings; FOLLOW inherits the main agent. Model changes
    apply to the next run; approval changes apply to its next flagged step. Memory is off unless sent: a run from the
    command line or an eval neither learns nor follows what the user taught on the page."""

    agents: dict[str, dict[str, str]] = field(default_factory=dict)
    approvals: Approvals = "ask"
    locale: str | None = None
    timezone: str | None = None  # IANA, e.g. "Asia/Taipei": today's date as the user's clock says
    learn: bool = False  # the main agent may remember rules from the user's corrections
    recall: bool = False  # the run is told what it remembers, and hands rules over


@lru_cache
def get_settings() -> Settings:
    return Settings()
