"""Drive a procedure from the command line: run, pause, resume.

A run stops one of three ways, and the runner prints one JSON object for each; the shapes
are a contract, documented in `docs/cli-json.md`:

- **paused**: the client must answer. `client_task` (do the step's work), `decision` (no
  decision model on this client: answer the questions), `review` (this client's decision model
  answered a question under its threshold: confirm or override). Each pause carries only the paused step's declared inputs
  as `state`; the answer is merged over the state the run file holds.
- **done**: the end step was reached; `state` is the end step's inputs.
- **error**: a step failed. The run file keeps the state before the failing step, and
  `resume` with no input retries it. A bad answer to a pause leaves the pause in place.

The loop itself is `aip.model.engine`, run by the backend: in this process for a skill folder,
on the server for a published name. The SDK's `Driver` (`aip.sdk`) turns each stop into a
result and writes the run file; the runner prints it, and in interactive mode answers pauses
from the terminal.

Every outcome but an error before anything ran writes the run file. A local run's file holds
the whole run, and at done the whole history, its ledger; a served run's holds only the run
id, server, revision, version and pending pause, since the server holds the rest. Run files
live under the user's home, at `~/.aip/runs/<run-id>.json` (`AIP_HOME` moves it), so
`aip resume <run-id>` works from any directory; a served run is keyed by the id the server
assigned, a local run by a generated one. With `progress`, one JSON line per completed step
is printed before the final object. In interactive mode a pause becomes prompts instead.
"""

import json
import os
import re
import sys
import time
import traceback
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, ClassVar, Dict, List

from aip.client.backend import Backend
from aip.model.engine import ERROR_KINDS

JSON = Dict[str, Any]

EXIT_DONE = 0
EXIT_PAUSED = 0
EXIT_ERROR = 1

RUN_ID = re.compile(r"[A-Za-z0-9_-]+")


def aip_home() -> Path:
    """`AIP_HOME`, else `~/.aip`: where run files live."""
    override = os.environ.get("AIP_HOME")
    return Path(override).expanduser() if override else Path.home() / ".aip"


def run_path(run_id: str) -> Path:
    """The run file of `run_id` under `aip_home()`."""
    if not RUN_ID.fullmatch(run_id):
        raise ValueError(f"not a run id: {run_id!r}")
    return aip_home() / "runs" / f"{run_id}.json"


def new_run_id() -> str:
    """A local run's id, the same shape the server's run backends assign."""
    return uuid.uuid4().hex[:16]


@dataclass
class RunFile:
    """Everything needed to continue a run. A local run's file holds the whole run (`skill_dir`,
    `after`, `state`, `history`); a served run's only a handle (`server`, `name`, `revision`,
    `version`): the server holds the rest. Both hold `run_id`, the run's working directory
    (`workdir`, where its scripts read and write files), and the pending `pause`
    (`{"kind": "client_task"|"review"|"decision"|"error"|"done", "step", ...}`). Unset fields
    are left out of the file."""
    pause: JSON
    run_id: str | None = None
    skill_dir: str | None = None
    after: str | None = None              # the step whose output the next input answers (None = start)
    state: JSON | None = None             # the run's full state; an answer is merged over it
    history: List[JSON] | None = None
    server: str | None = None
    name: str | None = None
    revision: str | None = None
    version: int | None = None            # the server's version of the run, sent back with the answer
    workdir: str | None = None            # where the run's scripts read and write files (AIP_WORKDIR)
    created: float = field(default_factory=time.time)

    LOCAL: ClassVar = ("skill_dir", "after", "state", "history")

    def save(self, path: Path) -> Path:
        data = {k: v for k, v in asdict(self).items()
                if v is not None or (k in self.LOCAL and self.server is None)}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n")
        return path

    @classmethod
    def load(cls, path: Path) -> "RunFile":
        data = json.loads(Path(path).read_text())
        if "suggested" in data:                  # written before 0.6a0
            data["state"] = data.pop("suggested")
        data.pop("thresholds", None)             # before B1: thresholds are the author's alone now
        return cls(**data)


def backend_for(run: RunFile, token: str | None = None, session: Any = None, client: Any = None) -> Backend:
    """The backend a run file was written against: the server it names, else the local folder.
    `client` is an injected decision-model client (tests); otherwise the configured key decides."""
    if run.server:
        from aip.client.backend import HttpBackend

        return HttpBackend(run.server, token, f"{run.name}@{run.revision}", session=session, workdir=run.workdir,
                           client=client)
    from aip.client.backend import LocalBackend

    return LocalBackend(Path(run.skill_dir), client=client, workdir=run.workdir)


@dataclass
class Outcome:
    code: int
    payload: JSON                # final state when done, the pause block when paused, the error object
    run_file: Path | None = None


Prompter = Callable[[str], str]


def error_object(exc: BaseException) -> JSON:
    """The error object's kind, step, message and per-kind detail, for a local or a server failure."""
    from aip.client.server import ServerError
    from aip.model.engine import error_object as step_error

    if isinstance(exc, ServerError):
        if exc.kind in ERROR_KINDS:
            detail = {k: v for k, v in exc.extra.items() if k not in ("run_id", "errors", "resumable")}
            return {"error": exc.kind, "step": exc.location, "message": exc.message, **detail}
        return {"error": "server", "step": exc.location, "message": str(exc), "status": exc.status}
    return step_error(exc)


class Runner:
    """The CLI's face on a run: prints what the SDK's `Driver` returns (`docs/cli-json.md`), and in
    interactive mode answers each pause on the terminal instead."""

    def __init__(self, backend: Backend | None, run_file: Path | None = None,
                 interactive: bool = False, prompter: Prompter = input, out=None,
                 progress: bool = False, debug: bool = False, run_id: str | None = None):
        """`run_file` is an explicit path; without one the run file is `run_path(<run id>)`.
        `run_id` is a resumed run's id. `backend` may be None when only `show` is used."""
        self.backend = backend
        self.run_file = run_file
        self.run_id = run_id
        self.interactive = interactive
        self.prompt = prompter
        self.out = out or sys.stdout
        self.progress = progress
        self.debug = debug

    # ------------------------------------------------------------------ entry points

    def start(self, payload: JSON | None) -> Outcome:
        from aip.sdk import Driver

        def go(on_step, on_pause):
            driver = Driver(self.backend, self.run_file, on_step, on_pause)
            return driver.start(self.start_input(driver.start_step()) if payload is None and self.interactive
                                else payload)
        return self.show(go)

    def resume(self, run: RunFile, payload: JSON | None) -> Outcome:
        from aip.sdk import Driver

        if payload is None and self.interactive and run.pause["kind"] not in ("error", "done"):
            payload = self.ask(run.pause)
        return self.show(lambda on_step, on_pause: Driver(self.backend, self.run_file, on_step, on_pause,
                                                          run_id=run.run_id).resume(run, payload))

    def start_input(self, start: JSON) -> JSON:
        """The start input, prompted on the terminal from the start step's description."""
        return self._prompt_inputs(start["inputs"])

    def show(self, call: Callable[[Callable, Callable | None], Any]) -> Outcome:
        """Run `call(on_step, on_pause)`, an SDK call that returns a `Paused` or `Done` or raises
        a `RunError`, and print what it stopped at: one object, after the `--progress` lines."""
        from aip.sdk import Done, RunError

        try:
            result = call(self._line, (lambda paused: self.ask(paused.to_json())) if self.interactive else None)
        except RunError as exc:
            if exc.cause is not None and self.debug:
                traceback.print_exception(exc.cause, file=sys.stderr)
            block = exc.to_json()
            self._print(block)
            return Outcome(EXIT_ERROR, block, exc.run_file)
        if isinstance(result, Done):
            self._print(result.to_json())
            return Outcome(EXIT_DONE, result.state, result.run_file)
        block = result.to_json()
        if not self.interactive:
            self._print(block)
        return Outcome(EXIT_PAUSED, block, result.run_file)

    def _print(self, obj: JSON) -> None:
        self.out.write((json.dumps(obj) if self.progress else json.dumps(obj, indent=2)) + "\n")

    def _line(self, line: JSON) -> None:
        if self.progress:
            self.out.write(json.dumps(line) + "\n")

    # ------------------------------------------------------------------- interactive

    def ask(self, pause: JSON) -> JSON:
        """The answer to a pause (a run file's, or the printed object), from the terminal."""
        kind = pause.get("kind") or pause.get("paused")
        if kind == "decision":
            return self._prompt_answers(pause["questions"])
        if kind == "client_task":
            self.out.write("\n" + pause["task"] + "\n\n")
            return self._prompt_inputs(pause["answer_with"])
        return self._prompt_review(pause["review"], pause["proposed_answers"])

    def _prompt_inputs(self, expects: JSON) -> JSON:
        """One prompt per declared key, typed from the vocabulary."""
        result: JSON = {}
        for name, dtype in expects.items():
            while True:
                raw = self.prompt(f"{name} ({dtype}): ").strip()
                try:
                    result[name] = _coerce(raw, dtype)
                    break
                except ValueError as exc:
                    self.out.write(f"  {exc}\n")
        return result

    def _prompt_answers(self, questions: JSON) -> JSON:
        answers: JSON = {}
        for name, q in questions.items():
            self.out.write(f"\n{name}: {q.get('instructions', '')}\n")
            if q["type"] == "noul":
                if q.get("criteria"):
                    self.out.write(f"  yes: {q['criteria'].get('true', '')}\n  no: {q['criteria'].get('false', '')}\n")
                answers[name] = _coerce(self.prompt("  yes/no: "), "boolean")
            elif q["type"] == "choice":
                for label, desc in q["criteria"].items():
                    self.out.write(f"  {label}: {desc or ''}\n")
                while (label := self.prompt("  choice: ").strip()) not in q["criteria"]:
                    self.out.write(f"  pick one of {list(q['criteria'])}\n")
                answers[name] = label
            else:
                for i, desc in enumerate(q["criteria"]):
                    self.out.write(f"  {i}: {desc}\n")
                while True:
                    level = int(_coerce(self.prompt("  level: "), "integer"))
                    if 0 <= level < len(q["criteria"]):
                        break
                    self.out.write(f"  pick 0..{len(q['criteria']) - 1}\n")
                answers[name] = level
        return answers

    def _prompt_review(self, review: List[JSON], proposed: JSON) -> JSON:
        """Only the overrides: an empty answer keeps the model's."""
        overrides: JSON = {}
        for item in review:
            name = item["question"]
            self.out.write(f"\n{name}: {item['reason']}  (model says {json.dumps(proposed.get(name))})\n")
            if "probabilities" in item:
                self.out.write("  " + json.dumps(item["probabilities"]) + "\n")
            raw = self.prompt(f"  keep {json.dumps(proposed.get(name))}? enter to keep, or a new value: ").strip()
            if raw:
                current = proposed.get(name)
                dtype = "boolean" if isinstance(current, bool) else "integer" if isinstance(current, int) else "string"
                overrides[name] = _coerce(raw, dtype)
        return overrides


def _coerce(raw: str, dtype: str) -> Any:
    raw = raw.strip()
    match dtype:
        case "string":
            return raw
        case "integer":
            try:
                return int(raw)
            except ValueError:
                raise ValueError(f"expected an integer, got {raw!r}") from None
        case "float":
            try:
                return float(raw)
            except ValueError:
                raise ValueError(f"expected a number, got {raw!r}") from None
        case "boolean":
            if raw.lower() in ("y", "yes", "true", "1"):
                return True
            if raw.lower() in ("n", "no", "false", "0"):
                return False
            raise ValueError(f"expected yes/no, got {raw!r}")
        case _:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                raise ValueError(f"expected JSON for {dtype}, got {raw!r}") from None
