"""The local server, started on demand (plan open item 3).

`aip config server local` points the client at a server on this machine that nobody has to
start: the first call that finds nothing answering on its port starts one (`aip server --local`,
detached from the command that needed it), every later call reuses it, and it stops by itself
when no request has arrived for a while. The next call starts it again; the store is one Relate
file under the user data directory, so nothing is lost in between.

    the address    http://127.0.0.1:8247        AIP_LOCAL_PORT moves the port
    the store      ~/.local/share/aip/server/store.rl   AIP_LOCAL_DATA moves the directory
    the log        local.log beside the store
    idle           900 seconds                  AIP_LOCAL_IDLE changes it (0: never stop)

`aip server --local --stop` stops it by hand (after an upgrade, say: a server that is running
keeps the code it started with).

The store is the one `aip server` opens by default, so a server started by hand on that file is
the same catalog and the same record; only one process may hold the file at a time. `ensure()`
tells an aip server from whatever else may answer on the port by `GET /health`.

A run never fails because of this: when the local server cannot be started (the server extra
or Relate is not installed, the port is taken), the stop is reported as not recorded, with why.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from aip.client.server import ServerError

JSON = dict[str, Any]

LOCAL = "local"
HOST = "127.0.0.1"
PORT_ENV, DATA_ENV, IDLE_ENV = "AIP_LOCAL_PORT", "AIP_LOCAL_DATA", "AIP_LOCAL_IDLE"
DEFAULT_PORT = 8247
DEFAULT_IDLE = 900.0
STORE_FILE = "store.rl"
LOG_FILE = "local.log"
START_WAIT = 30.0          # seconds a client waits for a server it started to answer
EXIT_GRACE = 3.0           # after its own start exited: another client's may be the one coming up


def port() -> int:
    try:
        return int(os.environ.get(PORT_ENV) or DEFAULT_PORT)
    except ValueError:
        return DEFAULT_PORT


def url() -> str:
    return f"http://{HOST}:{port()}"


def data_dir() -> Path:
    """Where the local server keeps its store and its log: `AIP_LOCAL_DATA`, else the directory
    `aip server` uses by default."""
    from aip.server.config import DEFAULT_STORE

    override = os.environ.get(DATA_ENV)
    return Path(override).expanduser() if override else DEFAULT_STORE.expanduser().parent


def store_path() -> Path:
    return data_dir() / STORE_FILE


def log_path() -> Path:
    return data_dir() / LOG_FILE


def idle_seconds() -> float:
    """How long the local server waits with no request before it stops; 0 means it never does."""
    try:
        return max(0.0, float(os.environ.get(IDLE_ENV) or DEFAULT_IDLE))
    except ValueError:
        return DEFAULT_IDLE


def health(at: str | None = None, timeout: float = 1.0) -> JSON | None:
    """What the aip server at `at` says of itself (`GET /health`), or None when nothing answers.
    Something that answers and is not an aip server is a `ServerError`."""
    import httpx

    at = at or url()
    try:
        response = httpx.get(f"{at}/health", timeout=timeout)
    except httpx.HTTPError:
        return None
    try:
        body = response.json()
    except ValueError:
        body = None
    if response.status_code != 200 or not isinstance(body, dict) or "aip" not in body:
        raise ServerError(0, "unreachable", f"something that is not an aip 0.9 server answers at {at}; set {PORT_ENV} to another "
                                            "port for the local server, or stop what is there")
    return body


def _log_tail() -> str:
    try:
        lines = [line for line in log_path().read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
    except OSError:
        return ""
    return lines[-1] if lines else ""


def start() -> subprocess.Popen:
    """Start `aip server --local`, detached: it outlives this command and writes to the log."""
    directory = data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    options: JSON = {}
    if os.name == "nt":
        options["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        options["start_new_session"] = True
    with open(log_path(), "ab") as log:
        return subprocess.Popen([sys.executable, "-m", "aip.client.cli", "server", "--local"], stdin=subprocess.DEVNULL,
                                stdout=log, stderr=log, cwd=str(directory), close_fds=True, **options)


def ensure(wait: float = START_WAIT) -> str:
    """The local server's URL, with a server answering there: the one already running, or one
    started now. `ServerError` (kind `unreachable`) when it cannot be started, with the last
    line of its log."""
    here = url()
    if health(here) is not None:
        return here
    process = start()
    deadline = time.monotonic() + wait
    exited_at: float | None = None
    while time.monotonic() < deadline:
        if health(here, timeout=0.5) is not None:
            return here
        if process.poll() is not None:
            exited_at = exited_at or time.monotonic()
            if time.monotonic() - exited_at > EXIT_GRACE:
                break
        time.sleep(0.1)
    why = _log_tail()
    raise ServerError(0, "unreachable", f"the local server did not start at {here}" + (f": {why}" if why else "")
                      + f" (its log is {log_path()})")


def stop(wait: float = 10.0) -> int | None:
    """Stop the local server if one is running: its pid, or None when nothing answers. A server
    on the port that is not a local one (started by hand with `aip server`) is left alone, as a
    `ServerError`."""
    here = url()
    about = health(here)
    if about is None:
        return None
    pid = about.get("pid")
    if not about.get("local") or not isinstance(pid, int):
        raise ServerError(0, "unreachable", f"the server at {here} was not started on demand; stop it where it was started")
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if health(here, timeout=0.5) is None:
            return pid
        time.sleep(0.1)
    raise ServerError(0, "unreachable", f"the local server (pid {pid}) at {here} did not stop")


__all__ = ["DATA_ENV", "DEFAULT_IDLE", "DEFAULT_PORT", "HOST", "IDLE_ENV", "LOCAL", "PORT_ENV", "data_dir", "ensure", "health",
           "idle_seconds", "log_path", "port", "start", "stop", "store_path", "url"]
