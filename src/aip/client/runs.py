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
the text `aip runs <run id>` prints: one row per entry, with the runs a step started (its
children) under it.

**Runs started from runs.** A run started by a script of another run (the orchestrator,
`docs/runah.md`) carries `parent` (`{run_id, step, pass}`, from the variables the engine gives
the script) and `depth` (one more than its parent's), and is listed in the parent's children
index, `~/.aip/runs/children/<parent run id>`, one run id a line, so the parent's record can show
it and its budget can count its tokens. `tokens` on a run file is what runah's model spent:
`own` (the tasks it answered in this run), `children` (the `total` of every child) and `total`.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, field
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
    human: list[str] | None = None         # the steps runah leaves to a person (`aip runah --human`), for its later calls
    scripts: bool = True                   # False for a trial, which executes no script and is not recorded
    parent: JSON | None = None             # the run, step and pass whose script started this run: `{run_id, step, pass}`
    depth: int = 0                         # how many runs up the parent chain goes
    budget_tokens: int | None = None       # runah's budget for this run, its children's tokens included (`--budget-tokens`)
    tokens: JSON | None = None             # what runah's model spent: `{own, children, total}`, written at every stop
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
        return cls(**data)

    def recording(self) -> JSON:
        """What is posted to the server at every stop (`POST /runs`): the whole run, so the
        server's record is the run file's. Its `history` is the record's (`recorded_history`):
        a run paused inside a `For` shows the passes it has made."""
        return {"run_id": self.run_id, **self.run, "history": recorded_history(self.run), "name": self.name,
                "revision": self.revision, "draft": self.draft, "workdir": self.workdir, "created": self.created,
                "updated": self.updated, **self.lineage()}

    def lineage(self) -> JSON:
        """What a run says of the runs around it: its parent and depth when a script of another
        run started it, its budget when it has one, and its tokens when runah's model spent any."""
        out: JSON = {}
        if self.parent:
            out.update(parent=self.parent, depth=self.depth)
        if self.budget_tokens is not None:
            out["budget_tokens"] = self.budget_tokens
        if self.tokens and self.tokens.get("total"):
            out["tokens"] = self.tokens
        return out

    def record(self, home: Path | None = None) -> JSON:
        """The run as `aip runs <run id> --json` prints it: the run file, flat, with the history
        as the record shows it (`recorded_history`), and `children`, the runs its scripts
        started that this machine has run files for, when there are any."""
        children = [child_row(c) for c in children_of(self.run_id, home)]
        return {"run_id": self.run_id, "name": self.name, "revision": self.revision, "draft": self.draft, "target": self.target,
                "workdir": self.workdir, "server": self.server, "recorded": self.recorded, "created": self.created,
                "updated": self.updated, **self.run, **self.lineage(),
                "history": recorded_history(self.run), **({"children": children} if children else {})}

    def summary(self) -> JSON:
        """One row of `aip runs`: what the server's list holds for a run, from the run file."""
        return {"run_id": self.run_id, "name": self.name, "revision": self.revision, "status": self.status, "draft": self.draft,
                "identity": self.run.get("identity"), "started": self.run.get("started") or self.created,
                "finished": self.run.get("finished"), "created": self.created, "updated": self.updated, "target": self.target}


def own_tokens(run: JSON) -> int:
    """The model tokens runah spent answering tasks in a run (`Run.to_dict()`): the `total` of
    every entry whose work it observed."""
    return sum(int((e.get("tokens") or {}).get("total") or 0) for e in recorded_history(run)
               if e.get("work") == "observed" and isinstance(e.get("tokens"), dict))


def children_path(run_id: str, home: Path | None = None) -> Path:
    return runs_dir(home) / "children" / run_id


def add_child(parent: str, child: str, home: Path | None = None) -> None:
    """Note in the parent's children index that `child` was started from it."""
    path = children_path(parent, home)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as out:
        out.write(child + "\n")


def children_of(run_id: str, home: Path | None = None) -> list[RunFile]:
    """The runs started from a run's scripts, in the order they started, that have a run file
    here (a child writes its file at its first stop)."""
    path = children_path(run_id, home)
    if not RUN_ID.fullmatch(run_id) or not path.is_file():
        return []
    found = []
    for child in dict.fromkeys(path.read_text(encoding="utf-8").split()):
        try:
            found.append(RunFile.load(run_path(child, home)))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return found


def children_tokens(run_id: str, home: Path | None = None) -> int:
    """What the runs started from a run spent, each its own `total` (which holds its children's)."""
    return sum(int((c.tokens or {}).get("total") or 0) for c in children_of(run_id, home))


def child_row(child: RunFile) -> JSON:
    """A child as its parent's record lists it."""
    parent = child.parent or {}
    return {"run_id": child.run_id, "name": child.name, "status": child.status, "draft": child.draft,
            "step": parent.get("step"), "pass": parent.get("pass"), "tokens": (child.tokens or {}).get("total") or 0,
            "started": child.run.get("started") or child.created}


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
        # what answering took: `observed` by runah of its own model, or `reported` by an outside agent
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


def _child(child: JSON) -> str:
    tokens = f", {child['tokens']} tokens" if child.get("tokens") else ""
    return f"{child.get('run_id')}  {child.get('name')}{' (draft)' if child.get('draft') else ''}  {child.get('status')}{tokens}"


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
    parent = record.get("parent") or {}
    if parent:
        at = f"{parent.get('step')}" + (f" pass {parent['pass']}" if parent.get("pass") is not None else "")
        lines.append(f"  parent    run {parent.get('run_id')} at {at}   depth {record.get('depth') or 1}")
    tokens = record.get("tokens") or {}
    if tokens.get("total") or record.get("budget_tokens") is not None:
        budget = f"   budget {record['budget_tokens']}" if record.get("budget_tokens") is not None else ""
        lines.append(f"  tokens    {tokens.get('total') or 0} (own {tokens.get('own') or 0}, children {tokens.get('children') or 0}){budget}")
    children = list(record.get("children") or [])
    rows = [("STEP", "KIND", "PASS", "WHEN", "+MS", "WHAT")]
    spawned: list[tuple[int, JSON]] = []           # (row, child): a child goes under the entry of the step and pass that started it
    for e in record.get("history") or []:
        passes = " / ".join(f"{p['loop']} {p['pass']}" for p in e.get("passes") or []) or "-"
        ms = str(round(e["seconds"] * 1000)) if isinstance(e.get("seconds"), (int, float)) else ""
        rows.append((e["step"], e["kind"], passes, _when(e.get("at")), ms, _what(e)))
        if e["kind"] == "Execute":
            for child in [c for c in children if c.get("step") == e["step"] and c.get("pass") == e.get("pass")]:
                spawned.append((len(rows) - 1, child))
                children.remove(child)
    widths = [max(len(r[i]) for r in rows) for i in range(5)]
    lines.append("")
    for i, r in enumerate(rows):
        lines.append(f"{r[0].ljust(widths[0])}  {r[1].ljust(widths[1])}  {r[2].ljust(widths[2])}  {r[3].ljust(widths[3])}  "
                     f"{r[4].rjust(widths[4])}  {r[5]}".rstrip())
        lines += [f"  -> run {_child(c)}" for row, c in spawned if row == i]
    lines += [f"  -> run {_child(c)}  (started at {c.get('step')}, whose entry is not written)" for c in children]
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
           "own_tokens", "children_path", "add_child", "children_of", "children_tokens", "child_row",
           "error_outcome", "answer_hint", "progress_line", "run_table"]
