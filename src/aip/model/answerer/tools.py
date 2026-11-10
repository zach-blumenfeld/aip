"""The tools runah's model works with, executed here and confined to the run's working directory.

`read_file`, `list_files` and `search` read; `write_file` writes; `compile` runs the compiler on a
program folder (`aip compile --check --json`, in process). Every path is relative to the working
directory and must stay inside it once resolved (`..` and symbolic links included). The
procedure's own files, its assets and references, are readable as `bundle:<path>` and are never
written. A tool that cannot do what it was asked answers with `error: ...`, which goes back to
the model like any result: the model reads it and tries something else.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

JSON = dict[str, Any]

BUNDLE_PREFIX = "bundle:"
MAX_READ = 60_000            # characters of a file one read_file returns
MAX_LIST = 400               # entries one list_files returns
MAX_HITS = 200               # lines one search returns
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", ".aip-e2e"}

DEFINITIONS: list[JSON] = [
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read a text file. Paths are relative to the run's working directory; `bundle:<path>` reads the "
                       "procedure's own files (its assets and references). Long files are cut; give `offset` (a line "
                       "number, from 1) to read further.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "offset": {"type": "integer", "description": "the first line to read, from 1"}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "list_files",
        "description": "List the files under a directory, recursively, with their sizes. Default: the working directory. "
                       "`bundle:` lists the procedure's own files.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}},
    {"type": "function", "function": {
        "name": "search",
        "description": "Search file contents under a directory for a regular expression (case-insensitive); answers "
                       "`path:line: text` per match.",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string"}, "path": {"type": "string", "description": "a directory or a file; default ."}},
            "required": ["pattern"]}}},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Write a text file, replacing it if it exists; directories are made as needed. Only under the "
                       "working directory.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                       "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "compile",
        "description": "Compile an AIP program folder (the directory holding procedure.aip) and answer whether it compiles, "
                       "its bundle id, and every diagnostic with its line and column. Writes nothing.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
]

NAMES = [d["function"]["name"] for d in DEFINITIONS]


class ToolError(Exception):
    """What a tool answers instead of a result."""


class Tools:
    """The tools over one working directory and, read-only, the procedure's unpacked files."""

    def __init__(self, workdir: Path, bundle_root: Path | None = None):
        self.workdir = Path(workdir).resolve()
        self.bundle_root = Path(bundle_root).resolve() if bundle_root is not None else None
        self.handlers: dict[str, Callable[..., str]] = {"read_file": self.read_file, "list_files": self.list_files,
                                                        "search": self.search, "write_file": self.write_file,
                                                        "compile": self.compile}

    def call(self, name: str, arguments: str | JSON | None) -> str:
        """Run one tool call as the model sent it; whatever goes wrong is the result's text."""
        handler = self.handlers.get(name)
        if handler is None:
            return f"error: there is no tool {name!r}; the tools are {', '.join(NAMES)}"
        try:
            args = json.loads(arguments) if isinstance(arguments, str) and arguments.strip() else (arguments or {})
            if not isinstance(args, dict):
                raise ToolError("the arguments are a JSON object")
            return handler(**args)
        except ToolError as exc:
            return f"error: {exc}"
        except json.JSONDecodeError as exc:
            return f"error: the arguments are not JSON ({exc})"
        except TypeError as exc:
            return f"error: {exc}"
        except OSError as exc:
            return f"error: {exc.strerror or exc}"

    # ------------------------------------------------------------ paths

    def _resolve(self, path: str | None, *, write: bool = False) -> tuple[Path, Path]:
        """The file a path names and the root it must stay under."""
        text = (path or ".").strip() or "."
        root = self.workdir
        if text.startswith(BUNDLE_PREFIX):
            if write:
                raise ToolError("the procedure's own files are read-only; write under the working directory")
            if self.bundle_root is None:
                raise ToolError("this run has no procedure files to read")
            root, text = self.bundle_root, text[len(BUNDLE_PREFIX):].lstrip("/") or "."
        candidate = Path(text).expanduser()
        if candidate.is_absolute():
            target = candidate.resolve()
        else:
            target = (root / candidate).resolve()
        if not target.is_relative_to(root):
            raise ToolError(f"{path} is outside the working directory ({self.workdir}); every path stays under it")
        return target, root

    def _show(self, target: Path, root: Path) -> str:
        relative = target.relative_to(root).as_posix()
        return (BUNDLE_PREFIX + relative) if root == self.bundle_root else relative

    # ------------------------------------------------------------ the tools

    def read_file(self, path: str, offset: int | None = None) -> str:
        target, _ = self._resolve(path)
        if not target.is_file():
            raise ToolError(f"no file {path}")
        text = target.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines(keepends=True)
        start = max(int(offset or 1), 1) - 1
        out, size = [], 0
        for line in lines[start:]:
            if size + len(line) > MAX_READ and out:
                out.append(f"\n[cut at line {start + len(out)} of {len(lines)}; read on with offset {start + len(out) + 1}]\n")
                break
            out.append(line)
            size += len(line)
        return "".join(out) if out else "(empty)"

    def list_files(self, path: str | None = None) -> str:
        target, root = self._resolve(path)
        if target.is_file():
            return f"{self._show(target, root)}  {target.stat().st_size}"
        if not target.is_dir():
            raise ToolError(f"no directory {path}")
        rows = []
        for item in sorted(target.rglob("*")):
            if any(part in SKIP_DIRS for part in item.relative_to(target).parts):
                continue
            if item.is_file():
                rows.append(f"{self._show(item, root)}  {item.stat().st_size}")
                if len(rows) >= MAX_LIST:
                    rows.append(f"[stopped at {MAX_LIST} files]")
                    break
        return "\n".join(rows) if rows else "(no files)"

    def search(self, pattern: str, path: str | None = None) -> str:
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            raise ToolError(f"not a regular expression: {exc}") from None
        target, root = self._resolve(path)
        files = [target] if target.is_file() else sorted(p for p in target.rglob("*") if p.is_file()
                                                           and not any(part in SKIP_DIRS for part in p.relative_to(target).parts))
        hits = []
        for file in files:
            try:
                text = file.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for number, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    hits.append(f"{self._show(file, root)}:{number}: {line.strip()[:300]}")
                    if len(hits) >= MAX_HITS:
                        return "\n".join(hits + [f"[stopped at {MAX_HITS} matches]"])
        return "\n".join(hits) if hits else "(no matches)"

    def write_file(self, path: str, content: str) -> str:
        target, root = self._resolve(path, write=True)
        if target.is_dir():
            raise ToolError(f"{path} is a directory")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"wrote {self._show(target, root)} ({len(content.encode('utf-8'))} bytes)"

    def compile(self, path: str) -> str:
        from aip.compiler import compile_folder, has_errors
        from aip.compiler.bundle import SOURCE_FILE

        target, root = self._resolve(path)
        folder = target.parent if target.name == SOURCE_FILE else target
        if not (folder / SOURCE_FILE).is_file():
            raise ToolError(f"{path} holds no {SOURCE_FILE}; give the program folder")
        bundle, diagnostics = compile_folder(folder)
        ok = bundle is not None and not has_errors(diagnostics)
        return json.dumps({"compiled": ok, "folder": self._show(folder, root), "bundle_id": bundle.id if ok else None,
                           "diagnostics": [str(d) for d in diagnostics]}, indent=1)


def summary(name: str, arguments: str | JSON | None) -> str:
    """One short line of what a call was asked, for the record and the progress line: the path,
    the pattern, never a written file's content."""
    try:
        args = json.loads(arguments) if isinstance(arguments, str) and arguments.strip() else (arguments or {})
    except json.JSONDecodeError:
        return "(arguments not JSON)"
    if not isinstance(args, dict):
        return ""
    parts = []
    for key in ("path", "pattern", "offset"):
        if args.get(key) not in (None, ""):
            parts.append(str(args[key]) if key == "path" else f"{key}={args[key]}")
    if name == "write_file" and isinstance(args.get("content"), str):
        parts.append(f"{len(args['content'].encode('utf-8'))} bytes")
    return " ".join(parts)[:200]


__all__ = ["BUNDLE_PREFIX", "DEFINITIONS", "NAMES", "Tools", "ToolError", "summary"]
