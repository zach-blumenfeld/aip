"""
AIP server-side step model.

Design:
- `State` is data only: what flows between steps and lands in history.
- Framing (how to read a payload) is owned by each step type, not by State.
  Decision: per-question `instructions` and descriptive payload keys.
  ClientTask: a prose template rendered at invoke time.
- Model / client inputs are pure projections (`render()`) built from state plus the
  step's own resources. They are sent and discarded, never written back, so nothing
  has to be scrubbed before `State.next()`.
- Assets are eager (content injected every invoke). References are lazy (uri and
  description only; the client pulls the body on demand).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, TypeAlias
import copy

from typesafe_sdk import Choice, Noul, Score, SystemOneResponse, TypeSafeClient

DecisionQuestion: TypeAlias = Noul | Choice | Score

SYSTEM_FRAMING = """\
You are executing a single step in a graph shaped workflow pertaining to "{skill_context}".
`currentState` holds the state for this specific step.
If needed, the historic state of past steps is contained in `history`.
Assets, if present, are fixed reference material for this step.
"""


class DataType(str, Enum):
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    OBJECT = "object"  # JSON-like key/value map
    LIST = "list[*]"   # collection of any of the above


# --------------------------------------------------------------------------- state


@dataclass
class State:
    """
    Data only. `currentState` is the input to the current step; `history` is every
    prior step's `currentState`. No framing ("system level") text lives here.
    """
    currentState: Dict[str, Any] = field(default_factory=dict)
    history: List[Dict[str, Any]] = field(default_factory=list)

    def next(self, update_state: Dict[str, Any] | None = None) -> None:
        self.history.append(copy.deepcopy(self.currentState))
        self.currentState = dict() if update_state is None else update_state


@dataclass
class Meta:
    """
    Workflow-level framing, owned by the Procedure and readable by any step.

    `system_framing` is the constant preamble every step can request. It is a template
    with a `{skill_context}` slot filled from `description` (falling back to `name`).
    """
    name: str
    description: str = ""
    version: str = "0.1.0"
    system_framing: str = SYSTEM_FRAMING

    def framing(self) -> str:
        return self.system_framing.format(skill_context=self.description or self.name)


# ----------------------------------------------------------------------- resources


class Resource(ABC):
    """
    A markdown file that belongs to an AIP package, addressed relative to the package root
    as `<aip_id>/<asset|reference>/<name>.md`. Bodies are read from disk by ResourceLoader.
    """
    uri: Path
    description: str

    def __init__(self, aip_id: str, name: str, description: str):
        path = Path(name)
        if not path.suffix:
            path = path.with_suffix(".md")
        if path.suffix.lower() != ".md":
            raise ValueError(f"{type(self).__name__} {name!r} must be a markdown (.md) file")
        self.uri = Path(aip_id, self._get_type(), path)
        self.description = description

    @property
    def name(self) -> str:
        return self.uri.stem

    @abstractmethod
    def _get_type(self) -> str:
        pass

    def summary(self) -> Dict[str, str]:
        """Lazy form: enough for a client to decide whether to fetch the body."""
        return {"uri": str(self.uri), "description": self.description}


class Asset(Resource):
    """Fixed templates and resources injected into every invoke."""
    def _get_type(self) -> str:
        return "asset"


class Reference(Resource):
    """Documents the client loads on demand (progressive disclosure)."""
    def _get_type(self) -> str:
        return "reference"


class ResourceLoader:
    """
    Reads resource markdown files from disk, relative to a package root, and caches them.
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

    def load_uri(self, uri: Path | str) -> str:
        uri = Path(uri)
        if uri not in self._cache:
            path = self.path(uri)
            if not path.is_file():
                raise FileNotFoundError(f"Resource {uri!s} not found at {path}")
            self._cache[uri] = path.read_text(encoding="utf-8")
        return self._cache[uri]

    def load(self, resource: Resource) -> str:
        return self.load_uri(resource.uri)

    def load_all(self, resources: List[Resource]) -> Dict[str, str]:
        return {r.name: self.load(r) for r in resources}


# ---------------------------------------------------------------------------- steps


@dataclass(kw_only=True)
class BaseStep(ABC):
    """
    Every step has state and can reach the package loader and workflow meta.
    `_invoke` produces the next step's input; `run` promotes it into state.
    """
    state: State = field(default_factory=State)
    loader: ResourceLoader | None = None
    meta: Meta | None = None
    include_framing: bool = False  # prepend Meta.framing() to what this step renders

    @abstractmethod
    def _invoke(self) -> Dict[str, Any]:
        pass

    def framing(self) -> str:
        """The system-level preamble, or empty when not requested or no meta is bound."""
        if not self.include_framing or self.meta is None:
            return ""
        return self.meta.framing()

    def run(self) -> None:
        update = self._invoke()
        self.state.next(update)

    def _require_loader(self) -> ResourceLoader:
        if self.loader is None:
            raise RuntimeError(f"{type(self).__name__} needs a ResourceLoader to resolve resources")
        return self.loader


@dataclass(kw_only=True)
class EndStep:
    result: Dict[str, DataType] = field(default_factory=dict)


@dataclass(kw_only=True)
class Decision(BaseStep):
    """
    Runs a SystemOne (TypeSafe / Jev) decision and hands the typed result to the next step.

    Framing lives in each question's `instructions`, per TypeSafe guidance: state is the
    content being evaluated, questions carry the criteria. Refer to injected assets by
    key, e.g. "Using assets.refund_policy, is this request eligible?".

    inputsTo: the step that receives this step's output
    tasks: questions keyed by name; answers come back under the same names
    assets: eager resources injected into the payload under `assets`
    client: optional injected TypeSafe client (tests, connection reuse); otherwise one
            is opened per invoke using TYPESAFE_API_KEY from the environment
    include_framing: off by default. TypeSafe advises keeping instructions out of state;
            when on, Meta.framing() is added under a `context` key.
    """
    inputsTo: BaseStep | EndStep | None = None
    tasks: Dict[str, DecisionQuestion] = field(default_factory=dict)
    assets: List[Asset] = field(default_factory=list)
    client: TypeSafeClient | None = None

    def render(self) -> Dict[str, Any]:
        """Pure projection of state + assets into the JSON `state` sent to Jev."""
        payload: Dict[str, Any] = {}
        if framing := self.framing():
            payload["context"] = framing
        payload["currentState"] = self.state.currentState
        if self.state.history:
            payload["history"] = self.state.history
        if self.assets:
            payload["assets"] = self._require_loader().load_all(self.assets)
        return payload

    def _invoke(self) -> Dict[str, Any]:
        """
        Returns the TypeSafe result as a JSON dict:
            {"model": str,
             "usage": {"input_tokens", "output_tokens"},
             "answers": {name: {"type": "noul"|"choice"|"score", ...}}}
        Thresholding on confidence is the client's job, per the protocol.
        """
        if not self.tasks:
            raise ValueError("Decision step has no tasks to ask")
        payload = self.render()
        if self.client is not None:
            result: SystemOneResponse = self.client.system_one(state=payload, questions=self.tasks)
        else:
            with TypeSafeClient() as client:
                result = client.system_one(state=payload, questions=self.tasks)
        return result.model_dump(mode="json")


class _SafeMap(dict):
    """format_map helper: unknown placeholders are left intact instead of raising."""
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


@dataclass(kw_only=True)
class ClientTask(BaseStep):
    """
    A step the client performs itself (text generation, synthesis, reasoning). Fallback
    for anything not expressible as a Decision, Execution, or Router.

    The template is this step's framing: prose rendered at invoke time with `{key}`
    placeholders drawn from currentState, plus `{assets[name]}` and `{meta.name}`.

    inputsTo: the step that receives this step's output
    template: the asset holding the task template, e.g. Asset(aip, "generate_email.md", ...)
    assets: extra eager resources available to the template as {assets[name]}
    references: lazy resources; only uri + description are handed to the client
    include_framing: on by default; Meta.framing() is prepended to the rendered template
    """
    inputsTo: BaseStep | EndStep | None = None
    include_framing: bool = True
    template: Asset
    assets: List[Asset] = field(default_factory=list)
    references: List[Reference] = field(default_factory=list)

    def render(self) -> str:
        """Pure projection of the template over state, assets, and meta."""
        loader = self._require_loader()
        mapping = _SafeMap(self.state.currentState)
        mapping["assets"] = loader.load_all(self.assets)
        mapping["meta"] = self.meta
        body = loader.load(self.template).format_map(mapping)
        framing = self.framing()
        return f"{framing}\n{body}" if framing else body

    def _invoke(self) -> Dict[str, Any]:
        """Hands the rendered task and the reference index to the client."""
        return {
            "task": self.render(),
            "references": [r.summary() for r in self.references],
        }


@dataclass(kw_only=True)
class Execution(BaseStep):
    """
    Executes an action rather than making a decision. Analogous to a tool call. For now
    a python script path; MCP and endpoints can be added later.

    inputsTo: the step that receives this step's output
    assets: constant inputs the script always receives
    script: path to the python script to execute
    """
    inputsTo: BaseStep | EndStep | None = None
    assets: List[Asset] = field(default_factory=list)
    script: str

    def _invoke(self) -> Dict[str, Any]:
        raise NotImplementedError("Execution invocation is not implemented yet")


@dataclass(kw_only=True)
class Router(BaseStep):
    """
    Dumb router: maps the value found at `choice` in currentState to the next step.
    Calls no model. Must have two or more outbound options.

    choice: key in currentState whose value selects the branch
    next_step: branch value -> step
    """
    choice: str
    next_step: Dict[str, BaseStep | EndStep]

    def route(self) -> BaseStep | EndStep:
        value = self.state.currentState.get(self.choice)
        if value not in self.next_step:
            raise KeyError(f"Router has no branch for {self.choice}={value!r}; options: {list(self.next_step)}")
        return self.next_step[value]

    def _invoke(self) -> Dict[str, Any]:
        """State passes through unchanged; the routing decision is `route()`."""
        return self.state.currentState


@dataclass(kw_only=True)
class Procedure:
    meta: Meta
    start: BaseStep
    intermediate: List[BaseStep] = field(default_factory=list)
    end: EndStep = field(default_factory=EndStep)

    def __post_init__(self) -> None:
        for step in [self.start, *self.intermediate]:
            if step.meta is None:
                step.meta = self.meta
