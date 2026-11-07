"""Run the launchers with fake service executables; no desktop or network is opened."""

import contextlib
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the launchers run in Linux containers")
RUNTIME = Path(__file__).resolve().parents[2]


@pytest.fixture
def launch(tmp_path):
    binaries = tmp_path / "bin"
    binaries.mkdir()

    def executable(name, body):
        path = binaries / name
        path.write_text("#!/bin/sh\nset -eu\n" + body)
        path.chmod(0o755)

    executable("hostname", "echo 127.0.0.1\n")
    for name in ("turnserver", "Xvfb", "xdotool", "python", "rm"):
        executable(name, "exit 0\n")
    executable("xfreerdp3", 'printf "%s\\n" "$@" > "$CAPTURE/rdp.args"\nexec sleep 30\n')
    executable("computer-use-runtime", '''
test -n "$CU_TURN_PASSWORD"
printf "%s\\n" "$@" > "$CAPTURE/api.args"
echo "$$" > "$CAPTURE/api.pid"
if [ "${EXPECT_RDP:-}" = 1 ]; then
    until [ -s "$CAPTURE/rdp.args" ]; do sleep 0.01; done
    printf "%s\\n" "$DISPLAY" "$RDP_KEYBOARD_PIPE" > "$CAPTURE/display"
fi
exit 7
''')
    (binaries / "desktop-entrypoint").symlink_to(RUNTIME / "entrypoint.sh")

    def run(name, **settings):
        env = {key: value for key, value in os.environ.items() if not key.startswith("RDP_")}
        env.update(PATH=f"{binaries}:{os.defpath}", CAPTURE=str(tmp_path), **settings)
        with (tmp_path / "output").open("w+") as output:
            process = subprocess.Popen(["bash", str(RUNTIME / name), "--port", "8123"], env=env,
                                       stdout=output, stderr=output, start_new_session=True)
            try:
                code = process.wait(timeout=5)
            finally:
                # Only the RDP fake leaves a long-lived child after the API exits.
                if process.poll() is None or (tmp_path / "rdp.args").exists():
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=5)
            output.seek(0)
            return code, process.pid, output.read()

    return run, tmp_path


def test_common_entrypoint_needs_no_rdp_configuration_and_execs_the_api(launch):
    run, captured = launch
    code, pid, _ = run("entrypoint.sh")
    assert code == 7
    assert (captured / "api.pid").read_text().strip() == str(pid)
    assert (captured / "api.args").read_text().splitlines() == ["--host", "0.0.0.0", "--port", "8123"]
    assert not (captured / "rdp.args").exists()


def test_rdp_launcher_prepares_the_shared_session_then_execs_the_common_entrypoint(launch):
    run, captured = launch
    code, pid, _ = run("rdp-entrypoint.sh", RDP_HOST="test-host", RDP_USER="test-user", RDP_PASSWORD="test-password",
                       RDP_DOMAIN="test-domain", RDP_DISPLAY=":91", RDP_KEYBOARD_PIPE=str(captured / "keyboard"),
                       RDP_SCREEN_WIDTH="1440", RDP_SCREEN_HEIGHT="900", EXPECT_RDP="1")
    assert code == 7
    assert (captured / "api.pid").read_text().strip() == str(pid)
    assert (captured / "display").read_text().splitlines() == [":91", str(captured / "keyboard")]
    args = (captured / "rdp.args").read_text().splitlines()
    assert "/size:1440x900" in args and "/d:test-domain" in args and "/cert:tofu" in args
    assert f"/kbd:layout:0x00000409,lang:0x0409,pipe:{captured / 'keyboard'},unicode:on" in args
