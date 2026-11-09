"""The run loop: one procedure, one state, one record, stepping until a pause, the end or a
failure (`docs/language/runtime.md`).

    engine = Engine(resolver=ScriptedResolver({...}))
    run = engine.start(procedure, {"message": "..."})      # steps until it must stop
    if run.status == "paused":
        run = engine.resume(run, {"reply": "..."})          # the agent's answer, then on it goes
    run.status, run.result, run.history

A `Run` is data: the state, the history, the node about to run (`at`), the pending pause, and
the error when a step failed; `to_dict` and `from_dict` move it in and out of a file or a
server. The `Engine` holds what every run on this machine shares: the decision model, the file
cache, the interpreter, the script timeout, the clock.

**Pauses.** A `Task_Agent` step always pauses; a `Decide` step pauses when no model is
configured, or the model fails, and the step says `Agent_Fallback true` (otherwise it fails,
`no_decision_model` or `decision_model_failed`). A pause is `{"kind": "task" | "decision",
"step", "tasks": [...]}`, one task per pass; outside a loop there is one, with `index` 0. A task
carries `prompt`, `state`, `references` and `answer_with` (the `Produce` keys and types), or for a
decision `questions` and `answer_with` (the question names and types), plus `reason` when a model
failed. `resume` takes the answers keyed by task index (`{"0": {...}}`), or one answer object when
there is one task; an answer that does not fit raises `InvalidOutput` and the pause stands.

**The record.** Every entry carries `bundle_id`, `step`, `kind`, `pass` (None outside a loop),
`at` (UTC), `input` (the Read keys the step saw) and `result` (what it produced), plus per kind:
a `Decide` entry `answered_by` (`{"model": name}` or `"agent"`) and `history_sent`; a `Route`
entry `read`, `answer`, `check` (`below`, `confidence`, `fired`, `reason`: `below` or `absent`),
`value` and `to`; an `Aggregate` entry `resolutions` per aggregation; an `Execute` entry `script`,
`stdin` and `seconds`; a `Task_Agent` entry the `prompt` and `references` it was given. The
record is appended, never rewritten; a failed run keeps everything up to the failure and `error`.

Loops, batching and the TypeSafe resolver arrive with the next milestone; a flow into a loop
fails the run until then."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from aip.model import cache, steps
from aip.model.environment import Requires, default_step_timeout
from aip.model.procedure import Procedure, Step
from aip.model.resolver import Resolver
from aip.model.types import (
    JSON, ERROR_KINDS, DecisionModelFailed, InvalidOutput, NoDecisionModel, NotPaused, StepError,
)

RUNNING, PAUSED, DONE, FAILED = "running", "paused", "done", "failed"
STATUSES = (RUNNING, PAUSED, DONE, FAILED)

DEFAULT_TIMEOUT = object()  # `Engine(timeout=...)` left unsaid: `default_step_timeout()`, read when the engine is made


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass
class Run:
    """One run of a procedure. `at` is the node about to run (None once done); `pause` the
    pending pause when `status` is `paused`; `error` the error object when it is `failed`
    (the step stays at `at`, and `Engine.retry` runs it again); `result` the End's keys when done."""
    procedure: Procedure
    state: JSON = field(default_factory=dict)
    history: list[JSON] = field(default_factory=list)
    at: str | None = None
    status: str = RUNNING
    pause: JSON | None = None
    error: JSON | None = None
    result: JSON | None = None
    requires_checked: bool = False

    @property
    def bundle_id(self) -> str:
        return self.procedure.bundle_id

    def to_dict(self) -> JSON:
        return {"bundle_id": self.bundle_id, "state": self.state, "history": self.history, "at": self.at, "status": self.status,
                "pause": self.pause, "error": self.error, "result": self.result, "requires_checked": self.requires_checked}

    @classmethod
    def from_dict(cls, procedure: Procedure, data: JSON) -> "Run":
        if data.get("bundle_id") != procedure.bundle_id:
            raise ValueError(f"the run is of bundle {data.get('bundle_id')}, not {procedure.bundle_id}")
        return cls(procedure, dict(data["state"]), list(data["history"]), data.get("at"), data.get("status", RUNNING),
                   data.get("pause"), data.get("error"), data.get("result"), bool(data.get("requires_checked")))


class Engine:
    """Runs procedures. `resolver` is the decision model (None: no model configured); `home` the
    directory the file cache lives under (`AIP_HOME` when None); `python` the interpreter for
    `python` scripts (this process's own when None); `timeout` the seconds a script may run;
    `workdir` the directory scripts read and write the run's files in (`AIP_WORKDIR`; the
    current directory when None); `clock` the source of timestamps."""

    def __init__(self, resolver: Resolver | None = None, *, home: Path | None = None, python: str | None = None,
                 timeout: float | None | Any = DEFAULT_TIMEOUT, workdir: Path | None = None, clock: Callable[[], str] = utc_now):
        self.resolver = resolver
        self.home = home
        self.python = python
        self.timeout = default_step_timeout() if timeout is DEFAULT_TIMEOUT else timeout
        self.workdir = workdir
        self.clock = clock
        self._requires: dict[str, Requires] = {}
        self._roots: dict[str, Path] = {}

    # ------------------------------------------------------------ the three entry points

    def start(self, procedure: Procedure, inputs: JSON) -> Run:
        """Open a run on the inputs and step it until it must stop. Inputs that do not fit the
        `Start` step raise `InvalidInput` before anything runs."""
        start = procedure.step(procedure.start)
        state = steps.start(start, inputs)
        run = Run(procedure, state, [], None)
        self._record(run, start, state, {}, pass_=None)
        run.at = self._follow(run, start)
        return self._advance(run)

    def resume(self, run: Run, answers: Any) -> Run:
        """Carry the agent's answers to a paused run and step on. `answers` is keyed by task
        index, or is the one answer when the pause has one task. A bad answer raises and leaves
        the pause standing."""
        if run.status != PAUSED or run.pause is None:
            raise NotPaused(None, f"the run is {run.status}; only a paused run takes an answer")
        pause = run.pause
        step = run.procedure.step(run.at)
        by_index = _by_index(pause, answers)
        for t in pause["tasks"]:
            if t["index"] not in by_index:
                raise InvalidOutput(step.name, [f"no answer for task {t['index']}"], missing=[str(t["index"])])
        [task] = pause["tasks"]  # one pass outside a loop; batching arrives with loops
        answer = by_index[task["index"]]
        if pause["kind"] == "decision":
            produced = {step.produced_key(): steps.check_decision(step, answer, by_hand=True)}
            extra: JSON = {"answered_by": "agent", "history_sent": False}
        else:
            produced = steps.check_outputs(run.procedure, step, answer, strict=False)
            extra = {"prompt": task["prompt"], "references": task["references"]}
        run.pause, run.status = None, RUNNING
        run.state.update(produced)
        self._record(run, step, task["state"], produced if pause["kind"] == "task" else produced[step.produced_key()],
                     pass_=task.get("pass"), **extra)
        run.at = self._follow(run, step)
        return self._advance(run)

    def retry(self, run: Run) -> Run:
        """Run the step that failed again, from the state before it."""
        if run.status != FAILED:
            raise NotPaused(None, f"the run is {run.status}; only a failed run is retried")
        run.error, run.status = None, RUNNING
        return self._advance(run)

    # ------------------------------------------------------------ the loop

    def _advance(self, run: Run) -> Run:
        while run.status == RUNNING:
            if run.at is None:
                raise RuntimeError("a running run has no step to run")
            if run.procedure.is_loop(run.at):
                run.status, run.error = FAILED, StepError(run.at.split(":", 1)[1], "loops are not run yet (plan milestone R2)").to_dict()
                break
            step = run.procedure.step(run.at)
            try:
                self._step(run, step)
            except StepError as err:
                run.status, run.error = FAILED, err.to_dict()
        return run

    def _step(self, run: Run, step: Step) -> None:
        procedure = run.procedure
        steps.check_reads(procedure, step, run.state)
        match step.kind:
            case "End":
                result = steps.end(step, run.state)
                self._record(run, step, result, result, pass_=None)
                run.result, run.status, run.at = result, DONE, None
            case "Route":
                target, record = steps.route(procedure, step, run.state)
                self._record(run, step, {record["read"]: record["answer"]}, {"to": record["to"]}, pass_=None,
                             read=record["read"], check=record["check"], value=record["value"], to=record["to"])
                run.at = target
            case "Aggregate":
                produced, resolutions = steps.aggregate(procedure, step, run.state)
                key = step.produced_key()
                run.state[key] = produced
                self._record(run, step, steps.project(step, run.state), produced, pass_=None, resolutions=resolutions)
                run.at = self._follow(run, step)
            case "Execute":
                self._ensure_requires(run, step)
                outputs, stdin, seconds = steps.execute(procedure, step, run.state, self._root(procedure), python=self.python,
                                                        timeout=self.timeout, workdir=self.workdir)
                run.state.update(outputs)
                self._record(run, step, stdin["state"], outputs, pass_=None, script=step.file("RUNS").path, stdin=stdin,
                             seconds=seconds)
                run.at = self._follow(run, step)
            case "Task_Agent":
                task = steps.task(procedure, step, run.state, self._root(procedure))
                run.pause = {"kind": "task", "step": step.name, "tasks": [{"index": 0, "pass": None, **task}]}
                run.status = PAUSED
            case "Decide":
                self._decide(run, step)
            case _:
                raise StepError(step.name, f"{step.kind} is not a step the engine runs")

    def _decide(self, run: Run, step: Step) -> None:
        request = steps.decision_request(step, run.state, run.history)
        fallback = bool(step.properties.get("agent_fallback"))
        reason: str | None = None
        if self.resolver is None:
            if not fallback:
                raise NoDecisionModel(step.name)
            reason = "no_decision_model"
        else:
            try:
                decision = self.resolver.decide(request)
                answers = steps.check_decision(step, decision.answers, by_hand=False)
            except InvalidOutput:
                raise
            except Exception as exc:  # the model failed: the agent's, or the run's failure
                failed = DecisionModelFailed(step.name, getattr(self.resolver, "name", type(self.resolver).__name__), exc)
                if not fallback:
                    raise failed from exc
                reason = f"{failed.kind}: {failed.cause}"
            else:
                run.state[step.produced_key()] = answers
                self._record(run, step, request.state, answers, pass_=None, answered_by={"model": decision.model},
                             history_sent=request.history is not None)
                run.at = self._follow(run, step)
                return
        run.pause = {"kind": "decision", "step": step.name, "reason": reason, "tasks": [{
            "index": 0, "pass": None, "questions": steps.questions_for_agent(request), "state": request.state,
            "answer_with": {q.name: q.type for q in request.questions}}]}
        run.status = PAUSED

    # ------------------------------------------------------------ helpers

    def _follow(self, run: Run, step: Step) -> str:
        flow = step.next
        if flow is None:
            raise StepError(step.name, f"{step.name} has no next step")
        return flow.to

    def _record(self, run: Run, step: Step, input: JSON, result: JSON, *, pass_: int | None, **extra: Any) -> None:
        """Append the step's entry. What it holds is copied: the state moves on, the record does not."""
        run.history.append(copy.deepcopy({"bundle_id": run.bundle_id, "step": step.name, "kind": step.kind, "pass": pass_,
                                          "at": self.clock(), "input": input, "result": result, **extra}))

    def _root(self, procedure: Procedure) -> Path:
        """The bundle's files, unpacked once per bundle id."""
        if procedure.bundle_id not in self._roots:
            self._roots[procedure.bundle_id] = cache.unpack(procedure.bundle_id, procedure.files(), self.home)
        return self._roots[procedure.bundle_id]

    def _ensure_requires(self, run: Run, step: Step) -> None:
        if run.requires_checked:
            return
        declared = run.procedure.requires
        if declared is not None:
            requires = self._requires.setdefault(run.bundle_id, Requires(*declared))
            requires.ensure(step.name, self.python)
        run.requires_checked = True


def _by_index(pause: JSON, answers: Any) -> dict[int, Any]:
    """The answers keyed by task index: as given, from a list in task order, or the one answer
    for the one task."""
    tasks = pause["tasks"]
    if isinstance(answers, list):
        return dict(enumerate(answers))
    if isinstance(answers, dict) and answers and all(str(k).isdigit() for k in answers) and all(isinstance(v, dict) for v in answers.values()):
        return {int(k): v for k, v in answers.items()}
    if isinstance(answers, dict) and len(tasks) == 1:
        return {tasks[0]["index"]: answers}
    raise InvalidOutput(pause["step"], ["the answers are an object keyed by task index, or one answer object for a single task"])


__all__ = ["Engine", "Run", "RUNNING", "PAUSED", "DONE", "FAILED", "STATUSES", "ERROR_KINDS", "utc_now"]
