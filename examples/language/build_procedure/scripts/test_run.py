#!/usr/bin/env python3
"""Run the new procedure once on example inputs, answering nothing, and report how far it gets.

stdin:  {"state": {"path": str}, "assets": {}, "expects": {...}}
stdout: {"started": bool, "test_report": str}

`path` is the program folder, relative to the run's working directory (AIP_WORKDIR). The trial
runs in a scratch directory with its own run files and no server (`AIP_SERVER=none`), so it is
not recorded and leaves nothing behind; its inputs are the placeholders `aip info
--example-inputs` prints. It stops at the first pause, which it does not answer: the report says
whether the run got past its `Start`, and where it stopped (its end, a pause and for which step,
or an error with its kind and message). A `Decide` asks the decision model this machine is
configured with, if any. The script itself fails only when it cannot run the trial at all.
"""
import json
import os
import sys
import tempfile
from pathlib import Path


def report(started: bool, text: str) -> None:
    json.dump({"started": started, "test_report": text}, sys.stdout)


def main() -> None:
    state = json.load(sys.stdin)["state"]
    workdir = Path(os.environ.get("AIP_WORKDIR") or ".").resolve()
    folder = (workdir / str(state["path"]).strip()).resolve()
    with tempfile.TemporaryDirectory(prefix="aip-trial-") as scratch:
        os.environ["AIP_SERVER"] = "none"
        os.environ["AIP_HOME"] = str(Path(scratch) / "home")
        os.environ.pop("AIP_ANSWER_WITH", None)
        import aip

        client = aip.Client(agent="build_procedure")
        try:
            inputs = client.describe(folder).example_inputs
        except aip.AipError as exc:
            return report(False, f"It could not be described, so it was not run: {exc}")
        trial = Path(scratch) / "work"
        trial.mkdir()
        shown = json.dumps(inputs)
        try:
            result = client.run(folder, inputs, workdir=trial)
        except aip.RunError as exc:
            error = exc.error
            if exc.run_id is None:
                return report(False, f"It did not start on the example inputs {shown}: {error.get('error')}: {error.get('message')}")
            return report(True, f"It started on the example inputs {shown} and failed at {error.get('step') or error.get('loop')}: "
                                f"{error.get('error')}: {error.get('message')}")
        except aip.AipError as exc:
            return report(False, f"It did not start: {exc}")
        if isinstance(result, aip.Done):
            return report(True, f"It ran to its end on the example inputs {shown}; the result had {sorted(result.result)}.")
        task = result.tasks[0]
        first = (task.prompt or "").strip().splitlines()[0] if (task.prompt or "").strip() else ""
        return report(True, f"It started on the example inputs {shown} and first pauses at {result.step} for the agent "
                            f"({len(result.tasks)} task(s), answering {sorted(task.answer_with)}): {first[:200]}")


main()
