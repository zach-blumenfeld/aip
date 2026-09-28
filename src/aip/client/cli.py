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


_PLACEHOLDER = {"string": "<string>", "integer": 0, "float": 0.0, "boolean": False, "object": {}, "list[*]": []}


def _example_input(items) -> dict:
    return {item.name: _PLACEHOLDER[item.type.value] for item in items}


def _inputs_table(items) -> str:
    if not items:
        return "  (none)\n"
    width = max(len(i.name) for i in items)
    return "".join(f"  {i.name.ljust(width)}  {i.type.value:8}  {i.description or ''}".rstrip() + "\n" for i in items)


def describe_skill(loaded) -> str:
    """Human-readable summary of a skill: what it does, what to give it, how it flows."""
    fm, spec = loaded.frontmatter, loaded.spec
    start = spec.start
    lines = [f"{fm['name']}  (AIP {fm.get('metadata', {}).get('aip-version', '?')})", "", fm.get("description", ""), ""]
    lines += ["PURPOSE", "  " + " ".join(spec.purpose.split()), ""]
    lines += ["TRIGGER WHEN"] + [f"  - {t}" for t in spec.trigger_when]
    if spec.do_not_use_when:
        lines += ["DO NOT USE WHEN"] + [f"  - {t}" for t in spec.do_not_use_when]
    lines += ["", f"START INPUT  (step `{start.name}`, {start.kind})", _inputs_table(start.inputs).rstrip(), "",
              "  example start.json:", "  " + json.dumps(_example_input(start.inputs)), "",
              f"  run:  aip run {loaded.skill_dir} --input start.json", ""]
    lines += ["STEPS"]
    for step in spec.steps:
        if step.kind == "router":
            branches = ", ".join(f"{v} -> {t}" for v, t in step.branches.items())
            lines.append(f"  {step.name}  [router on `{step.branch_on}`]  {branches}")
        elif step.kind == "end":
            lines.append(f"  {step.name}  [end]")
        else:
            lines.append(f"  {step.name}  [{step.kind}]  -> {step.inputs_to}")
        if getattr(step, "description", None):
            lines.append(f"      {step.description}")
        if step.kind == "decision":
            for name, q in step.questions.items():
                threshold = step.thresholds.get(name)
                suffix = f"  (threshold {threshold})" if threshold is not None else ""
                lines.append(f"      ? {name} [{q.type}]{suffix}: {q.instructions}")
        if step.kind == "execution":
            lines.append(f"      script: {step.script}" + (f"  assets: {', '.join(step.assets)}" if step.assets else ""))
        if step.kind == "client_task":
            lines.append(f"      template: {step.template}" + (f"  assets: {', '.join(step.assets)}" if step.assets else ""))
            for ref in step.references:
                lines.append(f"      reference: {ref.path}  ({ref.description})")
    end = next((s for s in spec.steps if s.kind == "end"), None)
    if end is not None:
        lines += ["", "RESULT  (end state)", _inputs_table(end.inputs).rstrip()]
    if spec.anti_patterns:
        lines += ["", "ANTI-PATTERNS"] + [f"  - {a}" for a in spec.anti_patterns]
    return "\n".join(lines) + "\n"


def info_command(argv: list[str]) -> int:
    from aip.spec import load_skill

    parser = argparse.ArgumentParser(prog="aip info", description="Describe a skill: what it does, the input it expects, and how it flows.")
    parser.add_argument("skill_dir", type=Path)
    parser.add_argument("--json", action="store_true", help="machine-readable description instead of the summary")
    parser.add_argument("--example-input", action="store_true", help="print only an example start input as JSON")
    args = parser.parse_args(argv)
    try:
        loaded = load_skill(args.skill_dir)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    if args.example_input:
        print(json.dumps(_example_input(loaded.spec.start.inputs), indent=2))
        return 0
    if args.json:
        from aip.spec.loader import build_procedure
        print(json.dumps(build_procedure(loaded).describe(), indent=2))
        return 0
    sys.stdout.write(describe_skill(loaded))
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
