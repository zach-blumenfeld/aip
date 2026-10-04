"""The Neo4j backend (design §5.1): the lossless projection, plus names, runs, and search.

Graph per skill revision, as the 0.4 `aip db` projection wrote it:

    (:Name {name, pinned})-[:HAS_REVISION]->(:Skill {id: name@revision, name, revision, description,
                                                     aip_version, frontmatter, manifest, root_name,
                                                     directories, published_at, retired})
    (:Skill)-[:HAS_FILE]->(:File {key, path, size, sha256, mode, encoding, content})
    (:Skill)-[:HAS_PROCEDURE]->(:Procedure {key, purpose, trigger_when, triggers, ...})
    (:Procedure)-[:HAS_STEP {order}]->(:Step:<Kind> {key, name, kind, order, ...})
    (:Procedure)-[:STARTS_AT|ENDS_AT]->(:Step)
    (:Step)-[:INPUTS_TO]->(:Step)        (:Step)-[:BRANCH {value}]->(:Step)
    (:Step)-[:DECLARES_INPUT]->(:Input)  (:Step)-[:ASKS]->(:Question)
    (:Step)-[:USES {role, description}]->(:File)

and per run:

    (:Run {id, name, revision, status, started_at, updated_at, pause})-[:OF_SKILL]->(:Skill)
    (:Run)-[:STEP_RUN]->(:StepRun {order, step, kind, input, result, manual, review, entry, at})
    (:StepRun)-[:NEXT]->(:StepRun)       (:StepRun)-[:OF_STEP]->(:Step)

`Skill.manifest` is the record minus file bytes (what the filesystem backend keeps in
`.aip-manifest.json`), so `get` returns exactly what was published without re-deriving
rows from the graph. `File` nodes carry the bytes; `files` verifies every hash.

Search is a full-text index over `Skill.name`, `Skill.description`, `Procedure.purpose`,
and `Procedure.triggers` (the `trigger_when` list joined). Hits are summed per revision,
filtered to what each name resolves to, and an exact name match is boosted on top.

Materialisation: `folder(name, revision)` rebuilds the skill under
`<cache>/<name>@<revision>/<name>/` (default `~/.cache/aip`, `AIP_CACHE_DIR` overrides)
from the `File` nodes, with the manifest beside the skill folder at
`<cache>/<name>@<revision>/.aip-manifest.json`, and reuses the copy only while every
file still matches its manifest hash.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from aip.server.backend import NotFound, split_ref
from aip.server.records import (MANIFEST, FileRecord, NameSummary, RunRecord, RunSummary, SearchHit,
                                SkillRecord, write_files)

JSON = Dict[str, Any]

STEP_LABELS = {"decision": "Decision", "execution": "Execution", "client_task": "ClientTask",
               "router": "Router", "end": "End"}
AIP_LABELS = ("Name", "Skill", "File", "Procedure", "Step", "Input", "Question", "Run", "StepRun")

FULLTEXT_INDEX = "aip_skill_text"
NAME_BOOST = 1000.0
_WORD = re.compile(r"[a-z0-9]+")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


# ------------------------------------------------------------------------ connection


@dataclass
class Connection:
    """Where the database is; every field defaults to the matching `NEO4J_*` variable."""
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


# ---------------------------------------------------------------------------- cypher

CONSTRAINTS = [
    "CREATE CONSTRAINT aip_name_name IF NOT EXISTS FOR (n:Name) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT aip_skill_id IF NOT EXISTS FOR (s:Skill) REQUIRE s.id IS UNIQUE",
    "CREATE CONSTRAINT aip_file_key IF NOT EXISTS FOR (f:File) REQUIRE f.key IS UNIQUE",
    "CREATE CONSTRAINT aip_procedure_key IF NOT EXISTS FOR (p:Procedure) REQUIRE p.key IS UNIQUE",
    "CREATE CONSTRAINT aip_step_key IF NOT EXISTS FOR (s:Step) REQUIRE s.key IS UNIQUE",
    "CREATE CONSTRAINT aip_input_key IF NOT EXISTS FOR (i:Input) REQUIRE i.key IS UNIQUE",
    "CREATE CONSTRAINT aip_question_key IF NOT EXISTS FOR (q:Question) REQUIRE q.key IS UNIQUE",
    "CREATE CONSTRAINT aip_run_id IF NOT EXISTS FOR (r:Run) REQUIRE r.id IS UNIQUE",
    "CREATE INDEX aip_skill_name IF NOT EXISTS FOR (s:Skill) ON (s.name)",
    "CREATE INDEX aip_run_name IF NOT EXISTS FOR (r:Run) ON (r.name)",
    f"CREATE FULLTEXT INDEX {FULLTEXT_INDEX} IF NOT EXISTS FOR (n:Skill|Procedure) "
    "ON EACH [n.name, n.description, n.purpose, n.triggers]",
]

SKILL_EXISTS = "MATCH (s:Skill {id: $id}) RETURN s.retired AS retired"

UNRETIRE_SKILL = """
MERGE (n:Name {name: $name})
WITH n
MATCH (s:Skill {id: $id})
SET s.retired = false
MERGE (n)-[:HAS_REVISION]->(s)
"""

CREATE_SKILL = """
MERGE (n:Name {name: $skill.name})
CREATE (s:Skill {id: $skill.id, name: $skill.name, revision: $skill.revision,
                 description: $skill.description, aip_version: $skill.aip_version,
                 frontmatter: $skill.frontmatter, manifest: $skill.manifest, root_name: $skill.root_name,
                 directories: $directories, published_at: datetime($published_at), retired: false})
CREATE (n)-[:HAS_REVISION]->(s)
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
                     triggers: $triggers, do_not_use_when: $p.do_not_use_when, anti_patterns: $p.anti_patterns})
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

# Every name with its revisions in publish order: the catalog view resolution works from.
NAME_ENTRIES = """
MATCH (n:Name)
WHERE $name IS NULL OR n.name = $name
OPTIONAL MATCH (n)-[:HAS_REVISION]->(s:Skill)
WITH n, s ORDER BY s.published_at, s.revision
WITH n, collect(CASE WHEN s IS NULL THEN NULL ELSE
     {revision: s.revision, published_at: toString(s.published_at), retired: s.retired,
      description: s.description} END) AS revisions
RETURN n.name AS name, n.pinned AS pinned, [r IN revisions WHERE r IS NOT NULL] AS revisions
ORDER BY name
"""

FETCH_MANIFEST = """
MATCH (s:Skill {id: $id})
RETURN s.manifest AS manifest, toString(s.published_at) AS published_at, s.retired AS retired
"""

FETCH_FILES = """
MATCH (s:Skill {id: $id})
OPTIONAL MATCH (s)-[:HAS_FILE]->(f)
WITH s, f ORDER BY f.path
RETURN s.id AS id, collect({path: f.path, size: f.size, sha256: f.sha256, mode: f.mode, encoding: f.encoding,
                            content: f.content}) AS files
"""

FETCH_FILE = "MATCH (f:File {key: $key}) RETURN f.encoding AS encoding, f.content AS content, f.sha256 AS sha256"

LIST_REVISIONS = """
MATCH (n:Name)-[:HAS_REVISION]->(s:Skill)
WHERE $name IS NULL OR n.name = $name
OPTIONAL MATCH (s)-[:HAS_FILE]->(f)
WITH n, s, count(f) AS files
OPTIONAL MATCH (s)-[:HAS_PROCEDURE]->(:Procedure)-[:HAS_STEP]->(st)
WITH n, s, files, count(st) AS steps
RETURN s.name AS name, s.revision AS revision, s.aip_version AS aip_version,
       toString(s.published_at) AS published_at, s.retired AS retired, n.pinned = s.revision AS pinned,
       files, steps, s.description AS description
ORDER BY name, s.published_at DESC
"""

SEARCH = f"""
CALL db.index.fulltext.queryNodes('{FULLTEXT_INDEX}', $query) YIELD node, score
WITH CASE WHEN node:Skill THEN node.id ELSE node.skill_id END AS id, sum(score) AS score
MATCH (s:Skill {{id: id}})
RETURN s.name AS name, s.revision AS revision, s.description AS description, score
"""

SET_PIN = "MATCH (n:Name {name: $name}) SET n.pinned = $revision"

RETIRE = """
MATCH (n:Name {name: $name})-[:HAS_REVISION]->(s:Skill {revision: $revision})
SET s.retired = true
SET n.pinned = CASE WHEN n.pinned = $revision THEN NULL ELSE n.pinned END
RETURN s.id AS id
"""

CREATE_RUN = """
CREATE (r:Run {id: $id, name: $name, revision: $revision, status: 'running',
               started_at: datetime($now), updated_at: datetime($now), pause: NULL})
WITH r
OPTIONAL MATCH (s:Skill {id: $name + '@' + $revision})
FOREACH (_ IN CASE WHEN s IS NULL THEN [] ELSE [1] END | CREATE (r)-[:OF_SKILL]->(s))
RETURN r.id AS id
"""

RUN_EXISTS = "MATCH (r:Run {id: $id}) RETURN r.id AS id"

APPEND_STEP_RUN = """
MATCH (r:Run {id: $id})
OPTIONAL MATCH (r)-[:STEP_RUN]->(prev:StepRun)
WITH r, prev ORDER BY prev.order DESC LIMIT 1
CREATE (sr:StepRun {order: coalesce(prev.order, -1) + 1, step: $step, kind: $kind, input: $input,
                    result: $result, manual: $manual, review: $review, entry: $entry, at: datetime($now)})
CREATE (r)-[:STEP_RUN]->(sr)
FOREACH (_ IN CASE WHEN prev IS NULL THEN [] ELSE [1] END | CREATE (prev)-[:NEXT]->(sr))
SET r.status = $status, r.pause = $pause, r.updated_at = datetime($now)
WITH r, sr
OPTIONAL MATCH (st:Step {key: r.name + '@' + r.revision + ':' + $step})
FOREACH (_ IN CASE WHEN st IS NULL THEN [] ELSE [1] END | CREATE (sr)-[:OF_STEP]->(st))
RETURN sr.order AS order
"""

FETCH_RUN = """
MATCH (r:Run {id: $id})
OPTIONAL MATCH (r)-[:STEP_RUN]->(sr:StepRun)
WITH r, sr ORDER BY sr.order
RETURN r.id AS id, r.name AS name, r.revision AS revision, r.status AS status,
       toString(r.started_at) AS started_at, toString(r.updated_at) AS updated_at, r.pause AS pause,
       collect(sr.entry) AS history
"""

LIST_RUNS = """
MATCH (r:Run)
WHERE ($name IS NULL OR r.name = $name) AND ($status IS NULL OR r.status = $status)
OPTIONAL MATCH (r)-[:STEP_RUN]->(sr:StepRun)
WITH r, count(sr) AS steps
RETURN r.id AS id, r.name AS name, r.revision AS revision, r.status AS status,
       toString(r.started_at) AS started_at, toString(r.updated_at) AS updated_at, steps
ORDER BY r.started_at DESC, r.id DESC
LIMIT $limit
"""

CLEAR = "MATCH (n) WHERE " + " OR ".join(f"n:{label}" for label in AIP_LABELS) + " DETACH DELETE n"


def ensure_schema(driver, database: str) -> None:
    for statement in CONSTRAINTS:
        driver.execute_query(statement, database_=database)
    driver.execute_query("CALL db.awaitIndexes(60)", database_=database)


def _step_props(step: JSON) -> JSON:
    """Kind-specific scalar properties, everything except the shared columns."""
    shared = {"name", "kind", "order", "description"}
    return {k: v for k, v in step.items() if k not in shared and v is not None}


def _dump(value: Any) -> str | None:
    return None if value is None else json.dumps(value, sort_keys=True)


def _load(text: str | None) -> Any:
    return None if text is None else json.loads(text)


def write_skill(tx, skill: SkillRecord, published_at: str) -> None:
    """Create one revision's whole graph inside an open write transaction."""
    sid = skill.id
    manifest = skill.to_json(with_content=False)
    manifest["published_at"], manifest["retired"] = published_at, False
    node = {"id": sid, "name": skill.name, "revision": skill.revision, "description": skill.description,
            "aip_version": skill.aip_version, "frontmatter": json.dumps(skill.frontmatter, sort_keys=True),
            "manifest": json.dumps(manifest), "root_name": skill.root_name}
    tx.run(CREATE_SKILL, skill=node, directories=skill.directories, published_at=published_at)
    tx.run(CREATE_FILES, id=sid, files=[f.to_json() for f in skill.files])
    tx.run(CREATE_PROCEDURE, id=sid, p=skill.procedure,
           triggers="\n".join(skill.procedure.get("trigger_when") or []))
    for kind, query in CREATE_STEPS.items():
        rows = [{"name": s["name"], "kind": s["kind"], "order": s["order"], "description": s["description"],
                 "props": _step_props(s)} for s in skill.steps if s["kind"] == kind]
        if rows:
            tx.run(query, id=sid, steps=rows)
    tx.run(MARK_ENDPOINTS, id=sid, start=skill.procedure["start"], end=skill.procedure["end"])
    tx.run(CREATE_EDGES, id=sid, edges=skill.edges)
    tx.run(CREATE_BRANCHES, id=sid, branches=skill.branches)
    tx.run(CREATE_INPUTS, id=sid, inputs=skill.inputs)
    tx.run(CREATE_QUESTIONS, id=sid, questions=skill.questions)
    tx.run(CREATE_RESOURCES, id=sid, resources=skill.resources)


def _publish_tx(tx, skill: SkillRecord) -> None:
    if tx.run(SKILL_EXISTS, id=skill.id).single() is not None:
        tx.run(UNRETIRE_SKILL, name=skill.name, id=skill.id)   # republishing a retired revision brings it back
        return
    write_skill(tx, skill, _now())


def default_cache_dir() -> Path:
    return Path(os.environ.get("AIP_CACHE_DIR") or "~/.cache/aip").expanduser()


# ---------------------------------------------------------------------------- catalog


class Neo4jCatalog:
    """`CatalogBackend` over the projection graph."""

    def __init__(self, driver, database: str, cache_dir: Path | None = None):
        self.driver = driver
        self.database = database
        self.cache_dir = Path(cache_dir) if cache_dir is not None else default_cache_dir()

    def _read(self, cypher: str, **params) -> List[JSON]:
        records, _, _ = self.driver.execute_query(cypher, database_=self.database, **params)
        return [r.data() for r in records]

    # --------------------------------------------------------------- resolution

    def _entries(self, name: str | None = None) -> Dict[str, JSON]:
        return {row["name"]: row for row in self._read(NAME_ENTRIES, name=name)}

    def _entry(self, name: str) -> JSON:
        entries = self._entries(name)
        if name not in entries:
            raise NotFound(f"no skill named {name!r}")
        return entries[name]

    @staticmethod
    def _revision_row(entry: JSON, revision: str) -> JSON:
        for row in entry["revisions"]:
            if row["revision"] == revision:
                return row
        raise NotFound(f"no revision {revision!r}")

    @staticmethod
    def _latest_live(entry: JSON) -> str | None:
        live = [r for r in entry["revisions"] if not r["retired"]]
        return live[-1]["revision"] if live else None    # rows come back in publish order

    @classmethod
    def _resolve_entry(cls, entry: JSON, rev: str | None) -> str:
        name = entry["name"]
        if rev is None and entry.get("pinned"):
            return entry["pinned"]
        if rev is None or rev == "latest":
            latest = cls._latest_live(entry)
            if latest is None:
                raise NotFound(f"every revision of {name!r} is retired")
            return latest
        cls._revision_row(entry, rev)
        return rev

    def _require(self, name: str, revision: str) -> str:
        """The skill id, after checking the revision exists."""
        self._revision_row(self._entry(name), revision)
        return f"{name}@{revision}"

    # ------------------------------------------------------------ CatalogBackend

    def publish(self, skill: SkillRecord) -> str:
        with self.driver.session(database=self.database) as session:
            session.execute_write(_publish_tx, skill)
        return skill.revision

    def get(self, name: str, revision: str | None = None) -> SkillRecord:
        name, revision = self.resolve(name if revision is None else f"{name}@{revision}")
        rows = self._read(FETCH_MANIFEST, id=f"{name}@{revision}")
        if not rows:
            raise NotFound(f"no revision {revision!r} of {name!r}")
        record = SkillRecord.from_json(json.loads(rows[0]["manifest"]), files=self.files(name, revision))
        record.published_at = rows[0]["published_at"]
        record.retired = bool(rows[0]["retired"])
        return record

    def files(self, name: str, revision: str) -> List[FileRecord]:
        sid = f"{name}@{revision}"
        rows = self._read(FETCH_FILES, id=sid)
        if not rows:
            raise NotFound(f"no revision {revision!r} of {name!r}")
        out = []
        for entry in rows[0]["files"]:
            if entry["path"] is None:
                continue
            record = FileRecord.from_json(entry)
            digest = hashlib.sha256(record.data).hexdigest()
            if digest != record.sha256:
                raise ValueError(f"{sid}/{record.path}: stored content hash {digest} does not match {record.sha256}")
            out.append(record)
        return out

    def file(self, name: str, revision: str, path: str) -> bytes:
        rows = self._read(FETCH_FILE, key=f"{name}@{revision}:{path}")
        if not rows:
            raise NotFound(f"no file {path!r} in {name}@{revision}")
        data = FileRecord.from_json({"path": path, "size": 0, "mode": 0, **rows[0]}).data
        if hashlib.sha256(data).hexdigest() != rows[0]["sha256"]:
            raise ValueError(f"{name}@{revision}/{path}: stored content does not match its hash")
        return data

    def list(self) -> List[NameSummary]:
        out = []
        for name, entry in sorted(self._entries().items()):
            latest = self._latest_live(entry)
            description, published_at = "", None
            if latest is not None:
                resolved = entry.get("pinned") or latest
                description = self._revision_row(entry, resolved)["description"] or ""
                published_at = self._revision_row(entry, latest)["published_at"]
            out.append(NameSummary(name=name, description=description, latest=latest,
                                   pinned=entry.get("pinned"), revisions=len(entry["revisions"]),
                                   published_at=published_at))
        return out

    def revisions(self, name: str | None = None) -> List[JSON]:
        """Every revision as a flat row (name, revision, aip_version, published_at, retired, pinned,
        files, steps, description), newest first per name. What `aip db list` prints."""
        return self._read(LIST_REVISIONS, name=name)

    def search(self, query: str, limit: int = 10) -> List[SearchHit]:
        terms = _WORD.findall(query.lower())
        if not terms:
            return []
        resolved: Dict[str, str] = {}
        for name, entry in self._entries().items():
            try:
                resolved[name] = self._resolve_entry(entry, None)
            except NotFound:
                continue
        hits: Dict[str, SearchHit] = {}
        for row in self._read(SEARCH, query=" OR ".join(terms)):
            if resolved.get(row["name"]) != row["revision"]:
                continue
            score = float(row["score"])
            if query.strip().lower() == row["name"].lower():
                score += NAME_BOOST
            hits[row["name"]] = SearchHit(name=row["name"], revision=row["revision"],
                                          description=row["description"] or "", score=score)
        return sorted(hits.values(), key=lambda h: (-h.score, h.name))[:limit]

    def pin(self, name: str, revision: str | None) -> None:
        entry = self._entry(name)
        if revision is not None:
            self._revision_row(entry, revision)
        self.driver.execute_query(SET_PIN, name=name, revision=revision, database_=self.database)

    def retire(self, name: str, revision: str) -> None:
        self._require(name, revision)
        self.driver.execute_query(RETIRE, name=name, revision=revision, database_=self.database)

    def resolve(self, ref: str) -> tuple[str, str]:
        name, rev = split_ref(ref)
        return name, self._resolve_entry(self._entry(name), rev)

    # ---------------------------------------------------------- materialisation

    def folder(self, name: str, revision: str) -> Path:
        """The skill folder of a revision on disk, under the cache; rebuilt unless every file still matches its hash."""
        sid = self._require(name, revision)
        target = self.cache_dir / sid
        skill_dir = target / name
        manifest_path = target / MANIFEST
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text())
                if all((skill_dir / f["path"]).is_file()
                       and hashlib.sha256((skill_dir / f["path"]).read_bytes()).hexdigest() == f["sha256"]
                       for f in manifest["files"]):
                    return skill_dir
            except (OSError, ValueError, KeyError):
                pass
        record = self.get(name, revision)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{sid}.", dir=self.cache_dir))
        try:
            write_files(record.files, record.directories, staging / name)
            (staging / MANIFEST).write_text(json.dumps(record.to_json(with_content=False), indent=2) + "\n")
            if target.exists():
                shutil.rmtree(target)
            os.rename(staging, target)
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
        return skill_dir


# ------------------------------------------------------------------------------- runs


class Neo4jRuns:
    """`RunBackend` over `Run` and `StepRun` nodes."""

    def __init__(self, driver, database: str):
        self.driver = driver
        self.database = database

    def _read(self, cypher: str, **params) -> List[JSON]:
        records, _, _ = self.driver.execute_query(cypher, database_=self.database, **params)
        return [r.data() for r in records]

    def create(self, name: str, revision: str) -> str:
        run_id = uuid.uuid4().hex[:16]
        self.driver.execute_query(CREATE_RUN, id=run_id, name=name, revision=revision, now=_now(),
                                  database_=self.database)
        return run_id

    def append(self, run_id: str, entry: JSON, status: str, pause: JSON | None) -> None:
        params = {"id": run_id, "step": entry.get("step"), "kind": entry.get("kind"),
                  "input": _dump(entry.get("input")), "result": _dump(entry.get("result")),
                  "manual": bool(entry.get("manual", False)), "review": _dump(entry.get("review")),
                  "entry": json.dumps(entry, sort_keys=True), "status": status, "pause": _dump(pause),
                  "now": _now()}

        def tx_fn(tx):
            if tx.run(RUN_EXISTS, id=run_id).single() is None:
                raise NotFound(f"no run {run_id!r}")
            tx.run(APPEND_STEP_RUN, **params).consume()

        with self.driver.session(database=self.database) as session:
            session.execute_write(tx_fn)

    def get(self, run_id: str) -> RunRecord:
        rows = self._read(FETCH_RUN, id=run_id)
        if not rows:
            raise NotFound(f"no run {run_id!r}")
        row = rows[0]
        return RunRecord(id=row["id"], name=row["name"], revision=row["revision"], status=row["status"],
                         started_at=row["started_at"], updated_at=row["updated_at"], pause=_load(row["pause"]),
                         history=[_load(e) for e in row["history"] if e is not None])

    def list(self, name: str | None = None, status: str | None = None, limit: int = 50) -> List[RunSummary]:
        return [RunSummary(id=r["id"], name=r["name"], revision=r["revision"], status=r["status"],
                           started_at=r["started_at"], updated_at=r["updated_at"], steps=int(r["steps"]))
                for r in self._read(LIST_RUNS, name=name, status=status, limit=int(limit))]


class Neo4jBackend:
    """Both halves over one driver: `.catalog` is the `CatalogBackend`, `.runs` the `RunBackend`.

    Opens the driver, verifies connectivity, and creates the constraints and the full-text
    index on construction. `close()` (or the context manager) releases the driver.
    """

    def __init__(self, conn: Connection | None = None, cache_dir: Path | None = None):
        self.conn = conn or Connection()
        self.driver = self.conn.driver()
        self.driver.verify_connectivity()
        ensure_schema(self.driver, self.conn.database)
        self.catalog = Neo4jCatalog(self.driver, self.conn.database, cache_dir)
        self.runs = Neo4jRuns(self.driver, self.conn.database)

    def clear(self) -> None:
        """Delete every AIP node (names, skills, files, projection, runs). For tests and resets."""
        self.driver.execute_query(CLEAR, database_=self.conn.database)

    def close(self) -> None:
        self.driver.close()

    def __enter__(self) -> "Neo4jBackend":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
