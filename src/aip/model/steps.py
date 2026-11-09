"""What each step kind does, as functions of the graph and the state (spec 2.1, 2.4, 2.5;
`docs/language/runtime.md`, Steps). The engine (`aip.model.engine`) calls these in order and
keeps the record; nothing here touches the run's history or cursor.

The state is one JSON object of keys. A step sees its `Read` keys, each under the last segment
of its path (`Read triage_decision.tone` gives the step `tone`, the one answer; spec 2.4), checked
against the declared types before it runs. A step's result is checked against its `Produce` keys
before anything is written; an answer written bare (`true`) is stored as `{"value": true}`
(`aip.model.types.normalise`), the one normalisation the runtime performs. An answer's value is
checked against the key's labels; an agent's answer may carry nothing but its value, a script's
the model fields of spec 2.4 (`confidence`, `probabilities`, ...), and anything else on it is
`invalid_output`."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from aip.model.answers import probability_of
from aip.model.procedure import Aggregation, Flow, Loop, Procedure, Question, Step
from aip.model.resolver import DecisionRequest
from aip.model.types import (
    ANSWER_FIELDS, JSON, VALUE_KIND, InvalidInput, InvalidOutput, LoopCap, NoBranch, ScriptFailed, ScriptTimeout, branch_key,
    conforms, describe, extra_fields, normalise,
)

WORKDIR = "AIP_WORKDIR"
PYTHON = "python"
INDEX, ITERATIONS = "index", "iterations"   # the runtime's keys (spec 2.1, Loops)
PASS_SUFFIX = "__"                           # `follows__3`: question `follows` of pass 3 in a batched call (runtime.md)

_FIELD = re.compile(r"\{([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*)\}")
_ASSET = re.compile(r"\{assets\[([^\]]+)\]\}")


# ---------------------------------------------------------------- the state

def lookup(state: JSON, path: list[str]) -> Any:
    """The value a dotted path names in the state; `KeyError` with the path when it is absent."""
    value: Any = state
    for i, seg in enumerate(path):
        if not isinstance(value, dict) or seg not in value:
            raise KeyError(".".join(path[: i + 1]))
        value = value[seg]
    return value


def project(step: Step, state: JSON) -> JSON:
    """The `Read` keys as the step sees them: each under the last segment of its path."""
    return {r.name: lookup(state, r.path) for r in step.declared_reads}


def check_reads(procedure: Procedure, step: Step, state: JSON) -> None:
    """Every `Read` key is in the state with its declared type (`invalid_input` otherwise)."""
    errors, missing, invalid = [], [], []
    for r in step.declared_reads:
        try:
            value = lookup(state, r.path)
        except KeyError as err:
            errors.append(f"{r.dotted} is not in the state ({err.args[0]} is missing)")
            missing.append(r.dotted)
            continue
        type = r.type if r.field is None else None
        if type is None and r.field is None:
            type = procedure.key_type(r.key)
        why = conforms(type, value)
        if why is not None:
            errors.append(f"{r.dotted}: {why}")
            invalid.append(r.dotted)
    if errors:
        raise InvalidInput(step.name, errors, missing, invalid)


def check_outputs(procedure: Procedure, step: Step, result: Any, *, source: str) -> JSON:
    """`result` as the step's `Produce` keys, normalised: every key present with its type, an
    answer's value among the key's labels. `source` is `script` (an `Execute`: a key the step did
    not declare is an error, and an answer may carry the model fields of spec 2.4) or `agent` (a
    `Task_Agent`: undeclared keys are dropped, and an answer is its value and nothing else)."""
    if not isinstance(result, dict):
        raise InvalidOutput(step.name, [f"expected a JSON object of the Produce keys, got {describe(result)}"])
    errors, missing, invalid, out = [], [], [], {}
    for p in step.produces:
        if p.key not in result:
            errors.append(f"{p.key} is missing")
            missing.append(p.key)
            continue
        value = normalise(p.type, result[p.key])
        why = conforms(p.type, value, p.labels) or extra_fields(p.type, value, ANSWER_FIELDS.get(p.type or "", ()) if source == "script" else ())
        if why is not None:
            errors.append(f"{p.key}: {why}")
            invalid.append(p.key)
        out[p.key] = value
    if source == "script":
        declared = {p.key for p in step.produces}
        for key in result:
            if key not in declared:
                errors.append(f"{key} is not a Produce key of {step.name}")
                invalid.append(key)
    if errors:
        raise InvalidOutput(step.name, errors, missing, invalid)
    return out


def answer_with(step: Step) -> dict[str, str | None]:
    """`{key: type}` for the step's `Produce` keys: what an agent answers with."""
    return {p.key: p.type for p in step.produces}


def labels_of(step: Step) -> dict[str, list[str]]:
    """`{key: labels}` for the `Produce` keys declared under labels (`tone: choice [angry, calm]`):
    the values an agent's `choice` answer may take, or the levels of its `score`."""
    return {p.key: list(p.labels) for p in step.produces if p.labels}


def expects(procedure: Procedure, step: Step) -> dict[str, str | None]:
    """The next step's `Read` keys with their types, handed to a script as `expects`."""
    flow = step.next
    if flow is None or procedure.is_loop(flow.to):
        return {}
    following = procedure.step(flow.to)
    return {r.name: (r.type or procedure.key_type(r.key)) if r.field is None else None for r in following.declared_reads}


# ---------------------------------------------------------------- rendering

def _text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def render(text: str, state: JSON, assets: dict[str, str] | None = None) -> str:
    """`{key}` and `{decision.question}` filled in from the state, `{assets[stem]}` from the
    step's `Use` files; a placeholder nothing resolves is left as written, and so is any other
    brace (spec 2.1, Strings)."""
    def field(m: re.Match) -> str:
        try:
            return _text(lookup(state, m.group(1).split(".")))
        except KeyError:
            return m.group(0)

    def asset(m: re.Match) -> str:
        if assets is not None and m.group(1) in assets:
            return assets[m.group(1)]
        return m.group(0)

    return _FIELD.sub(field, _ASSET.sub(asset, text))


# ---------------------------------------------------------------- Start and End

def start(step: Step, inputs: Any) -> JSON:
    """The inputs checked against the `Start` declarations: every one present with its type (an
    answer's value among its labels, and nothing on it but the value), nothing undeclared
    (`invalid_input` otherwise)."""
    if not isinstance(inputs, dict):
        raise InvalidInput("start", [f"the inputs are a JSON object, not {describe(inputs)}"])
    errors, missing, invalid, out = [], [], [], {}
    for p in step.produces:
        if p.key not in inputs:
            errors.append(f"{p.key} is missing")
            missing.append(p.key)
            continue
        value = normalise(p.type, inputs[p.key])
        why = conforms(p.type, value, p.labels) or extra_fields(p.type, value, ())
        if why is not None:
            errors.append(f"{p.key}: {why}")
            invalid.append(p.key)
        out[p.key] = value
    declared = {p.key for p in step.produces}
    for key in inputs:
        if key not in declared:
            errors.append(f"{key} is not an input of this procedure; the inputs are {sorted(declared)}")
            invalid.append(key)
    if errors:
        raise InvalidInput("start", errors, missing, invalid)
    return out


def end(step: Step, state: JSON) -> JSON:
    """The result: the `End` step's `Read` keys."""
    return project(step, state)


# ---------------------------------------------------------------- Decide

def decision_request(step: Step, state: JSON, history: list[JSON]) -> DecisionRequest:
    """What the decision model is asked: the questions with `{key}` rendered, the `Read` keys
    as the thing to judge, and the history when the step says `History true`."""
    questions = [Question(q.name, q.type, q.labels, render(q.instruction, state),
                          [(label, render(text, state)) for label, text in q.criteria], q.order) for q in step.questions]
    sent = list(history) if step.properties.get("history") else None
    return DecisionRequest(step.name, questions, project(step, state), sent)


def check_decision(step: Step, answers: Any) -> JSON:
    """The model's answers as the decision key holds them: one answer object per question, its
    value of the question's kind and among its labels, the model's own fields kept whole."""
    if not isinstance(answers, dict):
        raise InvalidOutput(step.name, [f"the answers are an object with one entry per question, not {describe(answers)}"])
    errors, missing, invalid, out = [], [], [], {}
    for q in step.questions:
        if q.name not in answers:
            errors.append(f"no answer to {q.name}")
            missing.append(q.name)
            continue
        answer = normalise(q.type, answers[q.name])
        why = conforms(q.type, answer, q.labels)
        if why is not None:
            errors.append(f"{q.name}: {why}")
            invalid.append(q.name)
            continue
        out[q.name] = dict(answer)
    for name in answers:
        if step.questions and all(q.name != name for q in step.questions):
            errors.append(f"{name} is not a question of {step.name}")
            invalid.append(name)
    if errors:
        raise InvalidOutput(step.name, errors, missing, invalid)
    return out


def batch_request(step: Step, requests: list[tuple[int, DecisionRequest]]) -> DecisionRequest:
    """One model call for a batch of `For` passes whose body is this one `Decide` (runtime.md,
    Batching): the `Read` keys once (the same on every pass) and every pass's rendered questions,
    each key suffixed with the pass index, `follows__3`. `split_answers` maps the reply back."""
    first = requests[0][1]
    questions = [Question(f"{q.name}{PASS_SUFFIX}{i}", q.type, q.labels, q.instruction, q.criteria, q.order)
                 for i, request in requests for q in request.questions]
    return DecisionRequest(step.name, questions, first.state, first.history)


def split_answers(step: Step, answers: Any, indexes: list[int]) -> dict[int, JSON]:
    """The batched reply as one answer set per pass: `follows__3` becomes `follows` of pass 3.
    A key with no suffix, or an index the batch did not send, is an `invalid_output`."""
    if not isinstance(answers, dict):
        raise InvalidOutput(step.name, [f"the answers are an object with one entry per question, not {describe(answers)}"])
    out: dict[int, JSON] = {i: {} for i in indexes}
    stray = []
    for name, answer in answers.items():
        base, sep, suffix = str(name).rpartition(PASS_SUFFIX)
        if not sep or not suffix.isdigit() or int(suffix) not in out:
            stray.append(str(name))
            continue
        out[int(suffix)][base] = answer
    if stray:
        raise InvalidOutput(step.name, [f"{n} is not a question of {step.name} for any pass in the batch" for n in stray], invalid=stray)
    return out


def is_batched_decide(procedure: Procedure, loop: Loop) -> Step | None:
    """The one `Decide` a `For` body consists of, when a batch of its passes is one model call:
    the body is that step alone, it ends the pass (`Continue`), and its `Read` keys are the same
    on every pass, so it reads neither the item nor `index` (an interpolation of either is fine:
    the question is rendered per pass). None otherwise."""
    if len(loop.body) != 1 or procedure.is_loop(loop.body[0]):
        return None
    step = procedure.step(loop.body[0])
    if step.kind != "Decide" or step.next is None or step.next.type != "CONTINUES":
        return None
    per_pass = {loop.item, INDEX}
    if any(r.key in per_pass for r in step.declared_reads):
        return None
    return step


# ---------------------------------------------------------------- Route

def route(procedure: Procedure, step: Step, state: JSON) -> tuple[Flow, JSON]:
    """Where the route sends the run and what its record says: the flow taken (its `to` is the
    target's node id; `continues` marks a branch to `Continue`), and `{"read": dotted, "answer",
    "check": {"below", "confidence", "fired", "reason"} | None, "value": the branch word | None,
    "to": name}`. The check reads the answer's `confidence` and fires when it is below the bound
    (`reason: "below"`) or absent (`reason: "absent"`: a script's answer written without one; the
    compiler allows the check only on a decision's or a script's answer, spec 2.2). Otherwise the
    branch for `value` is taken, and a value with no branch fails the step (`no_branch`)."""
    [read] = step.declared_reads
    answer = lookup(state, read.path)
    if not isinstance(answer, dict) or "value" not in answer:
        raise InvalidInput(step.name, [f"{read.dotted} is {describe(answer)}, not an answer with a value"], invalid=[read.dotted])
    record: JSON = {"read": read.dotted, "answer": answer, "check": None, "value": None}
    check = step.check
    if check is not None:
        confidence = answer.get("confidence")
        if confidence is None:
            fired, reason = True, "absent"
        else:
            fired, reason = confidence < check.below, "below" if confidence < check.below else None
        record["check"] = {"below": check.below, "confidence": confidence, "fired": fired, "reason": reason}
        if fired:
            record["to"] = _name(check)
            return check, record
    key = branch_key(answer["value"], procedure.labels_of(read.path))
    for b in step.branches:
        if b.value == key or b.value == str(answer["value"]):
            record["value"] = b.value
            record["to"] = _name(b)
            return b, record
    raise NoBranch(step.name, read.dotted, answer["value"], [b.value or "" for b in step.branches])


def _name(flow: Flow) -> str:
    """What the record calls a branch's target: the step or loop name, or `Continue`."""
    return "Continue" if flow.continues else flow.to.split(":", 1)[1]


# ---------------------------------------------------------------- Aggregate

def _leaf_answers(value: Any, path: list[str], label: str) -> list[tuple[str, JSON]]:
    """Every answer a source names: through a list, element by element; a decision or an
    aggregation as a whole, every answer in it; a field, that one answer."""
    if isinstance(value, list):
        return [a for i, v in enumerate(value) for a in _leaf_answers(v, path, f"{label}[{i}]")]
    if path:
        if not isinstance(value, dict) or path[0] not in value:
            raise KeyError(f"{label}.{path[0]}")
        return _leaf_answers(value[path[0]], path[1:], f"{label}.{path[0]}")
    if isinstance(value, dict) and "value" in value:
        return [(label, value)]
    if isinstance(value, dict):
        return [(f"{label}.{k}", v) for k, v in value.items() if isinstance(v, dict) and "value" in v]
    raise KeyError(label)


def _answer_type(answer: JSON) -> str | None:
    v = answer["value"]
    if isinstance(v, bool):
        return "true_or_false"
    if isinstance(v, str):
        return "choice"
    if isinstance(v, int):
        return "score"
    return None


def _target(type: str | None, word: str | None, labels: list[str] | None) -> Any:
    """The value a condition's word stands for: `true`/`false`, a label, or a level (by label or number)."""
    if type == "true_or_false":
        return word == "true" if word is not None else True
    if type == "score" and word is not None:
        if labels and word in labels:
            return labels.index(word)
        if word.isdigit():
            return int(word)
    return word


def resolve_condition(answer: JSON, type: str | None, operator: str | None, word: str | None, bar: float | None,
                      labels: list[str] | None, fails_as: bool) -> JSON:
    """One answer against a condition (spec 2.5, step 1): whether it holds, the probability the
    answer put on the condition (`1 −` for `!=`), and whether a bar turned it to `fails_as`."""
    target = _target(type, word, labels)
    equal = answer["value"] == target
    holds = equal if operator != "!=" else not equal
    p = probability_of(answer, type or "", target) if type else None
    if p is not None and operator == "!=":
        p = 1 - p
    barred = bar is not None and (p is None or p < bar)
    if barred:
        holds = fails_as
    return {"value": answer["value"], "holds": holds, "probability": None if p is None else round(p, 6), "barred": barred}


def aggregate(procedure: Procedure, step: Step, state: JSON) -> tuple[JSON, JSON]:
    """The aggregation key's value, one `{"value": bool}` per aggregation and nothing else, and
    the record of every answer's resolution per aggregation (spec 2.5)."""
    produced: JSON = {}
    resolutions: JSON = {}
    for agg in step.aggregations:
        try:
            leaves = _leaf_answers(lookup(state, agg.source[:1]), agg.source[1:], agg.source[0])
        except KeyError as err:
            raise InvalidInput(step.name, [f"the source {agg.dotted} of {agg.name} is not an answer in the state ({err.args[0]})"],
                               invalid=[agg.dotted])
        labels = procedure.labels_of(agg.source)
        fails_as = agg.mode == "None"
        rows = []
        for label, answer in leaves:
            resolution = resolve_condition(answer, _answer_type(answer), agg.operator, agg.value, agg.confidence_above, labels, fails_as)
            rows.append({"source": label, **resolution})
        held = [r["holds"] for r in rows]
        value = all(held) if agg.mode == "All" else any(held) if agg.mode == "Any" else not any(held)
        produced[agg.name] = {"value": value}
        resolutions[agg.name] = rows
    return produced, resolutions


# ---------------------------------------------------------------- loops

def loop_items(loop: Loop, state: JSON) -> list:
    """The list a `For` or a fold runs over, and the cap check before the first pass: a list
    longer than `At_Most` is `loop_cap` (spec 2.1, Loops)."""
    assert loop.over is not None
    try:
        items = lookup(state, loop.over)
    except KeyError as err:
        raise InvalidInput(loop.name, [f"{'.'.join(loop.over)} is not in the state ({err.args[0]} is missing)"], missing=[".".join(loop.over)])
    if not isinstance(items, list):
        raise InvalidInput(loop.name, [f"{'.'.join(loop.over)} is {describe(items)}, not a list"], invalid=[".".join(loop.over)])
    if loop.at_most is not None and len(items) > loop.at_most:
        raise LoopCap(loop.name, loop.at_most, len(items),
                      f"{'.'.join(loop.over)} has {len(items)} items, more than the {loop.at_most} that {loop.name} allows (At_Most)")
    return items


def until_holds(procedure: Procedure, loop: Loop, state: JSON) -> tuple[bool, JSON | None]:
    """Whether a `Loop`'s `Until` condition holds on the state, and the answer's resolution for
    the record. An absent answer does not hold and resolves to None; otherwise the condition is
    the spec's (2.1, Conditions): `== value`, `!= value`, `== true` for a bare `true_or_false`,
    and with `With Confidence_Above` a probability below the bar, or none, does not hold."""
    until = loop.until
    assert until is not None
    try:
        answer = lookup(state, until.path)
    except KeyError:
        return False, None
    if not isinstance(answer, dict) or "value" not in answer:
        raise InvalidInput(loop.name, [f"{until.dotted} is {describe(answer)}, not an answer with a value"], invalid=[until.dotted])
    resolution = resolve_condition(answer, _answer_type(answer), until.operator, until.value, until.confidence_above,
                                   procedure.labels_of(until.path), fails_as=False)
    return bool(resolution["holds"]), {"answer": until.dotted, **resolution}


# ---------------------------------------------------------------- Execute

def assets_of(procedure: Procedure, step: Step, root: Path) -> dict[str, str]:
    """The step's `Use` files by stem, read from the unpacked bundle."""
    out: dict[str, str] = {}
    for use in step.files:
        if use.relation != "USES":
            continue
        path = root / Path(*use.path.split("/"))
        try:
            out[use.stem] = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            out[use.stem] = path.read_bytes().hex()
    return out


def launch(command: str | None, script: Path, python: str) -> list[str]:
    """The argument list: `Command` split like a shell would with a leading `python` replaced by
    the interpreter, else the interpreter on the script."""
    if not command:
        return [python, str(script)]
    argv = shlex.split(command)
    if argv and argv[0] == PYTHON:
        argv[0] = python
    return argv


def run_script(step: str, script: str, argv: list[str], stdin: JSON, cwd: Path, timeout: float | None,
               workdir: Path | None) -> JSON:
    """Run one script under the stdin/stdout contract and return the JSON object it printed.
    `ScriptTimeout`, or `ScriptFailed` on a non-zero exit or output that is not one JSON object."""
    env = {**os.environ, WORKDIR: str(Path(workdir or Path.cwd()).resolve())}
    try:
        proc = subprocess.run(argv, input=json.dumps(stdin), capture_output=True, text=True, cwd=cwd, timeout=timeout, env=env)
    except subprocess.TimeoutExpired as err:
        raise ScriptTimeout(step, script, timeout) from err
    stderr = proc.stderr.strip()
    if proc.returncode != 0:
        raise ScriptFailed(step, script, proc.returncode, stderr, f"the script {script} exited with {proc.returncode}:\n{stderr}")
    out = proc.stdout.strip()
    if not out:
        return {}
    try:
        result = json.loads(out)
    except json.JSONDecodeError as err:
        raise ScriptFailed(step, script, 0, stderr, f"the script {script} did not write JSON to stdout: {err}\n{out[:500]}") from err
    if not isinstance(result, dict):
        raise ScriptFailed(step, script, 0, stderr, f"the script {script} must write a JSON object, got {describe(result)}")
    return result


def execute(procedure: Procedure, step: Step, state: JSON, root: Path, *, python: str | None, timeout: float | None,
            workdir: Path | None) -> tuple[JSON, JSON, float]:
    """Run the step's script from the unpacked bundle at `root`: stdin is `{"state": the Read
    keys, "assets": the Use files by stem, "expects": the next step's Read keys}`, stdout the
    `Produce` keys. Returns the checked outputs, the stdin sent, and the seconds taken."""
    script = step.file("RUNS")
    if script is None:
        raise InvalidInput(step.name, [f"{step.name} names no script"])
    path = root / Path(*script.path.split("/"))
    stdin = {"state": project(step, state), "assets": assets_of(procedure, step, root), "expects": expects(procedure, step)}
    argv = launch(step.properties.get("command"), path, python or sys.executable)
    began = time.monotonic()
    raw = run_script(step.name, script.path, argv, stdin, root, timeout, workdir)
    seconds = round(time.monotonic() - began, 3)
    try:
        outputs = check_outputs(procedure, step, raw, source="script")
    except InvalidOutput as err:
        err.script = script.path
        raise
    return outputs, stdin, seconds


# ---------------------------------------------------------------- Task_Agent

def task(procedure: Procedure, step: Step, state: JSON, root: Path) -> JSON:
    """What the agent is handed: the prompt (the `Prompt` file or the description) with `{key}`
    and `{assets[stem]}` rendered, the `Read` keys as `state`, the references with their
    descriptions, `answer_with`, the `Produce` keys and their types, and `labels`, the values
    each `choice` or `score` among them may take."""
    prompt_file = step.file("PROMPTED_BY")
    template = (root / Path(*prompt_file.path.split("/"))).read_text(encoding="utf-8") if prompt_file else step.description
    assets = {u.stem: text for u, text in ((u, (root / Path(*u.path.split("/"))).read_text(encoding="utf-8"))
                                           for u in step.uses("assets"))}
    return {"prompt": render(template, state, assets), "state": project(step, state),
            "references": [{"path": u.path, "description": u.description or ""} for u in step.uses("references")],
            "answer_with": answer_with(step), "labels": labels_of(step)}


__all__ = ["WORKDIR", "INDEX", "ITERATIONS", "PASS_SUFFIX", "lookup", "project", "check_reads", "check_outputs", "answer_with", "labels_of",
           "expects", "render", "start", "end", "decision_request", "check_decision", "batch_request",
           "split_answers", "is_batched_decide", "route", "aggregate", "resolve_condition", "loop_items", "until_holds", "assets_of",
           "launch", "run_script", "execute", "task"]
