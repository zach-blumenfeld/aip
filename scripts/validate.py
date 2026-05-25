#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "jsonschema>=4.21",
#     "pyyaml>=6.0",
# ]
# ///
"""Validate an AIP Skill against its declared schema.

Performs structural and AIP-compliance checks end-to-end:

1. Parses SKILL.md, extracting YAML frontmatter and the body.
2. Verifies required frontmatter fields (`name`, `description`,
   `metadata.aip.spec`, `metadata.aip.schemaId`), their Agent-Skills
   format rules, optional-field constraints (`compatibility`,
   `allowed-tools`), and that `name` matches the parent directory name.
3. Verifies required folder structure: `source/` directory present,
   schema bundled in `source/*.schema.json`.
4. Locates the bundled schema by `$id` matching `metadata.aip.schemaId`.
5. Runs every AIP-compliance check on the bundled schema (delegates to
   `validate_schema.run_all_checks`).
6. Extracts the body's fenced YAML block.
7. Validates the body against the resolved schema.

Output contract (identical to scripts/validate_schema.py):
- Exit 0 on success (no errors; warnings allowed); 1 on any error.
- stdout: single-line human summary.
- stderr: JSON Lines, one record per error or warning. Each record has
  fields `path`, `kind`, `message`, optional `location`, and `severity`
  ("error" or "warning"; absent = "error").
"""

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema.validators import validator_for

# Co-located helper script for AIP-compliance checks on the bundled schema.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate_schema as _vs  # noqa: E402


FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)
FENCE_PATTERN = re.compile(r"^```(?:yaml|yml)\s*\n(.*?)\n```\s*$", re.DOTALL)
# Agent Skills `name` rule: lowercase a-z/0-9, hyphen-separated groups,
# no leading/trailing/consecutive hyphens.
NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


@dataclass
class Error:
    path: str
    kind: str
    message: str
    location: str | None = None
    severity: str = "error"


def emit_errors(errors: list[Error]) -> tuple[int, int]:
    """Emit all records to stderr as JSON Lines.

    Returns (error_count, warning_count). Errors fail validation;
    warnings are advisory and don't change the exit code.
    """
    err_count = 0
    warn_count = 0
    for err in errors:
        record = {k: v for k, v in asdict(err).items() if v is not None}
        if record.get("severity") == "error":
            record.pop("severity")  # default; omit to keep output compact
        print(json.dumps(record), file=sys.stderr)
        if err.severity == "warning":
            warn_count += 1
        else:
            err_count += 1
    return err_count, warn_count


def parse_skill_md(skill_md_path: Path) -> tuple[dict, str, list[Error]]:
    """Parse SKILL.md. Returns (frontmatter_dict, body_text, errors)."""
    path_str = str(skill_md_path)

    if not skill_md_path.exists():
        return {}, "", [Error(
            path=path_str,
            kind="missing_skill_md",
            message="Skill folder is missing required SKILL.md",
        )]

    content = skill_md_path.read_text()
    match = FRONTMATTER_PATTERN.match(content)
    if not match:
        return {}, "", [Error(
            path=path_str,
            kind="missing_frontmatter",
            message="SKILL.md must begin with YAML frontmatter delimited by `---`",
        )]

    frontmatter_text, body = match.group(1), match.group(2)
    try:
        frontmatter = yaml.safe_load(frontmatter_text)
    except yaml.YAMLError as exc:
        return {}, "", [Error(
            path=path_str,
            kind="invalid_frontmatter",
            message=f"failed to parse frontmatter YAML: {exc}",
        )]

    if not isinstance(frontmatter, dict):
        return {}, "", [Error(
            path=path_str,
            kind="invalid_frontmatter",
            message=f"frontmatter must be a mapping, got {type(frontmatter).__name__}",
        )]

    return frontmatter, body, []


def extract_body_yaml(body: str, skill_md_path: Path) -> tuple[Any, list[Error]]:
    """Extract and parse the single fenced YAML block from the body."""
    path_str = str(skill_md_path)
    body = body.strip()
    if not body:
        return None, [Error(
            path=path_str,
            kind="empty_body",
            message="SKILL.md body is empty; expected one fenced YAML code block",
        )]

    match = FENCE_PATTERN.match(body)
    if not match:
        return None, [Error(
            path=path_str,
            kind="invalid_body_format",
            message=(
                "SKILL.md body must be exactly one fenced YAML code block "
                "(language tag `yaml` or `yml`) with no surrounding prose"
            ),
        )]

    yaml_text = match.group(1)
    try:
        body_data = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        return None, [Error(
            path=path_str,
            kind="invalid_body_yaml",
            message=f"failed to parse body YAML: {exc}",
        )]

    return body_data, []


def find_schema(
    source_dir: Path, schema_id: str
) -> tuple[dict | None, Path | None, list[Error]]:
    """Find the bundled schema in source_dir whose $id matches schema_id."""
    dir_str = str(source_dir)

    if not source_dir.exists() or not source_dir.is_dir():
        return None, None, [Error(
            path=dir_str,
            kind="missing_source_dir",
            message=(
                "Skill is missing required `source/` directory "
                "(bundles the schema and canonical human-readable source)"
            ),
        )]

    schema_files = sorted(source_dir.glob("*.schema.json"))
    if not schema_files:
        return None, None, [Error(
            path=dir_str,
            kind="missing_schema_file",
            message=(
                "`source/` directory contains no `*.schema.json` files; "
                "the schema must be bundled with the skill so it travels standalone"
            ),
        )]

    matching: list[tuple[dict, Path]] = []
    for sf in schema_files:
        try:
            schema = json.loads(sf.read_text())
        except json.JSONDecodeError:
            continue  # ignore malformed schema files at match time
        if isinstance(schema, dict) and schema.get("$id") == schema_id:
            matching.append((schema, sf))

    if not matching:
        return None, None, [Error(
            path=dir_str,
            kind="schema_id_mismatch",
            message=(
                f"no schema in `source/` has $id matching frontmatter "
                f"`metadata.aip.schemaId` value `{schema_id}`"
            ),
        )]
    if len(matching) > 1:
        paths = ", ".join(str(p) for _, p in matching)
        return None, None, [Error(
            path=dir_str,
            kind="duplicate_schema_id",
            message=f"multiple schemas have $id `{schema_id}`: {paths}",
        )]

    return matching[0][0], matching[0][1], []


def check_frontmatter_fields(
    frontmatter: dict, skill_md_path: Path, skill_path: Path
) -> tuple[str | None, list[Error]]:
    """Check required frontmatter fields. Returns (schema_id_or_none, errors)."""
    path_str = str(skill_md_path)
    errors: list[Error] = []

    # name: required, format rules, must match folder name
    name = frontmatter.get("name")
    folder_name = skill_path.resolve().name
    if not name:
        errors.append(Error(
            path=path_str,
            kind="missing_required_frontmatter",
            message="`name` is required in frontmatter (Agent Skills spec)",
            location="$.name",
        ))
    elif not isinstance(name, str):
        errors.append(Error(
            path=path_str,
            kind="invalid_name",
            message=f"`name` must be a string; got {type(name).__name__}",
            location="$.name",
        ))
    elif len(name) > 64:
        errors.append(Error(
            path=path_str,
            kind="invalid_name",
            message=f"`name` must be 1–64 characters; got {len(name)}",
            location="$.name",
        ))
    elif not NAME_PATTERN.match(name):
        errors.append(Error(
            path=path_str,
            kind="invalid_name",
            message=(
                "`name` must contain only lowercase a–z, 0–9, and hyphens, "
                "with no leading/trailing and no consecutive hyphens"
            ),
            location="$.name",
        ))
    elif name != folder_name:
        errors.append(Error(
            path=path_str,
            kind="name_mismatch",
            message=(
                f"`name` (`{name}`) must match the Skill's folder name "
                f"(`{folder_name}`)"
            ),
            location="$.name",
        ))

    # description: required, 1–1024 chars, non-whitespace
    description = frontmatter.get("description")
    if description is None:
        errors.append(Error(
            path=path_str,
            kind="missing_required_frontmatter",
            message="`description` is required in frontmatter (Agent Skills spec)",
            location="$.description",
        ))
    elif not isinstance(description, str):
        errors.append(Error(
            path=path_str,
            kind="invalid_description",
            message=f"`description` must be a string; got {type(description).__name__}",
            location="$.description",
        ))
    elif not description.strip():
        errors.append(Error(
            path=path_str,
            kind="invalid_description",
            message="`description` must be a non-empty string",
            location="$.description",
        ))
    elif len(description) > 1024:
        errors.append(Error(
            path=path_str,
            kind="invalid_description",
            message=f"`description` must be 1–1024 characters; got {len(description)}",
            location="$.description",
        ))

    # compatibility: optional, 1–500 chars when present
    compatibility = frontmatter.get("compatibility")
    if compatibility is not None:
        if not isinstance(compatibility, str):
            errors.append(Error(
                path=path_str,
                kind="invalid_compatibility",
                message=(
                    f"`compatibility` must be a string when present; "
                    f"got {type(compatibility).__name__}"
                ),
                location="$.compatibility",
            ))
        elif not (1 <= len(compatibility) <= 500):
            errors.append(Error(
                path=path_str,
                kind="invalid_compatibility",
                message=(
                    f"`compatibility` must be 1–500 characters; got {len(compatibility)}"
                ),
                location="$.compatibility",
            ))

    # allowed-tools: optional, must be a string when present
    allowed_tools = frontmatter.get("allowed-tools")
    if allowed_tools is not None and not isinstance(allowed_tools, str):
        errors.append(Error(
            path=path_str,
            kind="invalid_allowed_tools",
            message=(
                "`allowed-tools` must be a string (space-separated) when present; "
                f"got {type(allowed_tools).__name__}"
            ),
            location="$.allowed-tools",
        ))

    # license: optional, string when present
    license_val = frontmatter.get("license")
    if license_val is not None and not isinstance(license_val, str):
        errors.append(Error(
            path=path_str,
            kind="invalid_license",
            message=(
                f"`license` must be a string when present; "
                f"got {type(license_val).__name__}"
            ),
            location="$.license",
        ))

    # metadata: optional dict; non-aip entries must be strings (Agent Skills
    # spec: string→string mapping). The aip namespace is structured and is
    # validated separately below.
    metadata = frontmatter.get("metadata", {})
    if not isinstance(metadata, dict):
        errors.append(Error(
            path=path_str,
            kind="invalid_metadata",
            message="`metadata` must be an object",
            location="$.metadata",
        ))
        return None, errors

    for k, v in metadata.items():
        if k == "aip":
            continue  # structured; checked below
        if not isinstance(v, str):
            errors.append(Error(
                path=path_str,
                kind="invalid_metadata",
                message=(
                    f"`metadata.{k}` must be a string (Agent Skills spec: "
                    f"string→string mapping); got {type(v).__name__}"
                ),
                location=f"$.metadata.{k}",
            ))

    aip_meta = metadata.get("aip", {})
    if not isinstance(aip_meta, dict):
        errors.append(Error(
            path=path_str,
            kind="invalid_aip_metadata",
            message="`metadata.aip` must be an object",
            location="$.metadata.aip",
        ))
        return None, errors

    spec_url = aip_meta.get("spec")
    if not spec_url:
        errors.append(Error(
            path=path_str,
            kind="missing_aip_spec",
            message=(
                "missing required `metadata.aip.spec` "
                "(URL to AIP spec this Skill conforms to)"
            ),
            location="$.metadata.aip.spec",
        ))
    elif not isinstance(spec_url, str):
        errors.append(Error(
            path=path_str,
            kind="invalid_aip_spec",
            message="`metadata.aip.spec` must be a string (URL)",
            location="$.metadata.aip.spec",
        ))
    elif ":" not in spec_url:
        errors.append(Error(
            path=path_str,
            kind="invalid_aip_spec",
            message=(
                f"`metadata.aip.spec` must be a URL (contain a scheme); "
                f"got `{spec_url}`"
            ),
            location="$.metadata.aip.spec",
        ))
    else:
        expected = _vs.expected_aip_spec_url()
        if expected is not None and spec_url != expected:
            errors.append(Error(
                path=path_str,
                kind="aip_spec_mismatch",
                message=(
                    f"`metadata.aip.spec` (`{spec_url}`) does not match the "
                    f"AIP version this validator targets (`{expected}`). "
                    f"Update the skill's `metadata.aip.spec` to the current "
                    f"URL, or upgrade/downgrade the aip skill."
                ),
                location="$.metadata.aip.spec",
            ))

    schema_id = aip_meta.get("schemaId")
    if not schema_id:
        errors.append(Error(
            path=path_str,
            kind="missing_aip_schema_id",
            message=(
                "missing required `metadata.aip.schemaId` "
                "(URI matching the $id of the bundled schema in source/)"
            ),
            location="$.metadata.aip.schemaId",
        ))
        return None, errors
    if not isinstance(schema_id, str):
        errors.append(Error(
            path=path_str,
            kind="invalid_aip_schema_id",
            message="`metadata.aip.schemaId` must be a string (URI)",
            location="$.metadata.aip.schemaId",
        ))
        return None, errors

    return schema_id, errors


def check_bundled_schema(schema: dict, schema_path: Path) -> list[Error]:
    """Run AIP-compliance checks on the bundled schema.

    Delegates to validate_schema.run_all_checks and converts its Error
    records to this script's Error type so the output stream is unified.
    """
    records = _vs.run_all_checks(schema, str(schema_path))
    return [
        Error(
            path=r.path,
            kind=r.kind,
            message=r.message,
            location=r.location,
            severity=r.severity,
        )
        for r in records
    ]


def validate_body_against_schema(
    body_data: Any, schema: dict, skill_md_path: Path, schema_path: Path
) -> list[Error]:
    """Run jsonschema validation; convert errors to our Error format."""
    errors: list[Error] = []
    try:
        validator_class = validator_for(schema)
        validator = validator_class(schema)
    except Exception as exc:
        return [Error(
            path=str(schema_path),
            kind="schema_load_error",
            message=f"could not initialize validator from schema: {exc}",
        )]

    for verror in validator.iter_errors(body_data):
        if verror.absolute_path:
            json_path = "body:$." + ".".join(str(p) for p in verror.absolute_path)
        else:
            json_path = "body:$"
        errors.append(Error(
            path=str(skill_md_path),
            kind="schema_violation",
            message=verror.message,
            location=json_path,
        ))
    return errors


def _bail(errors: list[Error]) -> tuple[int, int, dict | None]:
    """Emit accumulated errors and bail with a no-frontmatter return."""
    err, warn = emit_errors(errors)
    return err, warn, None


def validate_skill(skill_path: Path) -> tuple[int, int, dict | None]:
    """Validate a Skill folder. Returns (error_count, warning_count, frontmatter_if_valid)."""
    path_str = str(skill_path)

    if not skill_path.exists():
        return _bail([Error(
            path=path_str,
            kind="file_not_found",
            message="Skill path does not exist",
        )])

    if not skill_path.is_dir():
        return _bail([Error(
            path=path_str,
            kind="not_a_directory",
            message="Skill path must be a directory (the Skill folder)",
        )])

    errors: list[Error] = []
    skill_md_path = skill_path / "SKILL.md"

    # 1. Parse SKILL.md
    frontmatter, body, fm_errors = parse_skill_md(skill_md_path)
    errors.extend(fm_errors)
    if fm_errors:
        return _bail(errors)

    # 2. Check required frontmatter fields
    schema_id, field_errors = check_frontmatter_fields(
        frontmatter, skill_md_path, skill_path
    )
    errors.extend(field_errors)

    # If schemaId is missing, we can't proceed to schema/body validation
    if schema_id is None:
        return _bail(errors)

    # 3. Find the bundled schema in source/
    schema, schema_path, schema_errors = find_schema(
        skill_path / "source", schema_id
    )
    errors.extend(schema_errors)
    if schema is None:
        return _bail(errors)

    # 4. Run AIP-compliance checks on the bundled schema
    errors.extend(check_bundled_schema(schema, schema_path))

    # 5. Extract the body's fenced YAML block
    body_data, body_errors = extract_body_yaml(body, skill_md_path)
    errors.extend(body_errors)
    if body_data is None:
        return _bail(errors)

    # 6. Validate body against the resolved schema
    errors.extend(
        validate_body_against_schema(body_data, schema, skill_md_path, schema_path)
    )

    err_count, warn_count = emit_errors(errors)
    return err_count, warn_count, frontmatter if err_count == 0 else None


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate an AIP Skill against its declared schema. "
            "Includes AIP-compliance checks on the bundled schema "
            "(equivalent to running validate_schema.py separately)."
        ),
    )
    parser.add_argument(
        "skill_path",
        type=Path,
        help="path to the Skill folder (containing SKILL.md, source/)",
    )
    args = parser.parse_args()

    error_count, warning_count, frontmatter = validate_skill(args.skill_path)
    warning_suffix = f" ({warning_count} warning(s) — see stderr)" if warning_count else ""

    if error_count == 0:
        name = frontmatter.get("name") if frontmatter else None
        suffix = f" (name: {name})" if name else ""
        print(f"VALID: {args.skill_path}{suffix}{warning_suffix}")
        return 0
    print(f"INVALID: {error_count} error(s){warning_suffix} — see stderr")
    return 1


if __name__ == "__main__":
    sys.exit(main())
