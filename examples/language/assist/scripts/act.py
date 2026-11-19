"""assist's `act` step: carry out the one verb `plan` said, through the aip client. No model is
called here; this script is the allow-list of what assist can do.

stdin `{"state": {"verb": ..., "args": {...}}}`; stdout `{"outcome": "<JSON>"}`, one object whose
`status` says what came of it:

    search   {"query", "limit"?}            -> {"status": "found", "hits": [...]}
    runs     {"run_id"?}                    -> {"status": "listed", "runs": [...]}, or one run's record
    run      {"procedure", "inputs"}        -> {"status": "done" | "paused" | "failed", "run_id", ...}
    resume   {"run_id", "answers"?}         -> the same; no answers retries a failed run
    publish  {"path", "draft"?}             -> {"status": "published", "name", "revision", ...}
    finish   {}                             -> {"status": "finished"}

Anything else, or a verb this list refuses, is `{"status": "refused", "message"}`, and the run of
assist goes on: the next `plan` reads why. Refused always: running or resuming `assist` itself,
and publishing over a name the catalog already has (publish a draft, or choose a new name). There
is no verb to retire, pin or overwrite, so a run of assist never changes what the catalog was.

A child run's pause comes back with its tasks as the runtime gives them, and the text of each
file a task references, so `plan` can answer it with `resume`. The child runs are this run's
agent's and session's (the runtime gives this script `AIP_AGENT` and `AIP_SESSION`), in this
run's working directory, under the script cap like any script: assist waits for nothing longer.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

SELF = "assist"
LONGEST = 120_000                      # characters of outcome plan is shown
VERBS = ("search", "runs", "run", "resume", "publish", "finish")

sys.path.insert(0, str(Path(__file__).resolve().parent))


def emit(outcome: dict) -> None:
    text = json.dumps(outcome, indent=1, ensure_ascii=False)
    if len(text) > LONGEST:
        text = text[:LONGEST] + "\n... (cut: the whole record is `aip runs " + str(outcome.get("run_id")) + " --json`)"
    print(json.dumps({"outcome": text}))


def refused(message: str) -> dict:
    return {"status": "refused", "message": message}


def client():
    from aip import Client

    return Client()


def builtin(name: str) -> Path | None:
    """A procedure aip ships, by name, for a client with no server to resolve names."""
    from aip.server.builtins import builtin_files

    return next((p for p in builtin_files() if p.stem == name), None)


def target_of(c: Any, procedure: str) -> str:
    if c.server is None and not Path(procedure).exists():
        found = builtin(procedure)
        if found is not None:
            return str(found)
    return procedure


def is_self(procedure: str) -> bool:
    text = str(procedure).strip().rstrip("/")
    return text.split("@")[0] == SELF or Path(text).name in (SELF, f"{SELF}.rl")


def result_of(c: Any, call) -> dict:
    """A run's stop as plan reads it."""
    from aip import Done, Paused, RunError
    from aip.chat import pause_view

    try:
        result = call()
    except RunError as exc:
        error = exc.to_json()
        if not exc.stopped:      # an answer refused: nothing changed, the pause stands
            return {"status": "refused", "run_id": exc.run_id, **{k: error[k] for k in ("error", "step", "message") if k in error},
                    "note": "the pause stands; answer it again with resume"}
        return {"status": "failed", "run_id": exc.run_id, **error}
    record = json.loads(Path(result.run_file).read_text(encoding="utf-8"))
    head = {"run_id": result.run_id, "procedure": record.get("name")}
    if isinstance(result, Done):
        return {"status": "done", **head, "result": result.result}
    assert isinstance(result, Paused)
    view = pause_view(c, result)
    return {"status": "paused", **head, "step": result.step, "hint": result.hint, "tasks": view.get("tasks")}


def search(c: Any, args: dict) -> dict:
    from search import entry

    query = str(args.get("query") or "").strip()
    if not query:
        return refused("search needs a query: what the procedure should do")
    if c.server is None:
        from aip.server.builtins import builtin_files

        return {"status": "found", "note": "no server is configured: these are the procedures aip ships",
                "hits": [entry(p.stem, None, c.describe(p).data) for p in builtin_files() if p.stem != SELF]}
    hits = []
    for hit in c.search(query, limit=int(args.get("limit") or 8)):
        if hit.name == SELF:
            continue
        try:
            hits.append(entry(hit.name, hit.revision, c.describe(hit.name).data))
        except Exception as exc:
            hits.append(f"- {hit.name}: {hit.description or ''} (could not describe it: {exc})")
    return {"status": "found", "hits": hits}


def runs(c: Any, args: dict) -> dict:
    if args.get("run_id"):
        from aip.client.runs import RunFile

        record = RunFile.load(c.run_file(str(args["run_id"]))).record()
        keep = ("run_id", "name", "status", "result", "error", "pause", "identity")
        return {"status": "record", **{k: record.get(k) for k in keep if record.get(k) is not None}}
    session = os.environ.get("AIP_SESSION")
    rows = c.runs(session=session) if session else []
    return {"status": "listed", "session": session,
            "runs": [{"run_id": r.run_id, "procedure": r.name, "status": r.status} for r in rows][:30]}


def run(c: Any, args: dict) -> dict:
    procedure = str(args.get("procedure") or "").strip()
    inputs = args.get("inputs") if args.get("inputs") is not None else {}
    if not procedure:
        return refused("run needs a procedure: a published name, or a folder holding procedure.aip")
    if is_self(procedure):
        return refused("assist does not run itself; run the procedure that does the work")
    if not isinstance(inputs, dict):
        return refused("inputs is a JSON object: the procedure's Start inputs")
    return result_of(c, lambda: c.run(target_of(c, procedure), inputs))


def resume(c: Any, args: dict) -> dict:
    run_id = str(args.get("run_id") or "").strip()
    if not run_id:
        return refused("resume needs the run_id of a run this session started")
    from aip.client.runs import RunFile

    try:
        handle = RunFile.load(c.run_file(run_id))
    except Exception as exc:
        return refused(f"no run {run_id!r} here: {exc}")
    if handle.name == SELF:
        return refused("assist does not resume itself")
    return result_of(c, lambda: c.resume(run_id, args.get("answers")))


def publish(c: Any, args: dict) -> dict:
    path = str(args.get("path") or "").strip()
    if not path or not (Path(path) / "procedure.aip").is_file():
        return refused("publish needs the path of a procedure folder (the one holding procedure.aip) under the working directory")
    compiled = c.compile(path)
    if not compiled.ok:
        return refused(f"{path} does not compile: " + "; ".join(str(d) for d in compiled.errors[:5]))
    if c.server is None:
        return refused("no server is configured, so there is no catalog to publish to; run the folder by its path")
    draft = bool(args.get("draft"))
    if not draft:
        from aip.client.server import ServerError

        try:
            c.server.describe(compiled.name)      # the catalog's answer; a folder of that name here is not the catalog
        except ServerError as exc:
            if exc.status != 404:
                return refused(f"cannot ask the catalog whether {compiled.name} is taken: {exc}")
        else:
            return refused(f"the catalog already has {compiled.name}; assist never publishes over a name. Publish it as a "
                           "draft (draft: true) and run it by its folder, or rename the procedure and publish that")
    p = c.publish(path, draft=draft)
    return {"status": "published", "name": p.name, "revision": p.revision, "draft": draft, "bundle_id": p.bundle_id,
            "run_it_as": path if draft else p.name}


def main() -> None:
    state = json.load(sys.stdin)["state"]
    verb, args = state.get("verb"), state.get("args") or {}
    if isinstance(verb, dict):           # a choice arrives as its answer object (spec 2.4): the label is its value
        verb = verb.get("value")
    if verb not in VERBS:
        return emit(refused(f"{verb!r} is not a verb assist has; it has {', '.join(VERBS)}"))
    if not isinstance(args, dict):
        return emit(refused("args is a JSON object"))
    if verb == "finish":
        return emit({"status": "finished"})
    from aip.errors import AipError

    c = client()
    try:
        outcome = {"search": search, "runs": runs, "run": run, "resume": resume, "publish": publish}[verb](c, args)
    except AipError as exc:
        outcome = {"status": "failed", "error": exc.kind, "message": str(exc)}
    emit({"verb": verb, **outcome})


if __name__ == "__main__":
    main()
