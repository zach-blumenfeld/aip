"""The records every backend stores and returns, and the folder <-> record conversions.

Two layers per skill revision, as in the original Neo4j projection:

- **Artifact** (lossless): every file under the skill folder as a `FileRecord` holding
  its exact bytes (text as UTF-8, anything else base64), size, sha256, and mode, plus
  the directory list. `materialize` rebuilds the folder byte for byte and verifies hashes.
- **Projection** (queryable): the parsed procedure as plain JSON rows (`procedure`,
  `steps`, `edges`, `branches`, `inputs`, `questions`, `resources`) that a graph
  backend turns into nodes and edges and a filesystem backend simply stores.

Identity: `name@revision`, where `revision` is a sha256 over every file's path and
bytes. Publishing identical content is a no-op; changed content becomes a new
revision alongside the old one.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List

JSON = Dict[str, Any]

MANIFEST = ".aip-manifest.json"

IGNORE_DIRS = {".git", "__pycache__", ".aip"}
IGNORE_FILES = {".DS_Store"}
IGNORE_SUFFIXES = {".pyc"}


# ----------------------------------------------------------------------------- files


@dataclass(frozen=True)
class FileRecord:
    """One file of a skill revision with its exact bytes. JSON-safe via `to_json`."""
    path: str
    size: int
    sha256: str
    mode: int
    encoding: str          # "utf-8" | "base64"
    content: str

    @property
    def data(self) -> bytes:
        return self.content.encode("utf-8") if self.encoding == "utf-8" else base64.b64decode(self.content)

    @classmethod
    def from_bytes(cls, path: str, data: bytes, mode: int = 0o644) -> "FileRecord":
        try:
            text = data.decode("utf-8")
            if "\x00" in text:
                raise UnicodeDecodeError("utf-8", b"", 0, 1, "binary")
            encoding, content = "utf-8", text
        except UnicodeDecodeError:
            encoding, content = "base64", base64.b64encode(data).decode("ascii")
        return cls(path=path, size=len(data), sha256=hashlib.sha256(data).hexdigest(),
                   mode=int(mode), encoding=encoding, content=content)

    @classmethod
    def from_json(cls, d: JSON) -> "FileRecord":
        return cls(path=d["path"], size=int(d["size"]), sha256=d["sha256"], mode=int(d["mode"]),
                   encoding=d["encoding"], content=d["content"])

    def to_json(self) -> JSON:
        return asdict(self)

    def manifest_entry(self) -> JSON:
        """The hash line without the bytes: what a manifest or listing carries."""
        return {"path": self.path, "size": self.size, "sha256": self.sha256, "mode": self.mode}


def _read_file(root: Path, path: Path) -> FileRecord:
    return FileRecord.from_bytes(path.relative_to(root).as_posix(), path.read_bytes(),
                                 stat.S_IMODE(path.stat().st_mode))


def walk(root: Path) -> tuple[List[FileRecord], List[str]]:
    """Every file and directory under `root`, sorted, minus ignored noise and symlinks."""
    files: List[FileRecord] = []
    directories: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORE_DIRS)
        here = Path(dirpath)
        if here != root:
            directories.append(here.relative_to(root).as_posix())
        for name in sorted(filenames):
            if name in IGNORE_FILES or Path(name).suffix in IGNORE_SUFFIXES:
                continue
            path = here / name
            if path.is_symlink():
                continue
            files.append(_read_file(root, path))
    return files, sorted(directories)


def revision(files: List[FileRecord]) -> str:
    """Content hash over every file's path and sha256; the revision identifier."""
    h = hashlib.sha256()
    for f in sorted(files, key=lambda x: x.path):
        h.update(f.path.encode()); h.update(b"\0"); h.update(f.sha256.encode()); h.update(b"\0")
    return h.hexdigest()[:16]


# ---------------------------------------------------------------------------- skills


@dataclass
class SkillRecord:
    """Everything a backend holds for one skill revision. Pure data; `to_json` is JSON-safe."""
    name: str
    revision: str
    description: str
    aip_version: str | None
    frontmatter: JSON
    root_name: str
    files: List[FileRecord]
    directories: List[str]
    procedure: JSON          # {"purpose", "trigger_when", "do_not_use_when", "anti_patterns", "start", "end"}
    steps: List[JSON]
    edges: List[JSON]        # {"from", "to"}
    branches: List[JSON]     # {"router", "value", "to"}
    inputs: List[JSON]       # {"step", "order", "name", "type", "description"}
    questions: List[JSON]    # {"step", "order", "name", "type", "instructions", "criteria", "threshold"}
    resources: List[JSON]    # {"step", "path", "role", "description"}
    published_at: str | None = None
    retired: bool = False

    @property
    def id(self) -> str:
        return f"{self.name}@{self.revision}"

    def to_json(self, with_content: bool = True) -> JSON:
        d = asdict(self)
        d["files"] = [f.to_json() if with_content else f.manifest_entry() for f in self.files]
        d["id"] = self.id
        return d

    @classmethod
    def from_json(cls, d: JSON, files: List[FileRecord] | None = None) -> "SkillRecord":
        d = dict(d)
        d.pop("id", None)
        raw = d.pop("files", [])
        if files is None:
            files = [FileRecord.from_json(f) if "content" in f else
                     FileRecord(path=f["path"], size=int(f["size"]), sha256=f["sha256"], mode=int(f["mode"]),
                                encoding="utf-8", content="") for f in raw]
        return cls(files=files, **d)


def snapshot(skill_dir: Path) -> SkillRecord:
    """Validate the skill and capture it: files for the artifact, the spec for the projection."""
    from aip.spec import load_skill

    skill_dir = Path(skill_dir).resolve()
    loaded = load_skill(skill_dir)
    fm, spec = loaded.frontmatter, loaded.spec
    files, directories = walk(skill_dir)

    steps, edges, branches, inputs, questions, resources = [], [], [], [], [], []
    for order, step in enumerate(spec.steps):
        record: JSON = {"name": step.name, "kind": step.kind, "order": order,
                        "description": getattr(step, "description", None)}
        if step.kind == "router":
            record["branch_on"] = step.branch_on
            for value, target in step.branches.items():
                branches.append({"router": step.name, "value": value, "to": target})
        else:
            if step.kind != "end":
                edges.append({"from": step.name, "to": step.inputs_to})
            for i, item in enumerate(step.inputs):
                inputs.append({"step": step.name, "order": i, "name": item.name, "type": item.type.value,
                               "description": item.description})
        if step.kind == "decision":
            for i, (qname, q) in enumerate(step.questions.items()):
                criteria = q.criteria.model_dump(exclude_none=True) if hasattr(q.criteria, "model_dump") else q.criteria
                questions.append({"step": step.name, "order": i, "name": qname, "type": q.type,
                                  "instructions": q.instructions,
                                  "criteria": json.dumps(criteria) if criteria is not None else None,
                                  "threshold": step.thresholds.get(qname)})
        if step.kind == "execution":
            record["script"] = step.script
            record["timeout"] = step.timeout
            resources.append({"step": step.name, "path": step.script, "role": "script", "description": None})
            resources += [{"step": step.name, "path": a, "role": "asset", "description": None} for a in step.assets]
        if step.kind == "client_task":
            record["template"] = step.template
            record["framing"] = step.framing
            resources.append({"step": step.name, "path": step.template, "role": "template", "description": None})
            resources += [{"step": step.name, "path": a, "role": "asset", "description": None} for a in step.assets]
            resources += [{"step": step.name, "path": r.path, "role": "reference", "description": r.description}
                          for r in step.references]
        steps.append(record)

    return SkillRecord(
        name=fm["name"], revision=revision(files),
        description=fm.get("description", ""),
        aip_version=fm.get("metadata", {}).get("aip-version"),
        frontmatter=fm, root_name=skill_dir.name,
        files=files, directories=directories,
        procedure={"purpose": spec.purpose, "trigger_when": list(spec.trigger_when),
                   "do_not_use_when": list(spec.do_not_use_when), "anti_patterns": list(spec.anti_patterns),
                   "start": spec.start.name, "end": next(s.name for s in spec.steps if s.kind == "end")},
        steps=steps, edges=edges, branches=branches, inputs=inputs, questions=questions, resources=resources,
    )


def write_files(files: List[FileRecord], directories: List[str], out_dir: Path) -> Path:
    """Write an artifact layer to disk, verifying every file's hash. Returns out_dir."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for d in directories:
        (out_dir / d).mkdir(parents=True, exist_ok=True)
    for f in files:
        data = f.data
        digest = hashlib.sha256(data).hexdigest()
        if digest != f.sha256:
            raise ValueError(f"{f.path}: content hash {digest} does not match stored {f.sha256}")
        target = out_dir / f.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        os.chmod(target, int(f.mode))
    return out_dir


def materialize(record: SkillRecord, out_dir: Path) -> Path:
    """Rebuild a skill folder from its record at `out_dir`, byte for byte. Returns out_dir."""
    return write_files(record.files, record.directories, out_dir)


# --------------------------------------------------------------------- catalog views


@dataclass(frozen=True)
class NameSummary:
    """One catalog entry: a name and what resolves for it."""
    name: str
    description: str
    latest: str | None          # newest live revision, None when every revision is retired
    pinned: str | None
    revisions: int              # including retired ones
    published_at: str | None    # of the latest live revision


@dataclass(frozen=True)
class SearchHit:
    name: str
    revision: str
    description: str
    score: float


# ------------------------------------------------------------------------------ runs


@dataclass
class RunRecord:
    id: str
    name: str
    revision: str
    status: str                 # "running" | "paused" | "done" | "failed" (free-form; the server sets it)
    started_at: str
    updated_at: str
    pause: JSON | None = None
    history: List[JSON] = field(default_factory=list)


@dataclass(frozen=True)
class RunSummary:
    id: str
    name: str
    revision: str
    status: str
    started_at: str
    updated_at: str
    steps: int
