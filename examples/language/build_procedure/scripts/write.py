#!/usr/bin/env python3
"""Write the files the agent answered with into the procedure's folder: the agent has no tools,
so its answer carries the folder's files and this script puts them on disk.

stdin:  {"state": {"path" or "out": str, one of "drafted", "rewritten", "repairs": {str: str | null}}, "assets": {}, "expects": {...}}
stdout: the step's Produce keys: `path` (the folder, relative to the working directory) and a
        list key (the files written or removed, by their path in the folder)

The folder (`path`, else `out`) is relative to the run's working directory (AIP_WORKDIR) and must
be under it; it is made if missing. Each file is keyed by its path inside the folder
(`procedure.aip`, `scripts/check.py`, `assets/reply.md`) and its value is the whole text, which
replaces the file; `null` removes it. A key that is absolute, climbs out of the folder (`..`) or
names a hidden file fails the step with the reason on stderr, and nothing is written. Only the
working directory is touched; no command runs, nothing is compiled here.
"""
import json
import os
import sys
from pathlib import Path, PurePosixPath

FILES = ("drafted", "rewritten", "repairs")


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    sys.exit(1)


def main() -> None:
    data = json.load(sys.stdin)
    state, expects = data["state"], data.get("expects") or {}
    workdir = Path(os.environ.get("AIP_WORKDIR") or ".").resolve()
    given = str(state.get("path") or state.get("out") or "").strip()
    if not given:
        fail("no folder: the step reads `path` or `out`, the procedure's folder under the working directory")
    folder = (workdir / given).resolve()
    if not folder.is_relative_to(workdir) or folder == workdir:
        fail(f"{given!r} is not a folder under the working directory {workdir}")
    files = next((state[k] for k in FILES if isinstance(state.get(k), dict)), None)
    if files is None:
        fail(f"no files: the step reads one of {', '.join(FILES)}, an object of path in the folder to its text")
    plan = []
    for key, text in files.items():
        relative = PurePosixPath(str(key).replace("\\", "/"))
        if relative.is_absolute() or not relative.parts or any(p in ("", ".", "..") or p.startswith(".") for p in relative.parts):
            fail(f"{key!r}: a file is named by its path inside the folder, like procedure.aip or scripts/check.py")
        if text is not None and not isinstance(text, str):
            fail(f"{key!r}: a file's value is its whole text, or null to remove it")
        plan.append((relative.as_posix(), folder.joinpath(*relative.parts), text))
    done = []
    for name, target, text in plan:
        if text is None:
            if target.is_file():
                target.unlink()
                done.append(name)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
        done.append(name)
    out = {}
    for key, type_ in expects.items():
        out[key] = folder.relative_to(workdir).as_posix() if key == "path" else done
    json.dump(out, sys.stdout)


main()
