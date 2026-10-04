"""Backend contract tests (design §5.3), parametrised over every registered backend.

Each case gets a fresh backend. The filesystem backend runs against a temp dir; the
Neo4j backend joins at M2 (skipped without NEO4J_URI).
"""

import hashlib
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from aip.server.backend import CatalogBackend, NotFound, RunBackend
from aip.server.backends.filesystem import FilesystemBackend
from aip.server.records import materialize, snapshot

EXAMPLE = Path(__file__).parent.parent.parent / "examples" / "billing-support"

BACKENDS = {
    "filesystem": lambda tmp: FilesystemBackend(tmp / "root"),
}


@pytest.fixture(params=sorted(BACKENDS))
def backend(request, tmp_path):
    return BACKENDS[request.param](tmp_path)


@pytest.fixture
def catalog(backend) -> CatalogBackend:
    return backend.catalog


@pytest.fixture
def runs(backend) -> RunBackend:
    return backend.runs


@pytest.fixture(scope="module")
def example():
    return snapshot(EXAMPLE)


def variant(tmp_path: Path, name: str, description: str | None = None, **edits: str):
    """A copy of the example under another name, optionally re-described or with files rewritten."""
    copy = tmp_path / name
    shutil.copytree(EXAMPLE, copy)
    md = copy / "SKILL.md"
    text = md.read_text().replace("name: billing-support", f"name: {name}")
    if description is not None:
        head, _, tail = text.partition("\ndescription: ")
        text = head + "\ndescription: " + description + tail[tail.index("\n"):]
    md.write_text(text)
    for rel, text in edits.items():
        (copy / rel).write_text(text)
    return snapshot(copy)


def tree(root: Path) -> dict:
    out = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.name in {".DS_Store", ".aip-manifest.json"} or "__pycache__" in path.parts:
            continue
        out[rel] = None if path.is_dir() else (hashlib.sha256(path.read_bytes()).hexdigest(),
                                                path.stat().st_mode & 0o777)
    return out


# ---------------------------------------------------------------------- protocols


def test_backend_satisfies_protocols(catalog, runs):
    assert isinstance(catalog, CatalogBackend)
    assert isinstance(runs, RunBackend)


# ------------------------------------------------------------------------ publish


def test_publish_and_resolve_every_ref_form(catalog, example):
    rev = catalog.publish(example)
    assert rev == example.revision
    assert catalog.resolve("billing-support") == ("billing-support", rev)
    assert catalog.resolve(f"billing-support@{rev}") == ("billing-support", rev)
    assert catalog.resolve("billing-support@latest") == ("billing-support", rev)
    with pytest.raises(NotFound):
        catalog.resolve("nope")
    with pytest.raises(NotFound):
        catalog.resolve("billing-support@0000000000000000")


def test_publish_is_idempotent_and_get_returns_the_record(catalog, example):
    rev = catalog.publish(example)
    assert catalog.publish(example) == rev
    assert [n.revisions for n in catalog.list()] == [1]

    got = catalog.get("billing-support")
    assert (got.name, got.revision, got.id) == ("billing-support", rev, f"billing-support@{rev}")
    assert got.description == example.description
    assert got.aip_version == "0.4a0"
    assert got.frontmatter == example.frontmatter
    assert got.procedure == example.procedure
    assert got.steps == example.steps and got.resources == example.resources
    assert got.published_at and not got.retired
    assert catalog.get("billing-support", rev).revision == rev


def test_list_summarises_names(catalog, example, tmp_path):
    catalog.publish(example)
    catalog.publish(variant(tmp_path, "aaa-first"))
    names = catalog.list()
    assert [n.name for n in names] == ["aaa-first", "billing-support"]
    bs = names[1]
    assert bs.latest == example.revision and bs.pinned is None and bs.revisions == 1
    assert bs.description == example.description


# -------------------------------------------------------------------------- files


def test_files_round_trip_byte_for_byte(catalog, example, tmp_path):
    rev = catalog.publish(example)
    files = catalog.files("billing-support", rev)
    assert sorted(f.path for f in files) == sorted(f.path for f in example.files)
    assert all(f.data == o.data for f, o in zip(sorted(files, key=lambda f: f.path),
                                                 sorted(example.files, key=lambda f: f.path)))

    out = materialize(replace(example, files=files), tmp_path / "out" / "billing-support")
    assert tree(out) == tree(EXAMPLE)
    # publishing the materialised copy is the same revision
    assert catalog.publish(snapshot(out)) == rev


def test_single_file_and_missing_file(catalog, example):
    rev = catalog.publish(example)
    assert catalog.file("billing-support", rev, "SKILL.md") == (EXAMPLE / "SKILL.md").read_bytes()
    assert catalog.file("billing-support", rev, "scripts/escalate.py") == (EXAMPLE / "scripts/escalate.py").read_bytes()
    with pytest.raises(NotFound):
        catalog.file("billing-support", rev, "nope.md")
    with pytest.raises(NotFound):
        catalog.files("billing-support", "0000000000000000")


def test_binary_files_survive(catalog, tmp_path):
    copy = tmp_path / "bin-skill"
    shutil.copytree(EXAMPLE, copy)
    md = copy / "SKILL.md"
    md.write_text(md.read_text().replace("name: billing-support", "name: bin-skill"))
    blob = bytes(range(256)) * 4
    (copy / "assets" / "logo.bin").write_bytes(blob)
    rev = catalog.publish(snapshot(copy))
    assert catalog.file("bin-skill", rev, "assets/logo.bin") == blob


# ------------------------------------------------------------------------- search


def test_search_ranks_the_described_skill_first(catalog, example, tmp_path):
    catalog.publish(example)
    # the twin mentions refunds only in its triggers, never in its description
    catalog.publish(variant(tmp_path, "aaa-other", description="Route an invoice question to the right team."))
    hits = catalog.search("refund")
    assert [h.name for h in hits] == ["billing-support", "aaa-other"]
    assert hits[0].revision == example.revision
    assert hits[0].score > hits[1].score > 0
    assert [h.name for h in catalog.search("invoice")] == ["aaa-other", "billing-support"]
    assert [h.name for h in catalog.search("other")] == ["aaa-other"]
    assert catalog.search("qqqqqq") == []
    assert catalog.search("") == []
    assert len(catalog.search("refund", limit=1)) == 1


def test_search_by_exact_name_wins(catalog, example, tmp_path):
    catalog.publish(example)
    catalog.publish(variant(tmp_path, "billing-support-v2", description="billing support, billing support, billing."))
    assert catalog.search("billing-support")[0].name == "billing-support"


# ---------------------------------------------------------------- pin and retire


def test_pin_and_retire_change_resolve(catalog, example, tmp_path):
    v1 = catalog.publish(example)
    second = variant(tmp_path, "billing-support", **{"assets/policy.md": "revised policy\n"})
    v2 = catalog.publish(second)
    assert v1 != v2

    # newest live revision wins by default; "@latest" says the same
    assert catalog.resolve("billing-support")[1] == v2
    assert catalog.resolve("billing-support@latest")[1] == v2
    assert catalog.list()[0].revisions == 2

    catalog.pin("billing-support", v1)
    assert catalog.resolve("billing-support")[1] == v1
    assert catalog.resolve("billing-support@latest")[1] == v2     # the pin does not hide newer work
    assert catalog.get("billing-support").revision == v1
    assert catalog.list()[0].pinned == v1
    assert catalog.search("refund")[0].revision == v1             # search follows what resolves

    catalog.pin("billing-support", None)
    assert catalog.resolve("billing-support")[1] == v2

    catalog.retire("billing-support", v2)
    assert catalog.resolve("billing-support")[1] == v1
    assert catalog.resolve("billing-support@latest")[1] == v1
    assert catalog.resolve(f"billing-support@{v2}")[1] == v2       # explicit refs still work
    assert catalog.get("billing-support", v2).retired

    catalog.retire("billing-support", v1)
    with pytest.raises(NotFound):
        catalog.resolve("billing-support")
    assert catalog.list()[0].latest is None
    assert catalog.search("refund") == []

    catalog.publish(example)                                       # republishing brings v1 back
    assert catalog.resolve("billing-support")[1] == v1


def test_retiring_the_pinned_revision_clears_the_pin(catalog, example, tmp_path):
    v1 = catalog.publish(example)
    v2 = catalog.publish(variant(tmp_path, "billing-support", **{"assets/policy.md": "revised\n"}))
    catalog.pin("billing-support", v1)
    catalog.retire("billing-support", v1)
    assert catalog.resolve("billing-support")[1] == v2
    assert catalog.list()[0].pinned is None


def test_pin_and_retire_reject_unknown(catalog, example):
    catalog.publish(example)
    with pytest.raises(NotFound):
        catalog.pin("billing-support", "0000000000000000")
    with pytest.raises(NotFound):
        catalog.retire("nope", "0000000000000000")


# --------------------------------------------------------------------------- runs


def test_runs_create_append_get_list(runs):
    rid = runs.create("billing-support", "abc123")
    run = runs.get(rid)
    assert (run.id, run.name, run.revision, run.status) == (rid, "billing-support", "abc123", "running")
    assert run.history == [] and run.pause is None

    runs.append(rid, {"step": "triage", "kind": "decision"}, status="running", pause=None)
    runs.append(rid, {"step": "reply", "kind": "client_task"}, status="paused",
                pause={"kind": "client_task", "step": "reply"})
    run = runs.get(rid)
    assert [e["step"] for e in run.history] == ["triage", "reply"]
    assert run.status == "paused" and run.pause["kind"] == "client_task"
    assert run.updated_at >= run.started_at

    other = runs.create("other", "def456")
    runs.append(other, {"step": "end"}, status="done", pause=None)

    summaries = runs.list()
    assert {s.id for s in summaries} == {rid, other}
    assert summaries[0].id == other                                # newest first
    by_id = {s.id: s for s in summaries}
    assert by_id[rid].steps == 2 and by_id[rid].status == "paused"
    assert [s.id for s in runs.list(name="other")] == [other]
    assert [s.id for s in runs.list(status="paused")] == [rid]
    assert runs.list(name="other", status="paused") == []
    assert len(runs.list(limit=1)) == 1

    with pytest.raises(NotFound):
        runs.get("nope")
    with pytest.raises(NotFound):
        runs.append("nope", {}, status="done", pause=None)
