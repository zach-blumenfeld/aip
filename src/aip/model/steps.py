"""Step model: state, meta, nodes, and the accept flow."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Dict, List, TypeAlias
import copy
import json
import subprocess
import sys

from typesafe_sdk import Choice, Noul, Score, SystemOneResponse, TypeSafeClient

from aip.model.resources import Asset, Reference, ResourceLoader, Script
from aip.model.types import JSON, InputValidationError, Inputs, describe_inputs, validate_input

DecisionQuestion: TypeAlias = Noul | Choice | Score

SYSTEM_FRAMING = """\
You are executing a single step in a graph shaped workflow pertaining to "{skill_context}".
`currentState` holds the state for this specific step.
If needed, the historic state of past steps is contained in `history`.
Assets, if present, are fixed reference material for this step.
"""

# Default decision thresholds. Noul: flag when |p - 0.5| < margin.
# Choice / Score: flag when the model's confidence < min_confidence.
DEFAULT_NOUL_MARGIN = 0.15
DEFAULT_MIN_CONFIDENCE = 0.6

@dataclass
class State:
    """
    Per-call view of the run: the accepted input for this step plus the history the
    client carried in. Built by `accept()`, never persisted server-side.
    """
    currentState: JSON = field(default_factory=dict)
    history: List[JSON] = field(default_factory=list)


@dataclass
class Meta:
    """
    Workflow-level framing and package metadata, owned by the Procedure.

    `system_framing` is the constant preamble steps can request. It is a template with
    a `{skill_context}` slot filled from `description` (falling back to `name`).
    `environment` is the path, relative to the skill root, of the requirements.txt or
    pyproject.toml the server builds the script interpreter from.
    """
    name: str
    description: str = ""
    version: str = "0.1.0"
    system_framing: str = SYSTEM_FRAMING
    environment: str | None = None

    def framing(self) -> str:
        return self.system_framing.format(skill_context=self.description or self.name)


@dataclass
class StepResponse:
    """
    What the server returns after running a step.

    ran:       name of the step that ran
    kind:      "decision" | "client_task" | "execution" | "end"
    result:    raw output of the step
    suggested: the server's proposed input for the next step; the client may post it
               as-is or override it
    review:    items the client should look at before accepting `suggested`
               (e.g. low-confidence decision answers); empty means safe to pass through
    next:      description of what comes next (see `describe_next`); None at the end
    history:   the carried-in history plus this step's entry
    """
    ran: str
    kind: str
    result: JSON
    suggested: JSON
    review: List[JSON]
    next: JSON | None
    history: List[JSON]

    def to_dict(self) -> JSON:
        return {
            "ran": self.ran, "kind": self.kind, "result": self.result, "suggested": self.suggested,
            "review": self.review, "next": self.next, "history": self.history,
        }


@dataclass(kw_only=True)
class EndStep:
    """Terminal node. `inputs` is the shape of the final state the client receives."""
    kind: ClassVar[str] = "end"
    name: str = "end"
    inputs: Inputs = field(default_factory=dict)


@dataclass(kw_only=True)
class Router:
    """
    Dumb router: maps the value the client posted under `branch_on` to the next node.
    Calls no model, has no endpoint. The server walks routers internally after the
    client's input arrives; the client only sees the branches for schema purposes.

    branch_on: key in the posted input whose value selects the branch
    branches: branch value -> node; needs two or more
    """
    kind: ClassVar[str] = "router"
    name: str
    branch_on: str
    branches: Dict[str, "Node"]

    def route(self, payload: JSON) -> "Node":
        if self.branch_on not in payload:
            raise InputValidationError(self.name, [f"missing routing key {self.branch_on!r}"])
        value = payload[self.branch_on]
        if value not in self.branches:
            raise InputValidationError(
                self.name, [f"{self.branch_on}={value!r} has no branch; options: {list(self.branches)}"])
        return self.branches[value]


@dataclass(kw_only=True)
class BaseStep(ABC):
    """
    A node the server runs. Steps are configuration; run state flows through `accept`.

    name: unique within the procedure; endpoints and history refer to it
    inputs: the shape the client must post to this step; validated on accept
    inputsTo: the node that receives this step's output (a step, a router, or the end)
    include_framing: prepend Meta.framing() to what this step renders
    """
    kind: ClassVar[str] = "step"
    name: str
    inputs: Inputs = field(default_factory=dict)
    inputsTo: "Node | None" = None
    include_framing: bool = False
    loader: ResourceLoader | None = None
    meta: Meta | None = None

    @abstractmethod
    def _invoke(self, state: State) -> JSON:
        """Run the step against the accepted state and return its raw result."""

    def suggest(self, result: JSON, state: State) -> JSON:
        """Default proposal for the next input: the result itself over the current state."""
        return {**state.currentState, **result}

    def review(self, result: JSON, thresholds: Dict[str, float] | None = None) -> List[JSON]:
        """Items the client should look at before passing `suggested` through."""
        return []

    def accept(self, payload: JSON, history: List[JSON], thresholds: Dict[str, float] | None = None) -> StepResponse:
        """Validate the client's input, run the step, and describe what comes next."""
        validate_input(self.name, self.inputs, payload)
        state = State(currentState=payload, history=copy.deepcopy(history))
        result = self._invoke(state)
        entry = {"step": self.name, "kind": self.kind, "input": payload, "result": result}
        return StepResponse(
            ran=self.name,
            kind=self.kind,
            result=result,
            suggested=self.suggest(result, state),
            review=self.review(result, thresholds),
            next=describe_next(self.inputsTo),
            history=[*history, entry],
        )

    def framing(self) -> str:
        """The system-level preamble, or empty when not requested or no meta is bound."""
        if not self.include_framing or self.meta is None:
            return ""
        return self.meta.framing()

    def _require_loader(self) -> ResourceLoader:
        if self.loader is None:
            raise RuntimeError(f"{type(self).__name__} {self.name!r} needs a ResourceLoader to resolve resources")
        return self.loader


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
        return {
            "step": node.name, "kind": node.kind, "branch_on": node.branch_on,
            "branches": {value: describe_next(target) for value, target in node.branches.items()},
        }
    return {"step": node.name, "kind": node.kind, "inputs": describe_inputs(node.inputs)}


@dataclass(kw_only=True)
class Decision(BaseStep):
    """
    Runs a SystemOne (TypeSafe / Jev) decision and hands the typed result to the client.

    State is the content being evaluated; the criteria live in each question's
    `instructions`, written by the author. No assets and no framing are injected.

    questions: keyed by name; answers come back under the same names and, after
               collapse, become state keys of the same name
    thresholds: per-question author defaults. Noul: margin around 0.5.
                Choice / Score: minimum confidence. The client may override on accept.
    client: optional injected TypeSafe client (tests, connection reuse); otherwise one
            is opened per invoke using TYPESAFE_API_KEY from the environment
    """
    kind: ClassVar[str] = "decision"
    questions: Dict[str, DecisionQuestion] = field(default_factory=dict)
    thresholds: Dict[str, float] = field(default_factory=dict)
    client: TypeSafeClient | None = None

    def render(self, state: State) -> JSON:
        """Pure projection of state into the JSON `state` sent to Jev."""
        payload: JSON = {"currentState": state.currentState}
        if state.history:
            payload["history"] = state.history
        return payload

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

    def suggest(self, result: JSON, state: State) -> JSON:
        """Current state with each answer collapsed to a discrete value under its question name."""
        collapsed = {name: self.collapse(answer) for name, answer in result["answers"].items()}
        return {**state.currentState, **collapsed}

    def review(self, result: JSON, thresholds: Dict[str, float] | None = None) -> List[JSON]:
        """Answers whose uncertainty crosses the threshold, with what the client needs to decide."""
        limits = {**self.thresholds, **(thresholds or {})}
        flagged: List[JSON] = []
        for name, answer in result["answers"].items():
            if answer["type"] == "noul":
                margin = limits.get(name, DEFAULT_NOUL_MARGIN)
                if abs(answer["noul"] - 0.5) < margin:
                    flagged.append({"question": name, "type": "noul", "noul": answer["noul"],
                                    "reason": f"within {margin} of 0.5"})
            else:
                minimum = limits.get(name, DEFAULT_MIN_CONFIDENCE)
                if answer["confidence"] < minimum:
                    flagged.append({"question": name, "type": answer["type"],
                                    "confidence": answer["confidence"],
                                    "probabilities": answer["probabilities"],
                                    "reason": f"confidence below {minimum}"})
        return flagged


class _SafeMap(dict):
    """format_map helper: unknown placeholders are left intact instead of raising."""
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


@dataclass(kw_only=True)
class ClientTask(BaseStep):
    """
    A step the client performs itself (text generation, synthesis, reasoning). Fallback
    for anything not expressible as a Decision or Execution.

    The template is this step's framing: prose rendered at invoke time with `{key}`
    placeholders drawn from currentState, plus `{assets[name]}` and `{meta.name}`.
    The client does the task and posts structured JSON matching `next.inputs`.

    template: the asset holding the task template
    assets: extra eager resources available to the template as {assets[name]}
    references: lazy resources; only uri + description are handed to the client
    include_framing: on by default; Meta.framing() is prepended to the rendered template
    """
    kind: ClassVar[str] = "client_task"
    include_framing: bool = True
    template: Asset
    assets: List[Asset] = field(default_factory=list)
    references: List[Reference] = field(default_factory=list)

    def render(self, state: State) -> str:
        """Pure projection of the template over state, assets, and meta."""
        loader = self._require_loader()
        mapping = _SafeMap(state.currentState)
        mapping["assets"] = loader.load_all(self.assets)
        mapping["meta"] = self.meta
        body = loader.load(self.template).format_map(mapping)
        framing = self.framing()
        return f"{framing}\n{body}" if framing else body

    def _invoke(self, state: State) -> JSON:
        """Hands the rendered task and the reference index to the client."""
        return {"task": self.render(state), "references": [r.summary() for r in self.references]}

    def suggest(self, result: JSON, state: State) -> JSON:
        """The client must produce the next input; only the current state passes through."""
        return dict(state.currentState)


@dataclass(kw_only=True)
class Execution(BaseStep):
    """
    Executes an action rather than making a decision. Analogous to a tool call. For now
    a python script in the package; MCP and endpoints can be added later.

    Script contract:
      stdin   one JSON object: {"currentState": {...}, "assets": {name: content},
                                "expects": <describe_next of the node after this one>}
      stdout  one JSON object, this step's result (empty stdout is treated as {})
      stderr  diagnostics; surfaced in the error when the exit code is non-zero
    The script runs with `python` (the per-AIP interpreter the server built from
    Meta.environment, falling back to the server's own), cwd set to the script's folder.

    script: the Script resource to run
    assets: constant inputs the script always receives, e.g. a JSON config. Re-read from
            disk on every invoke so edits are picked up.
    timeout: seconds before the script is killed; None waits forever
    """
    kind: ClassVar[str] = "execution"
    script: Script
    assets: List[Asset] = field(default_factory=list)
    timeout: float | None = 60.0
    python: Path | None = None

    def render(self, state: State) -> JSON:
        """Pure projection of state + assets into the script's stdin payload."""
        payload: JSON = {"currentState": state.currentState}
        if self.assets:
            payload["assets"] = self._require_loader().load_all(self.assets, fresh=True)
        payload["expects"] = describe_next(self.inputsTo)
        return payload

    def _invoke(self, state: State) -> JSON:
        loader = self._require_loader()
        path = loader.path(self.script.uri)
        if not path.is_file():
            raise FileNotFoundError(f"Script {self.script.uri!s} not found at {path}")

        proc = subprocess.run(
            [str(self.python or sys.executable), str(path)],
            input=json.dumps(self.render(state)),
            capture_output=True,
            text=True,
            cwd=path.parent,
            timeout=self.timeout,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"Script {self.script.uri!s} exited with {proc.returncode}:\n{proc.stderr.strip()}")

        out = proc.stdout.strip()
        if not out:
            return {}
        try:
            result = json.loads(out)
        except json.JSONDecodeError as err:
            raise RuntimeError(f"Script {self.script.uri!s} did not write JSON to stdout: {err}\n{out[:500]}") from err
        if not isinstance(result, dict):
            raise RuntimeError(f"Script {self.script.uri!s} must write a JSON object, got {type(result).__name__}")
        return result
