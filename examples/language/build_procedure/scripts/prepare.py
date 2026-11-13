#!/usr/bin/env python3
"""Read the documents, tidy the name the requester gave, and open an empty record of the person's answers.

stdin:  {"state": {"documents": str, "title": str}, "assets": {}, "expects": {...}}
stdout: {"files": [str], "texts": str, "name": str, "answers": str}

`documents` is a folder (or one file) relative to the run's working directory (AIP_WORKDIR), or
an empty string for none; `files` lists the text files under it, relative to the working
directory, and `texts` holds each one's text under a `## <path>` heading, so the agent, which has
no tools, reads them there (each file cut at 40000 characters, all of them at 200000, and the
cut said). `name` is `title` lowercased, with
every character a procedure name cannot hold made `_`, or an empty string when the requester
gave none (the `draft` step then names the procedure from the brief's subject). A `documents`
path that does not exist fails the step with the reason on stderr.
"""
import json
import os
import re
import sys
from pathlib import Path

TEXT = {".md", ".txt", ".json", ".yaml", ".yml", ".csv", ".aip", ".py", ".html", ".rst"}
PER_FILE, ALL = 40_000, 200_000


def read_all(workdir: Path, files: list) -> str:
    parts, total = [], 0
    for name in files:
        try:
            text = (workdir / name).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            parts.append(f"## {name}\n\n(could not be read: {exc})")
            continue
        if len(text) > PER_FILE:
            text = text[:PER_FILE] + f"\n\n(cut at {PER_FILE} characters)"
        if total + len(text) > ALL:
            parts.append(f"## {name}\n\n(left out: the documents passed {ALL} characters)")
            continue
        total += len(text)
        parts.append(f"## {name}\n\n{text.strip()}")
    return "\n\n".join(parts)


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
    name = re.sub(r"[^a-z0-9_]+", "_", str(state.get("title") or "").strip().lower()).strip("_")
    if name and not name[0].isalpha():
        name = "p_" + name
    json.dump({"files": files, "texts": read_all(workdir, files), "name": name, "answers": ""}, sys.stdout)


main()
