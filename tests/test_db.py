"""Tests for the Neo4j projection.

The bundle and materialize round trip needs no database. The integration test runs only
when NEO4J_URI is set (plus NEO4J_USERNAME / NEO4J_PASSWORD / NEO4J_DATABASE as needed)
and loads the example skill, exports it, and compares the trees byte for byte.
"""

import hashlib
import json
import os
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from aip.db.neo4j import materialize, snapshot

EXAMPLE = Path(__file__).parent.parent / "examples" / "billing-support"


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


class BundleTest(unittest.TestCase):
    def test_snapshot_captures_files_and_graph(self):
        b = snapshot(EXAMPLE)
        self.assertEqual(b.name, "billing-support")
        self.assertRegex(b.id, r"^billing-support@[0-9a-f]{16}$")
        self.assertEqual(b.aip_version, "0.4a0")
        paths = {f.path for f in b.files}
        self.assertIn("SKILL.md", paths)
        self.assertIn("scripts/escalate.py", paths)
        self.assertIn("source/README.md", paths)
        self.assertTrue(all(f.encoding == "utf-8" for f in b.files))
        self.assertEqual({d for d in b.directories}, {"assets", "references", "scripts", "source"})

        self.assertEqual([s["name"] for s in b.steps], ["triage", "by-tone", "escalate", "reply", "end"])
        self.assertEqual(b.procedure["start"], "triage")
        self.assertEqual(b.procedure["end"], "end")
        self.assertEqual(b.edges, [{"from": "triage", "to": "by-tone"}, {"from": "escalate", "to": "end"},
                                   {"from": "reply", "to": "end"}])
        self.assertEqual(b.branches, [{"router": "by-tone", "value": "angry", "to": "escalate"},
                                      {"router": "by-tone", "value": "calm", "to": "reply"}])
        q = {x["name"]: x for x in b.questions}
        self.assertEqual(q["tone"]["type"], "choice")
        self.assertEqual(json.loads(q["tone"]["criteria"])["angry"], "Frustrated, demanding, or threatening to leave.")
        self.assertEqual(q["tone"]["threshold"], 0.6)
        roles = {(r["step"], r["role"], r["path"]) for r in b.resources}
        self.assertIn(("escalate", "script", "scripts/escalate.py"), roles)
        self.assertIn(("reply", "template", "assets/reply.md"), roles)
        self.assertIn(("reply", "reference", "references/help.md"), roles)
        self.assertTrue(all(r["path"] in paths for r in b.resources))  # every USES edge has a File to point at

    def test_bundle_is_json_safe(self):
        b = snapshot(EXAMPLE)
        json.dumps(b.to_json())

    def test_revision_is_content_addressed(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "billing-support"
            shutil.copytree(EXAMPLE, copy)
            self.assertEqual(snapshot(copy).revision, snapshot(EXAMPLE).revision)
            (copy / "assets" / "policy.md").write_text("changed\n")
            self.assertNotEqual(snapshot(copy).revision, snapshot(EXAMPLE).revision)

    def test_materialize_round_trip_is_byte_identical(self):
        b = snapshot(EXAMPLE)
        with tempfile.TemporaryDirectory() as tmp:
            out = materialize(b, Path(tmp) / "billing-support")
            self.assertEqual(tree(out), tree(EXAMPLE))
            # and the rebuilt folder is a valid, loadable skill with the same revision
            self.assertEqual(snapshot(out).revision, b.revision)

    def test_binary_files_survive(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "billing-support"
            shutil.copytree(EXAMPLE, copy)
            blob = bytes(range(256)) * 4
            (copy / "assets" / "logo.bin").write_bytes(blob)
            os.chmod(copy / "scripts" / "escalate.py", 0o755)
            b = snapshot(copy)
            f = next(x for x in b.files if x.path == "assets/logo.bin")
            self.assertEqual(f.encoding, "base64")
            out = materialize(b, Path(tmp) / "rebuilt")
            self.assertEqual((out / "assets" / "logo.bin").read_bytes(), blob)
            self.assertEqual((out / "scripts" / "escalate.py").stat().st_mode & 0o777, 0o755)

    def test_materialize_rejects_tampered_content(self):
        b = snapshot(EXAMPLE)
        b.files[0] = replace(b.files[0], content=b.files[0].content + "x")
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
            materialize(b, Path(tmp) / "out")


@unittest.skipUnless(os.environ.get("NEO4J_URI"), "NEO4J_URI not set")
class Neo4jIntegration(unittest.TestCase):
    def test_load_export_round_trip_and_multiple_skills(self):
        from aip.db.neo4j import Connection, export, fetch, list_skills, load

        conn = Connection()
        skill_id = load(EXAMPLE, conn)
        self.assertEqual(load(EXAMPLE, conn), skill_id)  # idempotent

        with tempfile.TemporaryDirectory() as tmp:
            # a second, different skill under another name coexists
            other = Path(tmp) / "billing-other"
            shutil.copytree(EXAMPLE, other)
            md = other / "SKILL.md"
            md.write_text(md.read_text().replace("name: billing-support", "name: billing-other"))
            other_id = load(other, conn)
            self.assertNotEqual(other_id, skill_id)

            names = {(s["name"]) for s in list_skills(conn)}
            self.assertTrue({"billing-support", "billing-other"} <= names)

            out = export("billing-support", Path(tmp) / "export", conn=conn)
            self.assertEqual(tree(out), tree(EXAMPLE))
            self.assertEqual(snapshot(out).id, skill_id)

            record = fetch("billing-support", conn=conn)
            self.assertEqual(record["id"], skill_id)

        with conn.driver() as driver:
            records, _, _ = driver.execute_query(
                "MATCH (s:Skill {id: $id})-[:HAS_PROCEDURE]->(p)-[:HAS_STEP]->(st) "
                "OPTIONAL MATCH (st)-[u:USES]->(f:File) "
                "WITH st, collect(f.path) AS files ORDER BY st.order "
                "RETURN st.name AS step, st.kind AS kind, files",
                id=skill_id, database_=conn.database)
            rows = {r["step"]: (r["kind"], sorted(r["files"])) for r in records}
        self.assertEqual(rows["escalate"], ("execution", ["assets/config.json", "scripts/escalate.py"]))
        self.assertEqual(rows["by-tone"][0], "router")


if __name__ == "__main__":
    unittest.main()
