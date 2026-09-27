"""The `aip` command line entry point.

Implemented: validate, schema, runtime, info, run, resume. Planned: config, publish, list,
remove, get, and the `server` group.
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


def runtime_command(argv: list[str]) -> int:
    from aip.spec import runtime_text

    parser = argparse.ArgumentParser(prog="aip runtime", description="Print the AIP runtime block every authored skill carries at the top of its body.")
    parser.add_argument("--write", type=Path, default=None, help="write to this path instead of stdout")
    args = parser.parse_args(argv)
    text = runtime_text()
    if args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
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


def _read_input(spec: str | None) -> dict | None:
    """`--input path.json`, `--input -` for stdin, or None."""
    if spec is None:
        return None
    text = sys.stdin.read() if spec == "-" else Path(spec).read_text()
    data = json.loads(text)
    if not isinstance(data, dict):
        raise SystemExit("aip: input must be a JSON object")
    return data


def _thresholds(pairs: list[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for pair in pairs:
        name, _, value = pair.partition("=")
        if not name or not value:
            raise SystemExit(f"aip: --threshold expects name=value, got {pair!r}")
        out[name] = float(value)
    return out


def run_command(argv: list[str]) -> int:
    from aip.client.backend import LocalBackend
    from aip.client.runner import Runner

    parser = argparse.ArgumentParser(prog="aip run", description="Run a skill folder's procedure locally, pausing when the client must decide.")
    parser.add_argument("skill_dir", type=Path)
    parser.add_argument("--input", "-i", help="JSON object for the start step; `-` reads stdin")
    parser.add_argument("--interactive", action="store_true", help="prompt on the terminal instead of pausing to a run file")
    parser.add_argument("--run-file", type=Path, default=None, help="where to write the run file on pause")
    parser.add_argument("--threshold", action="append", default=[], metavar="NAME=VALUE", help="override a decision threshold")
    args = parser.parse_args(argv)
    try:
        backend = LocalBackend(args.skill_dir)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    runner = Runner(backend, args.skill_dir, run_file=args.run_file, interactive=args.interactive)
    return runner.start(_read_input(args.input), _thresholds(args.threshold)).code


def resume_command(argv: list[str]) -> int:
    from aip.client.backend import LocalBackend
    from aip.client.runner import RunFile, Runner

    parser = argparse.ArgumentParser(prog="aip resume", description="Continue a paused run.")
    parser.add_argument("run_file", type=Path)
    parser.add_argument("--input", "-i", help="JSON object answering the pause; `-` reads stdin")
    parser.add_argument("--interactive", action="store_true")
    args = parser.parse_args(argv)
    run = RunFile.load(args.run_file)
    backend = LocalBackend(Path(run.skill_dir))
    runner = Runner(backend, Path(run.skill_dir), run_file=args.run_file, interactive=args.interactive)
    return runner.resume(run, _read_input(args.input)).code


COMMANDS = {
    "validate": validate_command,
    "schema": schema_command,
    "runtime": runtime_command,
    "info": info_command,
    "run": run_command,
    "resume": resume_command,
}
PLANNED = ["config", "publish", "list", "remove", "get", "server"]


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
