"""launchd agent so the UI is always up at one bookmarkable URL.

The per-launch token that suits a one-session server would invalidate a bookmark
on every login, so the agent runs with the stable token from ~/.milisten/token.
Loopback binding is unchanged: this makes the server persistent, not reachable.
"""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

from ..library import home
from .launcher import HOST, secure_home, stable_token

LABEL = "io.lefv.milisten"
DEFAULT_PORT = 8765


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def agent_log() -> Path:
    return home() / "agent.log"


def executable() -> str:
    """Prefer the installed console script; a venv python -m fallback keeps dev usable."""
    found = shutil.which("milisten")
    return found or sys.executable


def plist_body(port: int, program: str | None = None) -> dict:
    binary = program or executable()
    args = (
        [binary, "ui", "run", "--port", str(port), "--stable-token", "--no-browser"]
        if Path(binary).name == "milisten"
        else [binary, "-m", "milisten.cli", "ui", "run", "--port", str(port),
              "--stable-token", "--no-browser"]
    )
    return {
        "Label": LABEL,
        "ProgramArguments": args,
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Background",
        "StandardOutPath": str(agent_log()),
        "StandardErrorPath": str(agent_log()),
        "WorkingDirectory": str(Path.home()),
    }


def url(port: int) -> str:
    return f"http://{HOST}:{port}/?token={stable_token()}"


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, check=False)


def is_loaded() -> bool:
    return _launchctl("list", LABEL).returncode == 0


def install(port: int = DEFAULT_PORT) -> tuple[int, str]:
    if sys.platform != "darwin":
        return 69, "launchd agents are macOS-only; use systemd --user on Linux"

    secure_home()
    target = plist_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as handle:
        plistlib.dump(plist_body(port), handle)

    uid = os.getuid()
    if is_loaded():
        _launchctl("bootout", f"gui/{uid}/{LABEL}")
    result = _launchctl("bootstrap", f"gui/{uid}", str(target))
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        return 69, f"launchctl bootstrap failed: {detail}"
    return 0, url(port)


def uninstall() -> tuple[int, str]:
    uid = os.getuid()
    if is_loaded():
        _launchctl("bootout", f"gui/{uid}/{LABEL}")
    existed = plist_path().exists()
    plist_path().unlink(missing_ok=True)
    return 0, "agent removed" if existed else "no agent was installed"


def status(port: int = DEFAULT_PORT) -> tuple[int, str]:
    if not plist_path().exists():
        return 1, "not installed — run `milisten agent install`"
    if not is_loaded():
        return 1, f"installed but not loaded; see {agent_log()}"
    return 0, f"running — {url(port)}"
