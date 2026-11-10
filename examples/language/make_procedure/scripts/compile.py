#!/usr/bin/env python3
"""Compile the program folder the agent wrote, with the compiler of the `aip` that runs this.

stdin:  {"state": {"path": str}, "assets": {}, "expects": {...}}
stdout: {"compiled": bool, "diagnostics": [str], "bundle_id": str}

`path` is the program folder (or its procedure.aip); a relative one is taken from the run's
working directory (AIP_WORKDIR). Each diagnostic is one line, `procedure.aip:LINE:COLUMN:
severity code: message`, errors first. When the folder compiles, procedure.aip is rewritten in
the canonical form (`aip fmt`), which is the form its bundle id should be taken from, and
`bundle_id` is the id it then compiles to. Nothing else in the folder is touched, and no bundle
is written: `aip compile`, `aip run` and `aip publish` do that.
"""
import json
import os
import sys
from pathlib import Path

from aip.compiler import compile_folder, format_source, has_errors

SOURCE = "procedure.aip"
ORDER = {"error": 0, "warning": 1, "info": 2}


def result(compiled: bool, diagnostics: list[str], bundle_id: str = "") -> None:
    json.dump({"compiled": compiled, "diagnostics": diagnostics, "bundle_id": bundle_id}, sys.stdout)


def main() -> None:
    given = str(json.load(sys.stdin)["state"]["path"]).strip()
    path = Path(given).expanduser()
    if not path.is_absolute():
        path = Path(os.environ.get("AIP_WORKDIR") or ".") / path
    file = path / SOURCE if path.is_dir() else path
    if not given or file.name != SOURCE or not file.is_file():
        return result(False, [f"{path}: error missing_file: no {SOURCE} here; `path` is the program folder, "
                              f"the directory that holds {SOURCE}"])

    bundle, diagnostics = compile_folder(file)
    if bundle is not None and not has_errors(diagnostics):
        source = file.read_text(encoding="utf-8")
        formatted = format_source(source, str(file))
        if formatted != source:
            file.write_text(formatted, encoding="utf-8")
            bundle, diagnostics = compile_folder(file)
    lines = []
    for d in sorted(diagnostics, key=lambda d: (ORDER.get(d.severity, 3), d.line, d.column)):
        where = f"{SOURCE}:{d.line}:{d.column}"
        lines.append(f"{where}: {d.severity} {d.code}: {d.message}" + (f" (step {d.step})" if d.step else ""))
    ok = bundle is not None and not has_errors(diagnostics)
    result(ok, lines, bundle.id if ok else "")


main()
