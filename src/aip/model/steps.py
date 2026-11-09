"""Step model: state, meta, nodes, and the accept flow."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Dict, List, TypeAlias
import copy
import json
import os
import subprocess
import sys
import time

from typesafe_sdk import Choice, Noul, Score, SystemOneResponse, TypeSafeClient

from aip.model.environment import PYTHON, Requires, RequiresUnmet
from aip.model.resources import Asset, Reference, ResourceLoader, Script
from aip.model.types import (
    JSON, DataType, InputValidationError, Inputs, OutputValidationError, ScriptFailed, ScriptTimeout,
    describe_inputs, project, validate_input, validate_output,
)

DecisionQuestion: TypeAlias = Noul | Choice | Score

@dataclass
class State:
    """
    What one step sees: the state projected to the step's declared `inputs`, plus the
    history the client carried in. Built by `accept()`, never persisted server-side.
    """
    currentState: JSON = field(default_factory=dict)
    history: List[JSON] = field(default_factory=list)


@dataclass
class Meta:
    """Package metadata, owned by the Procedure."""
    name: str
    description: str = ""
    version: str = "0.1.0"


@dataclass
class StepResponse:
    """
    What the server returns after running a step.

    ran:       name of the step that ran
    kind:      "start" | "decision" | "client_task" | "execution" | "end"
    result:    raw output of the step
    suggested: the full state after this step: the posted state plus the keys this step
               produced. The client posts it as the next input (answers merged over it)
    next:      description of what comes next (see `describe_next`); None at the end
    history:   the carried-in history plus this step's entry
    """
    ran: str
    kind: str
    result: JSON
    suggested: JSON
    next: JSON | None
    history: List[JSON]

    def to_dict(self) -> JSON:
        return {
            "ran": self.ran, "kind": self.kind, "result": self.result, "suggested": self.suggested,
            "next": self.next, "history": self.history,
        }


@dataclass(kw_only=True)
class EndStep:
    """Terminal node. `inputs` is the shape of the final state the client receives."""
    kind: ClassVar[str] = "end"
    name: str = "end"
    inputs: Inputs = field(default_factory=dict)


def branch_key(value: Any) -> str:
    """Branch keys are YAML strings; collapsed answers are typed. `true`/`false` for a
    noul, the label for a choice, the level number for a score."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


@dataclass(kw_only=True)
class ConfidenceCheck:
    """
    A router's confidence check, applied before its branches: when `key` is below `below`,
    absent from the state, or null, the run goes to `to` and the value match is skipped.
    Unknown confidence is low confidence; nobody invents a number. The check guards a model's
    answer: when the client answered the branch key by hand (`answered_by_hand`), the check is
    skipped and the client's own call takes the branch.

    key: a float key in the state, typically a decision's `<question>_confidence`
    below: the bound, in [0, 1]
    to: the node the run goes to when the check fires
    """
    key: str
    below: float
    to: "Node"


@dataclass(kw_only=True)
class Router:
    """
    Dumb router: maps the value the client posted under `branch_on` to the next node.
    Calls no model, has no endpoint. The server walks routers internally after the
    client's input arrives; the client only sees the branches for schema purposes.

    branch_on: key in the posted input whose value selects the branch
    branches: branch value -> node; needs two or more
    confidence: the optional check applied first (`ConfidenceCheck`)
    """
    kind: ClassVar[str] = "router"
    name: str
    branch_on: str
    branches: Dict[str, "Node"]
    confidence: ConfidenceCheck | None = None

    def check(self, payload: JSON, by_hand: bool = False) -> JSON | None:
        """What the confidence check made of `payload`: `{"fired": bool, "reason": "low" | "absent" |
        "null" | "manual" | None}`, or None when the router has no check. `reason` is None when it did
        not fire, and `manual` when it was skipped because the client answered the branch key by hand
        (`by_hand`): a hand answer has no confidence to check, and the client stands behind it."""
        if self.confidence is None:
            return None
        if by_hand:
            return {"fired": False, "reason": "manual"}
        key = self.confidence.key
        if key not in payload:
            return {"fired": True, "reason": "absent"}
        value = payload[key]
        if value is None:
            return {"fired": True, "reason": "null"}
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise InputValidationError(
                self.name, [f"confidence key {key}={value!r} is not a number"], invalid=[key])
        low = value < self.confidence.below
        return {"fired": low, "reason": "low" if low else None}

    def route(self, payload: JSON, by_hand: bool = False) -> "Node":
        """The node `payload` goes to: the check's `to` when it fires, else the branch its value selects."""
        fired = self.check(payload, by_hand)
        if fired is not None and fired["fired"]:
            return self.confidence.to
        if self.branch_on not in payload:
            raise InputValidationError(self.name, [f"missing routing key {self.branch_on!r}"], missing=[self.branch_on])
        value = payload[self.branch_on]
        key = branch_key(value)
        if key not in self.branches:
            raise InputValidationError(
                self.name, [f"{self.branch_on}={value!r} has no branch; options: {list(self.branches)}"],
                invalid=[self.branch_on])
        return self.branches[key]


@dataclass(kw_only=True)
class BaseStep(ABC):
    """
    A node the server runs. Steps are configuration; run state flows through `accept`.

    name: unique within the procedure; endpoints and history refer to it
    inputs: the keys this step reads; validated on accept, and the only keys it sees
    outputs: the keys this step adds to the state; its result is validated against them
    inputsTo: the node that receives this step's output (a step, a router, or the end)
    """
    kind: ClassVar[str] = "step"
    name: str
    inputs: Inputs = field(default_factory=dict)
    outputs: Inputs = field(default_factory=dict)
    inputsTo: "Node | None" = None
    loader: ResourceLoader | None = None
    meta: Meta | None = None

    @abstractmethod
    def _invoke(self, state: State) -> JSON:
        """Run the step against the accepted state and return its raw result."""

    def output_types(self) -> Inputs:
        """The keys this step adds to the state, with their types."""
        return dict(self.outputs)

    def required_outputs(self) -> Inputs:
        """The keys the state must hold once this step is answered: its outputs, by default."""
        return self.output_types()

    def produced(self, result: JSON) -> JSON:
        """The keys this step's result adds to the state. By default the (validated) result itself."""
        return dict(result)

    def accept(self, payload: JSON, history: List[JSON]) -> StepResponse:
        """
        Validate the posted state against the declared inputs, run the step on just those
        keys, and merge what it produced back into the full state.
        """
        validate_input(self.name, self.inputs, payload)
        state = State(currentState=project(payload, self.inputs), history=copy.deepcopy(history))
        began = time.monotonic()
        result = self._invoke(state)
        entry = {"step": self.name, "kind": self.kind, "input": state.currentState, "result": result}
        if isinstance(self, Execution):
            entry["seconds"] = round(time.monotonic() - began, 3)
        return StepResponse(
            ran=self.name,
            kind=self.kind,
            result=result,
            suggested={**payload, **self.produced(result)},
            next=describe_next(self.inputsTo),
            history=[*history, entry],
        )

    def _require_loader(self) -> ResourceLoader:
        if self.loader is None:
            raise RuntimeError(f"{type(self).__name__} {self.name!r} needs a ResourceLoader to resolve resources")
        return self.loader


@dataclass(kw_only=True)
class Start(BaseStep):
    """
    Where a run begins. `inputs` are the procedure's inputs, what the client supplies; the
    step checks them, writes its history entry, and hands the state on to `inputsTo`. It
    adds nothing of its own.
    """
    kind: ClassVar[str] = "start"
    name: str = "start"

    def _invoke(self, state: State) -> JSON:
        return {}


Node: TypeAlias = BaseStep | Router | EndStep


def describe_next(node: Node | None) -> JSON | None:
    """
    Client-facing description of the node that receives the next input. Routers are
    expanded into their branches so the client can see every possible input shape,
    but the client never resolves them; the server does on the next call.
    """
    if node is None:
        return None
    if isinstance(node, Router):
        described = {
            "step": node.name, "kind": node.kind, "branch_on": node.branch_on,
            "branches": {value: describe_next(target) for value, target in node.branches.items()},
        }
        if node.confidence is not None:
            described["confidence"] = {"key": node.confidence.key, "below": node.confidence.below,
                                       "to": describe_next(node.confidence.to)}
        return described
    described: JSON = {"step": node.name, "kind": node.kind, "inputs": describe_inputs(node.inputs)}
    if isinstance(node, Decision):
        described["questions"] = {name: q.model_dump(exclude_none=True) for name, q in node.questions.items()}
    return described


@dataclass(kw_only=True)
class Decision(BaseStep):
    """
    Runs a SystemOne (TypeSafe / Jev) decision and hands the typed result to the client.

    The declared inputs are the content being evaluated; the criteria live in each
    question's `instructions`, written by the author. No assets and no framing are injected.

    questions: keyed by name; answers come back under the same names and, after
               collapse, become state keys of the same name: a decision's outputs
    confidence: question names whose confidence the step also emits, each as the state key
                `<question>_confidence`, a float in [0, 1]: the probability the model put on
                the answer it gave (`confidence()`). A manual answer writes no confidence key.
    fallback: whether the client may answer by hand when it has no decision model. Off by
              default: `accept_answers` then rejects a manual attribution.
    history: send the run history to the decision model too; off unless the author asks
    client: optional injected TypeSafe client (tests, connection reuse); otherwise one
            is opened per invoke using TYPESAFE_API_KEY from the environment
    """
    kind: ClassVar[str] = "decision"
    questions: Dict[str, DecisionQuestion] = field(default_factory=dict)
    confidence: List[str] = field(default_factory=list)
    fallback: bool = False
    history: bool = False
    client: TypeSafeClient | None = None

    ANSWER_TYPES: ClassVar[Dict[str, DataType]] = {
        "noul": DataType.BOOLEAN, "choice": DataType.STRING, "score": DataType.INTEGER}

    def __post_init__(self) -> None:
        unknown = [q for q in self.confidence if q not in self.questions]
        if unknown:
            raise ValueError(f"Decision {self.name!r} names {unknown} in `confidence`, which are not its questions")

    def render(self, state: State) -> JSON:
        """Pure projection of state into the JSON `state` sent to Jev: the declared inputs,
        and the history only when the step asks for it."""
        payload: JSON = {"state": state.currentState}
        if self.history and state.history:
            payload["history"] = state.history
        return payload

    def output_types(self) -> Inputs:
        """One key per question, typed by what its answer collapses to, and a float
        `<question>_confidence` for each question the `confidence` list names."""
        return {**self.required_outputs(), **{confidence_key(name): DataType.FLOAT for name in self.confidence}}

    def required_outputs(self) -> Inputs:
        """The answers alone: a confidence key is written by a model and absent after a manual answer."""
        return {name: self.ANSWER_TYPES[q.type] for name, q in self.questions.items()}

    def _invoke(self, state: State) -> JSON:
        """
        Returns the TypeSafe result as a JSON dict:
            {"model": str,
             "usage": {"input_tokens", "output_tokens"},
             "answers": {name: {"type": "noul"|"choice"|"score", ...}}}
        """
        if not self.questions:
            raise ValueError(f"Decision {self.name!r} has no questions to ask")
        payload = self.render(state)
        if self.client is not None:
            result: SystemOneResponse = self.client.system_one(state=payload, questions=self.questions)
        else:
            with TypeSafeClient() as client:
                result = client.system_one(state=payload, questions=self.questions)
        return result.model_dump(mode="json")

    def accept_answers(self, payload: JSON, history: List[JSON], answers: JSON,
                       attribution: JSON | None = None) -> StepResponse:
        """
        The client resolved the decision: `answers` holds one collapsed value per question (bool
        for noul, label for choice, int level for score), and `attribution` says how it got them,
        `{"resolver": "typesafe"|"manual", "model", "confidence": {question: float}|None}`. None
        is a manual answer. Both are checked and recorded in the history entry. A model's
        confidence for each question the step's `confidence` list names is also written to the
        state as `<question>_confidence`; a manual answer writes none, and is rejected when the
        step does not allow `fallback`.
        """
        validate_input(self.name, self.inputs, payload)
        missing = [q for q in self.questions if q not in answers]
        if missing:
            raise OutputValidationError(self.name, [f"missing answers for {missing}"], missing=missing)
        self.check_answers(answers)
        attribution = self.check_attribution(manual() if attribution is None else attribution)
        result = {"answers": {name: answers[name] for name in self.questions}}
        entry = {"step": self.name, "kind": self.kind, "input": project(payload, self.inputs),
                 "result": result, "attribution": attribution}
        scores = attribution["confidence"] or {}
        emitted = {confidence_key(name): scores[name] for name in self.confidence if name in scores}
        return StepResponse(
            ran=self.name, kind=self.kind, result=result,
            suggested={**payload, **result["answers"], **emitted},
            next=describe_next(self.inputsTo), history=[*history, entry],
        )

    def check_attribution(self, attribution: JSON) -> JSON:
        """The attribution as recorded: a known resolver, a model name, and a confidence in 0..1 for
        questions of this step. A manual answer has no model and no confidence, and is refused
        unless the step allows `fallback`; a model's answer must carry a confidence for every
        question the step emits one for."""
        errors: List[str] = []
        if not isinstance(attribution, dict):
            raise OutputValidationError(self.name, ["attribution must be an object"], invalid=["attribution"])
        resolver = attribution.get("resolver")
        if resolver not in RESOLVERS:
            errors.append(f"attribution.resolver must be one of {list(RESOLVERS)}, got {resolver!r}")
        model = attribution.get("model")
        if model is not None and not isinstance(model, str):
            errors.append("attribution.model must be a string or null")
        scores = attribution.get("confidence")
        if scores is not None and not (isinstance(scores, dict) and all(
                k in self.questions and isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 1
                for k, v in scores.items())):
            errors.append("attribution.confidence must map this step's questions to numbers in 0..1")
        if resolver == "manual":
            if model is not None or scores is not None:
                errors.append("a manual answer has no model or confidence")
            if not self.fallback:
                errors.append(f"fallback_not_allowed: decision {self.name!r} does not allow a manual answer "
                              "(`fallback: false`); it needs a decision model")
        elif resolver in RESOLVERS and self.confidence:
            unscored = [q for q in self.confidence if q not in (scores or {})]
            if unscored:
                errors.append(f"attribution.confidence must give the confidence of {unscored}, which this step emits")
        if errors:
            raise OutputValidationError(self.name, errors, invalid=["attribution"])
        return {"resolver": resolver, "model": model, "confidence": scores}

    def check_answers(self, answers: JSON) -> None:
        """Collapsed answers must name only this step's questions and fit each question's type."""
        validate_output(self.name, self.required_outputs(), {k: v for k, v in answers.items() if k in self.questions},
                        strict=False)
        invalid = [key for key in answers if key not in self.questions]
        errors = [f"undeclared output {key!r} (not a question of this step)" for key in invalid]
        for name, q in self.questions.items():
            value = answers[name]
            if q.type == "choice" and value not in q.criteria:
                errors.append(f"{name}: {value!r} is not one of {list(q.criteria)}")
                invalid.append(name)
            if q.type == "score" and isinstance(value, int) and not 0 <= value < len(q.criteria):
                errors.append(f"{name}: level {value} is outside 0..{len(q.criteria) - 1}")
                invalid.append(name)
        if errors:
            raise OutputValidationError(self.name, errors, invalid=invalid)

    @staticmethod
    def collapse(answer: JSON) -> Any:
        """Discrete value for one answer: noul -> bool, choice -> label, score -> argmax level."""
        match answer["type"]:
            case "noul":
                return answer["noul"] >= 0.5
            case "choice":
                return answer["choice"]
            case "score":
                return int(max(answer["probabilities"], key=answer["probabilities"].get))
        raise ValueError(f"unknown answer type {answer['type']!r}")

    def produced(self, result: JSON) -> JSON:
        """Each answer collapsed to a discrete value under its question name, plus the model's
        confidence under `<question>_confidence` for each question the step names."""
        missing = [name for name in self.questions if name not in result["answers"]]
        if missing:
            raise OutputValidationError(self.name, [f"no answer for {missing}"])
        answers = result["answers"]
        return {**{name: self.collapse(answers[name]) for name in self.questions},
                **{confidence_key(name): confidence(answers[name]) for name in self.confidence}}


def confidence_key(question: str) -> str:
    """The state key a decision's `confidence` list emits for a question. Fixed, not configurable."""
    return f"{question}_confidence"


def confidence(answer: JSON) -> float:
    """The probability the model put on its collapsed answer, in [0, 1]: `|2p - 1|` for a noul
    (https://docs.typesafe.ai/confidence#noul), a choice's or score's own confidence. The one
    number recorded in the history attribution and written to the state."""
    if answer["type"] == "noul":
        return round(abs(2 * answer["noul"] - 1), 4)
    return answer["confidence"]


RESOLVERS = ("typesafe", "manual")


def answered_by_hand(history: List[JSON], key: str) -> bool:
    """Whether the latest producer of `key` in `history` is a decision answered with no model
    (`attribution.resolver` of `manual`). A later script, task or start input that wrote the key
    makes it theirs again; a key no entry produced is not a hand answer."""
    for entry in reversed(history):
        result = entry.get("result") or {}
        match entry.get("kind"):
            case "decision":
                if key in (result.get("answers") or {}):
                    return (entry.get("attribution") or {}).get("resolver") == "manual"
            case "client_task":
                if key in (result.get("answer") or {}):
                    return False
            case "router" | "end":
                continue
            case _:
                if key in result:
                    return False
    return False


def manual() -> JSON:
    """The attribution of a decision answered with no model: by the client, or the agent at a pause."""
    return {"resolver": "manual", "model": None, "confidence": None}


class _SafeMap(dict):
    """format_map helper: unknown placeholders are left intact instead of raising."""
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


@dataclass(kw_only=True)
class ClientTask(BaseStep):
    """
    A step the client performs itself (text generation, synthesis, reasoning). Fallback
    for anything not expressible as a Decision or Execution.

    The template is the whole task: prose rendered at invoke time with `{key}`
    placeholders drawn from the step's declared inputs, plus `{assets[name]}` and
    `{meta.name}`. Nothing is prepended to it. The client does the task and answers with
    the step's `outputs`.

    template: the asset holding the task template
    assets: extra eager resources available to the template as {assets[name]}
    references: lazy resources; only uri + description are handed to the client
    """
    kind: ClassVar[str] = "client_task"
    template: Asset
    assets: List[Asset] = field(default_factory=list)
    references: List[Reference] = field(default_factory=list)

    def render(self, state: State) -> str:
        """Pure projection of the template over state, assets, and meta."""
        loader = self._require_loader()
        mapping = _SafeMap(state.currentState)
        mapping["assets"] = loader.load_all(self.assets)
        mapping["meta"] = self.meta
        return loader.load(self.template).format_map(mapping)

    def _invoke(self, state: State) -> JSON:
        """Hands the rendered task, the reference index, and the keys to answer with to the client."""
        return {"task": self.render(state), "references": [r.summary() for r in self.references],
                "expects": describe_inputs(self.outputs)}

    def produced(self, result: JSON) -> JSON:
        """Nothing yet: the client's answer adds the outputs, checked when it is posted."""
        return {}


WORKDIR = "AIP_WORKDIR"


def run_script(step: str, script: str, argv: List[str], stdin: JSON, cwd: Path, timeout: float | None,
               workdir: Path | None = None) -> JSON:
    """Run one script under the stdin/stdout contract and return the JSON object it printed.

    The script runs from `cwd` (its own folder) with `AIP_WORKDIR` set to `workdir`, the run's
    working directory, where it reads and writes the run's files. Raises `ScriptTimeout`, or
    `ScriptFailed` for a non-zero exit or stdout that is not one JSON object. The result is not
    checked against the step's outputs here; `Execution.check` does that.
    """
    env = {**os.environ, WORKDIR: str(Path(workdir or Path.cwd()).resolve())}
    try:
        proc = subprocess.run(argv, input=json.dumps(stdin), capture_output=True, text=True, cwd=cwd,
                              timeout=timeout, env=env)
    except subprocess.TimeoutExpired as err:
        raise ScriptTimeout(step, script, timeout) from err
    stderr = proc.stderr.strip()
    if proc.returncode != 0:
        raise ScriptFailed(step, script, proc.returncode, stderr, failed_message(script, proc.returncode, stderr))

    out = proc.stdout.strip()
    if not out:
        return {}
    try:
        result = json.loads(out)
    except json.JSONDecodeError as err:
        raise ScriptFailed(step, script, 0, stderr,
                           f"Script {script} did not write JSON to stdout: {err}\n{out[:500]}") from err
    if not isinstance(result, dict):
        raise ScriptFailed(step, script, 0, stderr,
                           f"Script {script} must write a JSON object, got {type(result).__name__}")
    return result


def failed_message(script: str, exit_code: int, stderr: str) -> str:
    return f"Script {script} exited with {exit_code}:\n{stderr}"


def launch(command: List[str] | None, path: Path, python: Path | str | None = None) -> List[str]:
    """The argument list for a script at `path`: `command`, or `python` on the script. A leading
    `python` is `python` (default: this process's own interpreter)."""
    python = str(python or sys.executable)
    if command is None:
        return [python, str(path)]
    return [python if arg == PYTHON and i == 0 else arg for i, arg in enumerate(command)]


@dataclass(kw_only=True)
class Execution(BaseStep):
    """
    Executes an action rather than making a decision. Analogous to a tool call. For now
    a script in the package; MCP and endpoints can be added later.

    Script contract:
      stdin   one JSON object: {"state": <the declared inputs only>, "assets": {name: content},
                                "expects": <describe_next of the node after this one>}
              (`currentState` carries the same object for one version, for older scripts)
      stdout  one JSON object holding exactly the declared `outputs` (empty stdout is {});
              a missing, mistyped, or undeclared key fails the step
      stderr  diagnostics; carried in the `script_failed` error when the exit code is non-zero
      env     `AIP_WORKDIR`: the run's working directory, where the run's files are
    The script runs from its folder with `command` when the step declares one, otherwise
    `python <script>`. Before it runs, the skill's `requires` block is checked against the
    machine that runs it (`requires_unmet` names what is missing).

    The script runs on the client. A run that cannot run it in this process (the server's)
    stops at the step with `request()`, what the client needs to run it, and continues with
    `accept_report()` when the client posts what happened. `_invoke` runs it in-process.

    script: the Script resource to run
    command: the argument list that launches the script, from its folder; None is `python <script>`
    requires: the skill's environment declaration, shared by every Execution of the procedure
    assets: constant inputs the script always receives, e.g. a JSON config. Re-read from
            disk on every invoke so edits are picked up.
    timeout: seconds before the script is killed; None waits forever
    python: the interpreter for a `python` launcher in-process; None is this process's own
    """
    kind: ClassVar[str] = "execution"
    script: Script
    assets: List[Asset] = field(default_factory=list)
    timeout: float | None = 60.0
    command: List[str] | None = None
    requires: Requires | None = None
    python: Path | None = None

    @property
    def script_path(self) -> str:
        """The script as the SKILL.md names it, relative to the skill root: `scripts/x.py`."""
        return Path(*self.script.uri.parts[1:]).as_posix()

    def render(self, state: State) -> JSON:
        """Pure projection of the declared inputs + assets into the script's stdin payload."""
        payload: JSON = {"state": state.currentState, "currentState": state.currentState}
        if self.assets:
            payload["assets"] = self._require_loader().load_all(self.assets, fresh=True)
        payload["expects"] = describe_next(self.inputsTo)
        return payload

    def argv(self, path: Path) -> List[str]:
        """The launch command: the step's `command`, or `python` on the script."""
        return launch(self.command, path, self.python)

    def request(self, payload: JSON) -> JSON:
        """What a client needs to run this step itself on `payload` (the full state, checked against
        the declared inputs): the script, its launch command, the rendered stdin, the timeout,
        and the skill's `requires`. The stop the server's run waits at (kind `execute`)."""
        validate_input(self.name, self.inputs, payload)
        r = self.requires
        return {"kind": "execute", "step": self.name, "script": self.script_path, "command": self.command,
                "stdin": self.render(State(currentState=project(payload, self.inputs))), "timeout": self.timeout,
                "requires": None if r is None else {"interpreter": r.interpreter, "version": r.version,
                                                    "packages": list(r.packages), "tools": list(r.tools)}}

    def check(self, result: JSON) -> JSON:
        """The script's result, checked against the declared outputs."""
        try:
            validate_output(self.name, self.outputs, result)
        except OutputValidationError as err:
            err.script = self.script_path
            raise
        return result

    def accept_report(self, payload: JSON, history: List[JSON], report: JSON) -> StepResponse:
        """Continue after the client ran the script: `report` is `{"output": {...}, "seconds"}`, or
        a failure `{"error": "script_failed"|"timeout"|"requires_unmet", ...}` with its detail
        (exit code and stderr, the timeout, the missing items), raised here as that error so the
        run records it like a failure in-process."""
        validate_input(self.name, self.inputs, payload)
        if "error" in report:
            raise self.reported_error(report)
        result = self.check(report["output"])
        entry = {"step": self.name, "kind": self.kind, "input": project(payload, self.inputs), "result": result}
        if isinstance(report.get("seconds"), (int, float)):
            entry["seconds"] = round(float(report["seconds"]), 3)
        if isinstance(report.get("host"), str):
            entry["host"] = report["host"]
        return StepResponse(ran=self.name, kind=self.kind, result=result, suggested={**payload, **result},
                            next=describe_next(self.inputsTo), history=[*history, entry])

    def reported_error(self, report: JSON) -> Exception:
        """The error a client's failure report stands for; `host` is the machine that reported it."""
        kind, script = report["error"], self.script_path
        if kind == "timeout":
            exc: Exception = ScriptTimeout(self.name, script, report.get("seconds", self.timeout))
        elif kind == "requires_unmet":
            exc = RequiresUnmet(self.name, [str(m) for m in report.get("missing") or []])
        else:
            exit_code, stderr = int(report.get("exit_code", 0) or 0), str(report.get("stderr", ""))
            exc = ScriptFailed(self.name, script, exit_code, stderr,
                               report.get("message") or failed_message(script, exit_code, stderr))
        if isinstance(report.get("host"), str):
            exc.host = report["host"]
        return exc

    def _invoke(self, state: State) -> JSON:
        if self.requires is not None:
            self.requires.ensure(self.name, self.python)
        loader = self._require_loader()
        path = loader.path(self.script.uri)
        if not path.is_file():
            raise FileNotFoundError(f"Script {self.script.uri!s} not found at {path}")
        return self.check(run_script(self.name, self.script_path, self.argv(path), self.render(state), path.parent,
                                     self.timeout))
