"""The type vocabulary at run time, and the errors a step can fail with.

The language's types (spec 6, Types) are checked against JSON values: `string`, `integer`,
`float`, `boolean`, `list` and `object` as JSON holds them; the three answer types
`true_or_false`, `choice` and `score`, each an object with a `value` of its kind (spec 2.4); and
`decision` and `aggregation`, objects with one answer per question or aggregation. A key whose
type the program does not say (an item of a plain list) accepts anything.

An answer written by an agent is `{"value": ...}` and nothing else; one written by a script may
carry `confidence` and the probabilities a model's would (`ANSWER_FIELDS`, spec 2.4), and nothing
else. The runtime also accepts the bare value (`true` for `passed: true_or_false`) and stores it
as `{"value": true}`; that is the one normalisation it performs, and the record keeps the
normalised form (`docs/language/runtime.md`, The state).

Every failure of a step is a `StepError` whose `kind` is a word of `ERROR_KINDS`, the vocabulary
of the error objects the CLI and the SDK report; `fields()` is the kind's detail."""

from __future__ import annotations

from typing import Any, TypeAlias

from aip_spec.keywords import ANSWER_TYPES

JSON: TypeAlias = dict[str, Any]

# The JSON kind each answer type's `value` has (spec 2.4).
VALUE_KIND = {"true_or_false": "boolean", "choice": "string", "score": "integer"}

# The fields an answer of each type may carry beside `value`: the model's own (spec 2.4). A script
# may supply them; an agent's answer is `value` alone.
ANSWER_FIELDS = {"true_or_false": ("confidence", "noul", "probabilities"), "choice": ("confidence", "probabilities"),
                 "score": ("confidence", "score", "probabilities")}

ERROR_KINDS = ("invalid_input", "invalid_output", "no_branch", "script_failed", "timeout", "requires_unmet",
               "no_decision_model", "decision_model_failed", "loop_cap", "not_paused", "server")

DECISION_MODEL_HINT = ("run `aip config --decision-model-key KEY`, and `aip config --decision-model URL` for an endpoint other "
                       "than TypeSafe's")


def is_plain(type: str, value: Any) -> bool:
    """Whether `value` is a `string`, `integer`, `float`, `boolean`, `list` or `object` of that type."""
    if type == "string":
        return isinstance(value, str)
    if type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type == "float":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type == "boolean":
        return isinstance(value, bool)
    if type == "list":
        return isinstance(value, list)
    if type == "object":
        return isinstance(value, dict)
    return False


def normalise(type: str | None, value: Any) -> Any:
    """`value` as the state holds it: a bare `true`, label or level written for an answer type
    becomes `{"value": ...}`; everything else is returned as it is."""
    if type in ANSWER_TYPES and not isinstance(value, dict) and is_plain(VALUE_KIND[type], value):
        return {"value": value}
    return value


def conforms(type: str | None, value: Any, labels: list[str] | None = None) -> str | None:
    """Why `value` is not of `type`, or None when it is. `labels` are a `choice` or `score`
    answer's labels when known: a choice's value must be one, a score's an index into them."""
    if type is None:
        return None
    if type in ANSWER_TYPES:
        if not isinstance(value, dict) or "value" not in value:
            return f"a {type} answer is an object with a value, not {describe(value)}"
        v = value["value"]
        kind = VALUE_KIND[type]
        if not is_plain(kind, v):
            return f"the value of a {type} answer is a {kind}, not {describe(v)}"
        if labels:
            if type == "choice" and v not in labels:
                return f"{v!r} is not one of the labels {labels}"
            if type == "score" and not 0 <= v < len(labels):
                return f"level {v} is outside 0..{len(labels) - 1}"
        confidence = value.get("confidence")
        if confidence is not None and not (is_plain("float", confidence) and 0 <= confidence <= 1):
            return f"the confidence of an answer is a number in 0..1, not {describe(confidence)}"
        probabilities = value.get("probabilities")
        if probabilities is not None and not (isinstance(probabilities, dict)
                                              and all(is_plain("float", p) and 0 <= p <= 1 for p in probabilities.values())):
            return "the probabilities of an answer are an object of numbers in 0..1"
        return None
    if type in ("decision", "aggregation"):
        return None if isinstance(value, dict) else f"a {type} is an object, not {describe(value)}"
    if is_plain(type, value):
        return None
    return f"expected {an(type)}, got {describe(value)}"


def extra_fields(type: str | None, value: Any, allowed: tuple[str, ...]) -> str | None:
    """Why an answer carries fields its source may not write, or None: `allowed` is what may
    sit beside `value` (nothing for an agent, `ANSWER_FIELDS[type]` for a script)."""
    if type not in ANSWER_TYPES or not isinstance(value, dict):
        return None
    extra = sorted(k for k in value if k != "value" and k not in allowed)
    if not extra:
        return None
    if not allowed:
        return f"an agent's answer is its value and nothing else, not {', '.join(extra)}"
    return f"a {type} answer carries value, {', '.join(allowed)} and nothing else, not {', '.join(extra)}"


def an(word: str) -> str:
    return ("an " if word[0] in "aeiou" else "a ") + word


def describe(value: Any) -> str:
    """The JSON kind of a value, for messages: `a string`, `null`, `a list`..."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "a boolean"
    if isinstance(value, int):
        return "an integer"
    if isinstance(value, float):
        return "a float"
    if isinstance(value, str):
        return "a string"
    if isinstance(value, list):
        return "a list"
    if isinstance(value, dict):
        return "an object"
    return type(value).__name__


def branch_key(value: Any, labels: list[str] | None = None) -> str:
    """The word a route's branch line writes for an answer's value: `true` or `false` for a
    `true_or_false`, the label for a `choice`, and for a `score` the label of its level when the
    question has labels, else the level's number."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and labels and 0 <= value < len(labels):
        return labels[value]
    return str(value)


# ---------------------------------------------------------------- errors


class StepError(Exception):
    """A step failed. `kind` is a word of `ERROR_KINDS`; `step` the step's name; `fields()` the
    kind's detail (key lists, a script's exit code and stderr, what a machine lacks)."""

    kind = "server"

    def __init__(self, step: str | None, message: str):
        super().__init__(message)
        self.step = step
        self.message = message

    def fields(self) -> JSON:
        return {}

    def to_dict(self) -> JSON:
        return {"error": self.kind, "step": self.step, "message": self.message, **self.fields()}


class KeysError(StepError):
    """A state or a result that does not fit the declared keys: `missing` names absent keys,
    `invalid` the keys that are mistyped, undeclared, or hold a value nothing accepts."""

    what = ""

    def __init__(self, step: str | None, errors: list[str], missing: list[str] | None = None,
                 invalid: list[str] | None = None):
        self.errors = list(errors)
        self.missing = list(missing or [])
        self.invalid = list(invalid or [])
        super().__init__(step, f"{self.what} {step!r}: " + "; ".join(errors))

    def fields(self) -> JSON:
        return {"missing": self.missing, "invalid": self.invalid}


class InvalidInput(KeysError):
    kind, what = "invalid_input", "the input to"


class InvalidOutput(KeysError):
    """A step's result does not match its `Produce` keys. Nothing is written to the state;
    `script` is set when a script returned it."""

    kind, what = "invalid_output", "the output of"
    script: str | None = None

    def fields(self) -> JSON:
        return {**({"script": self.script} if self.script else {}), **super().fields()}


class NoBranch(StepError):
    """A route read a value none of its branch lines names."""

    kind = "no_branch"

    def __init__(self, step: str, key: str, value: Any, branches: list[str]):
        self.key, self.value, self.branches = key, value, list(branches)
        super().__init__(step, f"{key} is {value!r}, which no branch of {step} names; the branches are {self.branches}")

    def fields(self) -> JSON:
        return {"key": self.key, "value": self.value, "branches": self.branches}


class ScriptFailed(StepError):
    """A script exited non-zero, or wrote something other than one JSON object to stdout."""

    kind = "script_failed"

    def __init__(self, step: str, script: str, exit_code: int, stderr: str, message: str):
        self.script, self.exit_code, self.stderr = script, exit_code, stderr
        super().__init__(step, message)

    def fields(self) -> JSON:
        return {"script": self.script, "exit_code": self.exit_code, "stderr": self.stderr}


class ScriptTimeout(StepError):
    kind = "timeout"

    def __init__(self, step: str, script: str, seconds: float | None):
        self.script, self.seconds = script, seconds
        super().__init__(step, f"the script {script} did not finish within {seconds} seconds")

    def fields(self) -> JSON:
        return {"script": self.script, "seconds": self.seconds}


class RequiresUnmet(StepError):
    """The machine lacks what the procedure's `Requires` names."""

    kind = "requires_unmet"

    def __init__(self, step: str | None, missing: list[str]):
        self.missing = list(missing)
        super().__init__(step, "this machine lacks what the procedure requires: " + "; ".join(missing))

    def fields(self) -> JSON:
        return {"missing": self.missing}


class NoDecisionModel(StepError):
    """A `Decide` step with no model configured. Every decision needs one (spec 2.4)."""

    kind = "no_decision_model"

    def __init__(self, step: str):
        super().__init__(step, f"{step} is a decision and no decision model is configured; a Decide is always answered by a "
                               f"decision model, so configure one: {DECISION_MODEL_HINT}; then `aip resume <run_id>` asks it")


class DecisionModelFailed(StepError):
    """The decision model raised on a `Decide` step: `model` is the resolver's name, `endpoint`
    the URL it spoke to (None for a resolver that is not a service), `cause` the exception."""

    kind = "decision_model_failed"

    def __init__(self, step: str, model: str, cause: BaseException, endpoint: str | None = None):
        self.model, self.endpoint, self.cause = model, endpoint, f"{type(cause).__name__}: {cause}"
        where = f" at {endpoint}" if endpoint else ""
        super().__init__(step, f"the decision model {model}{where} failed on {step}: {self.cause}")

    def fields(self) -> JSON:
        return {"model": self.model, "endpoint": self.endpoint, "cause": self.cause}


class LoopCap(StepError):
    """A loop reached its cap: a `For` (or a fold) given more items than `At_Most`, or an `Until`
    loop that ran `At_Most` passes without its condition holding and says `Else_Fail`."""

    kind = "loop_cap"

    def __init__(self, loop: str, cap: int, count: int, message: str):
        self.loop, self.cap, self.count = loop, cap, count
        super().__init__(loop, message)

    def fields(self) -> JSON:
        return {"loop": self.loop, "cap": self.cap, "count": self.count}


class NotPaused(StepError):
    """An answer arrived for a run that is not waiting for one, or does not fit its pause."""

    kind = "not_paused"


__all__ = ["JSON", "ERROR_KINDS", "VALUE_KIND", "ANSWER_FIELDS", "DECISION_MODEL_HINT", "StepError", "KeysError", "InvalidInput",
           "InvalidOutput", "NoBranch", "ScriptFailed", "ScriptTimeout", "RequiresUnmet", "NoDecisionModel", "DecisionModelFailed",
           "LoopCap", "NotPaused", "is_plain", "normalise", "conforms", "extra_fields", "describe", "branch_key"]
