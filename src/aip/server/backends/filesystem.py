"""The filesystem backend (design §5.2): a root directory and nothing else.

    <root>/
    ├── catalog.json                 names -> {pinned, revisions: [{revision, published_at, retired}]}
    ├── catalog.lock                 flock target; catalog.json is the only file ever rewritten
    ├── skills/<name>/<revision>/    one revision
    │   ├── .aip-manifest.json       the record minus file bytes: manifest (path, size, sha256, mode)
    │   │                            plus the projection rows, so `get` never re-parses the skill
    │   └── <name>/                  the skill folder exactly as published, nothing else in it;
    │                                also the executable copy (the loader checks the folder name)
    └── runs/<run_id>.jsonl          first line the run header, one JSON line per history entry

Writes are atomic per file (temp name, then rename); a revision directory is built
beside its final name and renamed into place. Search is weighted term overlap over an
in-memory index of every name's resolved revision, rebuilt on publish, pin, and retire.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List

from aip.server.backend import NotFound, split_ref
from aip.server.records import (MANIFEST, FileRecord, NameSummary, RunRecord, RunSummary, SearchHit,
                                SkillRecord, materialize)

JSON = Dict[str, Any]

SEARCH_WEIGHTS = {"name": 10.0, "description": 3.0, "purpose": 2.0, "triggers": 1.0}
_WORD = re.compile(r"[a-z0-9]+")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


# --------------------------------------------------------------------------- catalog


class FilesystemCatalog:
    """`CatalogBackend` over `<root>/catalog.json` and `<root>/skills/`."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.skills_dir = self.root / "skills"
        self.catalog_path = self.root / "catalog.json"
        self.lock_path = self.root / "catalog.lock"
        self.root.mkdir(parents=True, exist_ok=True)
        self.skills_dir.mkdir(exist_ok=True)
        self._index: Dict[str, Dict[str, Any]] = {}
        self._reindex()

    # ------------------------------------------------------------- catalog.json

    @contextmanager
    def _locked(self) -> Iterator[None]:
        with open(self.lock_path, "a+") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def _read_catalog(self) -> Dict[str, JSON]:
        if not self.catalog_path.exists():
            return {}
        return json.loads(self.catalog_path.read_text())

    def _write_catalog(self, catalog: Dict[str, JSON]) -> None:
        _write_atomic(self.catalog_path, json.dumps(catalog, indent=2, sort_keys=True) + "\n")

    def _entry(self, catalog: Dict[str, JSON], name: str) -> JSON:
        try:
            return catalog[name]
        except KeyError:
            raise NotFound(f"no skill named {name!r}") from None

    @staticmethod
    def _revision_row(entry: JSON, revision: str) -> JSON:
        for row in entry["revisions"]:
            if row["revision"] == revision:
                return row
        raise NotFound(f"no revision {revision!r}")

    @staticmethod
    def _latest_live(entry: JSON) -> str | None:
        live = [r for r in entry["revisions"] if not r["retired"]]
        return live[-1]["revision"] if live else None    # rows are appended in publish order

    def _resolve_in(self, catalog: Dict[str, JSON], ref: str) -> tuple[str, str]:
        name, rev = split_ref(ref)
        entry = self._entry(catalog, name)
        if rev is None and entry.get("pinned"):
            return name, entry["pinned"]
        if rev is None or rev == "latest":
            latest = self._latest_live(entry)
            if latest is None:
                raise NotFound(f"every revision of {name!r} is retired")
            return name, latest
        self._revision_row(entry, rev)
        return name, rev

    # ------------------------------------------------------------------ folders

    def _revision_dir(self, name: str, revision: str) -> Path:
        path = self.skills_dir / name / revision
        if not (path / MANIFEST).exists():
            raise NotFound(f"no revision {revision!r} of {name!r}")
        return path

    def folder(self, name: str, revision: str) -> Path:
        """The skill folder of a revision on disk: the executable copy for `load_procedure`."""
        return self._revision_dir(name, revision) / name

    def _manifest(self, name: str, revision: str) -> JSON:
        return json.loads((self._revision_dir(name, revision) / MANIFEST).read_text())

    # --------------------------------------------------------- CatalogBackend

    def publish(self, skill: SkillRecord) -> str:
        final = self.skills_dir / skill.name / skill.revision
        if not (final / MANIFEST).exists():
            final.parent.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix=f".{skill.revision}.", dir=final.parent))
            try:
                materialize(skill, staging / skill.name)
                record = replace(skill, published_at=_now(), retired=False)
                _write_atomic(staging / MANIFEST, json.dumps(record.to_json(with_content=False), indent=2) + "\n")
                try:
                    os.rename(staging, final)
                except OSError:
                    if not (final / MANIFEST).exists():   # a concurrent publish of the same revision won
                        raise
            finally:
                if staging.exists():
                    shutil.rmtree(staging, ignore_errors=True)
        with self._locked():
            catalog = self._read_catalog()
            entry = catalog.setdefault(skill.name, {"pinned": None, "revisions": []})
            try:
                row = self._revision_row(entry, skill.revision)
                row["retired"] = False     # republishing a retired revision brings it back
            except NotFound:
                published_at = json.loads((final / MANIFEST).read_text()).get("published_at") or _now()
                entry["revisions"].append({"revision": skill.revision, "published_at": published_at,
                                           "retired": False})
            self._write_catalog(catalog)
        self._reindex()
        return skill.revision

    def get(self, name: str, revision: str | None = None) -> SkillRecord:
        name, revision = self.resolve(name if revision is None else f"{name}@{revision}")
        manifest = self._manifest(name, revision)
        row = self._revision_row(self._entry(self._read_catalog(), name), revision)
        record = SkillRecord.from_json(manifest, files=self.files(name, revision))
        record.retired = bool(row["retired"])
        record.published_at = row["published_at"]
        return record

    def files(self, name: str, revision: str) -> List[FileRecord]:
        folder = self.folder(name, revision)
        out = []
        for entry in self._manifest(name, revision)["files"]:
            record = FileRecord.from_bytes(entry["path"], (folder / entry["path"]).read_bytes(), entry["mode"])
            if record.sha256 != entry["sha256"]:
                raise ValueError(f"{name}@{revision}/{entry['path']}: on-disk hash {record.sha256} "
                                 f"does not match manifest {entry['sha256']}")
            out.append(record)
        return out

    def file(self, name: str, revision: str, path: str) -> bytes:
        folder = self.folder(name, revision)
        if not any(e["path"] == path for e in self._manifest(name, revision)["files"]):
            raise NotFound(f"no file {path!r} in {name}@{revision}")
        return (folder / path).read_bytes()

    def list(self) -> List[NameSummary]:
        out = []
        for name, entry in sorted(self._read_catalog().items()):
            latest = self._latest_live(entry)
            description, published_at = "", None
            if latest is not None:
                resolved = entry.get("pinned") or latest
                description = self._manifest(name, resolved).get("description", "")
                published_at = self._revision_row(entry, latest)["published_at"]
            out.append(NameSummary(name=name, description=description, latest=latest,
                                   pinned=entry.get("pinned"), revisions=len(entry["revisions"]),
                                   published_at=published_at))
        return out

    def search(self, query: str, limit: int = 10) -> List[SearchHit]:
        terms = _tokens(query)
        if not terms:
            return []
        hits = []
        for name, doc in self._index.items():
            score = 0.0
            if query.strip().lower() == name.lower():
                score += SEARCH_WEIGHTS["name"] * 2
            for field_name, weight in SEARCH_WEIGHTS.items():
                score += weight * len(terms & doc[field_name])
            if score > 0:
                hits.append(SearchHit(name=name, revision=doc["revision"], description=doc["text_description"],
                                      score=score))
        hits.sort(key=lambda h: (-h.score, h.name))
        return hits[:limit]

    def pin(self, name: str, revision: str | None) -> None:
        with self._locked():
            catalog = self._read_catalog()
            entry = self._entry(catalog, name)
            if revision is not None:
                self._revision_row(entry, revision)
            entry["pinned"] = revision
            self._write_catalog(catalog)
        self._reindex()

    def retire(self, name: str, revision: str) -> None:
        with self._locked():
            catalog = self._read_catalog()
            entry = self._entry(catalog, name)
            self._revision_row(entry, revision)["retired"] = True
            if entry.get("pinned") == revision:
                entry["pinned"] = None
            self._write_catalog(catalog)
        self._reindex()

    def resolve(self, ref: str) -> tuple[str, str]:
        return self._resolve_in(self._read_catalog(), ref)

    # ------------------------------------------------------------------ search

    def _reindex(self) -> None:
        index: Dict[str, Dict[str, Any]] = {}
        catalog = self._read_catalog()
        for name in catalog:
            try:
                _, revision = self._resolve_in(catalog, name)
            except NotFound:
                continue
            m = self._manifest(name, revision)
            proc = m.get("procedure", {})
            index[name] = {
                "revision": revision,
                "text_description": m.get("description", ""),
                "name": _tokens(name),
                "description": _tokens(m.get("description", "")),
                "purpose": _tokens(proc.get("purpose", "") or ""),
                "triggers": _tokens(" ".join(proc.get("trigger_when", []) or [])),
            }
        self._index = index


# ------------------------------------------------------------------------------ runs


class FilesystemRuns:
    """`RunBackend` over `<root>/runs/<id>.jsonl`."""

    def __init__(self, root: Path):
        self.runs_dir = Path(root) / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, run_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
            raise NotFound(f"no run {run_id!r}")
        path = self.runs_dir / f"{run_id}.jsonl"
        if not path.exists():
            raise NotFound(f"no run {run_id!r}")
        return path

    def _lines(self, path: Path) -> List[JSON]:
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def create(self, name: str, revision: str) -> str:
        run_id = uuid.uuid4().hex[:16]
        header = {"id": run_id, "name": name, "revision": revision, "status": "running", "started_at": _now()}
        _write_atomic(self.runs_dir / f"{run_id}.jsonl", json.dumps(header) + "\n")
        return run_id

    def append(self, run_id: str, entry: JSON, status: str, pause: JSON | None) -> None:
        path = self._path(run_id)
        line = json.dumps({"entry": entry, "status": status, "pause": pause, "at": _now()}) + "\n"
        with open(path, "a") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())

    def get(self, run_id: str) -> RunRecord:
        header, *rows = self._lines(self._path(run_id))
        last = rows[-1] if rows else None
        return RunRecord(
            id=header["id"], name=header["name"], revision=header["revision"],
            status=last["status"] if last else header["status"],
            started_at=header["started_at"],
            updated_at=last["at"] if last else header["started_at"],
            pause=last["pause"] if last else None,
            history=[r["entry"] for r in rows],
        )

    def list(self, name: str | None = None, status: str | None = None, limit: int = 50) -> List[RunSummary]:
        out = []
        for path in self.runs_dir.glob("*.jsonl"):
            run = self.get(path.stem)
            if name is not None and run.name != name:
                continue
            if status is not None and run.status != status:
                continue
            out.append(RunSummary(id=run.id, name=run.name, revision=run.revision, status=run.status,
                                  started_at=run.started_at, updated_at=run.updated_at, steps=len(run.history)))
        out.sort(key=lambda r: (r.started_at, r.id), reverse=True)
        return out[:limit]


class FilesystemBackend:
    """Both halves over one root: `.catalog` is the `CatalogBackend`, `.runs` the `RunBackend`."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.catalog = FilesystemCatalog(self.root)
        self.runs = FilesystemRuns(self.root)
