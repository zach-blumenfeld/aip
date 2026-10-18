"""The run loop: one procedure, one cursor, one answer at a time.

A run is a `Cursor`: the step whose output the next input answers (`after`), the full state,
the history, and what the run waits for (`pause`). `start` opens one from the start input;
`submit` carries one thing to it: the answer to its pause, or nothing to retry a failed step.
Each steps the procedure until a pause, the end, or a failure, and returns an `Advance`.

The same loop runs in both places a run can live: the local client (`aip run ./folder`)
keeps the cursor in its run file; the server keeps it in its run backend and the client
holds only the run id. Neither keeps anything in memory between calls.

Pause kinds, as `cursor.pause["kind"]`:

- `client_task`: the client must answer. The block is what the CLI prints, minus `run_id` and
  `run_file`.
- `decision`: every decision stops here; the loop never calls a decision model. The client
  resolves it (`aip.client.resolver`) with its own model when one is configured, else prints
  it for the agent to answer; the next `submit` carries the answers and their attribution
  (`Decision.accept_answers`). The block also carries the author's `thresholds` and, when the
  step sets `history: true`, the run's `history`: what a resolver needs, never printed (`PRIVATE`).
  A `review` (the model answered a question under its threshold) is the client's pause, not
  the loop's: the loop still waits at the decision.
- `execute`: an execution step, in a run whose loop does not run scripts (`scripts=False`: the
  server's, and the local client's, which runs them itself between calls). The block is
  `Execution.request`; the next `submit` carries the client's report of running it (`{"output":
  {...}, "seconds"}` or a failure, see `Execution.accept_report`). Never printed by the CLI.
- `error`: a step failed; `after`, `state`, and `history` are as they were before it, so a
  `submit` with no answer retries it.
- `done`: the end was reached; `state` is the end step's inputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from aip.model.procedure import Procedure
from aip.model.steps import Decision, Execution, describe_next, threshold
from aip.model.types import (
    JSON, InputValidationError, OutputValidationError, StepError, project, validate_input, validate_output,
)

# The error kinds of the error object (`docs/cli-json.md`); anything else is reported as `server`.
ERROR_KINDS = ("script_failed", "invalid_input", "invalid_output", "requires_unmet", "timeout", "server")

PAUSED = ("client_task", "decision")

# Keys of a pause block that are for the client program, not the agent: the CLI never prints them.
PRIVATE = ("thresholds", "history", "resolution")


@dataclass
class Cursor:
    after: str | None = None
    state: JSON = field(default_factory=dict)
    history: List[JSON] = field(default_factory=list)
    pause: JSON | None = None

    @property
    def status(self) -> str:
        """The run's status: `paused`, `failed`, `done`, or `running` (nothing pending)."""
        kind = (self.pause or {}).get("kind")
        return "paused" if kind in PAUSED else "failed" if kind == "error" else "done" if kind == "done" else "running"


@dataclass
class Advance:
    """What one `start` or `submit` did.

    cursor:  where the run is now; `None` when nothing is worth keeping (the start input was
             rejected before any step ran)
    entries: the history entries this call added, in order (also at the end of `cursor.history`)
    lines:   the `--progress` line of every step this call completed, in order
    error:   the error object when the call failed; `kept` says the run did not move (an answer
             that does not fit its pause: answer it again)
    failure: the history entry recording a step that failed while running (the server's ledger)
    exc:     the exception behind `error`, for `--debug`
    """
    cursor: Cursor | None
    entries: List[JSON] = field(default_factory=list)
    lines: List[JSON] = field(default_factory=list)
    error: JSON | None = None
    kept: bool = False
    failure: JSON | None = None
    exc: BaseException | None = None

    @property
    def resumable(self) -> bool:
        """Whether there is a run to come back to: the pause that still stands, or the retry point."""
        return self.kept or self.cursor is not None

    def outcome(self) -> JSON:
        """The paused, done, or error object, without `run_id` and `run_file` (the caller adds them)."""
        if self.error is not None:
            return dict(self.error)
        pause = self.cursor.pause
        if pause["kind"] == "done":
            return {"done": True, "state": pause["state"]}
        return {"paused": pause["kind"], **{k: v for k, v in pause.items() if k != "kind"}}


# ---------------------------------------------------------------------------- errors


def error_object(exc: BaseException) -> JSON:
    """The error object's kind, step, message and per-kind detail for a step that raised."""
    if isinstance(exc, StepError):
        kind = exc.kind if exc.kind in ERROR_KINDS else "server"
        return {"error": kind, "step": exc.step, "message": str(exc), **exc.fields()}
    return {"error": "server", "step": None, "message": f"{type(exc).__name__}: {exc}"}


def _answer_error(error: JSON) -> bool:
    """An answer to a pause that does not fit, as opposed to a step that failed while running."""
    return error["error"] in ("invalid_input", "invalid_output") and "script" not in error


# ----------------------------------------------------------------------------- lines


def step_line(entry: JSON) -> JSON:
    """The `--progress` line for one completed step, from its history entry."""
    line: JSON = {"event": "step", "step": entry["step"], "kind": entry["kind"]}
    if entry["kind"] == "router":
        line["to"] = entry["result"]["to"]
    elif entry["kind"] == "decision":
        line["resolver"] = (entry.get("attribution") or {}).get("resolver", "manual")
    elif entry["kind"] == "execution" and "seconds" in entry:
        line["seconds"] = entry["seconds"]
    return line


def settled_line(pause: JSON) -> JSON | None:
    """The line for a paused step, printed once its answer is accepted."""
    if pause["kind"] == "client_task":
        return {"event": "step", "step": pause["step"], "kind": "client_task"}
    return None


# ---------------------------------------------------------------------------- pauses


def pause_of(response: JSON) -> JSON | None:
    """The pause a step response asks for: a client task."""
    if response["next"] is None or response["kind"] != "client_task":
        return None
    entry, result = response["history"][-1], response["result"]
    return {"kind": "client_task", "step": response["ran"], "task": result["task"], "state": entry["input"],
            "references": result["references"], "answer_with": result["expects"]}


def thresholds_of(step: Decision) -> Dict[str, float]:
    """Every question's threshold as the author set it in SKILL.md, the type's default otherwise."""
    return {name: threshold(q.type, step.thresholds, name) for name, q in step.questions.items()}


def decision_pause(step: Decision, state: JSON, history: List[JSON]) -> JSON:
    """The pause at a decision: what the decision model is given (`questions`, `state`, and `history`
    when the step asks for it), and the thresholds the client's resolver applies."""
    pause = {"kind": "decision", "step": step.name, "questions": describe_next(step)["questions"],
             "state": project(state, step.inputs), "thresholds": thresholds_of(step)}
    if step.history:
        pause["history"] = history
    return pause


# ------------------------------------------------------------------------------ loop


def start(procedure: Procedure, payload: JSON, scripts: bool = True) -> Advance:
    """Open a run on the start input and step it until it must stop. With `scripts` false the run
    stops at each execution step (`execute`) instead of running its script here."""
    return _drive(procedure, scripts, None, payload, [])


def submit(procedure: Procedure, cursor: Cursor, answer: JSON | None, scripts: bool = True,
           attribution: JSON | None = None) -> Advance:
    """Carry one thing to a run: the answer to its pause (at a decision, with the `attribution` of
    whoever resolved it; None is a manual answer), the report of a script the client ran, or
    (`None`, at a failed step) a retry. A retry may carry keys too; they are merged over the
    state before the step. An answer that does not fit leaves the run where it was (`kept`)."""
    pause = cursor.pause or {}
    kind = pause.get("kind")
    if kind == "done":
        return Advance(cursor, kept=True, error={
            "error": "server", "step": None, "message": "the run is done; there is nothing to answer"})
    if kind == "error":
        return _drive(procedure, scripts, cursor.after, {**cursor.state, **(answer or {})}, cursor.history)
    if kind == "execute":
        if not _is_report(answer):
            return Advance(cursor, kept=True, error={
                "error": "invalid_output", "step": pause["step"],
                "message": f"step {pause['step']!r} runs on the client: post the report of running its script, "
                           '{"output": {...}} or {"error": "script_failed"|"timeout"|"requires_unmet", ...}',
                "missing": ["output"], "invalid": []})
        return _drive(procedure, scripts, cursor.after, cursor.state, cursor.history, report=answer)
    if kind not in PAUSED:
        return Advance(cursor, kept=True, error={
            "error": "server", "step": None, "message": f"the run is not paused (status {cursor.status})"})
    if answer is None:
        keys = list(pause["questions"] if kind == "decision" else pause.get("answer_with", {}))
        return Advance(cursor, kept=True, error={
            "error": "invalid_output", "step": pause["step"],
            "message": f"resume needs an answer for the paused {kind} step {pause['step']!r} (--input <answer.json>)",
            "missing": keys, "invalid": []})
    if kind == "decision":
        return _drive(procedure, scripts, cursor.after, cursor.state, cursor.history,
                      answering=pause, answers=(answer, attribution))
    try:
        validate_output(pause["step"], pause["answer_with"], answer, strict=False)
    except OutputValidationError as exc:
        return Advance(cursor, kept=True, error=error_object(exc), exc=exc)
    return _drive(procedure, scripts, cursor.after, {**cursor.state, **answer}, cursor.history, answering=pause)


def _is_report(answer: JSON | None) -> bool:
    """A client's report of running a script: its output, or a failure of a known kind."""
    if not isinstance(answer, dict):
        return False
    if "error" in answer:
        return answer["error"] in ("script_failed", "timeout", "requires_unmet")
    return isinstance(answer.get("output"), dict)


def _drive(procedure: Procedure, scripts: bool, after: str | None, payload: JSON,
           history: List[JSON], answering: JSON | None = None, answers: tuple[JSON, JSON | None] | None = None,
           report: JSON | None = None) -> Advance:
    """Step until a pause, the end, or a failure. `answering` is the pause this call answers: a bad
    answer leaves it in place. `answers` (the answers and their attribution) answers a decision
    first, `report` an execution step the client ran."""
    carried = len(history)
    lines: List[JSON] = []

    def settle() -> None:
        nonlocal answering
        line = settled_line(answering) if answering is not None else None
        if line is not None:
            lines.append(line)
        answering = None

    def stop(pause: JSON) -> Advance:
        return Advance(Cursor(after, payload, history, pause), entries=history[carried:], lines=lines)

    while True:
        node = None
        try:
            node, routed = procedure.resolve(after, payload)
            if answers is not None:
                if not isinstance(node, Decision):
                    raise KeyError(f"the step after {after!r} is not a decision")
                response = node.accept_answers(payload, [*history, *routed], *answers).to_dict()
                answers = None
            elif report is not None:
                if not isinstance(node, Execution):
                    raise KeyError(f"the step after {after!r} is not an execution step")
                response = node.accept_report(payload, [*history, *routed], report).to_dict()
                report = None
            elif isinstance(node, Decision):
                validate_input(node.name, node.inputs, payload)          # before asking anyone
                settle()
                return stop(decision_pause(node, payload, [*history, *routed]))
            elif isinstance(node, Execution) and not scripts:
                request = node.request(payload)
                settle()
                return stop(request)
            else:
                response = procedure.run(after, payload, history).to_dict()
        except Exception as exc:
            return _failed(exc, node, after, payload, history, carried, lines, keep=answering is not None)
        settle()
        pause = pause_of(response)
        for entry in response["history"][len(history):]:
            if entry["kind"] != "end" and not (pause is not None and entry is response["history"][-1]):
                lines.append(step_line(entry))
        after, payload, history = response["ran"], response["suggested"], response["history"]
        if response["next"] is None:
            payload = response["result"]
            return stop({"kind": "done", "state": response["result"]})
        if pause is not None:
            return stop(pause)


def _failed(exc: BaseException, node: Any, after: str | None, state: JSON, history: List[JSON], carried: int,
            lines: List[JSON], keep: bool) -> Advance:
    """A step failed. The run waits at the state before it, to be retried, unless the failure is a
    bad answer to a pause (`keep`: the pause stands, answer it again) or the start input was
    rejected before any step ran (start again)."""
    error = error_object(exc)
    if keep and _answer_error(error):
        return Advance(None, error=error, kept=True, exc=exc)
    if after is None and not history and isinstance(exc, InputValidationError):
        return Advance(None, error=error, exc=exc)
    detail = exc.fields() if isinstance(exc, StepError) else {}
    failure = {"step": getattr(node, "name", error["step"]), "kind": "error", "step_kind": getattr(node, "kind", None),
               "input": state, "result": {"error": f"{type(exc).__name__}: {exc}", **detail}}
    pause = {"kind": "error", "step": error["step"], "error": error["error"]}
    return Advance(Cursor(after, state, history, pause), entries=history[carried:], lines=lines,
                   error=error, failure=failure, exc=exc)


__all__ = ["Advance", "Cursor", "ERROR_KINDS", "PAUSED", "PRIVATE", "decision_pause", "error_object", "pause_of",
           "settled_line", "start", "step_line", "submit", "thresholds_of"]
