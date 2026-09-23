"""The `aip` command line entry point.

Implemented: validate, schema, info. Planned: config, publish, list, remove, get, run,
resume, and the `server` group.
"""

import argparse
import json
import sys
from pathlib import Path


def _emit(issues) -> tuple[int, int]:
    errors = warnings = 0
    for issue in issues:
        print(json.dumps(issue.to_record()), file=sys.stderr)
        if issue.severity == "warning":
            warnings += 1
        else:
            errors += 1
    return errors, warnings


def validate_command(argv: list[str]) -> int:
    from aip.spec import validate_skill

    parser = argparse.ArgumentParser(prog="aip validate", description="Validate an AIP skill folder.")
    parser.add_argument("skill_dir", type=Path, help="path to the skill folder (containing SKILL.md)")
    args = parser.parse_args(argv)

    loaded, issues = validate_skill(args.skill_dir)
    errors, warnings = _emit(issues)
    suffix = f" ({warnings} warning(s) — see stderr)" if warnings else ""
    if errors == 0 and loaded is not None:
        print(f"VALID: {args.skill_dir} (name: {loaded.frontmatter.get('name')}){suffix}")
        return 0
    print(f"INVALID: {errors} error(s){suffix} — see stderr")
    return 1


def schema_command(argv: list[str]) -> int:
    from aip.spec import json_schema

    parser = argparse.ArgumentParser(prog="aip schema", description="Print the JSON Schema generated from the format models.")
    parser.add_argument("--write", type=Path, default=None, help="write to this path instead of stdout")
    args = parser.parse_args(argv)

    text = json.dumps(json_schema(), indent=2) + "\n"
    if args.write:
        args.write.write_text(text)
        print(f"wrote {args.write}")
    else:
        sys.stdout.write(text)
    return 0


def info_command(argv: list[str]) -> int:
    from aip.spec.loader import load_procedure

    parser = argparse.ArgumentParser(prog="aip info", description="Show a skill's meta, start and end shapes, and steps.")
    parser.add_argument("skill_dir", type=Path)
    args = parser.parse_args(argv)
    try:
        procedure = load_procedure(args.skill_dir)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(json.dumps(procedure.describe(), indent=2))
    return 0


COMMANDS = {
    "validate": validate_command,
    "schema": schema_command,
    "info": info_command,
}
PLANNED = ["config", "publish", "list", "remove", "get", "run", "resume", "server"]


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: aip <command> [args]\n\ncommands:\n  " + "\n  ".join(COMMANDS)
              + "\n\nplanned:\n  " + "\n  ".join(PLANNED))
        return 0
    command, rest = argv[0], argv[1:]
    if command in COMMANDS:
        return COMMANDS[command](rest)
    if command in PLANNED:
        print(f"aip {command}: not implemented yet", file=sys.stderr)
        return 2
    print(f"aip: unknown command {command!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
