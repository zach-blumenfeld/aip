#!/usr/bin/env python3
"""Compile the program folder the agent wrote, with the compiler of the `aip` that runs this.

stdin:  {"state": {"path": str}, "assets": {}, "expects": {...}}
stdout: {"compiled": bool, "diagnostics": [str], "bundle_id": str, "contents": {str: str}}

`path` is the program folder (or its procedure.aip); a relative one is taken from the run's
working directory (AIP_WORKDIR). Each diagnostic is one line, `procedure.aip:LINE:COLUMN:
severity code: message`, errors first. When the folder compiles, `bundle_id` is the id it
compiles to as it is written. `contents`, when the step produces it, is every text file of the
folder by its path in the folder, so the agent that fixes or reviews it (which has no tools) reads
it there. The script checks and reports and nothing more: the author's
files are left exactly as they are (`aip fmt` is theirs to run), and no bundle is written:
`aip compile`, `aip run` and `aip publish` do that.
"""
import json
import os
import sys
from pathlib import Path

from aip.compiler import compile_folder, has_errors

SOURCE = "procedure.aip"
ORDER = {"error": 0, "warning": 1, "info": 2}


EXPECTS: dict = {}
SKIP = {"__pycache__"}


def contents(folder: Path) -> dict:
    """Every text file of the folder by its path in the folder; hidden ones and caches left out."""
    out = {}
    if folder.is_dir():
        for path in sorted(p for p in folder.rglob("*") if p.is_file()):
            relative = path.relative_to(folder)
            if any(part.startswith(".") or part in SKIP for part in relative.parts):
                continue
            try:
                out[relative.as_posix()] = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
    return out


def result(compiled: bool, diagnostics: list[str], bundle_id: str = "", folder: Path | None = None) -> None:
    out = {"compiled": compiled, "diagnostics": diagnostics, "bundle_id": bundle_id}
    if "contents" in EXPECTS:
        out["contents"] = contents(folder) if folder is not None else {}
    json.dump(out, sys.stdout)


def main() -> None:
    data = json.load(sys.stdin)
    EXPECTS.update(data.get("expects") or {})
    given = str(data["state"]["path"]).strip()
    path = Path(given).expanduser()
    if not path.is_absolute():
        path = Path(os.environ.get("AIP_WORKDIR") or ".") / path
    file = path / SOURCE if path.is_dir() else path
    if not given or file.name != SOURCE or not file.is_file():
        return result(False, [f"{path}: error missing_file: no {SOURCE} here; `path` is the program folder, "
                              f"the directory that holds {SOURCE}"])

    bundle, diagnostics = compile_folder(file)
    lines = []
    for d in sorted(diagnostics, key=lambda d: (ORDER.get(d.severity, 3), d.line, d.column)):
        where = f"{SOURCE}:{d.line}:{d.column}"
        lines.append(f"{where}: {d.severity} {d.code}: {d.message}" + (f" (step {d.step})" if d.step else ""))
    ok = bundle is not None and not has_errors(diagnostics)
    result(ok, lines, bundle.id if ok else "", file.parent)


main()
