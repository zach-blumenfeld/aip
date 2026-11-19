#!/usr/bin/env python3
"""Show the change: a unified diff of the folder against what the snapshot kept.

stdin:  {"state": {"path": str, "before": {str: str}}, "assets": {}, "expects": {...}}
stdout: {"diff": str}

`path` is the folder, relative to the run's working directory (AIP_WORKDIR); `before` its text
files as they were, by their path in the folder. The diff covers every file changed, added or
removed, labelled `a/<path>` and `b/<path>`; it is empty when nothing changed.
"""
import difflib
import json
import os
import sys
from pathlib import Path


def main() -> None:
    state = json.load(sys.stdin)["state"]
    folder = (Path(os.environ.get("AIP_WORKDIR") or ".").resolve() / str(state["path"])).resolve()
    before = state.get("before") or {}
    after = {}
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        relative = path.relative_to(folder)
        if any(part.startswith(".") or part == "__pycache__" for part in relative.parts):
            continue
        try:
            after[relative.as_posix()] = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
    chunks = []
    for name in sorted(set(before) | set(after)):
        old, new = before.get(name), after.get(name)
        if old == new:
            continue
        chunks.extend(difflib.unified_diff((old or "").splitlines(keepends=True), (new or "").splitlines(keepends=True),
                                           "/dev/null" if old is None else f"a/{name}", "/dev/null" if new is None else f"b/{name}"))
    text = "".join(line if line.endswith("\n") else line + "\n" for line in chunks)
    json.dump({"diff": text}, sys.stdout)


main()
