#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "jsonschema>=4.21",
# ]
# ///
"""Validate a JSON Schema against AIP conventions.

Checks performed (see spec.md §AIP schema conventions):

- Required root-level metadata keywords: $schema, $id, title, description.
- $id is a URI (UUID URN form recommended).
- Top-level `aip:` object present (AIP-compliance marker; fields inside
  are optional for v0.1).
- No reserved AIP property names anywhere in the schema's declared shape:
  id, schemaId, key, idx, _source.
- Root follows strict-core / open-extensions pattern
  (additionalProperties: false).
- $defs entry names are clearly named (become node labels in storage).
- The schema is itself a valid JSON Schema per its declared $schema
  dialect.

Output contract (also produced by scripts/validate.py):
- Exit 0 on success; 1 on any failure.
- stdout: single-line human summary.
- stderr: JSON Lines, one error record per line. Each record has fields
  `path`, `kind`, `message`, and optional `location`.
"""

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from jsonschema.validators import validator_for


RESERVED_PROPERTY_NAMES = frozenset({"id", "schemaId", "key", "idx", "_source"})


@dataclass
class Error:
    path: str
    kind: str
    message: str
    location: str | None = None


def emit_errors(errors: list[Error]) -> int:
    for err in errors:
        record = {k: v for k, v in asdict(err).items() if v is not None}
        print(json.dumps(record), file=sys.stderr)
    return len(errors)


def check_required_metadata(schema: dict, path: str) -> Iterable[Error]:
    required = [
        ("$schema", "JSON Schema dialect declaration"),
        ("$id", "global identifier"),
        ("title", "short human-readable display name"),
        ("description", "short human-readable description"),
    ]
    for key, descr in required:
        if key not in schema:
            yield Error(
                path=path,
                kind="missing_required_metadata",
                message=f"missing required keyword `{key}` ({descr}) at schema root",
            )
        elif not isinstance(schema[key], str) or not schema[key].strip():
            yield Error(
                path=path,
                kind="invalid_required_metadata",
                message=f"`{key}` must be a non-empty string",
                location=f"$.{key}",
            )


def check_id_form(schema: dict, path: str) -> Iterable[Error]:
    schema_id = schema.get("$id")
    if not isinstance(schema_id, str):
        return  # already caught by check_required_metadata
    if ":" not in schema_id:
        yield Error(
            path=path,
            kind="invalid_id_form",
            message=(
                f"`$id` must be a URI (contain a colon); got `{schema_id}`. "
                f"Recommended form: `urn:uuid:<uuid>`."
            ),
            location="$.$id",
        )


def check_aip_namespace(schema: dict, path: str) -> Iterable[Error]:
    if "aip" not in schema:
        yield Error(
            path=path,
            kind="missing_aip_namespace",
            message=(
                "missing required top-level `aip` object "
                "(AIP-compliance marker; may be empty for v0.1)"
            ),
        )
        return
    aip = schema["aip"]
    if not isinstance(aip, dict):
        yield Error(
            path=path,
            kind="invalid_aip_namespace",
            message="`aip` must be an object",
            location="$.aip",
        )
        return
    if "version" in aip and not isinstance(aip["version"], str):
        yield Error(
            path=path,
            kind="invalid_aip_field",
            message="`aip.version` must be a string when present",
            location="$.aip.version",
        )
    if "tag" in aip and not isinstance(aip["tag"], str):
        yield Error(
            path=path,
            kind="invalid_aip_field",
            message="`aip.tag` must be a string when present",
            location="$.aip.tag",
        )


def check_reserved_names(schema: dict, path: str) -> Iterable[Error]:
    for prop_name in schema.get("properties", {}):
        if prop_name in RESERVED_PROPERTY_NAMES:
            yield Error(
                path=path,
                kind="reserved_property_name",
                message=(
                    f"property `{prop_name}` is reserved by AIP "
                    f"(injected by the connector at ingest time)"
                ),
                location=f"$.properties.{prop_name}",
            )
    for def_name, def_schema in schema.get("$defs", {}).items():
        if not isinstance(def_schema, dict):
            continue
        for prop_name in def_schema.get("properties", {}):
            if prop_name in RESERVED_PROPERTY_NAMES:
                yield Error(
                    path=path,
                    kind="reserved_property_name",
                    message=(
                        f"property `{prop_name}` in $defs.{def_name} "
                        f"is reserved by AIP"
                    ),
                    location=f"$.$defs.{def_name}.properties.{prop_name}",
                )


def check_strict_core(schema: dict, path: str) -> Iterable[Error]:
    if schema.get("additionalProperties") is not False:
        yield Error(
            path=path,
            kind="not_strict_core",
            message=(
                "root schema must set `additionalProperties: false` "
                "(strict-core / open-extensions pattern; use an "
                "`extensions` property for doc-specific structure)"
            ),
            location="$.additionalProperties",
        )


def check_defs_naming(schema: dict, path: str) -> Iterable[Error]:
    for def_name in schema.get("$defs", {}):
        if (
            not def_name
            or not def_name[0].isalpha()
            or not all(c.isalnum() or c == "_" for c in def_name)
        ):
            yield Error(
                path=path,
                kind="invalid_def_name",
                message=(
                    f"$defs key `{def_name}` should be alphanumeric and start "
                    f"with a letter (becomes node label in storage)"
                ),
                location=f"$.$defs.{def_name}",
            )


def check_schema_validity(schema: dict, path: str) -> Iterable[Error]:
    """Schema must itself be a valid JSON Schema per its declared dialect."""
    try:
        validator_class = validator_for(schema)
    except Exception as exc:
        yield Error(
            path=path,
            kind="invalid_schema_dialect",
            message=f"could not resolve $schema dialect: {exc}",
        )
        return
    try:
        validator_class.check_schema(schema)
    except Exception as exc:
        yield Error(
            path=path,
            kind="invalid_schema",
            message=f"schema is not a valid JSON Schema: {exc}",
        )


def validate_schema_file(schema_path: Path) -> tuple[int, str | None]:
    """Run all checks. Returns (error_count, title_if_valid)."""
    path_str = str(schema_path)

    if not schema_path.exists():
        return emit_errors([
            Error(path=path_str, kind="file_not_found", message="schema file does not exist")
        ]), None

    try:
        schema = json.loads(schema_path.read_text())
    except json.JSONDecodeError as exc:
        return emit_errors([
            Error(
                path=path_str,
                kind="invalid_json",
                message=f"failed to parse JSON: {exc.msg}",
                location=f"line {exc.lineno}, col {exc.colno}",
            )
        ]), None

    if not isinstance(schema, dict):
        return emit_errors([
            Error(
                path=path_str,
                kind="invalid_root",
                message=f"schema root must be an object, got {type(schema).__name__}",
            )
        ]), None

    errors: list[Error] = []
    errors.extend(check_required_metadata(schema, path_str))
    errors.extend(check_id_form(schema, path_str))
    errors.extend(check_aip_namespace(schema, path_str))
    errors.extend(check_reserved_names(schema, path_str))
    errors.extend(check_strict_core(schema, path_str))
    errors.extend(check_defs_naming(schema, path_str))
    errors.extend(check_schema_validity(schema, path_str))

    if errors:
        return emit_errors(errors), None

    title = schema.get("title") if isinstance(schema.get("title"), str) else None
    return 0, title


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate a JSON Schema against AIP conventions. "
            "See spec.md §AIP schema conventions for the rule set."
        ),
    )
    parser.add_argument("schema_path", type=Path, help="path to the .schema.json file")
    args = parser.parse_args()

    error_count, title = validate_schema_file(args.schema_path)

    if error_count == 0:
        suffix = f" (title: {title})" if title else ""
        print(f"VALID: {args.schema_path}{suffix}")
        return 0
    print(f"INVALID: {error_count} error(s) — see stderr")
    return 1


if __name__ == "__main__":
    sys.exit(main())
