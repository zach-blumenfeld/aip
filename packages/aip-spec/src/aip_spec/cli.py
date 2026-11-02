"""The `aip-spec` command line entry point: the format without the runtime.

    aip-spec validate <folder>          validate an AIP skill folder
    aip-spec schema [--write PATH]      the JSON Schema generated from the models
    aip-spec runtime                    the runtime block every skill carries
    aip-spec skill install|list|remove  the authoring skill, into the agents on this machine
    aip-spec example <name> --out DIR   copy a bundled example skill out
    aip-spec --version                  the format version

Running a skill is the `aip` package (`aip run`); this command never executes anything.
The installer (`install.sh`) puts it on PATH, which is what the authoring skill assumes.
"""

import argparse
import json
import sys
from pathlib import Path

from aip_spec.models import FORMAT_VERSION


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
    """Exit 0 when valid (warnings allowed), 1 on any error. One human line on stdout;
    one JSON record per issue on stderr: `path`, `kind`, `message`, optional `location`
    and `severity` (absent means error)."""
    from aip_spec.skill import validate_skill

    parser = argparse.ArgumentParser(prog="aip-spec validate", description="Validate an AIP skill folder.")
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
    from aip_spec.models import json_schema

    parser = argparse.ArgumentParser(prog="aip-spec schema", description="Print the JSON Schema generated from the format models.")
    parser.add_argument("--write", type=Path, default=None, help="write to this path instead of stdout")
    args = parser.parse_args(argv)

    text = json.dumps(json_schema(), indent=2) + "\n"
    if args.write:
        args.write.write_text(text)
        print(f"wrote {args.write}")
    else:
        sys.stdout.write(text)
    return 0


def runtime_command(argv: list[str]) -> int:
    from aip_spec.models import runtime_text

    parser = argparse.ArgumentParser(prog="aip-spec runtime",
                                     description="Print the AIP runtime block every authored skill carries at the top of its body.")
    parser.add_argument("--write", type=Path, default=None, help="write to this path instead of stdout")
    args = parser.parse_args(argv)
    if args.write:
        args.write.write_text(runtime_text())
        print(f"wrote {args.write}")
    else:
        sys.stdout.write(runtime_text())
    return 0


def skill_command(argv: list[str]) -> int:
    from aip_spec import agents
    from aip_spec.resources import SKILL_ENTRIES, SKILL_NAME, skill_dir

    parser = argparse.ArgumentParser(prog="aip-spec skill", description="Install the AIP authoring skill into the agents on this machine.")
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("install", help="into every detected agent, one named agent, or a skills directory")
    p.add_argument("agent", nargs="?", help=f"one of: {', '.join(agents.AGENTS)}")
    p.add_argument("--path", type=Path, default=None, metavar="DIR", help=f"a skills directory; writes DIR/{SKILL_NAME}/")
    sub.add_parser("list", help="supported agents, whether each is detected, and whether the skill is installed")
    p = sub.add_parser("remove", help="from one agent, or from every agent that has it")
    p.add_argument("agent", nargs="?")
    p.add_argument("--path", type=Path, default=None, metavar="DIR")
    args = parser.parse_args(argv)

    if args.action == "list":
        print(agents.table([SKILL_NAME]))
        return 0
    try:
        if args.action == "install":
            for label, folder in agents.install([(skill_dir(), SKILL_ENTRIES)], args.agent, args.path):
                print(f"installed {SKILL_NAME} -> {folder}  ({label})")
            return 0
        removed = agents.remove([SKILL_NAME], args.agent, args.path)
        for folder in removed:
            print(f"removed {folder}")
        if not removed:
            print(f"{SKILL_NAME} is not installed anywhere `aip-spec skill list` looks")
        return 0
    except (KeyError, agents.NoAgentDetected) as exc:
        print(f"aip-spec skill: {exc.args[0]}", file=sys.stderr)
        return 1


def example_command(argv: list[str]) -> int:
    import shutil

    from aip_spec import agents
    from aip_spec.resources import example_dir, example_names

    parser = argparse.ArgumentParser(prog="aip-spec example", description="Copy a bundled example skill into a directory.")
    parser.add_argument("name", nargs="?", help=f"one of: {', '.join(example_names())}; omit to list them")
    parser.add_argument("--out", type=Path, default=None, metavar="DIR", help="write DIR/<name>/ (required with a name)")
    args = parser.parse_args(argv)
    if args.name is None:
        print("\n".join(example_names()))
        return 0
    if args.out is None:
        parser.error("--out DIR is required")
    try:
        source = example_dir(args.name)
    except FileNotFoundError as exc:
        print(f"aip-spec example: {exc}", file=sys.stderr)
        return 1
    target = args.out / args.name
    if target.exists():
        print(f"aip-spec example: {target} already exists", file=sys.stderr)
        return 1
    shutil.copytree(source, target, ignore=agents.IGNORE)
    print(f"wrote {target}")
    return 0


COMMANDS = {
    "validate": validate_command,
    "schema": schema_command,
    "runtime": runtime_command,
    "skill": skill_command,
    "example": example_command,
}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help"):
        print(f"usage: aip-spec <command> [args]        (AIP format {FORMAT_VERSION})\n\ncommands:\n  " + "\n  ".join(COMMANDS)
              + "\n  --version\n\nRunning a skill is the `aip` package: https://github.com/zach-blumenfeld/aip")
        return 0
    if argv[0] in ("--version", "version"):
        print(FORMAT_VERSION)
        return 0
    command, rest = argv[0], argv[1:]
    if command in COMMANDS:
        return COMMANDS[command](rest)
    print(f"aip-spec: unknown command {command!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
