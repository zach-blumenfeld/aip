#!/usr/bin/env python3
"""Keep the folder as it is now, to compare the change with, and list the documents.

stdin:  {"state": {"folder": str, "documents": str}, "assets": {}, "expects": {...}}
stdout: {"path": str, "source": str, "before": {str: str}, "files": [str]}

`folder` and `documents` are relative to the run's working directory (AIP_WORKDIR) and must be
under it, where the agent can read and write. `before` holds every text file of the folder by
its path inside the folder (`procedure.aip`, `scripts/escalate.py`); a file that is not UTF-8
text is left out. `files` lists the documents' text files, relative to the working directory.
A folder with no procedure.aip fails the step with the reason on stderr.
"""
import json
import os
import sys
from pathlib import Path

SOURCE = "procedure.aip"
TEXT = {".md", ".txt", ".json", ".yaml", ".yml", ".csv", ".aip", ".py", ".html", ".rst"}


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    sys.exit(1)


def under(workdir: Path, given: str, what: str) -> Path:
    path = (workdir / given).resolve()
    if not path.is_relative_to(workdir):
        fail(f"{what}: {given!r} is outside the working directory {workdir}")
    return path


def main() -> None:
    state = json.load(sys.stdin)["state"]
    workdir = Path(os.environ.get("AIP_WORKDIR") or ".").resolve()
    folder = under(workdir, str(state["folder"]).strip(), "folder")
    if folder.name == SOURCE:
        folder = folder.parent
    if not (folder / SOURCE).is_file():
        fail(f"folder: no {SOURCE} in {folder}; give the procedure's folder")
    before = {}
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        relative = path.relative_to(folder)
        if any(part.startswith(".") or part == "__pycache__" for part in relative.parts):
            continue
        try:
            before[relative.as_posix()] = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
    files = []
    documents = str(state.get("documents") or "").strip()
    if documents:
        root = under(workdir, documents, "documents")
        if not root.exists():
            fail(f"documents: no such folder or file {documents!r} under the working directory {workdir}")
        for path in [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file()):
            if path.suffix.lower() in TEXT:
                files.append(path.relative_to(workdir).as_posix())
    json.dump({"path": folder.relative_to(workdir).as_posix() or ".", "source": before[SOURCE], "before": before, "files": files},
              sys.stdout)


main()
