"""
AIP server-side step model.

Design:
- The server is stateless. Every call carries the client's accepted input and the full
  history; the server validates the input against the receiving step, runs it, appends a
  history entry, and returns the result plus a description of what comes next.
- The client makes decisions (thresholds, overrides, doing ClientTasks); the server
  implements them, including routing: after a client posts its input, the server walks
  through any routers and runs the first real node.
- Framing (how to read a payload) is owned by each step type, not by state.
- Model / script inputs are pure projections (`render()`), sent and discarded.
- Assets are eager (content injected every invoke). References are lazy (uri and
  description only; the client pulls the body on demand).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar, Dict, List, TypeAlias
import copy
import json
import subprocess
import sys

from jsonschema import Draft202012Validator
from typesafe_sdk import (
    Choice, ChoiceAnswer, Noul, NoulAnswer, Score, ScoreAnswer,
    SystemOneResponse, TypeSafeClient,
)

DecisionQuestion: TypeAlias = Noul | Choice | Score
JSON: TypeAlias = Dict[str, Any]

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


# ------------------------------------------------------------------- types & schema


class DataType(str, Enum):
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    OBJECT = "object"  # JSON-like key/value map
    LIST = "list[*]"   # collection of any of the above


_JSON_SCHEMA_TYPES = {
    DataType.STRING: "string",
    DataType.INTEGER: "integer",
    DataType.FLOAT: "number",
    DataType.BOOLEAN: "boolean",
    DataType.OBJECT: "object",
    DataType.LIST: "array",
}

Inputs: TypeAlias = Dict[str, DataType]


def to_json_schema(inputs: Inputs, strict: bool = False) -> JSON:
    """Compile a DataType map into a JSON Schema. All declared keys are required."""
    return {
        "type": "object",
        "properties": {name: {"type": _JSON_SCHEMA_TYPES[DataType(t)]} for name, t in inputs.items()},
        "required": list(inputs),
        "additionalProperties": not strict,
    }


def describe_inputs(inputs: Inputs) -> Dict[str, str]:
    """Client-facing form of an inputs map: {name: "string" | "integer" | ...}."""
    return {name: DataType(t).value for name, t in inputs.items()}


class InputValidationError(ValueError):
    def __init__(self, step: str, errors: List[str]):
        self.step = step
        self.errors = errors
        super().__init__(f"Input to step {step!r} is invalid: " + "; ".join(errors))


def validate_input(step: str, inputs: Inputs, payload: Any, strict: bool = False) -> None:
    validator = Draft202012Validator(to_json_schema(inputs, strict))
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
    if errors:
        raise InputValidationError(step, [
            (f"{'.'.join(str(p) for p in e.path)}: " if e.path else "") + e.message for e in errors
        ])


# --------------------------------------------------------------------------- state


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


# ----------------------------------------------------------------------- resources


class Resource(ABC):
    """
    A file that belongs to an AIP package, addressed relative to the package root as
    `<aip_id>/<assets|references|scripts>/<name>` (plural folders, per Agent Skills).
    Bodies are read from disk by ResourceLoader.
    """
    uri: Path
    description: str

    def __init__(self, aip_id: str, name: str, description: str = ""):
        self.uri = Path(aip_id, self._folder(), name)
        self.description = description

    @property
    def name(self) -> str:
        return self.uri.stem

    @abstractmethod
    def _folder(self) -> str:
        pass

    def summary(self) -> Dict[str, str]:
        """Lazy form: enough for a client to decide whether to fetch the body."""
        return {"uri": str(self.uri), "description": self.description}


class Asset(Resource):
    """Fixed templates and resources injected into every invoke."""
    def _folder(self) -> str:
        return "assets"


class Reference(Resource):
    """Documents the client loads on demand (progressive disclosure)."""
    def _folder(self) -> str:
        return "references"


class Script(Resource):
    """An executable python script in the package, run by an Execution step."""
    def _folder(self) -> str:
        return "scripts"


class ResourceLoader:
    """
    Reads resource files from disk, relative to a package root, and caches them.
    The single place to add size limits or non-file backends later.

    Assets are loaded eagerly by steps at render time. References are loaded on demand
    when the client asks for one by uri (`load_uri`).
    """
    def __init__(self, root: Path | str):
        self.root = Path(root).resolve()
        self._cache: Dict[Path, str] = {}

    def path(self, uri: Path | str) -> Path:
        """Resolve a package-relative uri to an absolute path inside the root."""
        path = (self.root / uri).resolve()
        if self.root not in path.parents:
            raise ValueError(f"Resource uri {uri!s} escapes package root {self.root}")
        return path

    def load_uri(self, uri: Path | str, fresh: bool = False) -> str:
        """Read a resource body. `fresh=True` bypasses the cache and re-reads from disk."""
        uri = Path(uri)
        if fresh or uri not in self._cache:
            path = self.path(uri)
            if not path.is_file():
                raise FileNotFoundError(f"Resource {uri!s} not found at {path}")
            self._cache[uri] = path.read_text(encoding="utf-8")
        return self._cache[uri]

    def load(self, resource: Resource, fresh: bool = False) -> str:
        return self.load_uri(resource.uri, fresh=fresh)

    def load_all(self, resources: List[Resource], fresh: bool = False) -> Dict[str, str]:
        return {r.name: self.load(r, fresh=fresh) for r in resources}


# ---------------------------------------------------------------------- responses


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


# ---------------------------------------------------------------------------- nodes


@dataclass(kw_only=True)
class EndStep:
    """Terminal node. `inputs` is the shape of the final state the client receives."""
    kind: ClassVar[str] = "end"
    name: str = "end"
    inputs: Inputs = field(default_factory=dict)


@dataclass(kw_only=True)
class Router:
    """
    Dumb router: maps the value the client posted under `choice` to the next node.
    Calls no model, has no endpoint. The server walks routers internally after the
    client's input arrives; the client only sees the branches for schema purposes.

    choice: key in the posted input whose value selects the branch
    branches: branch value -> node; needs two or more
    """
    kind: ClassVar[str] = "router"
    name: str
    choice: str
    branches: Dict[str, "Node"]

    def __post_init__(self) -> None:
        if len(self.branches) < 2:
            raise ValueError(f"Router {self.name!r} needs at least two branches")

    def route(self, payload: JSON) -> "Node":
        if self.choice not in payload:
            raise InputValidationError(self.name, [f"missing routing key {self.choice!r}"])
        value = payload[self.choice]
        if value not in self.branches:
            raise InputValidationError(
                self.name, [f"{self.choice}={value!r} has no branch; options: {list(self.branches)}"])
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
            "step": node.name, "kind": node.kind, "on": node.choice,
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


# ------------------------------------------------------------------------ procedure


@dataclass(kw_only=True)
class Procedure:
    """
    The whole graph. Binds meta, loader, and interpreter to every reachable node and
    exposes the single server operation, `run`.

    python: interpreter for Execution steps (built from Meta.environment on `server create`)
    """
    meta: Meta
    start: BaseStep
    loader: ResourceLoader | None = None
    python: Path | None = None
    nodes: Dict[str, Node] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self._walk(self.start)

    def _walk(self, node: Node | None) -> None:
        if node is None:
            return
        if node.name in self.nodes:
            if self.nodes[node.name] is not node:
                raise ValueError(f"Duplicate step name {node.name!r}")
            return
        self.nodes[node.name] = node
        if isinstance(node, BaseStep):
            if node.meta is None:
                node.meta = self.meta
            if node.loader is None:
                node.loader = self.loader
            if isinstance(node, Execution) and node.python is None:
                node.python = self.python
            self._walk(node.inputsTo)
        elif isinstance(node, Router):
            for target in node.branches.values():
                self._walk(target)

    @property
    def end(self) -> EndStep | None:
        return next((n for n in self.nodes.values() if isinstance(n, EndStep)), None)

    def describe(self) -> JSON:
        """For `aip info`: meta plus the start and end shapes."""
        return {
            "meta": {"name": self.meta.name, "description": self.meta.description, "version": self.meta.version},
            "start": describe_next(self.start),
            "end": describe_next(self.end),
            "steps": {name: node.kind for name, node in self.nodes.items()},
        }

    def run(self, after: str | None, payload: JSON, history: List[JSON] | None = None,
            thresholds: Dict[str, float] | None = None) -> StepResponse:
        """
        The single server operation.

        after:   name of the step the client just completed, or None to start
        payload: the client's accepted input for whatever comes next
        history: the history the client carried in
        """
        history = list(history or [])
        if after is None:
            node: Node | None = self.start
        else:
            prev = self.nodes.get(after)
            if not isinstance(prev, BaseStep):
                raise KeyError(f"No runnable step named {after!r}")
            node = prev.inputsTo

        # Server-side traversal: walk routers on the client's accepted input.
        while isinstance(node, Router):
            target = node.route(payload)
            history.append({"step": node.name, "kind": node.kind,
                            "input": {node.choice: payload[node.choice]}, "result": {"to": target.name}})
            node = target

        if node is None or isinstance(node, EndStep):
            end = node or EndStep()
            validate_input(end.name, end.inputs, payload)
            history.append({"step": end.name, "kind": end.kind, "input": payload, "result": payload})
            return StepResponse(ran=end.name, kind=end.kind, result=payload, suggested=payload,
                                review=[], next=None, history=history)

        return node.accept(payload, history, thresholds=thresholds)
