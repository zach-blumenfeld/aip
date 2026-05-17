#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "jsonschema>=4.21",
#     "pyyaml>=6.0",
# ]
# ///
"""Validate an AIP Instruction against its declared schema.

Loads the Instruction's SKILL.md, parses YAML frontmatter, locates the
schema in the Instruction's schema/ directory by metadata.aip.schemaId,
extracts the body's fenced YAML block, and validates the body against
the schema. Also checks that required Instruction folder structure is
present (source/README.md).

See spec.md §Instruction format and §SKILL.md format for the contract.

Output contract (also produced by scripts/validate_schema.py):
- Exit 0 on success; 1 on any failure.
- stdout: single-line human summary.
- stderr: JSON Lines, one error record per line. Each record has fields
  `path`, `kind`, `message`, and optional `location`.
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


FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)
FENCE_PATTERN = re.compile(r"^```(?:yaml|yml)\s*\n(.*?)\n```\s*$", re.DOTALL)


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


def parse_skill_md(skill_md_path: Path) -> tuple[dict, str, list[Error]]:
    """Parse SKILL.md. Returns (frontmatter_dict, body_text, errors)."""
    path_str = str(skill_md_path)

    if not skill_md_path.exists():
        return {}, "", [Error(
            path=path_str,
            kind="missing_skill_md",
            message="Instruction folder is missing required SKILL.md",
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
    schema_dir: Path, schema_id: str
) -> tuple[dict | None, Path | None, list[Error]]:
    """Find the schema in schema_dir whose $id matches schema_id."""
    dir_str = str(schema_dir)

    if not schema_dir.exists() or not schema_dir.is_dir():
        return None, None, [Error(
            path=dir_str,
            kind="missing_schema_dir",
            message="Instruction is missing required `schema/` directory",
        )]

    schema_files = sorted(schema_dir.glob("*.schema.json"))
    if not schema_files:
        return None, None, [Error(
            path=dir_str,
            kind="missing_schema_file",
            message="`schema/` directory contains no `*.schema.json` files",
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
                f"no schema in `schema/` has $id matching frontmatter "
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
    frontmatter: dict, skill_md_path: Path, instruction_path: Path
) -> tuple[str | None, list[Error]]:
    """Check required frontmatter fields. Returns (schema_id_or_none, errors)."""
    path_str = str(skill_md_path)
    errors: list[Error] = []

    # Agent Skills spec required fields
    name = frontmatter.get("name")
    # Resolve to absolute path for the name comparison so that `.`, `./`,
    # and trailing-slash forms produce the actual folder name.
    folder_name = instruction_path.resolve().name
    if not name:
        errors.append(Error(
            path=path_str,
            kind="missing_required_frontmatter",
            message="`name` is required in frontmatter (Agent Skills spec)",
            location="$.name",
        ))
    elif name != folder_name:
        errors.append(Error(
            path=path_str,
            kind="name_mismatch",
            message=(
                f"`name` (`{name}`) must match the Instruction's folder name "
                f"(`{folder_name}`)"
            ),
            location="$.name",
        ))

    description = frontmatter.get("description")
    if not description:
        errors.append(Error(
            path=path_str,
            kind="missing_required_frontmatter",
            message="`description` is required in frontmatter (Agent Skills spec)",
            location="$.description",
        ))

    # AIP-specific frontmatter under metadata.aip
    metadata = frontmatter.get("metadata", {})
    if not isinstance(metadata, dict):
        errors.append(Error(
            path=path_str,
            kind="invalid_metadata",
            message="`metadata` must be an object",
            location="$.metadata",
        ))
        return None, errors

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
                "(URL to AIP spec this Instruction conforms to)"
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

    schema_id = aip_meta.get("schemaId")
    if not schema_id:
        errors.append(Error(
            path=path_str,
            kind="missing_aip_schema_id",
            message=(
                "missing required `metadata.aip.schemaId` "
                "(UUID URN matching schema/*.schema.json $id)"
            ),
            location="$.metadata.aip.schemaId",
        ))
        return None, errors
    if not isinstance(schema_id, str):
        errors.append(Error(
            path=path_str,
            kind="invalid_aip_schema_id",
            message="`metadata.aip.schemaId` must be a string (UUID URN)",
            location="$.metadata.aip.schemaId",
        ))
        return None, errors

    return schema_id, errors


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


def validate_instruction(instruction_path: Path) -> tuple[int, dict | None]:
    """Validate an Instruction folder. Returns (error_count, frontmatter_if_valid)."""
    path_str = str(instruction_path)

    if not instruction_path.exists():
        return emit_errors([Error(
            path=path_str,
            kind="file_not_found",
            message="Instruction path does not exist",
        )]), None

    if not instruction_path.is_dir():
        return emit_errors([Error(
            path=path_str,
            kind="not_a_directory",
            message="Instruction path must be a directory (the Instruction folder)",
        )]), None

    errors: list[Error] = []
    skill_md_path = instruction_path / "SKILL.md"

    # 1. Parse SKILL.md
    frontmatter, body, fm_errors = parse_skill_md(skill_md_path)
    errors.extend(fm_errors)
    if fm_errors:
        return emit_errors(errors), None

    # 2. Check required frontmatter fields
    schema_id, field_errors = check_frontmatter_fields(
        frontmatter, skill_md_path, instruction_path
    )
    errors.extend(field_errors)

    # 3. Required Instruction folder structure: source/README.md
    source_readme = instruction_path / "source" / "README.md"
    if not source_readme.exists():
        errors.append(Error(
            path=str(source_readme),
            kind="missing_source_readme",
            message=(
                "Instruction is missing required `source/README.md` "
                "(canonical human-readable source)"
            ),
        ))

    # If schemaId is missing, we can't proceed to body validation
    if schema_id is None:
        return emit_errors(errors), None

    # 4. Find the schema in schema/
    schema, schema_path, schema_errors = find_schema(
        instruction_path / "schema", schema_id
    )
    errors.extend(schema_errors)
    if schema is None:
        return emit_errors(errors), None

    # 5. Extract the body's fenced YAML block
    body_data, body_errors = extract_body_yaml(body, skill_md_path)
    errors.extend(body_errors)
    if body_data is None:
        return emit_errors(errors), None

    # 6. Body must have top-level schemaId mirroring frontmatter
    if isinstance(body_data, dict):
        body_schema_id = body_data.get("schemaId")
        if body_schema_id is None:
            errors.append(Error(
                path=str(skill_md_path),
                kind="missing_body_schema_id",
                message=(
                    "body must have a top-level `schemaId` matching frontmatter "
                    "`metadata.aip.schemaId` (self-description after extraction)"
                ),
                location="body:$.schemaId",
            ))
        elif body_schema_id != schema_id:
            errors.append(Error(
                path=str(skill_md_path),
                kind="body_schema_id_mismatch",
                message=(
                    f"body top-level `schemaId` (`{body_schema_id}`) must equal "
                    f"frontmatter `metadata.aip.schemaId` (`{schema_id}`)"
                ),
                location="body:$.schemaId",
            ))

    # 7. Validate body against the resolved schema
    errors.extend(
        validate_body_against_schema(body_data, schema, skill_md_path, schema_path)
    )

    if errors:
        return emit_errors(errors), None
    return 0, frontmatter


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate an AIP Instruction against its declared schema. "
            "See spec.md §Instruction format and §SKILL.md format."
        ),
    )
    parser.add_argument(
        "instruction_path",
        type=Path,
        help="path to the Instruction folder (containing SKILL.md, schema/, source/)",
    )
    args = parser.parse_args()

    error_count, frontmatter = validate_instruction(args.instruction_path)

    if error_count == 0:
        name = frontmatter.get("name") if frontmatter else None
        suffix = f" (name: {name})" if name else ""
        print(f"VALID: {args.instruction_path}{suffix}")
        return 0
    print(f"INVALID: {error_count} error(s) — see stderr")
    return 1


if __name__ == "__main__":
    sys.exit(main())
