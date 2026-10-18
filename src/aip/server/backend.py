"""The storage contract (design §5): two protocols, implemented per backend.

`CatalogBackend` holds skill revisions and answers name, revision, file, and search
questions about them, and keeps each name's threshold overrides. `RunBackend` records
run history. `GovernanceBackend` answers the named corpus queries of
`aip.server.governance` over both. A backend class may implement all three; the
server only ever talks to these methods.

Search semantics are deliberately unspecified beyond "ranked, deterministic for a
fixed catalog". Refs passed to `resolve` take three forms: `name` (the pinned
revision if any, else the newest live one), `name@<revision>`, and `name@latest`
(the newest live revision, ignoring the pin).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Protocol, runtime_checkable

from aip.server.records import FileRecord, NameSummary, RunRecord, RunSummary, SearchHit, SkillRecord

JSON = Dict[str, Any]


class NotFound(KeyError):
    """A name, revision, file, or run the backend does not have."""

    def __str__(self) -> str:  # KeyError quotes its argument; we want the plain message
        return str(self.args[0]) if self.args else ""


class NotSupported(NotImplementedError):
    """A query this backend declines to answer (501 over HTTP)."""


def split_ref(ref: str) -> tuple[str, str | None]:
    """`"name"` -> (name, None); `"name@rev"` -> (name, "rev"); `"name@latest"` -> (name, "latest")."""
    name, sep, rev = ref.partition("@")
    if not name:
        raise ValueError(f"empty name in ref {ref!r}")
    return name, (rev or None) if sep else None


@runtime_checkable
class CatalogBackend(Protocol):
    def publish(self, skill: SkillRecord) -> str:
        """Store a revision; returns its revision id. Publishing identical content is a no-op."""

    def get(self, name: str, revision: str | None = None) -> SkillRecord:
        """The record for a revision (the resolved one when `revision` is None)."""

    def files(self, name: str, revision: str) -> List[FileRecord]:
        """Every file of a revision, with bytes, hash-verified."""

    def file(self, name: str, revision: str, path: str) -> bytes:
        """One file's bytes."""

    def list(self) -> List[NameSummary]:
        """Every name in the catalog, sorted by name."""

    def revisions(self, name: str) -> List[JSON]:
        """Every revision of a name, newest first: rows with at least `revision`, `published_at`, `retired`."""

    def search(self, query: str, limit: int = 10) -> List[SearchHit]:
        """Ranked hits over the resolved revision of every name; empty when nothing matches."""

    def pin(self, name: str, revision: str | None) -> None:
        """Make `name` resolve to `revision`; `None` clears the pin."""

    def retire(self, name: str, revision: str) -> None:
        """Stop `name` resolving to `revision`; explicit `name@revision` refs still work."""

    def resolve(self, ref: str) -> tuple[str, str]:
        """(name, revision) for a ref; raises NotFound when nothing live matches."""

    def folder(self, name: str, revision: str) -> Path:
        """The revision's skill folder on disk, named after the skill: what the server loads and executes.
        The filesystem backend hands out its published copy; others materialise into a hash-checked cache."""

    def thresholds(self, name: str) -> Dict[str, float]:
        """The per-question threshold overrides stored for `name` (design §7); `{}` when none."""

    def set_thresholds(self, name: str, thresholds: Dict[str, float]) -> None:
        """Replace the stored overrides for `name`; `{}` clears them."""


@runtime_checkable
class RunBackend(Protocol):
    def create(self, name: str, revision: str) -> str:
        """Start a run record; returns its id."""

    def append(self, run_id: str, entry: JSON, status: str, pause: JSON | None) -> None:
        """Add one history entry and set the run's status and current pause (None when running)."""

    def get(self, run_id: str) -> RunRecord: ...

    def list(self, name: str | None = None, status: str | None = None, limit: int = 50) -> List[RunSummary]:
        """Newest first, optionally filtered by name and status."""


@runtime_checkable
class GovernanceBackend(Protocol):
    def query(self, query: str, name: str | None = None, window: int = 100, limit: int = 50) -> List[JSON]:
        """Rows for one of `aip.server.governance.QUERIES` over the last `window` runs (filtered to
        `name` when given); raises NotFound for an unknown query and NotSupported for one this
        backend declines."""
