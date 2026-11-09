"""The `aip-spec` command: the language's own tooling, without the runtime.

    aip-spec compile <path> [-o FILE] [--check] [--json]   compile a program to a bundle, or just check it
    aip-spec export <bundle.rl> --out DIR [--force]        write the program directory back from a bundle
    aip-spec fmt <path>... [--check]                       rewrite procedure files in canonical form
    aip-spec --version                                     the language version

A path is a `procedure.aip` or a program directory holding one. `aip compile`, `aip export` and
`aip fmt` are the same commands under the runtime's name. Writing or reading a bundle needs
Relate installed (`aip_spec.relate`); `--check`, `--json` without a bundle, and `fmt` do not.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from aip_spec import ParseError, format_source, has_errors
from aip_spec.bundle import BUNDLE_SUFFIX, BundleError, compile_folder, export_bundle, read_bundle, write_bundle
from aip_spec.language import LANGUAGE_VERSION

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
    1 on any error, including a syntax error, 2 when the path is missing, 3 when the bundle could
    not be written (Relate missing). Without `--check` the bundle is written to `-o`, or to
    `<procedure name>.rl` in the current directory. `--json` prints one object: `procedure`,
    `file`, `ok`, `bundle_id`, `language_version`, `compiler_version`, `output`, `diagnostics`
    (each in the shape every compiler diagnostic has: `code, severity, message, file, line,
    column, end_line, end_column, step`) and, when `ok`, `graph`, the bundle's nodes and edges
    with their source spans and without the file contents (`docs/language/bundle.md`)."""
    parser = argparse.ArgumentParser(prog=prog, description="Compile a program to a bundle, reporting every diagnostic against its source lines.")
    parser.add_argument("path", type=Path, metavar="PATH", help="a program directory, or its procedure.aip")
    parser.add_argument("-o", "--output", type=Path, metavar="FILE", help=f"where to write the bundle (default: <name>{BUNDLE_SUFFIX} here)")
    parser.add_argument("--check", action="store_true", help="check only; write nothing")
    parser.add_argument("--json", action="store_true", help="print the report as JSON on stdout")
    args = parser.parse_args(argv)
    files = _source_paths([args.path], prog)
    if files is None:
        return 2
    [file] = files
    bundle, diagnostics = compile_folder(file)
    ok = not has_errors(diagnostics)
    output = None
    code = 0 if ok else 1
    written_error = None
    if ok and not args.check:
        output = args.output if args.output is not None else Path.cwd() / (bundle.name + BUNDLE_SUFFIX)
        try:
            write_bundle(bundle, output)
        except Exception as exc:
            from aip_spec.relate import RelateMissing
            written_error = str(exc) if isinstance(exc, RelateMissing) else f"could not write {output}: {exc}"
            output = None
            code = 3
    if args.json:
        report = {"procedure": bundle.name if bundle is not None else None, "file": str(file), "ok": ok,
                  "bundle_id": bundle.id if bundle is not None else None, "language_version": LANGUAGE_VERSION,
                  "compiler_version": bundle.compiler_version if bundle is not None else None,
                  "output": str(output) if output is not None else None,
                  "diagnostics": [d.to_dict() for d in diagnostics],
                  "graph": bundle.graph.to_dict(content=False) if bundle is not None else None}
        print(json.dumps(report, indent=2))
        if written_error:
            print(f"{prog}: {written_error}", file=sys.stderr)
        return code
    for d in diagnostics:
        print(d, file=sys.stderr)
    counts = {sev: sum(1 for d in diagnostics if d.severity == sev) for sev in ("error", "warning", "info")}
    summary = ", ".join(f"{n} {sev}{'s' if n != 1 else ''}" for sev, n in counts.items() if n)
    if not ok:
        print(f"{file}: {summary}", file=sys.stderr)
        return 1
    steps = len(bundle.graph.with_label("Step"))
    print(f"ok {bundle.name}: {steps} steps, {len(bundle.files)} files, bundle {bundle.id[:12]}" + (f"; {summary}" if summary else ""))
    if written_error:
        print(f"{prog}: {written_error}", file=sys.stderr)
    elif output is not None:
        print(f"wrote {output}")
    return code


def export_command(argv: list[str], prog: str = "aip-spec export") -> int:
    """Exit 0 after writing the program directory, 1 when the bundle cannot be opened, is not a
    bundle, or does not verify (`bundle_tampered`), or the target is not empty; 2 when the file
    is missing; 3 when Relate is not installed."""
    parser = argparse.ArgumentParser(prog=prog, description="Write a bundle's program directory back, byte for byte.")
    parser.add_argument("bundle", type=Path, metavar="BUNDLE", help=f"a compiled {BUNDLE_SUFFIX} file")
    parser.add_argument("--out", type=Path, required=True, metavar="DIR", help="the directory to write; must not exist or be empty")
    parser.add_argument("--force", action="store_true", help="write into a directory that is not empty")
    args = parser.parse_args(argv)
    if not args.bundle.exists():
        print(f"{prog}: {args.bundle} not found", file=sys.stderr)
        return 2
    from aip_spec.relate import RelateMissing
    try:
        bundle = read_bundle(args.bundle)
        export_bundle(bundle, args.out, force=args.force)
    except RelateMissing as exc:
        print(f"{prog}: {exc}", file=sys.stderr)
        return 3
    except BundleError as exc:
        print(f"{prog}: {exc}", file=sys.stderr)
        return 1
    print(f"exported {bundle.name} (bundle {bundle.id[:12]}) to {args.out}: {SOURCE_FILE} and {len(bundle.files)} files")
    return 0


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


COMMANDS = {"compile": compile_command, "export": export_command, "fmt": fmt_command}


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
