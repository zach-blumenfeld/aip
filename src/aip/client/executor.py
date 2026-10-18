"""The client runs every execution step: next to the data, in this process's machine.

A run's loop (`aip.model.engine`, on the server or in this process) stops at an execution step
with a request: the script as the SKILL.md names it, its launch command, the rendered stdin,
the timeout, and the skill's `requires`. `Executor.perform` checks `requires` against this
machine (once per run of the client), runs the script from its folder under the skill root
with `AIP_WORKDIR` set to the run's working directory, and returns the report the loop
continues with: `{"output": {...}, "seconds"}`, or a failure with its detail
(`script_failed` with exit code and stderr, `timeout`, `requires_unmet` with what is missing).
The loop checks the output against the step's declared outputs.

For a skill folder the skill root is the folder. For a served run it is the revision's
`scripts/` and `assets/`, fetched once into `~/.aip/cache/<name>@<revision>/` (`AIP_HOME`
moves it) and verified file by file against the server's manifest; `SKILL.md` is never
fetched: the client needs the files the scripts use, not the graph.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List

from aip.model.environment import Requires
from aip.model.steps import launch, run_script
from aip.model.types import StepError

JSON = Dict[str, Any]

# The folders of a revision a client fetches to run its scripts.
FETCHED = ("scripts", "assets")


class Executor:
    """Runs execution requests for one run. `root` is the skill root the request's `script` is
    relative to; `workdir` is the run's working directory; `python` runs a `python` launcher
    (default this process's own interpreter)."""

    def __init__(self, root: Path, workdir: Path, python: Path | None = None):
        self.root = Path(root).resolve()
        self.workdir = Path(workdir)
        self.python = python
        self._met: set[str] = set()

    def perform(self, request: JSON) -> JSON:
        """Run one execution request and report what happened."""
        step, script = request["step"], request["script"]
        try:
            self._check(step, request.get("requires"))
            path = (self.root / script).resolve()
            if self.root not in path.parents or not path.is_file():
                raise FileNotFoundError(f"script {script} not found under {self.root}")
            began = time.monotonic()
            output = run_script(step, script, launch(request.get("command"), path, self.python), request["stdin"],
                                path.parent, request.get("timeout"), self.workdir)
        except StepError as exc:
            return {"error": exc.kind, "message": str(exc), **exc.fields()}
        except OSError as exc:
            return {"error": "script_failed", "message": f"{type(exc).__name__}: {exc}", "script": script,
                    "exit_code": -1, "stderr": str(exc)}
        return {"output": output, "seconds": round(time.monotonic() - began, 3)}

    def _check(self, step: str, declared: JSON | None) -> None:
        """`requires` against this machine; a passing check is not repeated."""
        if not declared:
            return
        key = json.dumps(declared, sort_keys=True)
        if key in self._met:
            return
        Requires(interpreter=declared["interpreter"], version=declared.get("version"),
                 packages=list(declared.get("packages") or []),
                 tools=list(declared.get("tools") or [])).ensure(step, self.python)
        self._met.add(key)


# ----------------------------------------------------------------------------- cache


def cache_dir(name: str, revision: str) -> Path:
    """Where a served revision's `scripts/` and `assets/` are kept on this machine."""
    from aip.client.runner import aip_home

    return aip_home() / "cache" / f"{name}@{revision}"


def fetch(server: Any, name: str, revision: str) -> Path:
    """The revision's `scripts/` and `assets/` on this machine, fetched once and verified.

    The server's manifest names every file with its sha256 and mode; the client fetches only
    the files under `scripts/` and `assets/`, checks each hash (the first mismatch aborts, naming
    the file), and moves the folder into place in one step. A cached copy is re-verified against
    the manifest on every call and fetched again if anything differs."""
    from aip.client.server import ServerError

    ref = f"{name}@{revision}"
    wanted = [e for e in server.get(f"/catalog/{ref}/files") if e["path"].split("/", 1)[0] in FETCHED]
    target = cache_dir(name, revision)
    if target.is_dir() and _matches(target, wanted):
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f".{ref}-", dir=target.parent))
    try:
        for entry in wanted:
            data = server.file(ref, entry["path"])
            digest = hashlib.sha256(data).hexdigest()
            if digest != entry["sha256"]:
                raise ServerError(0, "hash_mismatch", f"{ref}/{entry['path']}: sha256 {digest[:12]}… does not "
                                                      f"match the manifest's {entry['sha256'][:12]}…",
                                  location=entry["path"])
            path = tmp / entry["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            path.chmod(int(entry["mode"]) & 0o777)
        shutil.rmtree(target, ignore_errors=True)
        tmp.rename(target)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return target


def _matches(folder: Path, entries: List[JSON]) -> bool:
    for entry in entries:
        path = folder / entry["path"]
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            return False
    return True


__all__ = ["Executor", "FETCHED", "cache_dir", "fetch"]
