"""Compatibility shim for the 0.4 `aip db` API over the Neo4j backend.

The projection itself lives in `aip.server.backends.neo4j` (graph shape, Cypher,
`Neo4jBackend`); the records and the folder <-> record conversions in
`aip.server.records`. This module keeps the four functions `aip db` and older callers
use, each opening a backend for the call:

- `load(skill_dir)`: validate, snapshot, publish; returns `name@revision`.
- `fetch(name, revision=None)`: the record as JSON (files with bytes), or None.
- `export(name, out_dir, revision=None)`: rebuild the folder at `out_dir/<name>`, hash-verified.
- `list_skills()`: one row per revision, newest first per name.

`Bundle` stays as an alias of `SkillRecord`, and `Connection` is re-exported.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from aip.server.backend import NotFound
from aip.server.backends.neo4j import Connection, Neo4jBackend  # noqa: F401
from aip.server.records import (IGNORE_DIRS, IGNORE_FILES, IGNORE_SUFFIXES, FileRecord, SkillRecord,  # noqa: F401
                                materialize, snapshot, write_files)

JSON = Dict[str, Any]

Bundle = SkillRecord


def load(skill_dir: Path, conn: Connection | None = None) -> str:
    """Validate, snapshot, and publish a skill. Returns the skill id (`name@revision`)."""
    record = snapshot(skill_dir)
    with Neo4jBackend(conn) as backend:
        backend.catalog.publish(record)
    return record.id


def fetch(name: str, revision: str | None = None, conn: Connection | None = None) -> JSON | None:
    """The resolved (or named) revision as JSON, files included; None when there is no such skill."""
    with Neo4jBackend(conn) as backend:
        try:
            return backend.catalog.get(name, revision).to_json()
        except NotFound:
            return None


def export(name: str, out_dir: Path, revision: str | None = None, conn: Connection | None = None) -> Path:
    """Rebuild a skill folder from the database at out_dir/<name>. Verifies every file hash."""
    with Neo4jBackend(conn) as backend:
        record = backend.catalog.get(name, revision)     # NotFound is a KeyError
    return materialize(record, Path(out_dir) / record.name)


def list_skills(conn: Connection | None = None) -> List[JSON]:
    """Every revision of every name: name, revision, aip_version, published_at, retired, pinned, files, steps."""
    with Neo4jBackend(conn) as backend:
        return backend.catalog.revisions()
