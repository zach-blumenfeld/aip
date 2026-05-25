#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "jsonschema>=4.21",
#     "pyyaml>=6.0",
# ]
# ///
"""Validate a JSON Schema against AIP conventions.

Checks performed:

- Required root-level metadata keywords (non-empty strings): $schema,
  $id, title, description.
- `$id` is a URI (contains a scheme — i.e., a colon). No specific URI
  form is mandated; HTTPS URIs and URN forms are both valid.
- Top-level `aip:` object present with required `aip.version`
  (non-empty string). `aip.tag` is optional but must be a string when
  present.
- `aip.spec` is a required non-empty string (URL). When the consuming
  aip skill's SKILL.md is readable, `aip.spec` must equal the
  validator's expected URL (`AIP_SPEC_URL_PREFIX + metadata.aip.version`
  from that SKILL.md); mismatches are flagged.
- Universal floor from assets/base.schema.json is present:
  - `purpose` (string) declared in properties and listed in `required`.
  - `trigger_when` (array of strings, minItems >= 1) declared in
    properties and listed in `required`.
- Every object subschema (root, $defs, nested properties, items,
  oneOf/anyOf/allOf branches) declares `additionalProperties: false`.
  No escape hatch — `true` or a sub-schema is rejected. Schemas with
  legitimate overflow needs should declare an explicit named property
  for it rather than opening the parent's key set.
- $defs entry names are clearly named.
- The schema is itself a valid JSON Schema per its declared $schema
  dialect.

Soft warnings (don't fail validation, advisory only):

- Property names that collide with JSON Schema annotation keywords
  (`examples`, `enum`, `required`, `format`, `const`, `default`) —
  spec-legal, but IDE linters in VS Code / JetBrains flag them as
  type mismatches against the meta-schema.

Output contract:
- Exit 0 on success (no errors; warnings allowed); 1 on any error.
- stdout: single-line human summary.
- stderr: JSON Lines, one record per line. Each record has fields
  `path`, `kind`, `message`, optional `location`, and `severity`
  ("error" or "warning"; absent = "error").
"""

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import yaml
from jsonschema.validators import validator_for


# JSON Schema annotation keywords whose meta-schema type is non-object.
# Naive IDE linters (VS Code, JetBrains) flag `properties.<name>` against
# these as a type mismatch, even though the schema is spec-legal. Soft
# warning, not an error; pick a synonym to avoid silent author friction.
JSON_SCHEMA_RESERVED_KEYWORDS = frozenset({
    "examples", "enum", "required", "format", "const", "default",
})

# URL template for `aip.spec`. The version segment is read from the
# consuming aip skill's SKILL.md `metadata.aip.version` field.
AIP_SPEC_URL_PREFIX = "https://github.com/zach-blumenfeld/aip/tree/v"

# Regex matching just the frontmatter half of the aip skill's SKILL.md.
_SKILL_MD_FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


@dataclass
class Error:
    path: str
    kind: str
    message: str
    location: str | None = None
    severity: str = "error"


def emit_records(records: list[Error]) -> tuple[int, int]:
    """Emit all records to stderr as JSON Lines.

    Returns (error_count, warning_count). Errors fail validation;
    warnings are advisory and don't change the exit code.
    """
    err_count = 0
    warn_count = 0
    for r in records:
        record = {k: v for k, v in asdict(r).items() if v is not None}
        if record.get("severity") == "error":
            record.pop("severity")  # default; omit to keep output compact
        print(json.dumps(record), file=sys.stderr)
        if r.severity == "warning":
            warn_count += 1
        else:
            err_count += 1
    return err_count, warn_count


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


def expected_aip_spec_url() -> str | None:
    """Return the expected `aip.spec` URL for this validator's AIP version.

    Reads the consuming aip skill's SKILL.md (sibling-of-`scripts/`) and
    builds `AIP_SPEC_URL_PREFIX + metadata.aip.version`. Returns None
    when the SKILL.md can't be read or doesn't carry a version (e.g.,
    validator invoked outside the aip skill folder) — in that case the
    URL-match check downstream gracefully skips.
    """
    skill_md = Path(__file__).resolve().parent.parent / "SKILL.md"
    try:
        content = skill_md.read_text()
    except OSError:
        return None
    match = _SKILL_MD_FRONTMATTER_PATTERN.match(content)
    if not match:
        return None
    try:
        frontmatter = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return None
    if not isinstance(frontmatter, dict):
        return None
    aip = frontmatter.get("metadata", {}).get("aip", {}) if isinstance(frontmatter.get("metadata"), dict) else {}
    if not isinstance(aip, dict):
        return None
    version = aip.get("version")
    if not isinstance(version, str) or not version.strip():
        return None
    return AIP_SPEC_URL_PREFIX + version.strip()


def check_id_form(schema: dict, path: str) -> Iterable[Error]:
    """`$id` must be a URI (contain a scheme — i.e., a colon).

    No specific URI form is mandated; HTTPS URIs in user-controlled
    namespaces and URN forms (e.g., urn:uuid:...) are both valid.
    """
    schema_id = schema.get("$id")
    if not isinstance(schema_id, str):
        return  # already caught by check_required_metadata
    if ":" not in schema_id:
        yield Error(
            path=path,
            kind="invalid_id_form",
            message=(
                f"`$id` must be a URI (contain a scheme); got `{schema_id}`."
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
    # aip.version is required
    if "version" not in aip:
        yield Error(
            path=path,
            kind="missing_aip_field",
            message="missing required `aip.version` (non-empty string)",
            location="$.aip.version",
        )
    elif not isinstance(aip["version"], str) or not aip["version"].strip():
        yield Error(
            path=path,
            kind="invalid_aip_field",
            message="`aip.version` must be a non-empty string",
            location="$.aip.version",
        )
    # aip.tag is optional
    if "tag" in aip and not isinstance(aip["tag"], str):
        yield Error(
            path=path,
            kind="invalid_aip_field",
            message="`aip.tag` must be a string when present",
            location="$.aip.tag",
        )


def check_aip_spec(schema: dict, path: str) -> Iterable[Error]:
    """Verify `aip.spec` is present, is a URI, and matches the expected
    AIP-protocol-version URL when this validator can discover it.
    """
    aip = schema.get("aip")
    if not isinstance(aip, dict):
        return  # already flagged by check_aip_namespace
    spec_url = aip.get("spec")
    if not spec_url:
        yield Error(
            path=path,
            kind="missing_aip_field",
            message=(
                "missing required `aip.spec` "
                "(URL to AIP spec version this schema targets)"
            ),
            location="$.aip.spec",
        )
        return
    if not isinstance(spec_url, str):
        yield Error(
            path=path,
            kind="invalid_aip_field",
            message="`aip.spec` must be a string (URL)",
            location="$.aip.spec",
        )
        return
    if ":" not in spec_url:
        yield Error(
            path=path,
            kind="invalid_aip_field",
            message=(
                f"`aip.spec` must be a URL (contain a scheme); got `{spec_url}`"
            ),
            location="$.aip.spec",
        )
        return
    expected = expected_aip_spec_url()
    if expected is not None and spec_url != expected:
        yield Error(
            path=path,
            kind="aip_spec_mismatch",
            message=(
                f"`aip.spec` (`{spec_url}`) does not match the AIP version "
                f"this validator targets (`{expected}`). Update the schema's "
                f"`aip.spec` to the current URL, or upgrade/downgrade the "
                f"aip skill."
            ),
            location="$.aip.spec",
        )


def check_base_floor(schema: dict, path: str) -> Iterable[Error]:
    """Verify the universal floor from assets/base.schema.json is present.

    Every AIP schema must include `purpose` (string) and `trigger_when`
    (array of strings, minItems >= 1), both listed in the schema's
    `required` array. Derived schemas may extend these (e.g., add
    `maxLength` to `purpose`) but must not relax the floor types.
    """
    properties = schema.get("properties") or {}
    required_list = schema.get("required") or []

    # purpose: required, string
    if "purpose" not in properties:
        yield Error(
            path=path,
            kind="missing_base_property",
            message="missing required property `purpose` (universal floor from base.schema.json)",
            location="$.properties.purpose",
        )
    elif isinstance(properties["purpose"], dict) and properties["purpose"].get("type") != "string":
        yield Error(
            path=path,
            kind="invalid_base_property",
            message="`purpose` must be declared with `type: \"string\"` per the base schema floor",
            location="$.properties.purpose.type",
        )
    if "purpose" not in required_list:
        yield Error(
            path=path,
            kind="missing_base_required",
            message="`purpose` must appear in the schema's `required` array",
            location="$.required",
        )

    # trigger_when: required, array of strings, minItems >= 1
    if "trigger_when" not in properties:
        yield Error(
            path=path,
            kind="missing_base_property",
            message="missing required property `trigger_when` (universal floor from base.schema.json)",
            location="$.properties.trigger_when",
        )
    elif isinstance(properties["trigger_when"], dict):
        tw = properties["trigger_when"]
        if tw.get("type") != "array":
            yield Error(
                path=path,
                kind="invalid_base_property",
                message="`trigger_when` must be declared with `type: \"array\"` per the base schema floor",
                location="$.properties.trigger_when.type",
            )
        items = tw.get("items")
        if not isinstance(items, dict) or items.get("type") != "string":
            yield Error(
                path=path,
                kind="invalid_base_property",
                message="`trigger_when.items` must be `{type: \"string\"}` per the base schema floor",
                location="$.properties.trigger_when.items",
            )
        if tw.get("minItems", 0) < 1:
            yield Error(
                path=path,
                kind="invalid_base_property",
                message="`trigger_when` must declare `minItems >= 1` (at least one trigger required)",
                location="$.properties.trigger_when.minItems",
            )
    if "trigger_when" not in required_list:
        yield Error(
            path=path,
            kind="missing_base_required",
            message="`trigger_when` must appear in the schema's `required` array",
            location="$.required",
        )


def check_json_schema_keyword_collisions(schema: dict, path: str) -> Iterable[Error]:
    """Soft-warn on property names that collide with JSON Schema annotation keywords.

    These don't break the AIP validators or spec-compliant JSON Schema
    validators, but naive IDE linters flag them as type mismatches.
    """
    for prop_name in schema.get("properties", {}):
        if prop_name in JSON_SCHEMA_RESERVED_KEYWORDS:
            yield Error(
                path=path,
                kind="json_schema_keyword_collision",
                message=(
                    f"property `{prop_name}` collides with a JSON Schema "
                    f"reserved annotation keyword. Spec-legal, but naive "
                    f"IDE linters will flag it. Consider a synonym."
                ),
                location=f"$.properties.{prop_name}",
                severity="warning",
            )
    for def_name, def_schema in schema.get("$defs", {}).items():
        if not isinstance(def_schema, dict):
            continue
        for prop_name in def_schema.get("properties", {}):
            if prop_name in JSON_SCHEMA_RESERVED_KEYWORDS:
                yield Error(
                    path=path,
                    kind="json_schema_keyword_collision",
                    message=(
                        f"property `{prop_name}` in $defs.{def_name} "
                        f"collides with a JSON Schema reserved annotation "
                        f"keyword. Spec-legal, but naive IDE linters will "
                        f"flag it. Consider a synonym."
                    ),
                    location=f"$.$defs.{def_name}.properties.{prop_name}",
                    severity="warning",
                )


def _is_object_subschema(sub: dict) -> bool:
    """An object-like subschema is one where additionalProperties is meaningful.

    True when the subschema explicitly declares object-ness via `type: object`
    or implies it by declaring keys via `properties` or `patternProperties`.
    """
    return (
        sub.get("type") == "object"
        or "properties" in sub
        or "patternProperties" in sub
    )


def _walk_object_subschemas(schema: dict, path: str = "$"):
    """Yield (subschema, path) for every object-like subschema in the tree."""
    if not isinstance(schema, dict):
        return

    if _is_object_subschema(schema):
        yield schema, path

    for name, defs_schema in schema.get("$defs", {}).items():
        yield from _walk_object_subschemas(defs_schema, f"{path}.$defs.{name}")

    for name, prop_schema in schema.get("properties", {}).items():
        yield from _walk_object_subschemas(prop_schema, f"{path}.properties.{name}")

    items = schema.get("items")
    if isinstance(items, dict):
        yield from _walk_object_subschemas(items, f"{path}.items")
    elif isinstance(items, list):
        for i, item in enumerate(items):
            yield from _walk_object_subschemas(item, f"{path}.items[{i}]")

    for combinator in ("oneOf", "anyOf", "allOf"):
        for i, sub in enumerate(schema.get(combinator, [])):
            yield from _walk_object_subschemas(sub, f"{path}.{combinator}[{i}]")

    ap = schema.get("additionalProperties")
    if isinstance(ap, dict):
        yield from _walk_object_subschemas(ap, f"{path}.additionalProperties")

    for pattern, pp_schema in schema.get("patternProperties", {}).items():
        yield from _walk_object_subschemas(pp_schema, f"{path}.patternProperties[{pattern}]")


def check_strict_core(schema: dict, path: str) -> Iterable[Error]:
    """Every object subschema must declare `additionalProperties: false`.

    No escape hatch — `true` or a sub-schema is rejected. AIP schemas
    have no intentionally-open objects; overflow needs an explicit
    named property rather than opening the parent's key set.
    """
    for sub, sub_path in _walk_object_subschemas(schema):
        if "additionalProperties" not in sub:
            yield Error(
                path=path,
                kind="missing_additional_properties",
                message=(
                    f"object subschema at `{sub_path}` must declare "
                    f"`additionalProperties: false`."
                ),
                location=f"{sub_path}.additionalProperties",
            )
            continue
        if sub["additionalProperties"] is not False:
            yield Error(
                path=path,
                kind="invalid_additional_properties",
                message=(
                    f"object subschema at `{sub_path}` must declare "
                    f"`additionalProperties: false` — got "
                    f"{sub['additionalProperties']!r}. AIP schemas do not "
                    f"allow intentionally-open objects."
                ),
                location=f"{sub_path}.additionalProperties",
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


def run_all_checks(schema: dict, path_str: str) -> list[Error]:
    """Run every AIP-compliance check against a parsed schema dict.

    Returns the combined error/warning records list. Used by
    validate_schema_file for standalone CLI use, and by scripts/validate.py
    to validate the bundled schema during Skill validation.
    """
    records: list[Error] = []
    records.extend(check_required_metadata(schema, path_str))
    records.extend(check_id_form(schema, path_str))
    records.extend(check_aip_namespace(schema, path_str))
    records.extend(check_aip_spec(schema, path_str))
    records.extend(check_base_floor(schema, path_str))
    records.extend(check_strict_core(schema, path_str))
    records.extend(check_defs_naming(schema, path_str))
    records.extend(check_schema_validity(schema, path_str))
    records.extend(check_json_schema_keyword_collisions(schema, path_str))
    return records


def validate_schema_file(schema_path: Path) -> tuple[int, int, str | None]:
    """Run all checks. Returns (error_count, warning_count, title_if_valid)."""
    path_str = str(schema_path)

    if not schema_path.exists():
        err, warn = emit_records([
            Error(path=path_str, kind="file_not_found", message="schema file does not exist")
        ])
        return err, warn, None

    try:
        schema = json.loads(schema_path.read_text())
    except json.JSONDecodeError as exc:
        err, warn = emit_records([
            Error(
                path=path_str,
                kind="invalid_json",
                message=f"failed to parse JSON: {exc.msg}",
                location=f"line {exc.lineno}, col {exc.colno}",
            )
        ])
        return err, warn, None

    if not isinstance(schema, dict):
        err, warn = emit_records([
            Error(
                path=path_str,
                kind="invalid_root",
                message=f"schema root must be an object, got {type(schema).__name__}",
            )
        ])
        return err, warn, None

    records = run_all_checks(schema, path_str)

    err_count, warn_count = emit_records(records)
    title = schema.get("title") if isinstance(schema.get("title"), str) else None
    return err_count, warn_count, title


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate a JSON Schema against AIP conventions. "
            "See the module docstring for the rule set."
        ),
    )
    parser.add_argument("schema_path", type=Path, help="path to the .schema.json file")
    args = parser.parse_args()

    error_count, warning_count, title = validate_schema_file(args.schema_path)
    warning_suffix = f" ({warning_count} warning(s) — see stderr)" if warning_count else ""

    if error_count == 0:
        title_suffix = f" (title: {title})" if title else ""
        print(f"VALID: {args.schema_path}{title_suffix}{warning_suffix}")
        return 0
    print(f"INVALID: {error_count} error(s){warning_suffix} — see stderr")
    return 1


if __name__ == "__main__":
    sys.exit(main())
