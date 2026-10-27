"""Build a task's starting state on Windows through the RDP clipboard, without the agent.

eval.py runs this inside the container with a marker argument and the task's setup steps as JSON on stdin. The steps
become one PowerShell script (setup_script), which Win+R starts from the clipboard; it answers through the clipboard
with "<marker> ok" or "<marker> failed: <error>". Prints JSON with ok/detail."""

import asyncio
import base64
import json
import os
import subprocess
import sys
import time

# Short enough for the Run dialog (259 characters); the script itself has no length limit.
BOOTSTRAP = 'powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command "iex (Get-Clipboard -Raw)"'
REPLY_TIMEOUT = 180  # downloads included
SETTLE_SECONDS = 2.0  # the screen must stay the same this long before the task starts
SETTLE_TIMEOUT = 30.0

# Like the `config` steps of WAA and OSWorld tasks. $docs and $desktop are the user's Documents and Desktop folders,
# wherever they are redirected (OneDrive); $ev is C:\ev, where the tasks keep their files (step_script).
SETUP_SCRIPT = """\
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = 'Tls12'
$docs = [Environment]::GetFolderPath('MyDocuments')
$desktop = [Environment]::GetFolderPath('Desktop')
$ev = 'C:\\ev'
try {{
{steps}
    $result = 'ok'
}} catch {{
    $result = 'failed: ' + $_.Exception.Message
}}
Remove-Item 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\RunMRU' -Recurse -ErrorAction SilentlyContinue
Set-Clipboard -Value ({marker} + ' ' + $result)
"""


def ps(text: str) -> str:
    """A PowerShell string literal."""
    return "'" + text.replace("'", "''") + "'"


def step_script(step: dict) -> str:
    """One setup step as PowerShell: start an app or URL (target, args); close every window (close-windows); set a
    registry value (key, name, value: a DWORD), or reset a Store app's data (package), to put back a setting an earlier
    run changed; or, on a path under ev/ (C:\\ev), docs/ or desktop/, folder, download (url), file (empty, or with
    text), recycle, or open (a file in its app, a folder in Explorer). The tasks keep their files in C:\\ev: the test
    PC's antivirus blocks a script from writing to Documents and the Desktop, which apps and Explorer still may
    (2026-10-19)."""
    if step["type"] == "start":
        args = step.get("args")
        return f"Start-Process {ps(step['target'])}" + (f" -ArgumentList {', '.join(map(ps, args))}" if args else "")
    if step["type"] == "reset-app":  # as Settings > Apps > Reset does; the app needs a moment before it starts again
        return f"Get-AppxPackage {ps(step['package'])} | Reset-AppxPackage; Start-Sleep -Seconds 3"
    if step["type"] == "close-windows":  # without saving: ask each app to close, then end the ones a prompt holds open
        # Not the desktop, nor the console this script runs in.
        return (
            "$keep = 'explorer', 'powershell', 'WindowsTerminal', 'OpenConsole', 'conhost'; "
            "(New-Object -ComObject Shell.Application).Windows() | ForEach-Object { $_.Quit() }; "
            "$open = Get-Process | Where-Object { $_.MainWindowHandle -ne 0 -and $_.Name -notin $keep }; "
            "$open | ForEach-Object { [void]$_.CloseMainWindow() }; Start-Sleep -Seconds 3; "
            "$open | Where-Object { -not $_.HasExited } | Stop-Process -Force -ErrorAction SilentlyContinue"
        )
    if step["type"] == "registry":
        key = ps(step["key"])
        # New-Item -Force on a key that exists would recreate it and drop its other values.
        return (f"if (-not (Test-Path {key})) {{ New-Item -Path {key} -Force | Out-Null }}; "
                f"Set-ItemProperty -Path {key} -Name {ps(step['name'])} -Value {int(step['value'])} -Type DWord")
    folder, *parts = step["path"].split("/")
    if folder not in ("ev", "docs", "desktop"):
        raise ValueError(f"setup paths start with ev/, docs/ or desktop/: {step['path']}")
    target = f"(Join-Path ${folder} {ps('\\'.join(parts))})"
    match step["type"]:
        case "folder":
            return f"New-Item -ItemType Directory -Force -Path {target} | Out-Null"
        case "download":
            return f"Invoke-WebRequest -UseBasicParsing -Uri {ps(step['url'])} -OutFile {target}"
        case "file" if "text" in step:  # as UTF-8 through base64, so any character survives
            data = base64.b64encode(step["text"].encode()).decode()
            return f"[IO.File]::WriteAllText({target}, [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{data}')))"
        case "file":
            return f"New-Item -ItemType File -Force -Path {target} | Out-Null"
        case "recycle":
            return (
                "Add-Type -AssemblyName Microsoft.VisualBasic; [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile("
                f"{target}, 'OnlyErrorDialogs', 'SendToRecycleBin')"
            )
        case "open":
            return f"Start-Process {target}"
    raise ValueError(f"unknown setup step: {step['type']}")


def setup_script(steps: list[dict], marker: str) -> str:
    return SETUP_SCRIPT.format(steps="\n".join(f"    {step_script(step)}" for step in steps), marker=ps(marker))


def clipboard(display: str) -> str:
    proc = subprocess.run(
        ["xclip", "-selection", "clipboard", "-o", "-t", "UTF8_STRING"],
        capture_output=True, text=True, timeout=5, env={**os.environ, "DISPLAY": display},
    )
    return proc.stdout if proc.returncode == 0 else ""


def set_clipboard(display: str, text: str) -> None:
    # xclip keeps a child alive to serve the selection, so it must not hold our pipes.
    subprocess.run(["xclip", "-selection", "clipboard"], input=text.encode(), env={**os.environ, "DISPLAY": display},
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, check=True)


async def settle(computer) -> None:
    """Wait until the screen stops changing: an app the script opened has finished drawing."""
    deadline = time.monotonic() + SETTLE_TIMEOUT
    last, still_since = (await computer.screenshot()).png, time.monotonic()
    while time.monotonic() < deadline and time.monotonic() - still_since < SETTLE_SECONDS:
        await asyncio.sleep(0.5)
        now = (await computer.screenshot()).png
        if now != last:
            last, still_since = now, time.monotonic()


async def main(marker: str, steps: list[dict]) -> dict:
    # Imported here: eval.py imports this file on the Mac only to build and check scripts.
    from computer_use.computers.rdp import RdpComputer
    from computer_use.config import get_settings

    settings = get_settings()
    computer = RdpComputer(settings.display, settings.type_mode)
    set_clipboard(settings.display, setup_script(steps, marker))
    before = (await computer.screenshot()).png
    await computer.press([["win", "r"]])
    await asyncio.sleep(1.5)
    if (await computer.screenshot()).png == before:
        return {"ok": False, "detail": "the Run dialog did not open"}
    await computer.type_text(BOOTSTRAP)  # pastes through the clipboard, then puts the script back
    await computer.press([["enter"]])
    deadline = time.monotonic() + REPLY_TIMEOUT
    while time.monotonic() < deadline:
        await asyncio.sleep(1)
        reply = clipboard(settings.display)
        if reply.startswith(marker):
            await settle(computer)
            status = reply[len(marker):].strip()
            return {"ok": status == "ok", "detail": status}
    return {"ok": False, "detail": f"no reply within {REPLY_TIMEOUT}s"}


if __name__ == "__main__":
    print(json.dumps(asyncio.run(main(sys.argv[1], json.loads(sys.stdin.read()))), ensure_ascii=False))
