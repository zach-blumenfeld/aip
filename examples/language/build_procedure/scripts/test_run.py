#!/usr/bin/env python3
"""Try the new procedure once on example inputs, running none of its scripts, and report how far
it gets and what each of its scripts says it does.

stdin:  {"state": {"path": str}, "assets": {}, "expects": {...}}
stdout: {"started": bool, "test_report": str}

`path` is the program folder, relative to the run's working directory (AIP_WORKDIR). The trial
is `aip.Client.run(..., scripts=False)`: the procedure's scripts were written by a model and
nobody has read them yet, so none of them runs; the trial stops at the first `Execute`, before
its script starts. It runs in a scratch directory with its own run files and no server
(`AIP_SERVER=none`), so it is not recorded and leaves nothing behind; its inputs are the
placeholders `aip info --example-inputs` prints. It stops at the first pause, which it does not
answer, and gives up after 30 seconds (a `Decide` asks the decision model this machine is
configured with, if any). The report says whether the run got past its `Start`, where it
stopped (its end, a pause and for which step, the first script it would have run, or an error
with its kind and message), and lists every file under the draft's `scripts/` with what its
docstring or opening comment says it does. The script itself fails only when it cannot try at all.
"""
import ast
import json
import os
import sys
import tempfile
import threading
from pathlib import Path

CAP = 30.0      # seconds the whole trial may take


def report(started: bool, text: str) -> None:
    json.dump({"started": started, "test_report": text}, sys.stdout)
    sys.stdout.flush()


def says(path: Path) -> str:
    """What a script says it does: a Python module's docstring, else its opening comment lines;
    the first paragraph, on one line."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return "(not readable as text)"
    if path.suffix == ".py":
        try:
            doc = ast.get_docstring(ast.parse(text))
        except SyntaxError:
            doc = None
        if doc:
            return " ".join(doc.strip().split("\n\n", 1)[0].split())
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#!"):
            continue
        if stripped.startswith(("#", "//")):
            lines.append(stripped.lstrip("#/ ").strip())
        elif lines or stripped:
            break
    return " ".join(" ".join(lines).split()) or "(it says nothing about what it does)"


def scripts_of(folder: Path) -> str:
    root = folder / "scripts"
    found = sorted(p for p in root.rglob("*") if p.is_file()) if root.is_dir() else []
    if not found:
        return "The draft carries no script."
    lines = [f"- scripts/{p.relative_to(root).as_posix()}: {says(p)}" for p in found]
    return "The draft carries these scripts, none of which ran:\n" + "\n".join(lines)


def trial(folder: Path, scratch: str) -> tuple[bool, str]:
    import aip

    client = aip.Client(agent="build_procedure")
    try:
        inputs = client.describe(folder).example_inputs
    except aip.AipError as exc:
        return False, f"It could not be described, so it was not tried: {exc}"
    work = Path(scratch) / "work"
    work.mkdir()
    shown = json.dumps(inputs)
    try:
        result = client.run(folder, inputs, workdir=work, scripts=False)
    except aip.RunError as exc:
        error = exc.error
        if exc.run_id is None:
            return False, f"It did not start on the example inputs {shown}: {error.get('error')}: {error.get('message')}"
        if error.get("error") == "script_not_run":
            return True, (f"It started on the example inputs {shown} and stopped before {error.get('step')}, which would run "
                          f"{error.get('script')}: the trial runs no script.")
        return True, (f"It started on the example inputs {shown} and failed at {error.get('step') or error.get('loop')}: "
                      f"{error.get('error')}: {error.get('message')}")
    except aip.AipError as exc:
        return False, f"It did not start: {exc}"
    if isinstance(result, aip.Done):
        return True, f"It ran to its end on the example inputs {shown}; the result had {sorted(result.result)}."
    task = result.tasks[0]
    first = (task.prompt or "").strip().splitlines()[0] if (task.prompt or "").strip() else ""
    return True, (f"It started on the example inputs {shown} and first pauses at {result.step} for the agent "
                  f"({len(result.tasks)} task(s), answering {sorted(task.answer_with)}): {first[:200]}")


def main() -> None:
    state = json.load(sys.stdin)["state"]
    workdir = Path(os.environ.get("AIP_WORKDIR") or ".").resolve()
    folder = (workdir / str(state["path"]).strip()).resolve()
    scripts = scripts_of(folder)
    with tempfile.TemporaryDirectory(prefix="aip-trial-") as scratch:
        os.environ["AIP_SERVER"] = "none"
        os.environ["AIP_HOME"] = str(Path(scratch) / "home")
        outcome: list[tuple[bool, str]] = []
        worker = threading.Thread(target=lambda: outcome.append(trial(folder, scratch)), daemon=True)
        worker.start()
        worker.join(CAP)
        if not outcome:
            report(True, f"The trial did not finish within {CAP:g} seconds and was stopped.\n\n{scripts}")
            os._exit(0)             # the trial's thread cannot be stopped; the process can
        started, text = outcome[0]
    report(started, f"{text}\n\n{scripts}")


main()
