"""Type vocabulary, JSON Schema compilation, and input validation."""

from typing import Any, Dict, List, TypeAlias

from jsonschema import Draft202012Validator

from aip.spec.models import DataType  # the format owns the vocabulary

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
