"""The AIP procedure format, as pydantic models.

These models ARE the spec. The JSON Schema in assets/procedure.schema.json is generated
from them (`aip-spec schema`), the validator reports their errors, and the `aip` runtime
builds its executable Procedure from them. Every field carries a description so the generated schema
is self-explanatory to an authoring agent.
"""

from enum import Enum
from typing import Annotated, Dict, List, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

FORMAT_VERSION = "0.6a1"
# Earlier formats this validator recognises, so it can say `runtime_block_outdated` instead of
# `missing_runtime_block`. 0.6a0 is breaking: skills in these formats are rejected, not accepted.
LEGACY_VERSIONS = ("0.5a1", "0.6a0")
SPEC_URL = f"https://github.com/zach-blumenfeld/aip-spec/tree/v{FORMAT_VERSION}"
SCHEMA_ID = f"https://raw.githubusercontent.com/zach-blumenfeld/aip-spec/v{FORMAT_VERSION}/assets/procedure.schema.json"

STEP_NAME_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"
QUESTION_NAME_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*$"


class DataType(str, Enum):
    """AIP type vocabulary. Machine-enforced at runtime: the server compiles each step's
    `inputs` and `outputs` to JSON Schemas and validates the state and the step's result against them."""
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    OBJECT = "object"  # JSON-like key/value map
    LIST = "list[*]"   # collection of any of the above


class Strict(BaseModel):
    """Every object in the format is closed: unknown keys are errors, not ignored."""
    model_config = ConfigDict(extra="forbid")


StepName = Annotated[str, Field(
    pattern=STEP_NAME_PATTERN,
    description="Short kebab-case identifier, unique within the procedure. Edges (`inputs_to`, router `branches`) reference steps by this name.",
)]

AssetPath = Annotated[str, Field(
    pattern=r"^assets/.+",
    description="Path under `assets/`, relative to the skill folder. Assets are eager: their content is injected on every invoke.",
)]


class IOItem(Strict):
    name: str = Field(
        min_length=1,
        description="Key in the state. In `inputs`, a key the step reads; in `outputs`, a key the step adds. Decision answers land under their question name, so a downstream step that consumes an answer declares an input of the same name.",
    )
    type: DataType = Field(description="Type from the AIP vocabulary. Enforced on the state before the step runs (inputs) and on the step's result (outputs).")
    description: str | None = Field(
        default=None,
        description="One-line summary of what this value is. Optional but recommended: it makes the graph readable without opening the backing script or template.",
    )


Inputs = Annotated[List[IOItem], Field(
    description="The keys this step reads from the state; every listed name is required. Each must be produced by a step on every path to this one, or declared on the start step, whose inputs are what the client supplies.",
)]

Outputs = Annotated[List[IOItem], Field(
    description="The keys this step adds to the state. Each key has exactly one producer in the procedure and is never a start input, so the state only grows and nothing is overwritten.",
)]


class Reference(Strict):
    path: str = Field(
        pattern=r"^references/.+",
        description="Path under `references/`, relative to the skill folder. References are lazy: the client receives the path and description and fetches the body only if it decides it needs it.",
    )
    description: str = Field(description="What the reference contains and when to pull it. This is all the client sees before deciding to load it.")


class NoulCriteria(Strict):
    true: str | None = Field(default=None, description="What counts as a yes answer.")
    false: str | None = Field(default=None, description="What counts as a no answer.")

    @model_validator(mode="before")
    @classmethod
    def _accept_yaml_booleans(cls, data):
        """YAML parses bare `true:` / `false:` keys as booleans; map them to the field names."""
        if isinstance(data, dict):
            return {("true" if k is True else "false" if k is False else k): v for k, v in data.items()}
        return data


class NoulQuestion(Strict):
    type: Literal["noul"] = Field(description="A yes/no question.")
    instructions: str = Field(description="A yes/no question or statement about the input. The answer is a probability of yes/true; it collapses to a boolean under the question name.")
    criteria: NoulCriteria | None = Field(default=None, description="Optional sharpening of what counts as yes and no.")


class ChoiceQuestion(Strict):
    type: Literal["choice"] = Field(description="Pick one label from a set.")
    instructions: str = Field(description="What to pick between and how to judge. The answer is the most likely label plus the full probability distribution; it collapses to the label under the question name.")
    criteria: Dict[str, str | None] = Field(
        min_length=2,
        description="Label to description. Null when the label is self-explanatory. Router branches keyed on this question use these labels.",
    )


class ScoreQuestion(Strict):
    type: Literal["score"] = Field(description="Rate the input on an ordered rubric.")
    instructions: str = Field(description="What is being rated. The answer is a probability-weighted position on the rubric; it collapses to the most likely integer level under the question name.")
    criteria: List[str] = Field(
        min_length=2, max_length=10,
        description="Ordered rubric, lowest level first. Level numbers are the list positions starting at 0.",
    )


Question = Annotated[Union[NoulQuestion, ChoiceQuestion, ScoreQuestion], Field(
    discriminator="type",
    description="One SystemOne question. `instructions` carry the evaluation criteria; the step's input is the content being evaluated. Passed through to the decision model as-is.",
)]


class DecisionStep(Strict):
    name: StepName
    kind: Literal["decision"] = Field(description="A structured decision model answers typed questions about the input.")
    description: str = Field(description="What this decision settles. One line.")
    inputs: Inputs
    questions: Dict[Annotated[str, Field(pattern=QUESTION_NAME_PATTERN)], Question] = Field(
        min_length=1,
        description="Questions keyed by name. Answers come back under the same names and, once collapsed, become keys in the state: a decision's outputs are its question names.",
    )
    thresholds: Dict[str, Annotated[float, Field(ge=0, le=1)]] = Field(
        default_factory=dict,
        description="Per-question review thresholds, keyed by question name. For `noul`: flag when the probability is within this margin of 0.5. For `choice` and `score`: flag when the model's confidence is below this value. The client may override per call; it makes the final call on flagged answers.",
    )
    history: bool = Field(
        default=False,
        description="Send the run's history (every earlier step's input and result) to the decision model alongside the declared inputs. Off by default: history grows with the run and is billed on every decision.",
    )
    inputs_to: StepName = Field(description="The step that receives this step's output.")


PACKAGE_PATTERN = r"^[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?(>=[0-9]+(\.[0-9]+)*)?$"
VERSION_PATTERN = r"^[0-9]+(\.[0-9]+)*$"
DEFAULT_LAUNCHER = "python"


class Interpreter(Strict):
    name: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._+-]*$",
        description="The program that runs the scripts, as found on PATH: `python`, `bash`, `node`. Execution steps without a `command` are launched with `python`.",
    )
    version: str | None = Field(
        default=None, pattern=VERSION_PATTERN,
        description="Minimum version, dotted numbers (`3.10`). For `python` it is checked against the interpreter that runs the scripts; for anything else against the first version number `<name> --version` prints.",
    )


class Requires(Strict):
    """What the machine that runs the scripts must have. The client checks it before the first
    execution step and stops with one message naming every missing item."""
    interpreter: Interpreter = Field(description="The interpreter the scripts need, with its minimum version.")
    packages: List[Annotated[str, Field(pattern=PACKAGE_PATTERN)]] = Field(
        default_factory=list,
        description="Python distributions the scripts import, as installed by pip (`numpy`, `scikit-learn>=1.3`), optionally with a minimum version. Checked in the interpreter that runs `python` scripts.",
    )
    tools: List[Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")]] = Field(
        default_factory=list,
        description="Other executables the scripts call or are launched with, each checked on PATH (`git`, `ffmpeg`, `bash`).",
    )


class ExecutionStep(Strict):
    name: StepName
    kind: Literal["execution"] = Field(description="A script runs. Analogous to a tool call.")
    description: str = Field(description="What the script does. One line; the script is the source of truth.")
    inputs: Inputs
    script: str = Field(
        pattern=r"^scripts/.+",
        description="Path under `scripts/`, relative to the skill folder. Receives one JSON object on stdin ({state, assets, expects}, where `state` holds only the step's declared `inputs`) and writes one JSON object to stdout holding exactly the step's `outputs`.",
    )
    outputs: Outputs = Field(default_factory=list)
    command: List[Annotated[str, Field(min_length=1)]] | None = Field(
        default=None, min_length=1,
        description="How the script is launched, as an argument list run from the script's folder: `[\"bash\", \"run.sh\"]`. Omitted, it is `python` on the script. The first item must be the `requires` interpreter or one of its `tools`.",
    )
    assets: List[AssetPath] = Field(
        default_factory=list,
        description="Constant inputs the script always receives, such as a config file. Re-read from disk on every invoke.",
    )
    timeout: float | None = Field(
        default=None, gt=0,
        description="Seconds before the script is killed. Defaults to the server's setting when omitted.",
    )
    inputs_to: StepName = Field(description="The step that receives this step's output.")


class ClientTaskStep(Strict):
    name: StepName
    kind: Literal["client_task"] = Field(description="The client performs the work itself: generation, synthesis, reasoning.")
    description: str = Field(description="What the client is asked to do. One line; the template carries the detail.")
    inputs: Inputs
    template: AssetPath = Field(
        description="The task template, rendered with `{key}` placeholders from the input, `{assets[name]}` for injected assets, and `{meta.name}` for the skill name. The client performs the task and answers with structured JSON matching the step's `outputs`.",
    )
    outputs: Outputs = Field(
        default_factory=list,
        description="The keys the client's answer adds to the state. Required: they are what the client is asked to answer with.",
    )
    assets: List[AssetPath] = Field(
        default_factory=list,
        description="Extra assets available to the template as `{assets[name]}`, where name is the file stem.",
    )
    references: List[Reference] = Field(
        default_factory=list,
        description="Documents the client may load on demand while doing the task.",
    )
    framing: bool = Field(
        default=True,
        description="Prepend the AIP system framing (which workflow this is, how to read the state) to the rendered task.",
    )
    inputs_to: StepName = Field(description="The step that receives this step's output.")


class RouterStep(Strict):
    name: StepName
    kind: Literal["router"] = Field(description="Server-side branch on a value the client chose. Calls no model, has no endpoint.")
    description: str = Field(description="What the branch decides. One line.")
    branch_on: str = Field(
        min_length=1,
        description="Key in the state whose value selects the branch. Typically a decision question name or an output of an execution or client task. The router adds nothing to the state; its choice is recorded in the run history only.",
    )
    branches: Dict[str, StepName] = Field(
        min_length=2,
        description="Value to step name. The server resolves this after the client posts; the client never traverses. A value with no branch is a validation error.",
    )


class EndStep(Strict):
    name: StepName
    kind: Literal["end"] = Field(description="Terminal node.")
    description: str | None = Field(default=None, description="What the final state represents. One line.")
    inputs: Inputs = Field(description="The procedure's result: the keys handed back to the client when the run is done.")


Step = Annotated[Union[DecisionStep, ExecutionStep, ClientTaskStep, RouterStep, EndStep], Field(discriminator="kind")]

RUNNABLE_KINDS = frozenset({"decision", "execution", "client_task"})


class ProcedureSpec(Strict):
    """An execution graph of typed steps run by an AIP server with the client in the loop.

    Step kinds are `decision` (SystemOne questions answered by a structured decision model),
    `execution` (a script under scripts/), `client_task` (templated work the client performs
    itself), `router` (server-side branching on a value the client chose), and `end` (the
    procedure's result). The first step in `steps` is the start; its `inputs` are what the
    client supplies. Edges are `inputs_to` by step name. Every runnable step declares the keys
    it reads as `inputs`; execution and client_task steps declare the keys they add as
    `outputs`, and a decision's outputs are its question names. Every key is produced by
    exactly one step, so the state only grows.
    """
    purpose: str = Field(description="What the procedure encapsulates as a coherent unit of work: the scope it covers and what it adds beyond general agent knowledge. One short paragraph.")
    trigger_when: List[str] = Field(
        min_length=1,
        description="Conditions under which the agent should consider this skill. Mixed granularity expected: immediate invocation triggers alongside broader applicability contexts belong in the same list.",
    )
    do_not_use_when: List[str] = Field(
        default_factory=list,
        description="Conditions under which the agent should NOT use this skill: explicit non-purposes that pair with trigger_when to sharpen activation.",
    )
    requires: Requires | None = Field(
        default=None,
        description="The environment the scripts need: interpreter and minimum version, Python packages, other tools. Required when the procedure has execution steps.",
    )
    steps: List[Step] = Field(
        min_length=2,
        description="The nodes of the execution graph. The first step is the start and must be runnable (decision, execution, or client_task). Exactly one step has kind `end`. Every runnable step names the node that receives its output via `inputs_to`; routers name theirs via `branches`. The validator checks that names are unique, every reference resolves, every step is reachable from the start, every step can reach the end, every consumed key is produced on every path to its consumer or declared on the start step, every key has exactly one producer, a procedure with execution steps declares `requires` and launches each script with its interpreter or one of its tools, and every referenced asset, reference, and script exists on disk.",
    )
    anti_patterns: List[str] = Field(
        default_factory=list,
        description="Common mistakes the procedure steers the agent away from. Concrete corrections to errors the agent would otherwise make.",
    )

    @property
    def start(self) -> Step:
        return self.steps[0]

    def step(self, name: str) -> Step | None:
        return next((s for s in self.steps if s.name == name), None)


def json_schema() -> dict:
    """The publishable JSON Schema for the format, generated from the models."""
    generated = ProcedureSpec.model_json_schema()
    generated.pop("title", None)
    generated.pop("description", None)
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_ID,
        "title": "Procedure",
        "description": " ".join(line.strip() for line in (ProcedureSpec.__doc__ or "").strip().splitlines() if line.strip()),
        "aip": {"spec": SPEC_URL, "version": FORMAT_VERSION},
        **generated,
    }


def runtime_text(version: str = FORMAT_VERSION) -> str:
    """The runtime block every authored skill carries verbatim at the top of its body.

    Shipped inside the package so the validator can check a skill's copy is current. The
    text of each version in `LEGACY_VERSIONS` ships too, so the validator can recognise an
    outdated copy and warn instead of reject.
    """
    from importlib.resources import files

    name = "runtime.md" if version == FORMAT_VERSION else f"runtime-{version}.md"
    return files("aip_spec").joinpath(name).read_text(encoding="utf-8")

