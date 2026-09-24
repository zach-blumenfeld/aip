"""The AIP procedure format, as pydantic models.

These models ARE the spec. The JSON Schema in assets/procedure.schema.json is generated
from them (`aip schema`), the validator reports their errors, and the loader builds the
runtime Procedure from them. Every field carries a description so the generated schema
is self-explanatory to an authoring agent.
"""

from enum import Enum
from typing import Annotated, Dict, List, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

FORMAT_VERSION = "0.4a0"
SPEC_URL = f"https://github.com/zach-blumenfeld/aip/tree/v{FORMAT_VERSION}"
SCHEMA_ID = f"https://raw.githubusercontent.com/zach-blumenfeld/aip/v{FORMAT_VERSION}/assets/procedure.schema.json"

STEP_NAME_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"
QUESTION_NAME_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*$"


class DataType(str, Enum):
    """AIP type vocabulary. Machine-enforced at runtime: the server compiles each step's
    `inputs` to a JSON Schema and validates the client's input against it."""
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
        description="Key in the input object the client posts to this step. Decision answers land under their question name, so a downstream step that consumes an answer declares an input of the same name.",
    )
    type: DataType = Field(description="Type from the AIP vocabulary. Enforced when the client posts to this step.")
    description: str | None = Field(
        default=None,
        description="One-line summary of what this value is. Optional but recommended: it makes the graph readable without opening the backing script or template.",
    )


Inputs = Annotated[List[IOItem], Field(
    description="The input shape this step accepts from the client. Every listed name is required in the posted input; extra keys pass through untouched so upstream state can travel down the graph.",
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
        description="Questions keyed by name. Answers come back under the same names and, once collapsed, become keys in the suggested input for the next step.",
    )
    thresholds: Dict[str, Annotated[float, Field(ge=0, le=1)]] = Field(
        default_factory=dict,
        description="Per-question review thresholds, keyed by question name. For `noul`: flag when the probability is within this margin of 0.5. For `choice` and `score`: flag when the model's confidence is below this value. The client may override per call; it makes the final call on flagged answers.",
    )
    inputs_to: StepName = Field(description="The step that receives this step's output.")


class ExecutionStep(Strict):
    name: StepName
    kind: Literal["execution"] = Field(description="A script runs. Analogous to a tool call.")
    description: str = Field(description="What the script does. One line; the script is the source of truth.")
    inputs: Inputs
    script: str = Field(
        pattern=r"^scripts/.+",
        description="Path under `scripts/`, relative to the skill folder. Receives one JSON object on stdin ({currentState, assets, expects}) and writes one JSON object to stdout, which becomes the result.",
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
        description="The task template, rendered with `{key}` placeholders from the input, `{assets[name]}` for injected assets, and `{meta.name}` for the skill name. The client performs the task and posts structured JSON matching the next step's inputs.",
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
        description="Key in the client's posted input whose value selects the branch. Typically a decision question name or an input produced by an execution or client task.",
    )
    branches: Dict[str, StepName] = Field(
        min_length=2,
        description="Value to step name. The server resolves this after the client posts; the client never traverses. A value with no branch is a validation error.",
    )


class EndStep(Strict):
    name: StepName
    kind: Literal["end"] = Field(description="Terminal node.")
    description: str | None = Field(default=None, description="What the final state represents. One line.")
    inputs: Inputs = Field(description="The shape of the final state the client receives when the procedure completes.")


Step = Annotated[Union[DecisionStep, ExecutionStep, ClientTaskStep, RouterStep, EndStep], Field(discriminator="kind")]

RUNNABLE_KINDS = frozenset({"decision", "execution", "client_task"})


class ProcedureSpec(Strict):
    """An execution graph of typed steps run by an AIP server with the client in the loop.

    Step kinds are `decision` (SystemOne questions answered by a structured decision model),
    `execution` (a script under scripts/), `client_task` (templated work the client performs
    itself), `router` (server-side branching on a value the client chose), and `end` (the
    shape of the final state). The first step in `steps` is the start. Edges are `inputs_to`
    by step name. Every runnable step declares the input shape it accepts; the server
    validates the client's input against it before running the step.
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
    steps: List[Step] = Field(
        min_length=2,
        description="The nodes of the execution graph. The first step is the start and must be runnable (decision, execution, or client_task). Exactly one step has kind `end`. Every runnable step names the node that receives its output via `inputs_to`; routers name theirs via `branches`. The validator checks that names are unique, every reference resolves, every step is reachable from the start, every step can reach the end, and every referenced asset, reference, and script exists on disk.",
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
