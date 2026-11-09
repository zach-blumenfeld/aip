"""Run files and the outcome objects: how a run lives between `aip run` and `aip resume`, and
the one JSON object each prints (`docs/cli-json.md`).

Every run is local (runtime.md: the bundle in an in-memory store, scripts from the cache), and
every stop writes the run file `~/.aip/runs/<run id>.json` (`AIP_HOME` moves it): the engine's
`Run.to_dict()` beside what the client needs to reopen it, the bundle id (the bundle itself is
in the bundle cache, `aip.client.bundles`), the target as given, the working directory, and where
the run is recorded. `aip resume <run id>` works from any directory; a run file's path works in
place of the id. When a server is configured the same run is posted there at every stop, so the
server's record and the run file say the same thing; `recorded` says whether the last post landed.

A run stops one of three ways, and `outcome(run)` is the object the CLI prints for each: paused
(`"paused": "task"`, the one kind), done (`"done": true`) or error (`"error": <kind>`).
`progress_line(entry)` is the `--progress` line for one record entry.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from aip.model.cache import aip_home
from aip.model.engine import DONE, FAILED, PAUSED, Run, utc_now

JSON = dict[str, Any]

EXIT_OK = 0
EXIT_ERROR = 1
RUN_ID = re.compile(r"[A-Za-z0-9_-]{4,64}")


def runs_dir(home: Path | None = None) -> Path:
    return (home or aip_home()).absolute() / "runs"


def run_path(run_id: str, home: Path | None = None) -> Path:
    if not RUN_ID.fullmatch(run_id):
        raise ValueError(f"not a run id: {run_id!r}")
    return runs_dir(home) / f"{run_id}.json"


def new_run_id() -> str:
    return uuid.uuid4().hex[:16]


@dataclass
class RunFile:
    """Everything needed to continue a run. `run` is the engine's `Run.to_dict()`."""
    run_id: str
    bundle_id: str
    name: str                              # the procedure's name
    target: str                            # what `aip run` was given: a folder, an `.rl`, or a catalog reference
    origin: str                            # folder | file | name
    run: JSON
    workdir: str
    revision: str | None = None            # the catalog revision a name resolved to
    server: str | None = None              # where the run is recorded
    recorded: bool = False                 # whether the last stop reached the server
    created: str = field(default_factory=utc_now)
    updated: str = field(default_factory=utc_now)

    @property
    def status(self) -> str:
        return self.run.get("status", "running")

    @property
    def draft(self) -> bool:
        """A run of a folder or a file is recorded as a run of a draft bundle."""
        return self.origin != "name"

    def save(self, path: Path | None = None, home: Path | None = None) -> Path:
        path = path or run_path(self.run_id, home)
        self.updated = utc_now()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{os.getpid()}")
        tmp.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
        return path

    @classmethod
    def load(cls, path: Path) -> "RunFile":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(**data)

    def recording(self) -> JSON:
        """What is posted to the server at every stop (`POST /runs`): the whole run, so the
        server's record is the run file's."""
        return {"run_id": self.run_id, **self.run, "name": self.name, "revision": self.revision, "draft": self.draft,
                "created": self.created, "updated": self.updated}


# ------------------------------------------------------------------ outcomes

def outcome(run: Run, run_id: str | None, run_file: Path | None, recorded: bool | None, resumable: bool = True) -> JSON:
    """The object the CLI prints for where a run stopped (`docs/cli-json.md`)."""
    tail: JSON = {"run_id": run_id, "run_file": str(run_file) if run_file is not None else None}
    if recorded is not None:
        tail["recorded"] = recorded
    if run.status == PAUSED and run.pause is not None:
        pause = run.pause
        return {"paused": pause["kind"], "step": pause["step"], "tasks": pause["tasks"], **tail}
    if run.status == DONE:
        return {"done": True, "result": run.result, **tail}
    if run.status == FAILED and run.error is not None:
        return error_outcome(run.error, run_id, run_file, recorded, resumable)
    raise ValueError(f"a {run.status} run has no outcome to print")


def error_outcome(error: JSON, run_id: str | None, run_file: Path | None, recorded: bool | None, resumable: bool) -> JSON:
    block = {**error, "run_id": run_id, "resumable": resumable}
    if resumable and run_file is not None:
        block["run_file"] = str(run_file)
    if recorded is not None:
        block["recorded"] = recorded
    return block


PROGRESS_KEYS = {"Route": ("to",), "Decide": ("answered_by",), "Execute": ("seconds",), "For": ("exit",), "Loop": ("exit",)}


def progress_line(entry: JSON) -> JSON:
    """One `--progress` line for a record entry: the step, its kind and pass, and the one or two
    fields that say what happened (`to` for a route, `answered_by` for a decision, `seconds` for
    a script, `exit` and `iterations` for a loop)."""
    line: JSON = {"event": "step", "step": entry["step"], "kind": entry["kind"], "pass": entry.get("pass"),
                  "passes": entry.get("passes") or []}
    for key in PROGRESS_KEYS.get(entry["kind"], ()):
        if key in entry:
            line[key] = entry[key]["reason"] if key == "exit" else entry[key]
    if entry["kind"] in ("For", "Loop"):
        line["iterations"] = (entry.get("result") or {}).get("iterations")
    return line


__all__ = ["EXIT_OK", "EXIT_ERROR", "RUN_ID", "RunFile", "runs_dir", "run_path", "new_run_id", "outcome", "error_outcome",
           "progress_line"]
