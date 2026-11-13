"""Run files and the outcome objects: how a run lives between `aip run` and `aip resume`, and
the one JSON object each prints (`docs/cli-json.md`).

Every run is local (runtime.md: the bundle in an in-memory store, scripts from the cache), and
every stop writes the run file `~/.aip/runs/<run id>.json` (`AIP_HOME` moves it): the engine's
`Run.to_dict()` beside what the client needs to reopen it, the bundle id (once, at the top; the
bundle itself is in the bundle cache, `aip.client.bundles`), the target as given, the working
directory, and where the run is recorded. `aip resume <run id>` works from any directory; a run
file's path works in place of the id. When a server is configured the same run is posted there
at every stop, so the server's record and the run file say the same thing; `recorded` says
whether the last post landed. `local_runs()` lists the run files, which is what `aip runs`
prints when no server is configured.

A run stops one of three ways, and `outcome(run)` is the object the CLI prints for each: paused
(`"paused": "task"`, the one kind), done (`"done": true`) or error (`"error": <kind>`).
`progress_line(entry)` is the `--progress` line for one history entry, and `run_table(record)`
the text `aip runs <run id>` prints: one row per entry.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from aip.compiler.keywords import ANSWER_TYPES
from aip.model.cache import aip_home
from aip.model.engine import DONE, FAILED, PAUSED, Run, recorded_history, utc_now
from aip.model.types import resumable as retry_can_help

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
    """Everything needed to continue a run. `run` is the engine's `Run.to_dict()`; the file
    holds the bundle id once, at the top."""
    run_id: str
    bundle_id: str
    name: str                              # the procedure's name
    target: str                            # what `aip run` was given: a folder, an `.rl`, or a catalog reference
    origin: str                            # folder | file | name
    run: JSON
    workdir: str
    revision: str | None = None            # the catalog revision: the one a name resolved to, or the one the server holds the bundle as
    server: str | None = None              # where the run is recorded
    recorded: bool = False                 # whether the last stop reached the server
    scripts: bool = True                   # False for a trial, which executes no script and is not recorded
    created: str = field(default_factory=utc_now)
    updated: str = field(default_factory=utc_now)

    @property
    def status(self) -> str:
        return self.run.get("status", "running")

    @property
    def draft(self) -> bool:
        """A run of a bundle with no revision. A folder or a file has none, unless the server
        it was recorded on holds that very bundle as a published revision and said so."""
        return self.revision is None

    @property
    def uploads(self) -> bool:
        """A run of a folder or a file: its bundle is uploaded before the run is recorded, since
        the server may not hold it."""
        return self.origin != "name"

    def save(self, path: Path | None = None, home: Path | None = None) -> Path:
        path = path or run_path(self.run_id, home)
        self.updated = utc_now()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{os.getpid()}")
        data = asdict(self)
        data["run"] = {k: v for k, v in data["run"].items() if k != "bundle_id"}
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
        return path

    @classmethod
    def load(cls, path: Path) -> "RunFile":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        data["run"] = {"bundle_id": data["bundle_id"], **data["run"]}
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})   # a file an earlier 0.9 wrote may hold keys that went

    def recording(self) -> JSON:
        """What is posted to the server at every stop (`POST /runs`): the whole run, so the
        server's record is the run file's. Its `history` is the record's (`recorded_history`):
        a run paused inside a `For` shows the passes it has made."""
        return {"run_id": self.run_id, **self.run, "history": recorded_history(self.run), "name": self.name,
                "revision": self.revision, "draft": self.draft, "workdir": self.workdir, "created": self.created,
                "updated": self.updated}

    def record(self) -> JSON:
        """The run as `aip runs <run id> --json` prints it: the run file, flat, with the history
        as the record shows it (`recorded_history`)."""
        return {"run_id": self.run_id, "name": self.name, "revision": self.revision, "draft": self.draft, "target": self.target,
                "workdir": self.workdir, "server": self.server, "recorded": self.recorded, "created": self.created,
                "updated": self.updated, **self.run,
                "history": recorded_history(self.run)}

    def summary(self) -> JSON:
        """One row of `aip runs`: what the server's list holds for a run, from the run file."""
        return {"run_id": self.run_id, "name": self.name, "revision": self.revision, "status": self.status, "draft": self.draft,
                "identity": self.run.get("identity"), "started": self.run.get("started") or self.created,
                "finished": self.run.get("finished"), "created": self.created, "updated": self.updated, "target": self.target}


def local_runs(home: Path | None = None) -> list[RunFile]:
    """Every run file on this machine, the most recently started first (the order the server
    lists runs in). A file that cannot be read as one is skipped."""
    found = []
    for path in runs_dir(home).glob("*.json"):
        try:
            found.append(RunFile.load(path))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return sorted(found, key=lambda r: r.run.get("started") or r.created, reverse=True)


# ------------------------------------------------------------------ outcomes

def outcome(run: Run, run_id: str | None, run_file: Path | None, recorded: bool | None, resumable: bool = True) -> JSON:
    """The object the CLI prints for where a run stopped (`docs/cli-json.md`). A failure a
    retry would only repeat (`loop_cap`) is not resumable."""
    tail: JSON = {"run_id": run_id, "run_file": str(run_file) if run_file is not None else None}
    if recorded is not None:
        tail["recorded"] = recorded
    if run.status == PAUSED and run.pause is not None:
        pause = run.pause
        return {"paused": pause["kind"], "step": pause["step"], "tasks": pause["tasks"], "hint": answer_hint(pause["tasks"]), **tail}
    if run.status == DONE:
        return {"done": True, "result": run.result, **tail}
    if run.status == FAILED and run.error is not None:
        return error_outcome(run.error, run_id, run_file, recorded, resumable and retry_can_help(run.error))
    raise ValueError(f"a {run.status} run has no outcome to print")


def error_outcome(error: JSON, run_id: str | None, run_file: Path | None, recorded: bool | None, resumable: bool) -> JSON:
    block = {**error, "run_id": run_id, "resumable": resumable}
    if resumable and run_file is not None:
        block["run_file"] = str(run_file)
    if recorded is not None:
        block["recorded"] = recorded
    return block


def answer_hint(tasks: list[JSON]) -> str:
    """One line on how to answer a pause: the shape of one answer (every task of a pause waits
    at the same step, so they share it), and that a bare value is enough for an answer-typed key."""
    task = tasks[0]
    labels = task.get("labels") or {}
    parts = []
    for key, type in (task.get("answer_with") or {}).items():
        if type == "true_or_false":
            value = "true | false"
        elif labels.get(key):
            value = " | ".join(json.dumps(label) for label in labels[key])
        else:
            value = f"<{type or 'value'}>"
        parts.append(f"{json.dumps(key)}: {value}")
    shape = "{" + ", ".join(parts) + "}"
    if len(tasks) == 1:
        text = f"answer with {shape}"
    else:
        text = f'answer all {len(tasks)} tasks at once, by index: {{"0": {shape}, "1": ...}}'
    if any(type in ANSWER_TYPES for type in (task.get("answer_with") or {}).values()):
        text += '; the bare value is enough for a true_or_false, choice or score key ({"value": ...} is the same answer)'
    return text


# ------------------------------------------------------------------ progress and the table

def _answers(result: JSON) -> JSON:
    """A decision's answers as a progress line shows them: the value and the confidence."""
    return {name: {"value": a.get("value"), "confidence": a.get("confidence")} for name, a in (result or {}).items()
            if isinstance(a, dict)}


def _values(result: JSON) -> JSON:
    return {name: a.get("value") if isinstance(a, dict) else a for name, a in (result or {}).items()}


def progress_line(entry: JSON) -> JSON:
    """One `--progress` line for a history entry: the step, its kind and pass, and what happened
    there: a decision's answers (value and confidence) and who answered, an aggregation's
    results, where a route went and whether its check fired, who answered a task, why and where
    a loop exited and after how many passes; `seconds` for every step."""
    kind = entry["kind"]
    line: JSON = {"event": "step", "step": entry["step"], "kind": kind, "pass": entry.get("pass"), "passes": entry.get("passes") or []}
    if kind == "Decide":
        line["answered_by"] = entry.get("answered_by")
        line["answers"] = _answers(entry.get("result") or {})
    elif kind == "Aggregate":
        line["result"] = _values(entry.get("result") or {})
    elif kind == "Route":
        line["to"] = entry.get("to")
        if entry.get("check") is not None:
            line["fired"] = entry["check"]["fired"]
    elif kind == "Task_Agent":
        line["answered_by"] = entry.get("answered_by")
    elif kind in ("For", "Loop"):
        exit = entry.get("exit") or {}
        line["exit"] = exit.get("reason")
        if exit.get("where"):
            line["where"] = exit["where"]
        line["iterations"] = (entry.get("result") or {}).get("iterations")
    if "seconds" in entry:
        line["seconds"] = entry["seconds"]
    return line


def _show(value: Any) -> str:
    return json.dumps(value) if isinstance(value, (bool, int, float)) or value is None else str(value)


def _produced(result: JSON) -> str:
    """What a script or an agent produced, for the table: each key, and for an answer (a
    `true_or_false`, `choice` or `score` key) its value, so a check that failed reads
    `passed=false` and not just `passed`."""
    return ", ".join(f"{k}={_show(v['value'])}" if isinstance(v, dict) and "value" in v else k for k, v in result.items())


def _what(entry: JSON) -> str:
    """The last column of the table: who answered, or where it went and why."""
    kind, result = entry["kind"], entry.get("result") or {}
    if kind == "Decide":
        said = ", ".join(f"{k}={_show(a['value'])} {_show(a['confidence'])}" for k, a in _answers(result).items())
        by = (entry.get("answered_by") or {}).get("model") or "?"
        batch = f", one call for {entry['batch_size']} passes" if entry.get("batched") else ""
        return f"{said}  (by {by}{batch})"
    if kind == "Aggregate":
        return ", ".join(f"{k}={_show(v)}" for k, v in _values(result).items())
    if kind == "Route":
        check = entry.get("check")
        if check and check["fired"]:
            why = "no confidence" if check.get("reason") == "absent" else f"confidence {_show(check['confidence'])}"
            return f"-> {entry.get('to')}  (check fired: {why}, below {_show(check['below'])})"
        passed = f"; confidence {_show(check['confidence'])} not below {_show(check['below'])}" if check else ""
        return f"-> {entry.get('to')}  ({entry.get('read')} is {entry.get('value')}{passed})"
    if kind == "Execute":
        return f"{entry.get('script')} -> {_produced(result) or 'nothing'}"
    if kind == "Task_Agent" and entry.get("work"):
        # what answering took, as the agent reported it (`aip resume --work`; `aip agent` reports its model's)
        by = entry.get("answered_by") or {}
        calls = entry.get("tool_calls")
        if isinstance(calls, list):
            counts = Counter(c.get("name") for c in calls)
            tools = f"{len(calls)} tool call{'' if len(calls) == 1 else 's'}" + (f" ({', '.join(f'{n} {c}' for n, c in counts.items())})" if calls else "")
        else:
            tools = f"{calls} tool call{'' if calls == 1 else 's'}" if isinstance(calls, int) else ""
        tokens = (entry.get("tokens") or {}).get("total")
        seconds = f"{entry['work_seconds']:g}s" if isinstance(entry.get("work_seconds"), (int, float)) else ""
        spent = ", ".join(s for s in (tools, f"{tokens} tokens" if tokens is not None else "", seconds) if s)
        refused = f", {entry['refusals']} refused" if entry.get("refusals") else ""
        model = f" ({by['model']})" if by.get("model") else ""
        return f"answered by {by.get('agent') or '?'}{model}, {entry['work']}: {spent or 'nothing said'}{refused} -> {_produced(result)}"
    if kind == "Task_Agent":
        by = (entry.get("answered_by") or {}).get("agent") or "?"
        waited = entry.get("waited_seconds")
        return f"answered by {by}" + (f" after {waited:.1f}s" if waited is not None else "") + f" -> {_produced(result)}"
    if kind in ("For", "Loop"):
        exit = entry.get("exit") or {}
        where = f" at {exit['where']}" if exit.get("where") else ""
        passes = result.get("iterations")
        return f"exit: {exit.get('reason')}{where}, {passes} pass{'' if passes == 1 else 'es'}"
    return ", ".join((entry.get("input") or {}) if kind == "Start" else result)


def _when(at: str | None) -> str:
    """The time of day of a timestamp, to the millisecond."""
    return at[11:23] if isinstance(at, str) and len(at) >= 23 else (at or "")


def run_table(record: JSON) -> str:
    """`aip runs <run id>`: the run's header, one row per history entry (step, kind, pass, when,
    +ms, who answered or where it went and why), and how it stands. `+ms` is the step's own time
    (`seconds`); a loop's exit entry has none, its time is its passes'."""
    identity = record.get("identity") or {}
    name = f"{record.get('name')}@{record['revision']}" if record.get("revision") else f"{record.get('name')}"
    lines = [f"run {record.get('run_id')}  {name}{'  draft' if record.get('draft') else ''}  {record.get('status')}",
             f"  bundle    {record.get('bundle_id')}"]
    if record.get("target"):
        lines.append(f"  target    {record['target']}")
    version = f" {identity['agent_version']}" if identity.get("agent") and identity.get("agent_version") else ""
    lines.append(f"  agent     {identity.get('agent') or '-'}{version}   session {identity.get('session') or '-'}   user {identity.get('user') or '-'}")
    lines.append(f"  started   {record.get('started') or record.get('created') or '-'}   finished {record.get('finished') or '-'}")
    rows = [("STEP", "KIND", "PASS", "WHEN", "+MS", "WHAT")]
    for e in record.get("history") or []:
        passes = " / ".join(f"{p['loop']} {p['pass']}" for p in e.get("passes") or []) or "-"
        ms = str(round(e["seconds"] * 1000)) if isinstance(e.get("seconds"), (int, float)) else ""
        rows.append((e["step"], e["kind"], passes, _when(e.get("at")), ms, _what(e)))
    widths = [max(len(r[i]) for r in rows) for i in range(5)]
    lines.append("")
    for r in rows:
        lines.append(f"{r[0].ljust(widths[0])}  {r[1].ljust(widths[1])}  {r[2].ljust(widths[2])}  {r[3].ljust(widths[3])}  "
                     f"{r[4].rjust(widths[4])}  {r[5]}".rstrip())
    lines.append("")
    status = record.get("status")
    if status == PAUSED and record.get("pause"):
        pause = record["pause"]
        lines.append(f"paused at {pause['step']} since {pause.get('since') or '-'}: {len(pause['tasks'])} task(s); "
                     f"aip resume {record.get('run_id')} --answers JSON")
    elif status == FAILED and record.get("error"):
        error = record["error"]
        where = error.get("step") or error.get("loop") or "-"
        retry = f"; aip resume {record.get('run_id')} retries it" if retry_can_help(error) else "; a retry would fail the same way"
        lines.append(f"failed at {where}: {error.get('error')}: {error.get('message')}{retry}")
    elif status == DONE:
        lines.append(f"result: {json.dumps(record.get('result'))}")
    return "\n".join(lines) + "\n"


__all__ = ["EXIT_OK", "EXIT_ERROR", "RUN_ID", "RunFile", "runs_dir", "run_path", "new_run_id", "local_runs", "outcome",
           "error_outcome", "answer_hint", "progress_line", "run_table"]
