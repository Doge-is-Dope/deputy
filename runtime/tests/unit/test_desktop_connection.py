"""Desktop ownership follows its own transport, never an optional helper's health."""

import json

import httpx
import pytest

from computer_use.adapters import build_control
from computer_use.computers import ComputerError, Status
from computer_use.config import Settings
from computer_use.desktop.control import ControlSyncError, hand_over
from computer_use.server import create_app


def test_stale_helper_acknowledgement_cannot_gate_desktop_input(tmp_path, monkeypatch):
    monkeypatch.setenv("CU_WINDOWS_AGENT_CONNECTION", str(tmp_path / "missing-helper.json"))
    settings = Settings(_env_file=None, data_dir=tmp_path, database_url="", code_runner_url="")
    control = build_control(settings)
    state = control.write("agent", "returned by user")
    (tmp_path / "windows-agent-control.json").write_text(json.dumps({
        "owner": state.owner, "since": state.since, "ready": False,
        "updated": 0, "error": "Windows agent connection lost",
    }))
    assert control.read().allows_input("agent")


async def test_missing_helper_configuration_cannot_break_startup_or_return(tmp_path, computer, monkeypatch):
    monkeypatch.setenv("CU_WINDOWS_AGENT_CONNECTION", str(tmp_path / "missing-helper.json"))
    settings = Settings(_env_file=None, data_dir=tmp_path, database_url="", code_runner_url="")
    app = create_app(settings, 10, computer)
    async with app.router.lifespan_context(app), httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost",
    ) as client:
        for _ in range(3):
            assert (await client.post("/api/control", json={"owner": "user"})).status_code == 200
            response = await client.post("/api/control", json={"owner": "agent"})
            assert response.status_code == 200
            assert response.json()["owner"] == "agent" and response.json()["ready"]
        status = (await client.get("/api/status")).json()
        assert status["control"]["owner"] == "agent" and status["computer"]["connected"]


async def test_return_refuses_a_disconnected_desktop(control, computer):
    control.write("user", "taken over by user")

    async def disconnected():
        return Status(False, "disconnected")

    computer.status = disconnected
    with pytest.raises(ControlSyncError, match="Reconnect"):
        await hand_over(control, computer, "agent", "returned by user")
    assert control.read().owner == "user"


async def test_http_return_requires_a_fresh_desktop_observation(settings, computer):
    app = create_app(settings, 10, computer)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as client:
        await client.post("/api/control", json={"owner": "user"})
        observed = []
        screenshot = computer.screenshot

        async def unavailable():
            raise ComputerError("capture failed")

        computer.screenshot = unavailable
        failed = await client.post("/api/control", json={"owner": "agent"})
        assert failed.status_code == 503
        assert (await client.get("/api/status")).json()["control"]["owner"] == "user"

        async def capture():
            observed.append(True)
            return await screenshot()

        computer.screenshot = capture
        returned = await client.post("/api/control", json={"owner": "agent"})
        assert returned.status_code == 200 and returned.json()["ready"] and observed == [True]
