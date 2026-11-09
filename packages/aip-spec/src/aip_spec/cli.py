"""The `aip-spec` command: the language's own tooling, without the runtime.

    aip-spec compile <path> [--check] [--json]   check a program and report every diagnostic
    aip-spec fmt <path>... [--check]             rewrite procedure files in canonical form
    aip-spec --version                           the language version

A path is a `procedure.aip` or a program directory holding one. `aip compile` and `aip fmt` are
the same commands under the runtime's name. The bundle writer (`compile` producing an `.rl`)
arrives with the next milestone; until then `compile` checks and writes nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from aip_spec import LANGUAGE_VERSION, ParseError, check_path, format_source, has_errors

SOURCE_FILE = "procedure.aip"


def _source_paths(paths: list[Path], prog: str) -> list[Path] | None:
    files = []
    for path in paths:
        if path.is_dir():
            path = path / SOURCE_FILE
        if not path.is_file():
            print(f"{prog}: {path} not found", file=sys.stderr)
            return None
        files.append(path)
    return files


def compile_command(argv: list[str], prog: str = "aip-spec compile") -> int:
    """Exit 0 when the program has no error (warnings and infos are printed and do not fail it),
    1 on any error, including a syntax error, 2 when the path is missing. `--json` prints one
    object: `procedure`, `file`, `ok` and `diagnostics`, each in the shape every compiler
    diagnostic has (`code, severity, message, file, line, column, end_line, end_column, step`)."""
    parser = argparse.ArgumentParser(prog=prog, description="Check a program and report every diagnostic against its source lines.")
    parser.add_argument("path", type=Path, metavar="PATH", help="a program directory, or its procedure.aip")
    parser.add_argument("--check", action="store_true", help="check only; write nothing")
    parser.add_argument("--json", action="store_true", help="print the diagnostics as JSON on stdout")
    args = parser.parse_args(argv)
    files = _source_paths([args.path], prog)
    if files is None:
        return 2
    [file] = files
    program, diagnostics = check_path(file)
    ok = not has_errors(diagnostics)
    if args.json:
        print(json.dumps({"procedure": program.name if program is not None else None, "file": str(file), "ok": ok,
                          "diagnostics": [d.to_dict() for d in diagnostics]}, indent=2))
    else:
        for d in diagnostics:
            print(d, file=sys.stderr)
        counts = {sev: sum(1 for d in diagnostics if d.severity == sev) for sev in ("error", "warning", "info")}
        summary = ", ".join(f"{n} {sev}{'s' if n != 1 else ''}" for sev, n in counts.items() if n)
        if ok:
            steps = sum(1 for _ in program.steps())
            print(f"ok {program.name}: {steps} steps" + (f"; {summary}" if summary else ""))
        else:
            print(f"{file}: {summary}", file=sys.stderr)
    if ok and not args.check and not args.json:
        print(f"{prog}: no bundle written; the bundle writer arrives with the next milestone", file=sys.stderr)
    return 0 if ok else 1


def fmt_command(argv: list[str], prog: str = "aip-spec fmt") -> int:
    """Exit 0 when every file is (now) in canonical form, 1 when `--check` found one that is not
    or a file does not parse (the error names its line and column), 2 when a path is missing."""
    parser = argparse.ArgumentParser(prog=prog, description="Rewrite procedure.aip files in canonical form.")
    parser.add_argument("paths", nargs="+", type=Path, metavar="PATH", help="a procedure.aip, or a program directory")
    parser.add_argument("--check", action="store_true", help="report the files that would change; write nothing")
    args = parser.parse_args(argv)
    files = _source_paths(args.paths, prog)
    if files is None:
        return 2
    changed = failed = 0
    for file in files:
        source = file.read_text(encoding="utf-8")
        try:
            formatted = format_source(source, str(file))
        except ParseError as exc:
            print(exc, file=sys.stderr)
            failed += 1
            continue
        if formatted == source:
            print(f"unchanged {file}")
            continue
        changed += 1
        if args.check:
            print(f"would reformat {file}")
        else:
            file.write_text(formatted, encoding="utf-8")
            print(f"formatted {file}")
    if failed:
        print(f"{prog}: {failed} file(s) did not parse", file=sys.stderr)
        return 1
    return 1 if args.check and changed else 0


COMMANDS = {"compile": compile_command, "fmt": fmt_command}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help"):
        print(f"usage: aip-spec <command> [args]        (AIP language {LANGUAGE_VERSION})\n\ncommands:\n  "
              + "\n  ".join(COMMANDS) + "\n  --version\n\nRunning a procedure is the `aip` package: https://github.com/zach-blumenfeld/aip")
        return 0
    if argv[0] in ("--version", "version"):
        print(LANGUAGE_VERSION)
        return 0
    command, rest = argv[0], argv[1:]
    if command in COMMANDS:
        return COMMANDS[command](rest)
    print(f"aip-spec: unknown command {command!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
