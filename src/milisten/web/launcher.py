"""One-command launcher, following the prview pattern.

Picks a free loopback port, mints a session token, wires it into the app, then
runs uvicorn on 127.0.0.1 and opens the browser at the token-carrying URL. Binds
127.0.0.1 only — never 0.0.0.0.

`run` is foreground. `start` / `stop` / `open` manage a detached server through a
daemon file at ~/.milisten/daemon.json, so `start` returns immediately and the
server outlives the calling shell.
"""

from __future__ import annotations

import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from ..library import home

HOST = "127.0.0.1"
BROWSER_DELAY = 0.7
START_TIMEOUT = 25.0
STOP_TIMEOUT = 5.0
POLL = 0.1

def daemon_file() -> Path:
    return home() / "daemon.json"


def daemon_log() -> Path:
    return home() / "daemon.log"


def pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        return sock.getsockname()[1]


def mint_token() -> str:
    return secrets.token_urlsafe(32)


def build_launch_url(port: int, token: str) -> str:
    return f"http://{HOST}:{port}/?token={token}"


def schedule_browser_open(url: str, delay: float = BROWSER_DELAY) -> threading.Timer:
    timer = threading.Timer(delay, lambda: webbrowser.open(url))
    timer.daemon = True
    timer.start()
    return timer


def read_daemon_state() -> dict | None:
    try:
        return json.loads(daemon_file().read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def secure_home() -> Path:
    """The daemon file holds the session token, and that token is enough to read any
    file this user can read (add a local path as a source, then preview it)."""
    root = home()
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o700)
    return root


def open_private(path: Path, append: bool = False) -> int:
    flags = os.O_WRONLY | os.O_CREAT | (os.O_APPEND if append else os.O_TRUNC)
    fd = os.open(path, flags, 0o600)
    os.fchmod(fd, 0o600)  # a pre-existing file keeps its old mode without this
    return fd


def write_daemon_state(state: dict) -> None:
    secure_home()
    with os.fdopen(open_private(daemon_file()), "w") as handle:
        json.dump(state, handle)


def clear_daemon_state() -> None:
    daemon_file().unlink(missing_ok=True)


def pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def live_daemon() -> dict | None:
    state = read_daemon_state()
    if state and pid_is_alive(state.get("pid", -1)):
        return state
    if state:
        clear_daemon_state()
    return None


def port_is_open(port: int, timeout: float = 0.25) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((HOST, port)) == 0


def serve(port: int, token: str, open_browser: bool, announce: bool = True) -> None:
    import uvicorn

    from . import server

    server.set_session_token(token)
    url = build_launch_url(port, token)
    if announce:
        print(f"milisten ui  →  {url}")
    if open_browser:
        schedule_browser_open(url)
    uvicorn.run(server.app, host=HOST, port=port, log_level="warning")


def _run(port: int, open_browser: bool) -> int:
    serve(port or pick_free_port(), mint_token(), open_browser)
    return 0


def _start(port: int, open_browser: bool) -> int:
    existing = live_daemon()
    if existing:
        print(f"already running: {existing['url']}")
        if open_browser:
            webbrowser.open(existing["url"])
        return 0

    chosen = port or pick_free_port()
    token = mint_token()
    secure_home()
    with os.fdopen(open_private(daemon_log(), append=True), "ab", buffering=0) as log:
        # The token goes over stdin, never argv: a command line is world-readable
        # through `ps`, and this token grants local file reads via preview.
        child = subprocess.Popen(
            [sys.executable, "-m", "milisten.web", str(chosen)],
            stdout=log,
            stderr=log,
            stdin=subprocess.PIPE,
            start_new_session=True,
        )
    with child.stdin as handle:
        handle.write(f"{token}\n".encode())

    deadline = time.time() + START_TIMEOUT
    while time.time() < deadline:
        if port_is_open(chosen):
            url = build_launch_url(chosen, token)
            write_daemon_state({"pid": child.pid, "port": chosen, "token": token, "url": url})
            print(f"milisten ui  →  {url}")
            if open_browser:
                webbrowser.open(url)
            return 0
        if child.poll() is not None:
            print(f"server exited early; see {daemon_log()}", file=sys.stderr)
            return 69
        time.sleep(POLL)

    child.terminate()
    print(f"server did not come up within {START_TIMEOUT:.0f}s; see {daemon_log()}", file=sys.stderr)
    return 69


def _stop() -> int:
    state = live_daemon()
    if not state:
        print("not running")
        return 0
    pid = state["pid"]
    os.kill(pid, signal.SIGTERM)
    deadline = time.time() + STOP_TIMEOUT
    while time.time() < deadline and pid_is_alive(pid):
        time.sleep(POLL)
    if pid_is_alive(pid):
        os.kill(pid, signal.SIGKILL)
    clear_daemon_state()
    print("stopped")
    return 0


def _open() -> int:
    state = live_daemon()
    if not state:
        print("not running — try `milisten ui start`", file=sys.stderr)
        return 1
    webbrowser.open(state["url"])
    print(state["url"])
    return 0


def dispatch(action: str, port: int = 0, open_browser: bool = True) -> None:
    code = {
        "run": lambda: _run(port, open_browser),
        "start": lambda: _start(port, open_browser),
        "stop": _stop,
        "open": _open,
    }[action]()
    if code:
        raise SystemExit(code)
