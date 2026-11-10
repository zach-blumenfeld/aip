#!/usr/bin/env python3
"""List the documents, name the procedure, and open an empty record of the person's answers.

stdin:  {"state": {"documents": str, "out": str}, "assets": {}, "expects": {...}}
stdout: {"files": [str], "name": str, "answers": str}

`documents` is a folder (or one file) relative to the run's working directory (AIP_WORKDIR), or
an empty string for none; `files` lists the text files under it, relative to the working
directory, so the agent reads them with the same paths. `name` is the last part of `out`,
lowercased, with every character a procedure name cannot hold made `_`. A `documents` path that
does not exist, or an `out` with no name in it, fails the step with the reason on stderr.
"""
import json
import os
import re
import sys
from pathlib import Path

TEXT = {".md", ".txt", ".json", ".yaml", ".yml", ".csv", ".aip", ".py", ".html", ".rst"}


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    sys.exit(1)


def main() -> None:
    state = json.load(sys.stdin)["state"]
    workdir = Path(os.environ.get("AIP_WORKDIR") or ".").resolve()
    documents = str(state.get("documents") or "").strip()
    files: list[str] = []
    if documents:
        root = (workdir / documents).resolve()
        if not root.exists():
            fail(f"documents: no such folder or file {documents!r} under the working directory {workdir}")
        found = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file())
        if not root.is_relative_to(workdir):
            fail(f"documents: {documents!r} is outside the working directory {workdir}, where the agent can read")
        for path in found:
            relative = path.relative_to(workdir)
            if path.suffix.lower() in TEXT and not any(part.startswith(".") for part in relative.parts):
                files.append(relative.as_posix())
    out = str(state.get("out") or "").strip().rstrip("/")
    name = re.sub(r"[^a-z0-9_]", "_", Path(out).name.lower()).strip("_")
    if not name:
        fail(f"out: {out!r} names no folder to write the procedure into")
    if not name[0].isalpha():
        name = "p_" + name
    json.dump({"files": files, "name": name, "answers": ""}, sys.stdout)


main()
