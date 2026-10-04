"""Load AIP skills into Neo4j losslessly, and export them back to disk.

Two layers per skill, as defined by the records in `aip.server.records`:

- **Artifact** (lossless): every file under the skill folder as a `File` node holding
  its exact bytes (text as UTF-8, anything else base64), size, sha256, and mode, plus
  the directory list. `export` rebuilds the folder byte for byte and verifies hashes.
- **Projection** (queryable): the parsed procedure as `Procedure`, `Step` (labelled by
  kind), `Input`, and `Question` nodes with `INPUTS_TO`, `BRANCH`, `DECLARES_INPUT`,
  `ASKS`, and `USES` edges. `USES` edges point at the `File` nodes, so resource
  questions ("which skills run this script?") are one hop.

Identity: `Skill.id = "<name>@<revision>"`, where `revision` is a sha256 over every
file's path and bytes. Reloading identical content is a no-op; changed content becomes
a new revision alongside the old one. `Skill.name` groups revisions; the latest is the
newest `loaded_at`.

The record types and the folder <-> record conversions live in `aip.server.records`;
`Bundle` is kept here as an alias of `SkillRecord` for callers of the 0.4 API.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from aip.server.records import (IGNORE_DIRS, IGNORE_FILES, IGNORE_SUFFIXES, FileRecord, SkillRecord,  # noqa: F401
                                materialize, snapshot, write_files)

JSON = Dict[str, Any]

Bundle = SkillRecord

STEP_LABELS = {"decision": "Decision", "execution": "Execution", "client_task": "ClientTask",
               "router": "Router", "end": "End"}


# --------------------------------------------------------------------------- cypher

CONSTRAINTS = [
    "CREATE CONSTRAINT aip_skill_id IF NOT EXISTS FOR (s:Skill) REQUIRE s.id IS UNIQUE",
    "CREATE CONSTRAINT aip_file_key IF NOT EXISTS FOR (f:File) REQUIRE f.key IS UNIQUE",
    "CREATE CONSTRAINT aip_procedure_key IF NOT EXISTS FOR (p:Procedure) REQUIRE p.key IS UNIQUE",
    "CREATE CONSTRAINT aip_step_key IF NOT EXISTS FOR (s:Step) REQUIRE s.key IS UNIQUE",
    "CREATE CONSTRAINT aip_input_key IF NOT EXISTS FOR (i:Input) REQUIRE i.key IS UNIQUE",
    "CREATE CONSTRAINT aip_question_key IF NOT EXISTS FOR (q:Question) REQUIRE q.key IS UNIQUE",
    "CREATE INDEX aip_skill_name IF NOT EXISTS FOR (s:Skill) ON (s.name)",
]

DELETE_REVISION = """
MATCH (s:Skill {id: $id})
OPTIONAL MATCH (s)-[:HAS_FILE]->(f)
OPTIONAL MATCH (s)-[:HAS_PROCEDURE]->(p)
OPTIONAL MATCH (p)-[:HAS_STEP]->(st)
OPTIONAL MATCH (st)-[:DECLARES_INPUT|ASKS]->(leaf)
DETACH DELETE leaf, st, p, f, s
"""

CREATE_SKILL = """
CREATE (s:Skill {id: $skill.id, name: $skill.name, revision: $skill.revision,
                 description: $skill.description, aip_version: $skill.aip_version,
                 frontmatter: $skill.frontmatter, root_name: $skill.root_name,
                 directories: $directories, loaded_at: datetime($loaded_at)})
"""

CREATE_FILES = """
MATCH (s:Skill {id: $id})
UNWIND $files AS f
CREATE (x:File {key: $id + ':' + f.path, skill_id: $id, path: f.path, size: f.size, sha256: f.sha256,
                mode: f.mode, encoding: f.encoding, content: f.content})
CREATE (s)-[:HAS_FILE]->(x)
"""

CREATE_PROCEDURE = """
MATCH (s:Skill {id: $id})
CREATE (p:Procedure {key: $id, skill_id: $id, purpose: $p.purpose, trigger_when: $p.trigger_when,
                     do_not_use_when: $p.do_not_use_when, anti_patterns: $p.anti_patterns})
CREATE (s)-[:HAS_PROCEDURE]->(p)
"""

# One statement per kind so each step gets its kind label without dynamic labels.
CREATE_STEPS = {
    kind: f"""
MATCH (p:Procedure {{key: $id}})
UNWIND $steps AS st
CREATE (n:Step:{label} {{key: $id + ':' + st.name, skill_id: $id, name: st.name, kind: st.kind,
                          order: st.order, description: st.description}})
SET n += st.props
CREATE (p)-[:HAS_STEP {{order: st.order}}]->(n)
"""
    for kind, label in STEP_LABELS.items()
}

MARK_ENDPOINTS = """
MATCH (p:Procedure {key: $id})
MATCH (a:Step {key: $id + ':' + $start}), (z:Step {key: $id + ':' + $end})
CREATE (p)-[:STARTS_AT]->(a)
CREATE (p)-[:ENDS_AT]->(z)
"""

CREATE_EDGES = """
UNWIND $edges AS e
MATCH (a:Step {key: $id + ':' + e.from}), (b:Step {key: $id + ':' + e.to})
CREATE (a)-[:INPUTS_TO]->(b)
"""

CREATE_BRANCHES = """
UNWIND $branches AS b
MATCH (r:Step {key: $id + ':' + b.router}), (t:Step {key: $id + ':' + b.to})
CREATE (r)-[:BRANCH {value: b.value}]->(t)
"""

CREATE_INPUTS = """
UNWIND $inputs AS i
MATCH (st:Step {key: $id + ':' + i.step})
CREATE (n:Input {key: $id + ':' + i.step + ':' + i.name, skill_id: $id, name: i.name, type: i.type,
                 description: i.description, order: i.order})
CREATE (st)-[:DECLARES_INPUT]->(n)
"""

CREATE_QUESTIONS = """
UNWIND $questions AS q
MATCH (st:Step {key: $id + ':' + q.step})
CREATE (n:Question {key: $id + ':' + q.step + ':' + q.name, skill_id: $id, name: q.name, type: q.type,
                    instructions: q.instructions, criteria: q.criteria, threshold: q.threshold, order: q.order})
CREATE (st)-[:ASKS]->(n)
"""

CREATE_RESOURCES = """
UNWIND $resources AS r
MATCH (st:Step {key: $id + ':' + r.step}), (f:File {key: $id + ':' + r.path})
CREATE (st)-[:USES {role: r.role, description: r.description}]->(f)
"""

FETCH_SKILL = """
MATCH (s:Skill {name: $name})
WHERE $revision IS NULL OR s.revision = $revision
WITH s ORDER BY s.loaded_at DESC LIMIT 1
OPTIONAL MATCH (s)-[:HAS_FILE]->(f)
WITH s, f ORDER BY f.path
RETURN s.id AS id, s.name AS name, s.revision AS revision, s.root_name AS root_name,
       s.directories AS directories,
       collect({path: f.path, size: f.size, sha256: f.sha256, mode: f.mode, encoding: f.encoding, content: f.content}) AS files
"""

LIST_SKILLS = """
MATCH (s:Skill)
OPTIONAL MATCH (s)-[:HAS_FILE]->(f)
WITH s, count(f) AS files
OPTIONAL MATCH (s)-[:HAS_PROCEDURE]->(:Procedure)-[:HAS_STEP]->(st)
WITH s, files, count(st) AS steps
RETURN s.name AS name, s.revision AS revision, s.aip_version AS aip_version,
       toString(s.loaded_at) AS loaded_at, files, steps, s.description AS description
ORDER BY name, s.loaded_at DESC
"""


def _step_props(step: JSON) -> JSON:
    """Kind-specific scalar properties, everything except the shared columns."""
    shared = {"name", "kind", "order", "description"}
    return {k: v for k, v in step.items() if k not in shared and v is not None}


def write_bundle(tx, bundle: Bundle) -> None:
    """Write one skill revision inside an open write transaction. Replaces an existing copy of the same id."""
    sid = bundle.id
    skill = {"id": sid, "name": bundle.name, "revision": bundle.revision, "description": bundle.description,
             "aip_version": bundle.aip_version, "frontmatter": json.dumps(bundle.frontmatter, sort_keys=True),
             "root_name": bundle.root_name}
    tx.run(DELETE_REVISION, id=sid)
    tx.run(CREATE_SKILL, skill=skill, directories=bundle.directories,
           loaded_at=datetime.now(timezone.utc).isoformat())
    tx.run(CREATE_FILES, id=sid, files=[f.to_json() for f in bundle.files])
    tx.run(CREATE_PROCEDURE, id=sid, p=bundle.procedure)
    for kind, query in CREATE_STEPS.items():
        rows = [{"name": s["name"], "kind": s["kind"], "order": s["order"], "description": s["description"],
                 "props": _step_props(s)} for s in bundle.steps if s["kind"] == kind]
        if rows:
            tx.run(query, id=sid, steps=rows)
    tx.run(MARK_ENDPOINTS, id=sid, start=bundle.procedure["start"], end=bundle.procedure["end"])
    tx.run(CREATE_EDGES, id=sid, edges=bundle.edges)
    tx.run(CREATE_BRANCHES, id=sid, branches=bundle.branches)
    tx.run(CREATE_INPUTS, id=sid, inputs=bundle.inputs)
    tx.run(CREATE_QUESTIONS, id=sid, questions=bundle.questions)
    tx.run(CREATE_RESOURCES, id=sid, resources=bundle.resources)


# ------------------------------------------------------------------------- database


@dataclass
class Connection:
    uri: str = field(default_factory=lambda: os.environ.get("NEO4J_URI", "neo4j://localhost:7687"))
    user: str = field(default_factory=lambda: os.environ.get("NEO4J_USERNAME", "neo4j"))
    password: str = field(default_factory=lambda: os.environ.get("NEO4J_PASSWORD", ""))
    database: str = field(default_factory=lambda: os.environ.get("NEO4J_DATABASE", "neo4j"))

    def driver(self):
        try:
            from neo4j import GraphDatabase
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("the Neo4j driver is not installed; install with `uv sync --extra neo4j`") from exc
        # notifications off: an empty database otherwise logs a warning per unknown label on every read
        return GraphDatabase.driver(self.uri, auth=(self.user, self.password), notifications_min_severity="OFF")


def ensure_schema(driver, database: str) -> None:
    for statement in CONSTRAINTS:
        driver.execute_query(statement, database_=database)


def load(skill_dir: Path, conn: Connection | None = None) -> str:
    """Validate, snapshot, and write a skill. Returns the skill id (`name@revision`)."""
    conn = conn or Connection()
    bundle = snapshot(skill_dir)
    with conn.driver() as driver:
        driver.verify_connectivity()
        ensure_schema(driver, conn.database)
        with driver.session(database=conn.database) as session:
            session.execute_write(write_bundle, bundle)
    return bundle.id


def fetch(name: str, revision: str | None = None, conn: Connection | None = None) -> JSON | None:
    conn = conn or Connection()
    with conn.driver() as driver:
        records, _, _ = driver.execute_query(FETCH_SKILL, name=name, revision=revision, database_=conn.database)
    if not records or records[0]["id"] is None:
        return None
    record = records[0].data()
    record["files"] = [f for f in record["files"] if f["path"] is not None]
    return record


def export(name: str, out_dir: Path, revision: str | None = None, conn: Connection | None = None) -> Path:
    """Rebuild a skill folder from the database at out_dir/<name>. Verifies every file hash."""
    record = fetch(name, revision, conn)
    if record is None:
        raise KeyError(f"no skill named {name!r}" + (f" at revision {revision}" if revision else ""))
    target = Path(out_dir) / record["name"]
    write_files([FileRecord.from_json(f) for f in record["files"]], record["directories"] or [], target)
    return target


def list_skills(conn: Connection | None = None) -> List[JSON]:
    conn = conn or Connection()
    with conn.driver() as driver:
        records, _, _ = driver.execute_query(LIST_SKILLS, database_=conn.database)
    return [r.data() for r in records]
