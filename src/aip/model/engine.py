"""The run loop: one procedure, one cursor, one answer at a time.

A run is a `Cursor`: the step whose output the next input answers (`after`), the full state,
the history, and what the run waits for (`pause`). `start` opens one from the start input;
`submit` carries one thing to it: the answer to its pause, or nothing to retry a failed step.
Each steps the procedure until a pause, the end, or a failure, and returns an `Advance`.

The same loop runs in both places a run can live: the local client (`aip run ./folder`)
keeps the cursor in its run file; the server keeps it in its run backend and the client
holds only the run id. Neither keeps anything in memory between calls.

Pause kinds, as `cursor.pause["kind"]`:

- `client_task`, `decision` (no decision model), `review` (an answer under its threshold):
  the client must answer. The block is what the CLI prints, minus `run_id` and `run_file`.
- `error`: a step failed; `after`, `state`, and `history` are as they were before it, so a
  `submit` with no answer retries it.
- `done`: the end was reached; `state` is the end step's inputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from aip.model.procedure import Procedure
from aip.model.steps import DEFAULT_MIN_CONFIDENCE, DEFAULT_NOUL_MARGIN, Decision, describe_next
from aip.model.types import (
    JSON, InputValidationError, OutputValidationError, StepError, project, validate_input, validate_output,
)

# The error kinds of the error object (`docs/cli-json.md`); anything else is reported as `server`.
ERROR_KINDS = ("script_failed", "invalid_input", "invalid_output", "requires_unmet", "timeout", "server")

PAUSED = ("client_task", "decision", "review")


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
        line["resolver"] = "manual" if entry.get("manual") else "typesafe"
    elif entry["kind"] == "execution" and "seconds" in entry:
        line["seconds"] = entry["seconds"]
    return line


def settled_line(pause: JSON) -> JSON | None:
    """The line for a paused step, printed once its answer is accepted."""
    if pause["kind"] == "client_task":
        return {"event": "step", "step": pause["step"], "kind": "client_task"}
    if pause["kind"] == "review":
        return {"event": "step", "step": pause["step"], "kind": "decision", "resolver": "typesafe"}
    return None


# ---------------------------------------------------------------------------- pauses


def pause_of(response: JSON) -> JSON | None:
    """The pause a step response asks for: a client task, or a decision answered under its threshold."""
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


def thresholds_of(step: Decision) -> Dict[str, float]:
    """Every question's threshold as the author set it in SKILL.md, the type's default otherwise."""
    return {name: step.thresholds.get(name, DEFAULT_NOUL_MARGIN if q.type == "noul" else DEFAULT_MIN_CONFIDENCE)
            for name, q in step.questions.items()}


def decision_pause(step: Decision, state: JSON) -> JSON:
    """The pause for a decision nothing could answer: what the decision model would have been given,
    and the thresholds a client-side resolver applies (not printed by the CLI)."""
    return {"kind": "decision", "step": step.name, "questions": describe_next(step)["questions"],
            "state": project(state, step.inputs), "thresholds": thresholds_of(step)}


# ------------------------------------------------------------------------------ loop


def start(procedure: Procedure, payload: JSON, decision_model: bool) -> Advance:
    """Open a run on the start input and step it until it must stop."""
    return _drive(procedure, decision_model, None, payload, [])


def submit(procedure: Procedure, cursor: Cursor, answer: JSON | None, decision_model: bool) -> Advance:
    """Carry one thing to a run: the answer to its pause, or (`None`, at a failed step) a retry.
    A retry may carry keys too; they are merged over the state before the step. An answer that
    does not fit leaves the run where it was (`kept`)."""
    pause = cursor.pause or {}
    kind = pause.get("kind")
    if kind == "done":
        return Advance(cursor, kept=True, error={
            "error": "server", "step": None, "message": "the run is done; there is nothing to answer"})
    if kind == "error":
        return _drive(procedure, decision_model, cursor.after, {**cursor.state, **(answer or {})}, cursor.history)
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
        return _drive(procedure, decision_model, cursor.after, cursor.state, cursor.history,
                      answering=pause, answers=answer)
    if kind == "client_task":
        try:
            validate_output(pause["step"], pause["answer_with"], answer, strict=False)
        except OutputValidationError as exc:
            return Advance(cursor, kept=True, error=error_object(exc), exc=exc)
    if kind == "review":
        unknown = [k for k in answer if k not in pause["proposed_answers"]]
        if unknown:
            return Advance(cursor, kept=True, error={
                "error": "invalid_output", "step": pause["step"],
                "message": f"not questions of step {pause['step']!r}: {unknown}; "
                           f"override only {list(pause['proposed_answers'])}",
                "missing": [], "invalid": unknown})
    return _drive(procedure, decision_model, cursor.after, {**cursor.state, **answer}, cursor.history,
                  answering=pause)


def _drive(procedure: Procedure, decision_model: bool, after: str | None, payload: JSON, history: List[JSON],
           answering: JSON | None = None, answers: JSON | None = None) -> Advance:
    """Step until a pause, the end, or a failure. `answering` is the pause this call answers: a bad
    answer leaves it in place. `answers` answers a manual decision first."""
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
                response = node.accept_manual(payload, [*history, *routed], answers).to_dict()
                answers = None
            elif isinstance(node, Decision) and not decision_model:
                validate_input(node.name, node.inputs, payload)          # before asking anyone
                settle()
                return stop(decision_pause(node, payload))
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


__all__ = ["Advance", "Cursor", "ERROR_KINDS", "PAUSED", "decision_pause", "error_object", "pause_of",
           "settled_line", "start", "step_line", "submit", "thresholds_of"]
