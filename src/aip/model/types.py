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


class InputValidationError(ValueError):
    def __init__(self, step: str, errors: List[str]):
        self.step = step
        self.errors = errors
        super().__init__(f"Input to step {step!r} is invalid: " + "; ".join(errors))


class OutputValidationError(ValueError):
    """A step's result does not match its declared `outputs`: a key missing, mistyped, or undeclared.
    The step failed; nothing is merged into the state."""
    def __init__(self, step: str, errors: List[str]):
        self.step = step
        self.errors = errors
        super().__init__(f"Output of step {step!r} is invalid: " + "; ".join(errors))


def _schema_errors(inputs: Inputs, payload: Any, strict: bool) -> List[str]:
    validator = Draft202012Validator(to_json_schema(inputs, strict))
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
    return [(f"{'.'.join(str(p) for p in e.path)}: " if e.path else "") + e.message for e in errors]


def validate_input(step: str, inputs: Inputs, payload: Any, strict: bool = False) -> None:
    errors = _schema_errors(inputs, payload, strict)
    if errors:
        raise InputValidationError(step, errors)


def validate_output(step: str, outputs: Inputs, result: Any, strict: bool = True) -> None:
    """Check a step's result against its declared outputs. `strict` also rejects keys the step
    did not declare, naming each one; off when `result` is the whole state (an answer merged over it)."""
    if not isinstance(result, dict):
        raise OutputValidationError(step, [f"expected a JSON object, got {type(result).__name__}"])
    errors = _schema_errors(outputs, result, strict=False)
    if strict:
        errors += [f"undeclared output {key!r}" for key in result if key not in outputs]
    if errors:
        raise OutputValidationError(step, errors)


def project(state: JSON, inputs: Inputs) -> JSON:
    """The part of the state a step may see: its declared input keys, nothing else."""
    return {name: state[name] for name in inputs if name in state}
