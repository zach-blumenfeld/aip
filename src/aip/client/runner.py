"""Drive a procedure from the command line: run, pause, resume.

A run stops one of three ways, and the runner prints one JSON object for each; the shapes
are a contract, documented in `docs/cli-json.md`:

- **paused**: the client must answer. `client_task` (do the step's work), `decision` (no
  decision model: answer the questions), `review` (the model answered a question under its
  threshold: confirm or override). Each pause carries only the paused step's declared inputs
  as `state`; the answer is merged over the state the run file holds.
- **done**: the end step was reached; `state` is the end step's inputs.
- **error**: a step failed. The run file keeps the state before the failing step, and
  `resume` with no input retries it. A bad answer to a pause leaves the pause in place.

Every outcome but an error before anything ran writes the run file; at done it holds the
whole history, the ledger of a local run. Run files live under the user's home, at
`~/.aip/runs/<run-id>.json` (`AIP_HOME` moves it), so `aip resume <run-id>` works from any
directory; a served run is keyed by the id the server assigned, a local run by a generated one. With `progress`, one JSON line per completed step
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
from typing import Any, Callable, Dict, List

from aip.client.backend import Backend
from aip.model.types import validate_input

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


# The error kinds of the error object; anything else is reported as `server`.
ERROR_KINDS = ("script_failed", "invalid_input", "invalid_output", "requires_unmet", "timeout", "server")


@dataclass
class RunFile:
    """Everything needed to continue a run."""
    skill_dir: str
    after: str | None            # the step whose output the next input answers (None = start)
    state: JSON                  # the run's full state; an answer is merged over it
    history: List[JSON]
    pause: JSON                  # {"kind": "client_task"|"review"|"decision"|"error"|"done", "step", ...}
    thresholds: Dict[str, float] = field(default_factory=dict)
    created: float = field(default_factory=time.time)
    # set when the run is on a server: `resume` rebuilds an HttpBackend from these
    server: str | None = None
    name: str | None = None
    revision: str | None = None
    run_id: str | None = None

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2) + "\n")
        return path

    @classmethod
    def load(cls, path: Path) -> "RunFile":
        data = json.loads(Path(path).read_text())
        if "suggested" in data:                  # written before 0.6a0
            data["state"] = data.pop("suggested")
        return cls(**data)


def backend_for(run: RunFile, token: str | None = None, session: Any = None) -> Backend:
    """The backend a run file was written against: the server it names, else the local folder."""
    if run.server:
        from aip.client.backend import HttpBackend

        ref = f"{run.name}@{run.revision}" if run.revision else (run.name or run.skill_dir)
        return HttpBackend(run.server, token, ref, run_id=run.run_id, session=session)
    from aip.client.backend import LocalBackend

    return LocalBackend(Path(run.skill_dir))


@dataclass
class Outcome:
    code: int
    payload: JSON                # final state when done, the pause block when paused, the error object
    run_file: Path | None = None


Prompter = Callable[[str], str]


def error_object(exc: BaseException) -> JSON:
    """The error object's kind, step, message and per-kind detail, for a local or a server failure."""
    from aip.client.server import ServerError
    from aip.model.types import StepError

    if isinstance(exc, StepError):
        kind = exc.kind if exc.kind in ERROR_KINDS else "server"
        return {"error": kind, "step": exc.step, "message": str(exc), **exc.fields()}
    if isinstance(exc, ServerError):
        if exc.kind in ERROR_KINDS:
            detail = {k: v for k, v in exc.extra.items() if k not in ("run_id", "errors")}
            return {"error": exc.kind, "step": exc.location, "message": exc.message, **detail}
        return {"error": "server", "step": exc.location, "message": str(exc), "status": exc.status}
    return {"error": "server", "step": None, "message": f"{type(exc).__name__}: {exc}"}


def _answer_error(error: JSON) -> bool:
    """An answer to a pause that does not fit, as opposed to a step that failed while running."""
    return error["error"] in ("invalid_input", "invalid_output") and "script" not in error


def step_line(entry: JSON) -> JSON:
    """The `--progress` line for one completed step, from its history entry."""
    line: JSON = {"event": "step", "step": entry["step"], "kind": entry["kind"]}
    if entry["kind"] == "router":
        line["to"] = entry["result"]["to"]
    elif entry["kind"] == "decision":
        line["resolver"] = "manual" if entry.get("manual") else "typesafe"
    elif entry["kind"] == "execution" and "seconds" in entry:
        line["seconds"] = entry["seconds"]
    return line


def _settled_line(pause: JSON) -> JSON | None:
    """The line for a paused step, printed once its answer is accepted."""
    if pause["kind"] == "client_task":
        return {"event": "step", "step": pause["step"], "kind": "client_task"}
    if pause["kind"] == "review":
        return {"event": "step", "step": pause["step"], "kind": "decision", "resolver": "typesafe"}
    return None


def pause_of(response: JSON) -> JSON | None:
    """The pause a step response asks for: a client task, or a decision answered under its threshold.
    The server records the same block on the run."""
    if response["next"] is None:
        return None
    entry = response["history"][-1]
    if response["kind"] == "client_task":
        result = response["result"]
        return {"kind": "client_task", "step": response["ran"], "task": result["task"], "state": entry["input"],
                "references": result["references"], "answer_with": result["expects"]}
    if response["review"]:
        return {"kind": "review", "step": response["ran"], "state": entry["input"],
                "proposed_answers": {q: response["suggested"][q] for q in entry["result"]["answers"]},
                "review": response["review"]}
    return None


class Runner:
    def __init__(self, backend: Backend, skill_dir: Path, run_file: Path | None = None,
                 interactive: bool = False, prompter: Prompter = input, out=None,
                 progress: bool = False, debug: bool = False, run_id: str | None = None):
        """`run_file` is an explicit path; without one the run file is `run_path(<run id>)`.
        `run_id` is a resumed run's id; a new local run generates one."""
        self.backend = backend
        self.skill_dir = Path(skill_dir)
        self.run_file = run_file
        # keyed: the run file lives under the user's home by id, and follows the id if it changes
        self.keyed = run_file is None or Path(run_file).resolve().parent == run_path("x").parent.resolve()
        self.run_id = run_id or (Path(run_file).stem if run_file is not None and self.keyed else new_run_id())
        self.interactive = interactive
        self.prompt = prompter
        self.out = out or sys.stdout
        self.progress = progress
        self.debug = debug

    # ------------------------------------------------------------------ entry points

    def start(self, payload: JSON | None, thresholds: Dict[str, float] | None = None) -> Outcome:
        if payload is None:
            try:
                start = self.backend.describe()["start"]
            except Exception as exc:
                return self._failed(exc, None, {}, [], {})
            if not self.interactive:
                return self._error({"error": "invalid_input", "step": start["step"],
                                    "message": f"no input given; start step {start['step']!r} expects {start['inputs']}",
                                    "missing": list(start["inputs"]), "invalid": []})
            payload = self._prompt_inputs(start["inputs"], {})
        return self._drive(None, payload, [], thresholds or {})

    def resume(self, run: RunFile, payload: JSON | None) -> Outcome:
        pause, kind = run.pause, run.pause["kind"]
        if kind == "done":
            return self._done(run.state, run.history, run.after)
        if kind == "error":                       # retry the failing step, with any input merged in
            return self._drive(run.after, {**run.state, **(payload or {})}, run.history, run.thresholds)
        if kind == "decision":
            answers = payload if payload is not None else (
                self._prompt_answers(pause["questions"]) if self.interactive else None)
            if answers is None:
                return self._answer_needed(run, list(pause["questions"]))
            return self._drive(run.after, run.state, run.history, run.thresholds, answering=pause, answers=answers)
        if payload is None and self.interactive:
            payload = (self._prompt_inputs(pause["answer_with"], {}) if kind == "client_task"
                       else self._prompt_review(pause["review"], pause["proposed_answers"]))
        if payload is None:
            return self._answer_needed(run, list(pause.get("answer_with", {})))
        if kind == "client_task":
            from aip.model.types import OutputValidationError, validate_output
            try:
                validate_output(pause["step"], pause["answer_with"], payload, strict=False)
            except OutputValidationError as exc:
                return self._failed(exc, run.after, run.state, run.history, run.thresholds, keep=True)
        if kind == "review":
            unknown = [k for k in payload if k not in pause["proposed_answers"]]
            if unknown:
                return self._error({"error": "invalid_output", "step": pause["step"],
                                    "message": f"not questions of step {pause['step']!r}: {unknown}; "
                                               f"override only {list(pause['proposed_answers'])}",
                                    "missing": [], "invalid": unknown}, keep=True)
        return self._drive(run.after, {**run.state, **payload}, run.history, run.thresholds, answering=pause)

    # ------------------------------------------------------------------------- loop

    def _drive(self, after: str | None, payload: JSON, history: List[JSON], thresholds: Dict[str, float],
               answering: JSON | None = None, answers: JSON | None = None) -> Outcome:
        """Step until a pause, the end, or an error. `answering` is the pause this call answers:
        a bad answer leaves it in place. `answers` answers a manual decision first."""
        while True:
            try:
                if answers is not None:
                    response = self.backend.answer_decision(after, payload, history, answers)
                    answers = None
                else:
                    node = self.backend.peek(after, payload)
                    if node is not None and node["kind"] == "decision" and not self.backend.has_decision_model():
                        validate_input(node["step"], node["inputs"], payload)     # before asking anyone
                        if not self.interactive:
                            self._settle(answering)
                            return self._pause(after, payload, history, thresholds, {
                                "kind": "decision", "step": node["step"], "questions": node["questions"],
                                "state": {k: payload[k] for k in node["inputs"] if k in payload}})
                        response = self.backend.answer_decision(after, payload, history,
                                                                self._prompt_answers(node["questions"]))
                    else:
                        response = self.backend.run(after, payload, history, thresholds)
            except Exception as exc:
                return self._failed(exc, after, payload, history, thresholds, keep=answering is not None)
            self._settle(answering)
            answering = None
            pause = pause_of(response)
            for entry in response["history"][len(history):]:
                if entry["kind"] != "end" and not (pause is not None and entry is response["history"][-1]):
                    self._line(step_line(entry))
            after, payload, history = response["ran"], response["suggested"], response["history"]
            if response["next"] is None:
                return self._done(response["result"], history, after)
            if pause is None:
                continue
            if not self.interactive:
                return self._pause(after, payload, history, thresholds, pause)
            if pause["kind"] == "client_task":
                self.out.write("\n" + pause["task"] + "\n\n")
                payload = self._prompt_inputs(pause["answer_with"], payload)
            else:
                payload = self._prompt_review(pause["review"], payload)
            answering = pause

    def _settle(self, answering: JSON | None) -> None:
        line = _settled_line(answering) if answering is not None else None
        if line is not None:
            self._line(line)

    # ---------------------------------------------------------------------- outcomes

    def _run_file(self, after: str | None, state: JSON, history: List[JSON], pause: JSON,
                  thresholds: Dict[str, float]) -> RunFile:
        fields = getattr(self.backend, "run_file_fields", None)
        if fields is None:                        # local: absolute, so `resume` works from any directory
            return RunFile(str(self.skill_dir.resolve()), after, state, history, pause, thresholds,
                           run_id=self.run_id)
        return RunFile(str(self.skill_dir), after, state, history, pause, thresholds, **fields())

    def _save(self, run: RunFile) -> Path:
        """Write the run file: the explicit path, else under the user's home by run id. A served
        run is keyed by the server's id; until the server has one (a pause before the first step)
        it is keyed by the local id, and moves once the server assigns its own."""
        old = self.run_file
        if self.keyed:
            self.run_file = run_path(self._id(run))
        run.save(self.run_file)
        if old is not None and Path(old) != self.run_file:
            Path(old).unlink(missing_ok=True)
        return self.run_file

    def _id(self, run: RunFile) -> str:
        """The id `aip resume` takes for this run."""
        return run.run_id or self.run_id

    def _pause(self, after: str | None, state: JSON, history: List[JSON], thresholds: Dict[str, float],
               pause: JSON) -> Outcome:
        run = self._run_file(after, state, history, pause, thresholds)
        path = self._save(run)
        block = {"paused": pause["kind"], **{k: v for k, v in pause.items() if k != "kind"},
                 "run_id": self._id(run), "run_file": str(path)}
        self._print(block)
        return Outcome(EXIT_PAUSED, block, path)

    def _done(self, state: JSON, history: List[JSON], after: str | None) -> Outcome:
        run = self._run_file(after, state, history, {"kind": "done"}, {})
        path = self._save(run)
        self._print({"done": True, "run_id": self._id(run), "state": state, "run_file": str(path)})
        return Outcome(EXIT_DONE, state, path)

    def _failed(self, exc: BaseException, after: str | None, state: JSON, history: List[JSON],
                thresholds: Dict[str, float], keep: bool = False) -> Outcome:
        """A step failed. The run file is rewritten to retry it from the state before it, unless
        the failure is a bad answer to a pause (`keep`: the pause stands, answer it again) or
        nothing had run yet (start again with `aip run`)."""
        if self.debug:
            traceback.print_exception(exc, file=sys.stderr)
        error = error_object(exc)
        run_id = getattr(exc, "extra", {}).get("run_id")
        if run_id and hasattr(self.backend, "run_id"):
            self.backend.run_id = run_id
        if keep and _answer_error(error):
            return self._error(error, keep=True)
        if after is None and not history:
            return self._error(error)
        pause = {"kind": "error", "step": error["step"], "error": error["error"]}
        run = self._run_file(after, state, history, pause, thresholds)
        self._save(run)
        return self._error(error, keep=True, run_id=self._id(run))

    def _answer_needed(self, run: RunFile, keys: List[str]) -> Outcome:
        return self._error({"error": "invalid_output", "step": run.pause["step"],
                            "message": f"resume needs an answer for the paused {run.pause['kind']} step "
                                       f"{run.pause['step']!r} (--input <answer.json>)",
                            "missing": keys, "invalid": []}, keep=True, run_id=self._id(run))

    def _error(self, error: JSON, keep: bool = False, run_id: str | None = None) -> Outcome:
        """Print the error object. `keep`: a run file exists to resume (the pause, or the retry point)."""
        if run_id is None:
            run_id = getattr(self.backend, "run_id", None) or (self.run_id if keep else None)
        block = {**error, "run_id": run_id, "resumable": keep}
        held = Path(self.run_file) if keep and self.run_file is not None else None
        if held is not None:
            block["run_file"] = str(held)
        self._print(block)
        return Outcome(EXIT_ERROR, block, held)

    def _print(self, obj: JSON) -> None:
        self.out.write((json.dumps(obj) if self.progress else json.dumps(obj, indent=2)) + "\n")

    def _line(self, line: JSON) -> None:
        if self.progress:
            self.out.write(json.dumps(line) + "\n")

    # ------------------------------------------------------------------- interactive

    def _prompt_inputs(self, expects: JSON, suggested: JSON) -> JSON:
        """One prompt per declared input, typed from the vocabulary, prefilled from `suggested`."""
        result = dict(suggested)
        for name, dtype in expects.items():
            default = suggested.get(name)
            hint = f" [{json.dumps(default)}]" if default is not None else ""
            while True:
                raw = self.prompt(f"{name} ({dtype}){hint}: ").strip()
                if not raw and default is not None:
                    result[name] = default
                    break
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

    def _prompt_review(self, review: List[JSON], suggested: JSON) -> JSON:
        payload = dict(suggested)
        for item in review:
            name = item["question"]
            self.out.write(f"\n{name}: {item['reason']}  (model says {json.dumps(suggested.get(name))})\n")
            if "probabilities" in item:
                self.out.write("  " + json.dumps(item["probabilities"]) + "\n")
            raw = self.prompt(f"  keep {json.dumps(suggested.get(name))}? enter to keep, or a new value: ").strip()
            if raw:
                current = suggested.get(name)
                dtype = "boolean" if isinstance(current, bool) else "integer" if isinstance(current, int) else "string"
                payload[name] = _coerce(raw, dtype)
        return payload


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
