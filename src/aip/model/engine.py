"""The run loop: one procedure, one state, one record, stepping until a pause, the end or a
failure (`docs/language/runtime.md`).

    engine = Engine(resolver=TypeSafeResolver.from_environment())  # None when no model is configured
    run = engine.start(procedure, {"message": "..."})      # steps until it must stop
    if run.status == "paused":
        run = engine.resume(run, {"0": {"reply": "..."}})   # the agent's answers, then on it goes
    run.status, run.result, run.history

A `Run` is data: the state, the history, the node about to run (`at`), the loop frames, the
pending pause, the error when a step failed, the identity of who ran it; `to_dict` and
`from_dict` move it in and out of a file or a server. The `Engine` holds what every run on this
machine shares: the decision model, the file cache, the interpreter, the script timeout, the
batch size, the clock.

**Loops.** A `Loop` runs its passes in order on the one state, with a frame on the cursor's
stack that holds the pass count; `Until` is tested at the head of every pass and the moment a
body step (or a loop in the body) produces the watched answer, `At_Most` at the head, `Again`
re-enters at a step at the loop's level and the pass ends when the loop is reached again. A
`For` runs its passes as independent cursors over a copy of the state, `batch` at a time: a
batch whose body is one `Decide` is one model call with the question keys suffixed by pass and
mapped back; any other body drives each pass in turn until it pauses or finishes, so one pause
carries every pass waiting at the same step. The record of a pass is buffered and appended
when its batch completes, pass by pass in input order, so the record is the same at every
batch size; a pass that fails fails the run, and the passes of its batch that finished are
recorded.

**Pauses.** A `Task_Agent` step always pauses; a `Decide` step never does: with no model
configured it fails the run (`no_decision_model`), and so does a model that raises
(`decision_model_failed`), and `retry` asks again. A pause is `{"kind": "task", "step", "tasks":
[...]}`, one task per pass waiting at the step; outside a loop there is one. A task carries
`index` (its position in the list), `pass` and `passes` (which pass of which loop), `prompt`,
`state`, `references`, `answer_with` (the `Produce` keys and types) and `labels` (the values a
`choice` or `score` among them may take). `resume` takes the answers keyed by task index
(`{"0": {...}}`), or one answer object when there is one task; an answer that does not fit (a
missing key, a value outside the labels, anything on an answer but its value) raises
`InvalidOutput` and the pause stands; a task left unanswered fails its pass.

**The record.** Every entry carries `bundle_id`, `step`, `kind`, `pass` (the innermost loop's
pass index, None outside loops), `passes` (`[{"loop", "pass"}]` from the outermost loop in),
`at` (UTC), `input` (the Read keys the step saw) and `result` (what it produced), plus per kind:
a `Decide` entry `answered_by` (`{"model": name, "endpoint": url}`) and `history_sent`; a `Route`
entry `read`, `answer`, `check` (`below`, `confidence`, `fired`, `reason`: `below` or `absent`),
`value` and `to`; an `Aggregate` entry `resolutions` per aggregation; an `Execute` entry `script`,
`stdin` and `seconds`; a `Task_Agent` entry the `prompt` and `references` it was given. A loop
writes one entry when it exits (`kind` `For` or `Loop`): `result` holds `iterations` and the
collected list, `exit` says why and where (`until` at a step or at the head, `items`, `times`,
`cap`) with the `Until` answer's resolution. The record is appended, never rewritten; a failed
run keeps everything up to the failure and `error`. The run carries `identity`: `agent`,
`session` and `user`, as given to `start`."""

from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from aip.model import cache, steps
from aip.model.environment import Requires, default_step_timeout
from aip.model.procedure import Loop, Procedure, Step
from aip.model.resolver import Resolver
from aip.model.types import (
    JSON, ERROR_KINDS, DecisionModelFailed, InvalidOutput, LoopCap, NoDecisionModel, NotPaused, StepError, resumable,
)

RUNNING, PAUSED, DONE, FAILED = "running", "paused", "done", "failed"
STATUSES = (RUNNING, PAUSED, DONE, FAILED)

DEFAULT_BATCH = 10
DEFAULT_TIMEOUT = object()  # `Engine(timeout=...)` left unsaid: `default_step_timeout()`, read when the engine is made
IDENTITY_FIELDS = ("agent", "session", "user")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def new_identity(agent: str | None = None, session: str | None = None, user: str | None = None) -> JSON:
    """The identity fields of a run (plan question 14): who ran it, claimed, not verified. The
    CLI fills `agent` from `--agent` or `AIP_AGENT`, `session` from `--session` or `AIP_SESSION`,
    `user` from the server token's name."""
    return {"agent": agent, "session": session, "user": user}


@dataclass
class Cursor:
    """One thread of execution: the state, the node about to run (`position`, None once done),
    the loop frames from the outermost in, the entries written so far, the status, and the pause
    or error when stopped. The run is a cursor; each pass of a `For` is one too, over its own
    copy of the state, with `passes` naming the enclosing passes (`[{"loop", "pass"}]`). `loops`
    holds the runtime's keys (spec 2.6: `index`, `iterations`, and each loop's own key), which a
    step reads beside the state and which are never part of it."""
    state: JSON = field(default_factory=dict)
    history: list[JSON] = field(default_factory=list)
    position: str | None = None
    status: str = RUNNING
    pause: JSON | None = None
    error: JSON | None = None
    frames: list[JSON] = field(default_factory=list)
    passes: list[JSON] = field(default_factory=list)
    loops: JSON = field(default_factory=dict)
    before: list[JSON] = field(default_factory=list, repr=False)  # the history visible from before this cursor began

    def view(self) -> JSON:
        """What a step reads from: the state and the runtime's loop keys."""
        return {**self.state, **self.loops}

    def to_dict(self) -> JSON:
        return {"status": self.status, "position": self.position, "state": self.state, "loops": self.loops, "history": self.history,
                "pause": self.pause, "error": self.error, "frames": [_frame_to_dict(f) for f in self.frames], "passes": self.passes}

    @classmethod
    def from_dict(cls, data: JSON) -> "Cursor":
        return cls(dict(data.get("state") or {}), list(data.get("history") or []), data.get("position"), data.get("status", RUNNING),
                   data.get("pause"), data.get("error"), [_frame_from_dict(f) for f in data.get("frames") or []],
                   list(data.get("passes") or []), dict(data.get("loops") or {}))


def _frame_to_dict(frame: JSON) -> JSON:
    if frame["kind"] == "For":
        return {**frame, "cursors": [c.to_dict() for c in frame["cursors"]]}
    return dict(frame)


def _frame_from_dict(frame: JSON) -> JSON:
    if frame["kind"] == "For":
        return {**frame, "cursors": [Cursor.from_dict(c) for c in frame["cursors"]]}
    return dict(frame)


@dataclass
class Run(Cursor):
    """One run of a procedure: the cursor at the top level, plus what belongs to the run as a
    whole. `result` is the End's keys when done; `error` the error object when `failed` (the
    cursor stays at the step, and `Engine.retry` runs it again); `identity` who ran it;
    `started` and `finished` when it began and when it last reached done or failed."""
    procedure: Procedure = None  # type: ignore[assignment]
    result: JSON | None = None
    requires_checked: bool = False
    batch: int = DEFAULT_BATCH
    identity: JSON = field(default_factory=new_identity)
    started: str | None = None
    finished: str | None = None

    @property
    def bundle_id(self) -> str:
        return self.procedure.bundle_id

    def to_dict(self) -> JSON:
        return {"bundle_id": self.bundle_id, "started": self.started, "finished": self.finished, "identity": self.identity,
                **super().to_dict(), "result": self.result, "requires_checked": self.requires_checked, "batch": self.batch}

    @classmethod
    def from_dict(cls, procedure: Procedure, data: JSON) -> "Run":  # type: ignore[override]
        if data.get("bundle_id") != procedure.bundle_id:
            raise ValueError(f"the run is of bundle {data.get('bundle_id')}, not {procedure.bundle_id}")
        cursor = Cursor.from_dict(data)
        return cls(cursor.state, cursor.history, cursor.position, cursor.status, cursor.pause, cursor.error, cursor.frames, cursor.passes,
                   cursor.loops, procedure=procedure, result=data.get("result"), requires_checked=bool(data.get("requires_checked")),
                   batch=int(data.get("batch") or DEFAULT_BATCH), identity={**new_identity(), **(data.get("identity") or {})},
                   started=data.get("started"), finished=data.get("finished"))


class Engine:
    """Runs procedures. `resolver` is the decision model (None: no model configured); `home` the
    directory the file cache lives under (`AIP_HOME` when None); `python` the interpreter for
    `python` scripts (this process's own when None); `timeout` the seconds a script may run;
    `workdir` the directory scripts read and write the run's files in (`AIP_WORKDIR`; the
    current directory when None); `batch` how many `For` passes run at once (`--batch`, default
    10); `clock` the source of timestamps."""

    def __init__(self, resolver: Resolver | None = None, *, home: Path | None = None, python: str | None = None,
                 timeout: float | None | Any = DEFAULT_TIMEOUT, workdir: Path | None = None, batch: int = DEFAULT_BATCH,
                 clock: Callable[[], str] = utc_now):
        self.resolver = resolver
        self.home = home
        self.python = python
        self.timeout = default_step_timeout() if timeout is DEFAULT_TIMEOUT else timeout
        self.workdir = workdir
        self.batch = batch
        self.clock = clock
        self._requires: dict[str, Requires] = {}
        self._roots: dict[str, Path] = {}

    # ------------------------------------------------------------ the three entry points

    def start(self, procedure: Procedure, inputs: JSON, *, identity: JSON | None = None, batch: int | None = None) -> Run:
        """Open a run on the inputs and step it until it must stop. Inputs that do not fit the
        `Start` step raise `InvalidInput` before anything runs. `identity` is who runs it
        (`agent`, `session`, `user`); `batch` overrides the engine's batch size for this run."""
        start = procedure.step(procedure.start)
        state = steps.start(start, inputs)
        batch = self.batch if batch is None else batch
        if batch < 1:
            raise ValueError(f"the batch size is at least 1, not {batch}")
        run = Run(state, procedure=procedure, batch=batch, identity={**new_identity(), **(identity or {})})
        self._record(run, run, start, state, {})
        self._follow(run, run, start)
        return self._advance(run, run)

    def resume(self, run: Run, answers: Any) -> Run:
        """Carry the agent's answers to a paused run and step on. `answers` is keyed by task
        index, or is the one answer when the pause has one task. A bad answer raises and leaves
        the pause standing; a task with no answer fails its pass."""
        if run.status != PAUSED or run.pause is None:
            raise NotPaused(None, f"the run is {run.status}; only a paused run takes an answer")
        pause = run.pause
        by_index = _by_index(pause, answers)
        accepted, missing = [], []
        for task in pause["tasks"]:
            cursor, step = self._locate(run, task)
            if task["index"] not in by_index:
                if cursor is run:
                    raise InvalidOutput(step.name, [f"no answer for task {task['index']}"], missing=[str(task["index"])])
                missing.append((cursor, step, task))
                continue
            produced = steps.check_outputs(run.procedure, step, by_index[task["index"]], source="agent")
            accepted.append((cursor, step, task, produced))
        for cursor, step, task, produced in accepted:  # every answer checked before any is applied
            cursor.pause, cursor.status = None, RUNNING
            cursor.state.update(produced)
            self._record(run, cursor, step, task["state"], produced, prompt=task["prompt"], references=task["references"])
            try:
                self._after_step(run, cursor, step, set(produced))
            except StepError as err:  # the flow after the step: a loop's cap at the head of the next pass
                cursor.status, cursor.error = FAILED, {**err.to_dict(), **_where(cursor)}
        for cursor, step, task, in missing:
            cursor.pause, cursor.status = None, FAILED
            cursor.error = {**InvalidOutput(step.name, [f"no answer for task {task['index']} (pass {task['pass']})"],
                                            missing=[str(task["index"])]).to_dict(), **_where(cursor)}
        run.pause, run.status = None, RUNNING
        return self._advance(run, run)

    def retry(self, run: Run) -> Run:
        """Run the step that failed again, from the state before it."""
        if run.status != FAILED:
            raise NotPaused(None, f"the run is {run.status}; only a failed run is retried")
        self._clear_failure(run, run)
        return self._advance(run, run)

    # ------------------------------------------------------------ the loop

    def _advance(self, run: Run, cursor: Cursor) -> Run:
        """Step the cursor until it stops. For the run itself that is a pause, the end or a
        failure; for a `For` pass also the end of the pass."""
        while cursor.status == RUNNING:
            if cursor.position is None:
                raise RuntimeError("a running cursor has no step to run")
            try:
                if run.procedure.is_loop(cursor.position):
                    self._loop(run, cursor, run.procedure.loop(cursor.position))
                else:
                    self._step(run, cursor, run.procedure.step(cursor.position))
            except StepError as err:
                cursor.status, cursor.error = FAILED, {**err.to_dict(), **_where(cursor)}
        return run

    def _step(self, run: Run, cursor: Cursor, step: Step) -> None:
        procedure = run.procedure
        state = cursor.state
        if step.kind != "End":                 # End takes what the path produced (steps.end)
            steps.check_reads(procedure, step, state)
        match step.kind:
            case "End":
                result = steps.end(step, state)
                self._record(run, cursor, step, result, result)
                run.result, cursor.status, cursor.position = result, DONE, None
            case "Route":
                flow, record = steps.route(procedure, step, state)
                self._record(run, cursor, step, {record["read"]: record["answer"]}, {"to": record["to"]},
                             read=record["read"], check=record["check"], value=record["value"], to=record["to"])
                if flow.continues:
                    self._pass_over(run, cursor, flow.to)
                else:
                    cursor.position = flow.to
            case "Aggregate":
                produced, resolutions = steps.aggregate(procedure, step, state)
                key = step.produced_key()
                state[key] = produced
                self._record(run, cursor, step, steps.project(step, state), produced, resolutions=resolutions)
                self._after_step(run, cursor, step, {key})
            case "Execute":
                self._ensure_requires(run, step)
                outputs, stdin, seconds = steps.execute(procedure, step, state, self._root(procedure), python=self.python,
                                                        timeout=self.timeout, workdir=self.workdir)
                state.update(outputs)
                self._record(run, cursor, step, stdin["state"], outputs, script=step.file("RUNS").path, stdin=stdin, seconds=seconds)
                self._after_step(run, cursor, step, set(outputs))
            case "Task_Agent":
                task = steps.task(procedure, step, state, self._root(procedure))
                self._pause(cursor, "task", step, [task])
            case "Decide":
                self._decide(run, cursor, step)
            case _:
                raise StepError(step.name, f"{step.kind} is not a step the engine runs")

    def _decide(self, run: Run, cursor: Cursor, step: Step) -> None:
        """A `Decide` is the model's: no model fails the step, and so does a model that raises;
        a retry asks again (spec 2.4)."""
        if self.resolver is None:
            raise NoDecisionModel(step.name)
        request = steps.decision_request(step, cursor.state, self._visible_history(cursor))
        try:
            decision = self.resolver.decide(request)
        except Exception as exc:
            raise self._model_failed(step, exc) from exc
        answers = steps.check_decision(step, decision.answers)
        key = step.produced_key()
        cursor.state[key] = answers
        self._record(run, cursor, step, request.state, answers, answered_by=decision.answered_by(), history_sent=request.history is not None)
        self._after_step(run, cursor, step, {key})

    def _model_failed(self, step: Step, exc: BaseException) -> DecisionModelFailed:
        resolver = self.resolver
        return DecisionModelFailed(step.name, getattr(resolver, "name", type(resolver).__name__), exc, getattr(resolver, "url", None))

    def _pause(self, cursor: Cursor, kind: str, step: Step, tasks: list[JSON]) -> None:
        where = _where(cursor)
        cursor.pause = {"kind": kind, "step": step.name, "tasks": [{"index": i, **where, **t} for i, t in enumerate(tasks)]}
        cursor.status = PAUSED

    # ------------------------------------------------------------ flow

    def _after_step(self, run: Run, cursor: Cursor, step: Step, written: set[str]) -> None:
        """A step is done and wrote `written`: an `Until` on the enclosing loop may end the loop
        here (spec 2.6), otherwise the step's flow is followed."""
        if written and self._until_ends(run, cursor, step.id, written, where=step.name):
            return
        self._follow(run, cursor, step)

    def _until_ends(self, run: Run, cursor: Cursor, node: str, written: set[str], *, where: str) -> bool:
        """`written` was just produced by `node`. Every enclosing `Loop` frame notes it (for the
        rule that a loop in a body exits having produced it); if the innermost loop's `Until`
        answer is among it, the node is in that loop's body and the condition now holds, the loop
        exits here, the pass counted, and the rest of the pass does not run."""
        for frame in cursor.frames:
            frame["written"] = sorted(set(frame.get("written") or []) | written)
        if not cursor.frames:
            return False
        frame = cursor.frames[-1]
        loop = run.procedure.loop(frame["loop"])
        if loop.until is None or loop.until.path[0] not in written or node not in loop.body:
            return False
        holds, resolution = steps.until_holds(run.procedure, loop, cursor.state)
        if not holds:
            return False
        frame["count"] += 1
        self._exit_loop(run, cursor, loop, frame, {"reason": "until", "where": where, "resolution": resolution})
        return True

    def _follow(self, run: Run, cursor: Cursor, step: Step) -> None:
        flow = step.next
        if flow is None:
            raise StepError(step.name, f"{step.name} has no next step")
        if flow.type == "CONTINUES":
            self._pass_over(run, cursor, flow.to)
        else:  # NEXT, or AGAIN: re-enter at a step at the loop's level; the pass ends when the loop is reached
            cursor.position = flow.to

    def _pass_over(self, run: Run, cursor: Cursor, loop_id: str) -> None:
        """`Continue`, or a loop's exit line reaching the enclosing loop: the pass is over. For a
        `Loop` the next pass begins at its head; for a `For` the pass's cursor is done."""
        if cursor.frames and cursor.frames[-1]["loop"] == loop_id:
            frame = cursor.frames[-1]
            frame["count"] += 1
            cursor.position = loop_id
            self._head(run, cursor, run.procedure.loop(loop_id), frame)
        else:
            cursor.status, cursor.position = DONE, loop_id

    # ------------------------------------------------------------ loops

    def _loop(self, run: Run, cursor: Cursor, loop: Loop) -> None:
        """The cursor is at a loop node: entering it, or back at it from `Again`."""
        frame = cursor.frames[-1] if cursor.frames and cursor.frames[-1]["loop"] == loop.id else None
        if loop.kind == "For":
            self._for(run, cursor, loop, frame)
        elif frame is None:
            items = steps.loop_items(loop, cursor.state) if loop.mode == "Over" else None
            frame = {"loop": loop.id, "name": loop.name, "kind": "Loop", "count": 0, "items": items, "written": [], "head": True}
            cursor.frames.append(frame)
            self._head(run, cursor, loop, frame)
        elif frame.pop("head", False):
            self._head(run, cursor, loop, frame)
        else:  # `Again` ran its course and the flow reached the loop: the pass is over, the count moves
            frame["count"] += 1
            self._head(run, cursor, loop, frame)

    def _head(self, run: Run, cursor: Cursor, loop: Loop, frame: JSON) -> None:
        """The head of a `Loop` pass: `Until`, the list, the count and the cap decide whether a
        pass runs (spec 2.6; runtime.md, Loops)."""
        count = frame["count"]
        frame.pop("head", None)
        if loop.until is not None:
            holds, resolution = steps.until_holds(run.procedure, loop, cursor.state)
            if holds:
                self._exit_loop(run, cursor, loop, frame, {"reason": "until", "where": "head", "resolution": resolution})
                return
        if loop.mode == "Over" and count >= len(frame["items"]):
            self._exit_loop(run, cursor, loop, frame, {"reason": "items", "where": "head"})
            return
        cap = loop.cap
        if cap is not None and count >= cap:
            if loop.mode == "Times":
                self._exit_loop(run, cursor, loop, frame, {"reason": "times", "where": "head"})
            elif loop.at_cap == "Else_Exit":
                self._exit_loop(run, cursor, loop, frame, {"reason": "cap", "where": "head"})
            else:
                frame["head"] = True  # a retry arrives at the head again, not at a pass over
                raise LoopCap(loop.name, cap, count, f"{loop.name} ran {count} passes without its condition holding (At_Most {cap}, Else_Fail)")
            return
        cursor.state[steps.INDEX] = count
        cursor.state[loop.name] = {steps.INDEX: count}  # the loop's own key (spec 2.6): `revise.index`
        if loop.mode == "Over":
            cursor.state[loop.item] = copy.deepcopy(frame["items"][count])
        cursor.position = loop.enters

    def _exit_loop(self, run: Run, cursor: Cursor, loop: Loop, frame: JSON, exit: JSON, result: JSON | None = None) -> None:
        """A loop is over: its frame goes, `iterations` (and a `For`'s list) are written, its
        entry is recorded, and the flow follows its exit line."""
        assert cursor.frames and cursor.frames[-1] is frame
        cursor.frames.pop()
        written = set(frame.get("written") or []) | loop.produced_keys
        cursor.state[steps.ITERATIONS] = frame["count"]
        cursor.state[loop.name] = {steps.ITERATIONS: frame["count"]}  # `revise.iterations`, which a later loop does not overwrite
        produced: JSON = {steps.ITERATIONS: frame["count"], **(result or {})}
        cursor.state.update(result or {})
        enclosing = _passes(cursor)
        if enclosing:
            cursor.state[steps.INDEX] = enclosing[-1]["pass"]
        else:
            cursor.state.pop(steps.INDEX, None)
        input = {".".join(loop.over): frame["items"]} if loop.over else {}
        self._record(run, cursor, loop, input, produced, exit=exit)
        if self._until_ends(run, cursor, loop.id, written, where=loop.name):
            return
        flow = loop.exit
        if flow is None:
            raise StepError(loop.name, f"{loop.name} has no exit line")
        if flow.type == "CONTINUES":
            self._pass_over(run, cursor, flow.to)
        else:
            cursor.position = flow.to

    def _for(self, run: Run, cursor: Cursor, loop: Loop, frame: JSON | None) -> None:
        """A `For`: independent passes over a list, `batch` at a time, each a cursor of its own
        (runtime.md, Batching). The cursor stays at the loop until every pass is done."""
        if frame is None:
            items = steps.loop_items(loop, cursor.state)
            frame = {"loop": loop.id, "name": loop.name, "kind": "For", "count": 0, "items": items, "collected": [None] * len(items),
                     "next": 0, "cursors": [], "before": len(cursor.history)}
            cursor.frames.append(frame)
        batched = steps.is_batched_decide(run.procedure, loop)
        while True:
            if not frame["cursors"]:
                if frame["next"] >= len(frame["items"]):
                    break
                indexes = range(frame["next"], min(frame["next"] + run.batch, len(frame["items"])))
                frame["cursors"] = [self._pass_cursor(cursor, loop, frame, i) for i in indexes]
                frame["next"] = indexes.stop
            for p in frame["cursors"]:  # a pass sees the record as it was before the loop, whatever batch it is in
                p.before = [*cursor.before, *cursor.history[:frame["before"]]]
            ready = [p for p in frame["cursors"] if p.status == RUNNING]
            if batched is not None and self.resolver is not None and ready and all(p.position == batched.id and not p.history for p in ready):
                self._decide_batch(run, cursor, batched, ready)
            for p in frame["cursors"]:
                if p.status == RUNNING:
                    self._advance(run, p)
            failed = [p for p in frame["cursors"] if p.status == FAILED]
            paused = [p for p in frame["cursors"] if p.status == PAUSED]
            if failed:
                self._flush(cursor, [p for p in frame["cursors"] if p.status != RUNNING])
                cursor.status, cursor.error = FAILED, failed[0].error
                return
            if paused:
                step = paused[0].pause["step"]
                group = [p for p in paused if p.pause["step"] == step]
                tasks = [{**t, "index": i} for i, t in enumerate(t for p in group for t in p.pause["tasks"])]
                cursor.pause = {**paused[0].pause, "tasks": tasks}
                cursor.status = PAUSED
                return
            for p in frame["cursors"]:
                if loop.collect_key is not None:
                    frame["collected"][p.passes[-1]["pass"]] = p.state.get(loop.collect_key)
            self._flush(cursor, frame["cursors"])
            frame["count"] += len(frame["cursors"])
            frame["cursors"] = []
        result = {loop.collect_into: frame["collected"]} if loop.collect_into else {}
        self._exit_loop(run, cursor, loop, frame, {"reason": "items"}, result)

    def _pass_cursor(self, cursor: Cursor, loop: Loop, frame: JSON, index: int) -> Cursor:
        """A fresh cursor for pass `index`: the state as it was before the loop, the item and `index`."""
        state = copy.deepcopy(cursor.state)
        state[loop.item] = copy.deepcopy(frame["items"][index])
        state[steps.INDEX] = index
        state[loop.name] = {steps.INDEX: index}
        return Cursor(state, [], loop.enters, RUNNING, None, None, [], [*_passes(cursor), {"loop": loop.name, "pass": index}])

    def _decide_batch(self, run: Run, cursor: Cursor, step: Step, passes: list[Cursor]) -> None:
        """One model call for a batch of passes whose body is this `Decide`: the question keys
        suffixed with the pass index on the way out and mapped back on the way in, so the record
        is one entry per pass as if each had called alone. The call failing fails every pass of
        it, so a retry makes one call again."""
        requests = [(p.passes[-1]["pass"], steps.decision_request(step, p.state, self._visible_history(p))) for p in passes]
        try:
            try:
                decision = self.resolver.decide(steps.batch_request(step, requests))
            except Exception as exc:
                raise self._model_failed(step, exc) from exc
            split = steps.split_answers(step, decision.answers, [i for i, _ in requests])
        except StepError as err:
            for p in passes:
                p.status, p.error = FAILED, {**err.to_dict(), **_where(p)}
            return
        key = step.produced_key()
        for p, (index, request) in zip(passes, requests):
            try:
                answers = steps.check_decision(step, split[index])
            except InvalidOutput as err:
                p.status, p.error = FAILED, {**err.to_dict(), **_where(p)}
                continue
            p.state[key] = answers
            self._record(run, p, step, request.state, answers, answered_by=decision.answered_by(), history_sent=request.history is not None)
            self._after_step(run, p, step, {key})

    def _flush(self, cursor: Cursor, passes: list[Cursor]) -> None:
        """Append the passes' entries to the cursor's record, pass by pass in input order."""
        for p in sorted(passes, key=lambda p: p.passes[-1]["pass"]):
            cursor.history.extend(p.history)
            p.history = []

    # ------------------------------------------------------------ pauses and failures, located

    def _locate(self, run: Run, task: JSON) -> tuple[Cursor, Step]:
        """The cursor a task belongs to (the run, or a `For` pass, following the task's `passes`)
        and the step it waits at."""
        cursor: Cursor = run
        while cursor.position is not None and run.procedure.is_loop(cursor.position) and cursor.frames and cursor.frames[-1]["kind"] == "For" \
                and cursor.frames[-1]["loop"] == cursor.position:
            frame = cursor.frames[-1]
            wanted = next((e["pass"] for e in task.get("passes") or [] if e["loop"] == frame["name"]), None)
            found = next((p for p in frame["cursors"] if p.passes[-1]["pass"] == wanted), None)
            if found is None:
                raise InvalidOutput(frame["name"], [f"task {task['index']} names no pass of {frame['name']}"])
            cursor = found
        if cursor.position is None or run.procedure.is_loop(cursor.position):
            raise NotPaused(None, f"task {task['index']} is not waiting at a step")
        return cursor, run.procedure.step(cursor.position)

    def _clear_failure(self, run: Run, cursor: Cursor) -> None:
        cursor.error, cursor.status = None, RUNNING
        if cursor.position is not None and run.procedure.is_loop(cursor.position) and cursor.frames and cursor.frames[-1]["kind"] == "For":
            for p in cursor.frames[-1]["cursors"]:
                if p.status == FAILED:
                    self._clear_failure(run, p)

    # ------------------------------------------------------------ helpers

    def _visible_history(self, cursor: Cursor) -> list[JSON]:
        """The record as this cursor sees it: a pass sees what came before the loop and its own
        entries, never another pass's (runtime.md, independence)."""
        return [*cursor.before, *cursor.history]

    def _record(self, run: Run, cursor: Cursor, node: Step | Loop, input: JSON, result: JSON, **extra: Any) -> None:
        """Append the node's entry to the cursor's record. What it holds is copied: the state
        moves on, the record does not."""
        cursor.history.append(copy.deepcopy({"bundle_id": run.bundle_id, "step": node.name, "kind": node.kind, **_where(cursor),
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


def _passes(cursor: Cursor) -> list[JSON]:
    """Every enclosing pass, outermost first: the `For` passes the cursor runs in, then the
    `Loop` frames on its stack."""
    return [*cursor.passes, *({"loop": f["name"], "pass": f["count"]} for f in cursor.frames if f["kind"] == "Loop")]


def _where(cursor: Cursor) -> JSON:
    """The `pass` and `passes` fields of an entry, a task or an error."""
    passes = _passes(cursor)
    return {"pass": passes[-1]["pass"] if passes else None, "passes": passes}


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


__all__ = ["Engine", "Run", "Cursor", "new_identity", "RUNNING", "PAUSED", "DONE", "FAILED", "STATUSES", "ERROR_KINDS",
           "DEFAULT_BATCH", "IDENTITY_FIELDS", "utc_now"]
