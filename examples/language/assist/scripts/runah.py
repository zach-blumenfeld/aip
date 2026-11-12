"""assist's `act` step: run what the planner chose through the aip client, and wait on it.

stdin `{"state": {"run": ..., "inputs": "<JSON>"}}`; stdout `{"outcome": "<JSON>"}`, one object:

    {"status": "done",    "run_id", "procedure", "result", "published"?}
    {"status": "paused",  "run_id", "procedure", "step", "hint", "tasks", "why"}
    {"status": "failed",  "run_id", "procedure", "error", "step", "message", "resumable"}
    {"status": "running", "run_id", "procedure", "message"}
    {"status": "refused", "message"}

`run` is a procedure (a published name, a folder, an `.rl`) to start with `inputs`, or the run
id of a run this script started before, to carry on: `{"answers": ...}` goes into its pause,
`{}` waits on it while it is going, retries it when it failed, and has the model answer the
pause when it is paused.

**The verbs, and the guard.** These are the only things the orchestrator can do: start a run
with `Client.runah`, carry one on with `Client.runah(run_id, answers=...)`, and, when a run of
`build_procedure` is done, publish the folder it built under its new name (`Client.publish`). A
name the catalog already has is not published over: the folder is uploaded as a draft instead and
run by its path. Nothing here retires or pins, and `assist` itself is refused, so a run never
changes the catalog it was given and never starts itself.

**The wait.** A child can take longer than the script cap (`AIP_SCRIPT_TIMEOUT`, which the
engine gives every script). So the child runs in a process of its own, started detached, that
writes the outcome to `<workdir>/.assist/<run id>.json` when the child stops; this script waits on
that file until a little before the cap, and if the child is still going it says `running` and
the planner's next pass waits again. The child is an ordinary run with a run file, started from
this run's script, so it is this run's child (`parent` in its record) and one level deeper; it
runs ahead with runah, with the steps a person answers (by their description, "a person" or "the
person") left to the planner, which answers them or asks the person.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SELF = "assist"
BUILDER = "build_procedure"
SPOOL = ".assist"
PERSON = re.compile(r"\b(a|the) person\b", re.IGNORECASE)
LONGEST = 20_000                       # characters of outcome the planner is shown


def emit(outcome: dict) -> None:
    text = json.dumps(outcome, indent=1)
    if len(text) > LONGEST:
        text = text[:LONGEST] + "\n... (cut: the whole record is `aip runs " + str(outcome.get("run_id")) + " --json`)"
    print(json.dumps({"outcome": text}))


def refuse(message: str) -> None:
    emit({"status": "refused", "message": message})


def workdir() -> Path:
    return Path(os.environ.get("AIP_WORKDIR") or ".").resolve()


def spool(run_id: str) -> Path:
    return workdir() / SPOOL / f"{run_id}.json"


def patience() -> float | None:
    """Seconds this script may wait: a little under the cap it runs under; None when uncapped."""
    raw = os.environ.get("AIP_SCRIPT_TIMEOUT", "").strip()
    try:
        cap = float(raw) if raw else 300.0
    except ValueError:
        cap = 300.0
    if cap <= 0:
        return None
    return max(cap - max(2.0, min(15.0, cap * 0.1)), 0.5)


# ------------------------------------------------------------------ the child's own process


def outcome_of(result: Any, client: Any) -> dict:
    """A run's stop as the planner reads it."""
    import aip
    from aip.client.runs import RunFile, run_path

    if isinstance(result, aip.Done):
        name = RunFile.load(result.run_file).name if result.run_file else None
        out = {"status": "done", "run_id": result.run_id, "procedure": name, "result": result.result}
        if name == BUILDER:
            out["published"] = publish_built(result.result, client)
        return out
    if isinstance(result, aip.Paused):
        name = RunFile.load(result.run_file).name
        tasks = [{"index": t.index, "prompt": t.prompt, "state": t.state, "answer_with": t.answer_with, "labels": t.labels}
                 for t in result.tasks]
        why = (result.answerer or {}).get("reason") or "it waits for an answer"
        return {"status": "paused", "run_id": result.run_id, "procedure": name, "step": result.step, "hint": result.hint,
                "tasks": tasks, "why": why}
    raise TypeError(f"not a result: {result!r}")


def publish_built(result: dict, client: Any) -> dict:
    """The folder build_procedure built, published under its new name; uploaded as a draft when
    the catalog has that name (never published over it), or left as a folder with no server."""
    folder = workdir() / (result.get("path") or "")
    name = result.get("procedure") or folder.name
    if client.server is None:
        return {"as": "folder", "run_with": str(folder), "message": "no server is configured: run it by its folder"}
    taken = {entry.name for entry in client.list()}
    if name in taken:
        draft = client.publish(folder, draft=True)
        return {"as": "draft", "run_with": str(folder), "bundle_id": draft.bundle_id,
                "message": f"the catalog already has {name}; this one is a draft, run it by its folder"}
    published = client.publish(folder)
    return {"as": "revision", "run_with": published.name, "name": published.name, "revision": published.revision,
            "message": f"published as {published.name}@{published.revision}: run it by that name"}


def child(order_file: str) -> int:
    """The detached process: run the order, write the outcome where the waiting script looks."""
    import aip
    from aip.client.runs import RunFile, run_path

    order = json.loads(Path(order_file).read_text(encoding="utf-8"))
    run_id = order["run_id"]
    client = aip.Client()
    try:
        if order["start"]:
            target = order["target"]
            steps = client.describe(target).steps
            human = [s["name"] for s in steps if s.get("kind") == "Task_Agent" and PERSON.search(s.get("description") or "")]
            result = client.runah(target, order["inputs"], human=human, run_id=run_id, workdir=workdir())
        else:
            result = client.runah(run_id, answers=order.get("answers"))
        out = outcome_of(result, client)
    except aip.RunError as err:
        error = err.to_json()
        name = None
        try:
            name = RunFile.load(run_path(run_id)).name
        except Exception:
            pass
        out = {"status": "failed", "run_id": run_id, "procedure": name, "error": error.get("error"), "step": error.get("step"),
               "message": error.get("message"), "resumable": bool(error.get("resumable"))}
    except aip.AipError as err:                 # refused before it ran: a name the catalog lacks, inputs that do not fit, depth
        out = {"status": "refused", "run_id": run_id, "error": err.kind, "message": str(err)}
    except Exception as err:                    # the outcome is the planner's to read, whatever happened
        out = {"status": "refused", "run_id": run_id, "error": type(err).__name__, "message": str(err)}
    path = spool(run_id)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(out), encoding="utf-8")
    os.replace(tmp, path)
    return 0


# ------------------------------------------------------------------ the script


def launch(order: dict) -> None:
    """Start the child process, detached, so it outlives this script if it must."""
    folder = workdir() / SPOOL
    folder.mkdir(parents=True, exist_ok=True)
    spool(order["run_id"]).unlink(missing_ok=True)
    order_file = folder / f"{order['run_id']}.order.json"
    order_file.write_text(json.dumps(order), encoding="utf-8")
    log = (folder / f"{order['run_id']}.log").open("a", encoding="utf-8")
    flags: dict = {"start_new_session": True} if os.name != "nt" else \
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS}
    process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--child", str(order_file)],
                               stdin=subprocess.DEVNULL, stdout=log, stderr=log, cwd=workdir(), **flags)
    log.close()
    (folder / f"{order['run_id']}.pid").write_text(str(process.pid), encoding="utf-8")


def wait(run_id: str) -> dict:
    """The child's outcome, or `running` when the patience runs out first."""
    path = spool(run_id)
    limit = patience()
    began = time.monotonic()
    while not path.is_file():
        if limit is not None and time.monotonic() - began >= limit:
            from aip.client.runs import RunFile, run_path

            name = None
            try:
                name = RunFile.load(run_path(run_id)).name
            except Exception:
                pass
            return {"status": "running", "run_id": run_id, "procedure": name,
                    "message": f"still going after {limit:.0f}s, the most this step waits; run it again with run "
                               f"{run_id!r} and inputs {{}} to wait on"}
        time.sleep(0.2)
    return json.loads(path.read_text(encoding="utf-8"))


def alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True)
        return str(pid) in out.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def going(run_id: str) -> bool:
    """Whether a child this script started is still in its process: no outcome written yet, and
    the process that would write it still there."""
    pid_file = workdir() / SPOOL / f"{run_id}.pid"
    if spool(run_id).is_file() or not pid_file.is_file():
        return False
    try:
        return alive(int(pid_file.read_text(encoding="utf-8").strip()))
    except ValueError:
        return False


def main() -> None:
    state = json.load(sys.stdin)["state"]
    run = (state.get("run") or "").strip()
    raw = (state.get("inputs") or "").strip()
    try:
        inputs = json.loads(raw) if raw else {}
    except ValueError as exc:
        return refuse(f"inputs is not JSON: {exc}")
    if not isinstance(inputs, dict):
        return refuse("inputs is one JSON object")
    if not run:
        return refuse("run names nothing; name a procedure, or answer done")
    if run.split("@", 1)[0] == SELF or Path(run).name == SELF or Path(run).stem == SELF:
        return refuse("assist does not run itself: choose a procedure that does the work, or finish")

    from aip.client.runs import RUN_ID, RunFile, new_run_id, run_path
    from aip.server.builtins import builtin_files

    ours = RUN_ID.fullmatch(run) and (workdir() / SPOOL / f"{run}.order.json").is_file()
    if RUN_ID.fullmatch(run) and (ours or run_path(run).is_file()):   # a run, likely one this orchestrator started: carry it on
        if "answers" not in inputs and going(run):
            return emit(wait(run))                                      # a child writes its run file at its first stop
        if set(inputs) - {"answers"}:
            return refuse(f"a run is carried on with {{\"answers\": ...}} or {{}}, not {sorted(inputs)}")
        if not run_path(run).is_file():
            return refuse(f"run {run} stopped without a run file; its outcome was: {spool(run).read_text(encoding='utf-8')[:2000]}"
                          if spool(run).is_file() else f"run {run} is not going and left no run file")
        if RunFile.load(run_path(run)).status == "done":
            return refuse(f"run {run} is done; its outcome was shown when it finished")
        launch({"run_id": run, "start": False, "answers": inputs.get("answers")})
        return emit(wait(run))

    target = run
    from aip import Client

    if Client().server is None:                                    # no catalog: the procedures aip ships run from their bundles
        shipped = {p.stem: p for p in builtin_files()}
        if run.split("@", 1)[0] in shipped:
            target = str(shipped[run.split("@", 1)[0]])
    run_id = new_run_id()
    launch({"run_id": run_id, "start": True, "target": target, "inputs": inputs})
    emit(wait(run_id))


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--child":
        sys.exit(child(sys.argv[2]))
    main()
