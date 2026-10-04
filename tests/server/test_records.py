"""Tests for `aip.server.records`: snapshot, the projection rows, and materialize.

None of these need a backend. They came from the 0.4 `tests/test_db.py`; the database
half of that file is now the Neo4j parametrisation of `test_contract.py`.
"""

import hashlib
import json
import os
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from aip.server.records import materialize, snapshot

EXAMPLE = Path(__file__).parent.parent.parent / "examples" / "billing-support"


def tree(root: Path) -> dict:
    """{relative path: (sha256, mode)} for every file, plus directories, skipping ignored noise."""
    out = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if any(part in {"__pycache__", ".git", ".aip"} for part in path.parts) or path.name == ".DS_Store":
            continue
        if path.is_dir():
            out[rel + "/"] = None
        else:
            out[rel] = (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mode & 0o777)
    return out


def test_snapshot_captures_files_and_graph():
    b = snapshot(EXAMPLE)
    assert b.name == "billing-support"
    assert b.id == f"billing-support@{b.revision}" and len(b.revision) == 16
    assert b.aip_version == "0.4a0"
    paths = {f.path for f in b.files}
    assert {"SKILL.md", "scripts/escalate.py", "source/README.md"} <= paths
    assert all(f.encoding == "utf-8" for f in b.files)
    assert set(b.directories) == {"assets", "references", "scripts", "source"}

    assert [s["name"] for s in b.steps] == ["triage", "by-tone", "escalate", "reply", "end"]
    assert (b.procedure["start"], b.procedure["end"]) == ("triage", "end")
    assert b.edges == [{"from": "triage", "to": "by-tone"}, {"from": "escalate", "to": "end"},
                       {"from": "reply", "to": "end"}]
    assert b.branches == [{"router": "by-tone", "value": "angry", "to": "escalate"},
                          {"router": "by-tone", "value": "calm", "to": "reply"}]
    q = {x["name"]: x for x in b.questions}
    assert q["tone"]["type"] == "choice"
    assert json.loads(q["tone"]["criteria"])["angry"] == "Frustrated, demanding, or threatening to leave."
    assert q["tone"]["threshold"] == 0.6
    roles = {(r["step"], r["role"], r["path"]) for r in b.resources}
    assert {("escalate", "script", "scripts/escalate.py"), ("reply", "template", "assets/reply.md"),
            ("reply", "reference", "references/help.md")} <= roles
    assert all(r["path"] in paths for r in b.resources)      # every USES edge has a File to point at


def test_record_is_json_safe():
    json.dumps(snapshot(EXAMPLE).to_json())


def test_revision_is_content_addressed(tmp_path):
    copy = tmp_path / "billing-support"
    shutil.copytree(EXAMPLE, copy)
    assert snapshot(copy).revision == snapshot(EXAMPLE).revision
    (copy / "assets" / "policy.md").write_text("changed\n")
    assert snapshot(copy).revision != snapshot(EXAMPLE).revision


def test_materialize_round_trip_is_byte_identical(tmp_path):
    b = snapshot(EXAMPLE)
    out = materialize(b, tmp_path / "billing-support")
    assert tree(out) == tree(EXAMPLE)
    # and the rebuilt folder is a valid, loadable skill with the same revision
    assert snapshot(out).revision == b.revision


def test_binary_files_and_modes_survive(tmp_path):
    copy = tmp_path / "billing-support"
    shutil.copytree(EXAMPLE, copy)
    blob = bytes(range(256)) * 4
    (copy / "assets" / "logo.bin").write_bytes(blob)
    os.chmod(copy / "scripts" / "escalate.py", 0o755)
    b = snapshot(copy)
    f = next(x for x in b.files if x.path == "assets/logo.bin")
    assert f.encoding == "base64"
    out = materialize(b, tmp_path / "rebuilt")
    assert (out / "assets" / "logo.bin").read_bytes() == blob
    assert (out / "scripts" / "escalate.py").stat().st_mode & 0o777 == 0o755


def test_materialize_rejects_tampered_content(tmp_path):
    b = snapshot(EXAMPLE)
    b.files[0] = replace(b.files[0], content=b.files[0].content + "x")
    with pytest.raises(ValueError):
        materialize(b, tmp_path / "out")
