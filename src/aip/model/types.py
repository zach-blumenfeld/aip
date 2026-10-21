"""Type vocabulary, JSON Schema compilation, and input validation."""

from typing import Any, Dict, List, TypeAlias

from jsonschema import Draft202012Validator

from aip_spec.models import DataType  # the format owns the vocabulary

JSON: TypeAlias = Dict[str, Any]


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


EXAMPLE_VALUES = {"string": "<string>", "integer": 0, "float": 0.0, "boolean": False, "object": {}, "list[*]": []}


def example_input(inputs: Dict[str, str]) -> JSON:
    """A placeholder start input for a described inputs map ({name: type name}); accepted as-is by the step."""
    return {name: EXAMPLE_VALUES[dtype] for name, dtype in inputs.items()}


class StepError(Exception):
    """A step failed. `kind` names the failure in the client's error object (`docs/cli-json.md`);
    `fields()` is the kind's detail: key lists, or the script's exit code and stderr."""
    kind: str = "step_failed"

    def __init__(self, step: str | None, message: str):
        self.step = step
        super().__init__(message)

    def fields(self) -> JSON:
        return {}


class _KeysError(StepError, ValueError):
    """A state or a result that does not match the declared keys. `missing` names absent keys,
    `invalid` keys that are mistyped, undeclared, or hold a value with no branch."""
    what = ""

    def __init__(self, step: str, errors: List[str], missing: List[str] | None = None,
                 invalid: List[str] | None = None):
        self.errors = errors
        self.missing = list(missing or [])
        self.invalid = list(invalid or [])
        super().__init__(step, f"{self.what} step {step!r} is invalid: " + "; ".join(errors))

    def fields(self) -> JSON:
        return {"missing": self.missing, "invalid": self.invalid}


class InputValidationError(_KeysError):
    kind, what = "invalid_input", "Input to"


class OutputValidationError(_KeysError):
    """A step's result does not match its declared `outputs`: a key missing, mistyped, or undeclared.
    The step failed; nothing is merged into the state. `script` is set when a script returned it."""
    kind, what = "invalid_output", "Output of"
    script: str | None = None

    def fields(self) -> JSON:
        return {**({"script": self.script} if self.script else {}), **super().fields()}


class ScriptFailed(StepError, RuntimeError):
    """A script exited non-zero, or wrote something other than one JSON object to stdout."""
    kind = "script_failed"

    def __init__(self, step: str, script: str, exit_code: int, stderr: str, message: str):
        self.script, self.exit_code, self.stderr = script, exit_code, stderr
        super().__init__(step, message)

    def fields(self) -> JSON:
        return {"script": self.script, "exit_code": self.exit_code, "stderr": self.stderr}


class ScriptTimeout(StepError, RuntimeError):
    kind = "timeout"

    def __init__(self, step: str, script: str, seconds: float | None):
        self.script, self.seconds = script, seconds
        super().__init__(step, f"Script {script} did not finish within {seconds} seconds")

    def fields(self) -> JSON:
        return {"script": self.script, "seconds": self.seconds}


def _schema_errors(inputs: Inputs, payload: Any, strict: bool) -> tuple[List[str], List[str], List[str]]:
    """Messages, missing keys, invalid keys."""
    validator = Draft202012Validator(to_json_schema(inputs, strict))
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
    messages = [(f"{'.'.join(str(p) for p in e.path)}: " if e.path else "") + e.message for e in errors]
    missing: List[str] = []
    invalid: List[str] = []
    for e in errors:
        if e.validator == "required" and isinstance(e.instance, dict):
            missing += [k for k in e.validator_value if k not in e.instance and k not in missing]
        elif e.path and str(e.path[0]) not in invalid:
            invalid.append(str(e.path[0]))
    return messages, missing, invalid


def validate_input(step: str, inputs: Inputs, payload: Any, strict: bool = False) -> None:
    errors, missing, invalid = _schema_errors(inputs, payload, strict)
    if errors:
        raise InputValidationError(step, errors, missing, invalid)


def validate_output(step: str, outputs: Inputs, result: Any, strict: bool = True) -> None:
    """Check a step's result against its declared outputs. `strict` also rejects keys the step
    did not declare, naming each one; off when `result` is the whole state (an answer merged over it)."""
    if not isinstance(result, dict):
        raise OutputValidationError(step, [f"expected a JSON object, got {type(result).__name__}"])
    errors, missing, invalid = _schema_errors(outputs, result, strict=False)
    if strict:
        undeclared = [key for key in result if key not in outputs]
        errors += [f"undeclared output {key!r}" for key in undeclared]
        invalid += undeclared
    if errors:
        raise OutputValidationError(step, errors, missing, invalid)


def project(state: JSON, inputs: Inputs) -> JSON:
    """The part of the state a step may see: its declared input keys, nothing else."""
    return {name: state[name] for name in inputs if name in state}
