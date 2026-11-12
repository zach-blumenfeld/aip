"""The server's store: bundles, revisions and runs in one graph, and the one body of Cypher that
reads and writes it, whichever database is underneath (`docs/server-design.md`, The store).

A backend supplies a `Graph`, the thin adapter the Cypher here runs through (`aip.server.backends.relate`
over one Relate file, the default; `aip.server.backends.neo4j` for a shared deployment), and
`Store(graph)` is everything the HTTP API asks of it. Nothing below names either database.

**What the store holds.** Each bundle's own graph exactly as `aip compile` wrote it
(`docs/language/bundle.md`; `aip.compiler.write_graph` puts it there, so a bundle in the store
and a bundle in an `.rl` are the same nodes and edges), and beside it the server's nodes:

    (:Name {name, pinned})-[:HAS_REVISION]->(:Revision {id, name, revision, number, bundle_id, published_at, retired})
    (:Revision)-[:OF]->(:Bundle {bundle_id, name, description, stored_at, draft, described})-[:HOLDS]->(:Procedure)
    (:Run {run_id, bundle_id, name, revision, draft, status, agent, session, user, started, finished, ...})-[:OF]->(:Bundle)
    (:Run)-[:HAS_ENTRY]->(:Entry {run_id, seq, step, kind, pass, at, seconds, ...})-[:THEN]->(:Entry)
    (:Entry)-[:AT]->(:Step | :Loop)                      the node of the bundle's graph the entry ran
    (:Entry)-[:GAVE]->(:Answer {name, value, confidence, source, ...})-[:ANSWERS]->(:Question | :Aggregation)
    (:Entry {kind: 'Execute'})-[:SPAWNED]->(:Run)       a run the entry's script started (its child: `parent_run`, ...)
    (:AuditQuery {name, description, cypher, stored_at})   a query someone stored (`aip.server.audit`)

A bundle is merged by its id: storing one the store holds is a no-op. A `Bundle` with no
`Revision` is a *draft* (uploaded so that runs of a folder or a file can be recorded);
publishing assigns the next number under the procedure's name, and publishing a draft promotes
it. The server's nodes are told from a bundle's by label (`BUNDLE_LABELS`), so the bundle's
graph can be read back whole and handed out as an `.rl` that verifies (`Store.bundle_file`).

**Runs.** The client posts the whole run at every stop and `record` upserts it by `run_id`: the
run's own fields on the `Run` node, one `Entry` per history entry (only the entries that are
new or changed are written), and one `Answer` per answer an entry produced. Each node keeps
the fields an audit asks about as properties (who, when, how long, where a route went and
whether its check fired, why a loop exited) and the entry itself as JSON, so `run(run_id)`
returns the record as it was posted. A run started from another run's script carries `parent`
(`{run_id, step, pass}`); its `Run` node keeps `parent_run`, `parent_step`, `parent_pass` and
`depth`, and the parent's entry for that step and pass is linked to it by `SPAWNED`, made by
whichever of the two is posted second (`run` lists a run's children). Two fields are the server's to say, whatever the client
claimed: `user`, the name of the token the run was posted with, and `draft`, whether the bundle
the run ran has a revision, with the `revision` it is published as (a folder whose bundle is
published is a run of that revision; a bundle with none is a draft whatever the client said).

**An export** (`export_runs`) is a second store in a new Relate file: the runs that match, the
bundles they ran and those bundles' revisions, written by the same statements, so every query
that works on the store works on the file.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from pathlib import Path
from typing import Any, Callable, Protocol, TypeVar

from aip.compiler.bundle import BUNDLE_LABELS, BUNDLE_SUFFIX, Bundle, read_graph, write_graph
from aip.compiler.graph import Graph as BundleGraph
from aip.model.engine import utc_now
from aip.server.search import BM25Index

JSON = dict[str, Any]
T = TypeVar("T")

RUN_ID = re.compile(r"[A-Za-z0-9_-]{4,64}")
SERVER_LABELS = ("Name", "Revision", "Bundle", "Run", "Entry", "Answer", "Meta", "AuditQuery")
SEARCH_WEIGHTS = {"name": 10.0, "description": 3.0, "use_when": 2.0, "steps": 1.0}
NAME_BOOST = 100.0                       # a query that is exactly a published name wins outright
LOOP_KINDS = ("For", "Loop")
SOURCE_OF = {"Decide": "measured", "Execute": "scripted", "Task_Agent": "agent", "Aggregate": "aggregated", "Start": "input"}


class NotFound(KeyError):
    """A name, revision, bundle or run the store does not have (404 over HTTP)."""

    def __str__(self) -> str:  # KeyError quotes its argument; we want the plain message
        return str(self.args[0]) if self.args else ""


class UnknownBundle(NotFound):
    """A run of a bundle the store does not hold: upload it first (`POST /bundles`)."""


class InvalidRun(ValueError):
    """A posted run that cannot be stored as one (422 over HTTP)."""


class RetiredRevision(ValueError):
    """A pin asked for a retired revision: retire wins (409 `retired` over HTTP)."""


def plain(value: Any) -> Any:
    """A value a query returned, as JSON can carry it: a node as `{"labels", "properties"}`, a
    relationship as `{"type", "properties"}`, a path as its `nodes` and `relationships`, maps
    and lists through and through, and anything else that is not a JSON scalar as its text.
    Both engines' node and relationship objects are read by what they have in common."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [plain(v) for v in value]
    if hasattr(value, "nodes") and hasattr(value, "relationships"):
        return {"nodes": [plain(n) for n in value.nodes], "relationships": [plain(r) for r in value.relationships]}
    if hasattr(value, "labels") or hasattr(value, "start_node"):
        properties = getattr(value, "properties", None)
        if callable(properties):
            properties = properties()
        if not isinstance(properties, dict):
            properties = dict(value.items()) if callable(getattr(value, "items", None)) else {}
        head = {"labels": sorted(value.labels)} if hasattr(value, "labels") else {"type": value.type}
        return {**head, "properties": plain(properties)}
    return str(value)


# ------------------------------------------------------------------- the adapter


class Tx(Protocol):
    """One transaction. `run` takes parameters by keyword and returns rows as dicts; `execute`
    is the same call in the shape `aip.compiler.write_graph` and `read_graph` use."""

    def run(self, cypher: str, /, **params: Any) -> list[JSON]: ...
    def execute(self, cypher: str, params: JSON | None = None) -> list[JSON]: ...


class Graph(Protocol):
    """What a backend supplies."""

    def read(self, cypher: str, /, **params: Any) -> list[JSON]:
        """Rows of one read statement."""

    def reading(self, fn: Callable[[Tx], T]) -> T:
        """`fn(tx)` over one consistent view; nothing it does is kept."""

    def write(self, fn: Callable[[Tx], T]) -> T:
        """`fn(tx)` in one transaction: committed when it returns, rolled back when it raises."""

    def schema(self, statements: list[str]) -> None:
        """Run the constraint and index statements, each on its own."""

    def close(self) -> None: ...


# ------------------------------------------------------------------------ cypher

SCHEMA = [
    "CREATE CONSTRAINT aip_name IF NOT EXISTS FOR (n:Name) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT aip_bundle IF NOT EXISTS FOR (b:Bundle) REQUIRE b.bundle_id IS UNIQUE",
    "CREATE CONSTRAINT aip_revision IF NOT EXISTS FOR (r:Revision) REQUIRE r.id IS UNIQUE",
    "CREATE CONSTRAINT aip_run IF NOT EXISTS FOR (r:Run) REQUIRE r.run_id IS UNIQUE",
    "CREATE CONSTRAINT aip_audit_query IF NOT EXISTS FOR (q:AuditQuery) REQUIRE q.name IS UNIQUE",
    "CREATE INDEX aip_entry IF NOT EXISTS FOR (e:Entry) ON (e.run_id, e.seq)",
    *[f"CREATE INDEX aip_{label.lower()}_id IF NOT EXISTS FOR (n:{label}) ON (n.bundle_id, n.id)" for label in BUNDLE_LABELS],
]

HELD = "MATCH (b:Bundle {bundle_id: $bundle}) RETURN b.draft AS draft, b.name AS name"

HOLD = """
MATCH (p:Procedure {bundle_id: $bundle})
CREATE (b:Bundle {bundle_id: $bundle, name: $name, description: $description, stored_at: $at, draft: true, described: $described})
CREATE (b)-[:HOLDS]->(p)
"""

REVISION_OF = "MATCH (r:Revision {bundle_id: $bundle}) RETURN r.name AS name, r.revision AS revision, r.retired AS retired"

# Touching the name first takes its write lock, so two publishes under one name number in turn.
TOUCH_NAME = "MERGE (n:Name {name: $name}) SET n.touched = $at"

NEXT_NUMBER = """
MATCH (n:Name {name: $name})
OPTIONAL MATCH (n)-[:HAS_REVISION]->(r:Revision)
RETURN coalesce(max(r.number), 0) + 1 AS next
"""

CREATE_REVISION = """
MATCH (n:Name {name: $name}), (b:Bundle {bundle_id: $bundle})
CREATE (n)-[:HAS_REVISION]->(r:Revision {id: $id, name: $name, revision: $revision, number: $number, bundle_id: $bundle,
                                         published_at: $at, retired: false})
CREATE (r)-[:OF]->(b)
SET b.draft = false
"""

UNRETIRE = "MATCH (r:Revision {bundle_id: $bundle}) SET r.retired = false"

REVISIONS = """
MATCH (n:Name)-[:HAS_REVISION]->(r:Revision)-[:OF]->(b:Bundle)
WHERE $name IS NULL OR n.name = $name
RETURN n.name AS name, n.pinned AS pinned, r.revision AS revision, r.number AS number, r.bundle_id AS bundle_id,
       r.published_at AS published_at, r.retired AS retired, b.description AS description
ORDER BY name, number DESC
"""

BUNDLES = """
MATCH (b:Bundle)
WHERE $drafts IS NULL OR b.draft = $drafts
OPTIONAL MATCH (r:Revision)-[:OF]->(b)
RETURN b.bundle_id AS bundle_id, b.name AS name, b.description AS description, b.stored_at AS stored_at, b.draft AS draft,
       r.revision AS revision
ORDER BY stored_at DESC, bundle_id
"""

DESCRIBED = "MATCH (b:Bundle {bundle_id: $bundle}) RETURN b.described AS described, b.draft AS draft, b.stored_at AS stored_at"

SEARCH_TEXT = """
MATCH (b:Bundle)-[:HOLDS]->(p:Procedure)
WHERE b.bundle_id IN $bundles
OPTIONAL MATCH (p)-[:HAS_STEP]->(s:Step)
RETURN b.bundle_id AS bundle_id, p.name AS name, p.description AS description, p.use_when AS use_when,
       collect(s.description) AS steps
"""

SET_PIN = "MATCH (n:Name {name: $name}) SET n.pinned = $revision"
RETIRE = "MATCH (r:Revision {id: $id}) SET r.retired = true"
UNPIN_RETIRED = "MATCH (n:Name {name: $name}) WHERE n.pinned = $revision SET n.pinned = null"

UPSERT_RUN = "MERGE (r:Run {run_id: $run_id}) SET r = $props"
LINK_RUN = """
MATCH (r:Run {run_id: $run_id}), (b:Bundle {bundle_id: $bundle})
WHERE NOT (r)-[:OF]->(b)
CREATE (r)-[:OF]->(b)
"""
ENTRY_HASHES = "MATCH (e:Entry {run_id: $run_id}) RETURN e.seq AS seq, e.sha AS sha"
DROP_ENTRIES = """
MATCH (e:Entry {run_id: $run_id}) WHERE e.seq IN $seqs
OPTIONAL MATCH (e)-[:GAVE]->(a:Answer)
DETACH DELETE a, e
"""
CREATE_ENTRIES = """
MATCH (r:Run {run_id: $run_id})
UNWIND $rows AS row
CREATE (r)-[:HAS_ENTRY]->(e:Entry)
SET e = row
"""
LINK_STEPS = """
UNWIND $rows AS row
MATCH (e:Entry {run_id: $run_id, seq: row.seq}), (s:Step {bundle_id: $bundle, name: row.step})
CREATE (e)-[:AT]->(s)
"""
LINK_LOOPS = """
UNWIND $rows AS row
MATCH (e:Entry {run_id: $run_id, seq: row.seq}), (l:Loop {bundle_id: $bundle, name: row.step})
CREATE (e)-[:AT]->(l)
"""
LINK_THEN = """
UNWIND $pairs AS pair
MATCH (a:Entry {run_id: $run_id, seq: pair[0]}), (b:Entry {run_id: $run_id, seq: pair[1]})
CREATE (a)-[:THEN]->(b)
"""
CREATE_ANSWERS = """
UNWIND $rows AS row
MATCH (e:Entry {run_id: $run_id, seq: row.seq})
CREATE (e)-[:GAVE]->(a:Answer)
SET a = row.properties
"""
LINK_QUESTIONS = """
UNWIND $rows AS row
MATCH (a:Answer {run_id: $run_id, seq: row.seq, name: row.name}), (q:Question {bundle_id: $bundle, id: row.target})
CREATE (a)-[:ANSWERS]->(q)
"""
LINK_AGGREGATIONS = """
UNWIND $rows AS row
MATCH (a:Answer {run_id: $run_id, seq: row.seq, name: row.name}), (q:Aggregation {bundle_id: $bundle, id: row.target})
CREATE (a)-[:ANSWERS]->(q)
"""

# A child posted after its parent's entry, or a parent's entries posted after its children: either
# way the entry of the step and pass that started the child gets its SPAWNED edge once.
LINK_TO_PARENT = """
MATCH (c:Run {run_id: $run_id}), (e:Entry {run_id: $parent, step: $step, kind: 'Execute'})
WHERE coalesce(e.pass, -1) = coalesce($pass, -1) AND NOT (e)-[:SPAWNED]->(c)
CREATE (e)-[:SPAWNED]->(c)
"""
LINK_TO_CHILDREN = """
MATCH (c:Run {parent_run: $run_id}), (e:Entry {run_id: $run_id, kind: 'Execute'})
WHERE e.step = c.parent_step AND coalesce(e.pass, -1) = coalesce(c.parent_pass, -1) AND NOT (e)-[:SPAWNED]->(c)
CREATE (e)-[:SPAWNED]->(c)
"""
FETCH_CHILDREN = """
MATCH (c:Run {parent_run: $run_id})
RETURN c.run_id AS run_id, c.name AS name, c.status AS status, c.draft AS draft, c.parent_step AS step, c.parent_pass AS pass,
       c.tokens AS tokens, c.started AS started
ORDER BY coalesce(c.started, c.created), run_id
"""

FETCH_RUN = "MATCH (r:Run {run_id: $run_id}) RETURN r.json AS json"
FETCH_ENTRIES = "MATCH (e:Entry {run_id: $run_id}) RETURN e.json AS json ORDER BY e.seq"

RUN_FILTER = """
MATCH (r:Run)
WHERE ($name IS NULL OR r.name = $name) AND ($status IS NULL OR r.status = $status)
  AND ($agent IS NULL OR r.agent = $agent) AND ($session IS NULL OR r.session = $session)
  AND ($user IS NULL OR r.user = $user) AND ($draft IS NULL OR r.draft = $draft)
"""
LIST_RUNS = RUN_FILTER + """
RETURN r.run_id AS run_id, r.name AS name, r.revision AS revision, r.bundle_id AS bundle_id, r.status AS status, r.draft AS draft,
       r.agent AS agent, r.agent_version AS agent_version, r.session AS session, r.user AS user, r.started AS started,
       r.finished AS finished,
       r.created AS created, r.updated AS updated, r.entries AS entries
ORDER BY coalesce(started, created, updated) DESC, run_id
LIMIT $limit
"""

EXPORT_RUNS = RUN_FILTER + """  AND ($since IS NULL OR coalesce(r.started, r.created) >= $since)
RETURN r.run_id AS run_id, r.bundle_id AS bundle_id
ORDER BY r.updated DESC, run_id
"""
BUNDLE_ROW = """
MATCH (b:Bundle {bundle_id: $bundle})
RETURN b.name AS name, b.description AS description, b.stored_at AS stored_at, b.described AS described
"""
REVISIONS_OF = """
MATCH (r:Revision {bundle_id: $bundle})
RETURN r.name AS name, r.revision AS revision, r.number AS number, r.published_at AS published_at, r.retired AS retired
ORDER BY name, number
"""

STORED_QUERIES = """
MATCH (q:AuditQuery)
RETURN q.name AS name, q.description AS description, q.cypher AS cypher, q.stored_at AS stored_at
ORDER BY name
"""
SAVE_QUERY = "MERGE (q:AuditQuery {name: $name}) SET q.description = $description, q.cypher = $cypher, q.stored_at = $at"
DELETE_QUERY = "MATCH (q:AuditQuery {name: $name}) DELETE q"

OFFERED = "MATCH (m:Meta {key: 'builtins'}) RETURN m.offered AS offered"
SET_OFFERED = "MERGE (m:Meta {key: 'builtins'}) SET m.offered = $offered"

CLEAR = "MATCH (n) WHERE " + " OR ".join(f"n:{label}" for label in SERVER_LABELS + BUNDLE_LABELS) + " DETACH DELETE n"


# ----------------------------------------------------------------- run projection


def _scalar(value: Any) -> Any:
    """A value as a node property: a scalar as it is, anything else as JSON text."""
    return value if value is None or isinstance(value, (str, int, float, bool)) else json.dumps(value, sort_keys=True)


def _clean(properties: JSON) -> JSON:
    return {k: v for k, v in properties.items() if v is not None}


def run_properties(run: JSON) -> JSON:
    """The `Run` node of a posted run: the fields a list or an audit query filters on, and
    the run without its history as JSON (the history is the `Entry` nodes)."""
    identity = run.get("identity") or {}
    pause, error = run.get("pause") or {}, run.get("error") or {}
    parent = run.get("parent") if isinstance(run.get("parent"), dict) else {}
    tokens = run.get("tokens") or {}
    head = {k: v for k, v in run.items() if k not in ("history", "children")}
    return _clean({
        "run_id": run["run_id"], "bundle_id": run["bundle_id"], "name": run.get("name"), "revision": run.get("revision"),
        "draft": bool(run.get("draft")), "status": run.get("status"),
        "agent": identity.get("agent"), "agent_version": identity.get("agent_version"), "session": identity.get("session"),
        "user": identity.get("user"), "started": run.get("started"), "finished": run.get("finished"), "created": run.get("created"),
        "updated": run.get("updated") or utc_now(), "position": _scalar(run.get("position")), "batch": run.get("batch"),
        "entries": len(run.get("history") or []),
        "paused_at": pause.get("step"), "paused_since": pause.get("since"), "tasks": len(pause.get("tasks") or []) or None,
        "error": error.get("error"), "error_step": error.get("step") or error.get("loop"), "error_message": error.get("message"),
        "parent_run": parent.get("run_id"), "parent_step": parent.get("step"), "parent_pass": parent.get("pass"),
        "depth": run.get("depth") if parent else None, "budget_tokens": run.get("budget_tokens"),
        "tokens": tokens.get("total") if isinstance(tokens, dict) else None,
        "json": json.dumps(head, sort_keys=True),
    })


def entry_properties(run_id: str, bundle_id: str, seq: int, entry: JSON) -> JSON:
    """The `Entry` node of one history entry: every field of the record that is a single value
    (the timings, who answered, where a route went and what its check found, why a loop exited,
    what the head of the pass found of `Until`), and the entry as JSON."""
    text = json.dumps(entry, sort_keys=True)
    by, check, exit, until = (entry.get(k) or {} for k in ("answered_by", "check", "exit", "until"))
    passes = entry.get("passes") or []
    return _clean({
        "run_id": run_id, "bundle_id": bundle_id, "seq": seq, "sha": hashlib.sha256(text.encode("utf-8")).hexdigest(), "json": text,
        "step": entry.get("step"), "kind": entry.get("kind"), "pass": entry.get("pass"),
        "loop": passes[-1].get("loop") if passes else None, "loops": [f"{p.get('loop')} {p.get('pass')}" for p in passes] or None,
        "at": entry.get("at"), "seconds": entry.get("seconds"), "model_seconds": entry.get("model_seconds"),
        "waited_seconds": entry.get("waited_seconds"), "batched": entry.get("batched"), "batch_size": entry.get("batch_size"),
        "history_sent": entry.get("history_sent"),
        "model": by.get("model"), "endpoint": by.get("endpoint"), "agent": by.get("agent"), "session": by.get("session"),
        "read": entry.get("read"), "value": _scalar(entry.get("value")), "to": entry.get("to"),
        "check_fired": check.get("fired"), "check_reason": check.get("reason"), "check_confidence": check.get("confidence"),
        "check_below": check.get("below"),
        "exit": exit.get("reason"), "exit_where": exit.get("where"), "iterations": (entry.get("result") or {}).get("iterations")
        if entry.get("kind") in LOOP_KINDS else None,
        "until_holds": until.get("holds"), "until_where": until.get("where"),
        "script": entry.get("script"),
        "work": entry.get("work"), "work_seconds": entry.get("work_seconds"),
        "tool_calls": len(entry["tool_calls"]) if isinstance(entry.get("tool_calls"), list)
        else entry["tool_calls"] if isinstance(entry.get("tool_calls"), int) else None,
        "tokens": (entry.get("tokens") or {}).get("total") if isinstance(entry.get("tokens"), dict) else None,
    })


def answer_rows(run_id: str, bundle_id: str, seq: int, entry: JSON) -> list[JSON]:
    """The `Answer` nodes of one entry: each answer object among what the step produced (a
    decision's answers with their confidence, an aggregation's value with how many answers it
    judged and how many a bar turned, a labelled answer from a script or an agent). `target` is
    the id of the `Question` or `Aggregation` it answers, when it has one."""
    kind, step = entry.get("kind"), entry.get("step")
    resolutions = entry.get("resolutions") or {}
    rows = []
    for name, answer in (entry.get("result") or {}).items():
        if not isinstance(answer, dict) or "value" not in answer:
            continue
        properties = {"run_id": run_id, "bundle_id": bundle_id, "seq": seq, "step": step, "name": name, "source": SOURCE_OF.get(kind),
                      "value": _scalar(answer.get("value")), "confidence": answer.get("confidence"), "score": answer.get("score"),
                      "probabilities": _scalar(answer.get("probabilities")) if answer.get("probabilities") is not None else None}
        target = None
        if kind == "Decide":
            target = f"question:{step}.{name}"
        elif kind == "Aggregate":
            target = f"aggregation:{step}.{name}"
            judged = resolutions.get(name) or []
            properties.update(answers=len(judged), held=sum(1 for r in judged if r.get("holds")),
                              barred=sum(1 for r in judged if r.get("barred")))
        rows.append({"seq": seq, "name": name, "target": target, "kind": kind, "properties": _clean(properties)})
    return rows


# ------------------------------------------------------------------------- store


class _Reader:
    """`graph.read` in the shape `read_graph` calls a connection."""

    def __init__(self, tx: Tx):
        self.tx = tx

    def execute(self, cypher: str, params: JSON | None = None) -> list[JSON]:
        return self.tx.execute(cypher, params)


class Store:
    """Everything the HTTP API asks of the store, over a backend's `Graph`."""

    def __init__(self, graph: Graph):
        self.graph = graph
        graph.schema(SCHEMA)

    # ---------------------------------------------------------------- bundles

    def has_bundle(self, bundle_id: str) -> bool:
        return bool(self.graph.read(HELD, bundle=bundle_id))

    @staticmethod
    def _hold(tx: Tx, bundle: Bundle, described: JSON, at: str) -> bool:
        """Merge a bundle by id; True when the store held it already."""
        if tx.run(HELD, bundle=bundle.id):
            return True
        write_graph(tx, bundle.graph, bundle.id)
        tx.run(HOLD, bundle=bundle.id, name=bundle.name, description=described.get("description") or "", at=at,
               described=json.dumps(described, sort_keys=True))
        return False

    def draft(self, bundle: Bundle, described: JSON) -> JSON:
        """Hold a bundle with no revision. `{"bundle_id", "name", "existed", "draft"}`; `draft`
        is False when the bundle is already a published revision."""
        at = utc_now()

        def tx_fn(tx: Tx) -> JSON:
            existed = self._hold(tx, bundle, described, at)
            draft = bool(tx.run(HELD, bundle=bundle.id)[0]["draft"])
            return {"bundle_id": bundle.id, "name": bundle.name, "existed": existed, "draft": draft}
        return self.graph.write(tx_fn)

    def publish(self, bundle: Bundle, described: JSON) -> JSON:
        """Hold a bundle and give it the next revision under its procedure's name, unless it has
        one already (then that revision, live again if it was retired). `{"name", "revision",
        "bundle_id", "existed"}`; `existed` says the store held the bundle before this call."""
        at = utc_now()

        def tx_fn(tx: Tx) -> JSON:
            existed = self._hold(tx, bundle, described, at)
            found = tx.run(REVISION_OF, bundle=bundle.id)
            if found:
                if found[0]["retired"]:
                    tx.run(UNRETIRE, bundle=bundle.id)
                return {"name": found[0]["name"], "revision": found[0]["revision"], "bundle_id": bundle.id, "existed": True}
            tx.run(TOUCH_NAME, name=bundle.name, at=at)
            number = int(tx.run(NEXT_NUMBER, name=bundle.name)[0]["next"])
            tx.run(CREATE_REVISION, name=bundle.name, bundle=bundle.id, id=f"{bundle.name}@{number}", revision=str(number),
                   number=number, at=at)
            return {"name": bundle.name, "revision": str(number), "bundle_id": bundle.id, "existed": existed}
        return self.graph.write(tx_fn)

    def bundles(self, drafts: bool | None = None) -> list[JSON]:
        """Every bundle held, newest first; `drafts` True for the drafts alone, False for the published."""
        return self.graph.read(BUNDLES, drafts=drafts)

    def bundle_graph(self, bundle_id: str) -> BundleGraph:
        """The bundle's own graph, as `aip compile` wrote it."""
        if not self.has_bundle(bundle_id):
            raise NotFound(f"the store holds no bundle {bundle_id}")
        return self.graph.reading(lambda tx: read_graph(_Reader(tx), bundle_id, BUNDLE_LABELS))

    def bundle_file(self, bundle_id: str) -> bytes:
        """The bundle as an `.rl`: its subgraph written to a new file, which verifies on the
        other side like any bundle (the id is the content's, not the file's)."""
        from aip.compiler import relate

        graph = self.bundle_graph(bundle_id)
        with tempfile.TemporaryDirectory(prefix="aip-serve-") as tmp:
            path = Path(tmp) / f"bundle{BUNDLE_SUFFIX}"
            with relate.create(path) as conn:
                write_graph(conn, graph, bundle_id)
            return path.read_bytes()

    def describe_bundle(self, bundle_id: str) -> JSON:
        """A bundle's description by id, with `draft` and, when it is published, the `revision`
        it is published as."""
        rows = self.graph.read(DESCRIBED, bundle=bundle_id)
        if not rows:
            raise NotFound(f"the store holds no bundle {bundle_id}")
        published = self.graph.read(REVISION_OF, bundle=bundle_id)
        return {**json.loads(rows[0]["described"]), "bundle_id": bundle_id, "draft": bool(rows[0]["draft"]),
                "revision": published[0]["revision"] if published else None, "stored_at": rows[0]["stored_at"]}

    # ---------------------------------------------------------------- catalog

    @staticmethod
    def _entries(rows: list[JSON]) -> list[JSON]:
        """The catalog's entries from `REVISIONS` rows (by name, newest revision first)."""
        entries: dict[str, JSON] = {}
        for row in rows:
            entry = entries.setdefault(row["name"], {"name": row["name"], "description": None, "pinned": row["pinned"], "latest": None,
                                                     "resolves": None, "revisions": [], "_descriptions": {}})
            entry["revisions"].append({"revision": row["revision"], "bundle_id": row["bundle_id"], "published_at": row["published_at"],
                                       "retired": bool(row["retired"])})
            entry["_descriptions"][row["revision"]] = row["description"]
        for entry in entries.values():
            live = [r["revision"] for r in entry["revisions"] if not r["retired"]]
            entry["latest"] = live[0] if live else None
            if entry["pinned"] not in live:          # retire wins over pin: a pin on a retired revision does not hold
                entry["pinned"] = None
            entry["resolves"] = entry["pinned"] or entry["latest"]
            # a name with every revision retired keeps the description of its newest one
            entry["description"] = entry.pop("_descriptions").get(entry["resolves"] or entry["revisions"][0]["revision"])
        return [entries[name] for name in sorted(entries)]

    def catalog(self) -> list[JSON]:
        """Every published name: `{"name", "description", "pinned", "latest", "resolves",
        "revisions"}`, the revisions newest first, each `{"revision", "bundle_id", "published_at", "retired"}`."""
        return self._entries(self.graph.read(REVISIONS, name=None))

    def entry(self, name: str) -> JSON:
        """One published name. `NotFound` says `no procedure 'x'`, and when the name was written
        with `-` where the published one has `_` (a folder's spelling, `billing-support`), which
        one was meant."""
        found = self._entries(self.graph.read(REVISIONS, name=name))
        if not found:
            meant = name.replace("-", "_")
            hint = f"; did you mean `{meant}`?" if meant != name and self.graph.read(REVISIONS, name=meant) else ""
            raise NotFound(f"no procedure {name!r}{hint}")
        return found[0]

    def resolve(self, ref: str) -> tuple[str, str, str]:
        """`(name, revision, bundle_id)` for `name` (the pinned revision, else the newest live
        one), `name@latest` (the newest live one, whatever is pinned) or `name@<revision>`
        (that one, retired or not)."""
        name, sep, revision = ref.partition("@")
        if not name:
            raise ValueError(f"empty name in ref {ref!r}")
        entry = self.entry(name)
        if not sep or not revision:
            revision = entry["resolves"]
        elif revision == "latest":
            revision = entry["latest"]
        if revision is None:
            count = len(entry["revisions"])
            raise NotFound(f"{name} has no live revision: {'its one revision is' if count == 1 else f'all {count} are'} retired "
                           f"(`{name}@<revision>` still names one; publishing it again brings it back)")
        found = next((r for r in entry["revisions"] if r["revision"] == revision), None)
        if found is None:
            raise NotFound(f"no revision {revision} of {name}")
        return name, revision, found["bundle_id"]

    def describe(self, ref: str) -> JSON:
        """What `aip info` prints for a reference: the procedure's description as stored with
        its bundle, and the revision it is published as."""
        name, revision, bundle_id = self.resolve(ref)
        row = next(r for r in self.entry(name)["revisions"] if r["revision"] == revision)
        return {**self.describe_bundle(bundle_id), "name": name, "revision": revision, "published_at": row["published_at"],
                "retired": row["retired"]}

    def search(self, query: str, limit: int = 10) -> list[JSON]:
        """Published procedures by what they do: BM25 with stemming over the name, description,
        `Use_When` lines and step descriptions of the revision each name resolves to, best
        first. `{"name", "revision", "bundle_id", "score", "description"}`."""
        resolved = {e["name"]: e for e in self.catalog() if e["resolves"] is not None}
        by_bundle = {}
        for entry in resolved.values():
            revision = next(r for r in entry["revisions"] if r["revision"] == entry["resolves"])
            by_bundle[revision["bundle_id"]] = entry
        if not by_bundle:
            return []
        index = BM25Index(SEARCH_WEIGHTS)
        for row in self.graph.read(SEARCH_TEXT, bundles=sorted(by_bundle)):
            entry = by_bundle[row["bundle_id"]]
            index.add(entry["name"], {"name": entry["name"], "description": row["description"] or "",
                                      "use_when": " ".join(row["use_when"] or []), "steps": " ".join(s for s in row["steps"] or [] if s)},
                      payload={"revision": entry["resolves"], "bundle_id": row["bundle_id"], "description": row["description"] or ""})
        exact = query.strip().lower()
        hits = [{"name": name, "revision": doc["revision"], "bundle_id": doc["bundle_id"],
                 "score": score + (NAME_BOOST if name.lower() == exact else 0.0), "description": doc["description"]}
                for name, doc, score in index.search(query, limit=len(index) or 1)]
        hits.sort(key=lambda h: (-h["score"], h["name"]))
        return hits[:limit]

    def pin(self, name: str, revision: str | None) -> None:
        """Make `name` resolve to `revision`; None clears the pin. A retired revision is not
        pinned (`RetiredRevision`): retire wins."""
        entry = self.entry(name)
        found = next((r for r in entry["revisions"] if r["revision"] == revision), None)
        if revision is not None and found is None:
            raise NotFound(f"no revision {revision} of {name}")
        if found is not None and found["retired"]:
            raise RetiredRevision(f"{name}@{revision} is retired, and a retired revision is not pinned; publish it again to bring it "
                                  "back, or pin a live one")
        self.graph.write(lambda tx: tx.run(SET_PIN, name=name, revision=revision))

    def retire(self, name: str, revision: str) -> None:
        """Stop `name` resolving to `revision`, a pin on it included; `name@revision` still
        names it, for the runs that reference it."""
        if not any(r["revision"] == revision for r in self.entry(name)["revisions"]):
            raise NotFound(f"no revision {revision} of {name}")

        def tx_fn(tx: Tx) -> None:
            tx.run(RETIRE, id=f"{name}@{revision}")
            tx.run(UNPIN_RETIRED, name=name, revision=revision)
        self.graph.write(tx_fn)

    # ------------------------------------------------------------------- runs

    def record(self, run: JSON, user: str | None = None, settle: bool = True) -> JSON:
        """Upsert a run by `run_id` where it stopped. The bundle must be held (`UnknownBundle`
        otherwise); `user` is who the server says posted it, whatever the run claims. `draft`
        and `revision` are the store's to say too: a run is a draft's when its bundle has no
        revision, and otherwise it is a run of the revision the bundle is published as, whether
        the client ran it by name or from a folder. `settle=False` keeps both as the run has
        them (an export copies records, it does not judge them).
        `{"run_id", "user", "draft", "revision"}`."""
        run_id, bundle_id = run.get("run_id"), run.get("bundle_id")
        if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
            raise InvalidRun(f"a run is posted with its run_id (4 to 64 letters, digits, - or _), not {run_id!r}")
        if not isinstance(bundle_id, str) or not bundle_id:
            raise InvalidRun("a run is posted with the bundle_id of the bundle it ran")
        history = run.get("history") or []
        if not isinstance(history, list) or not all(isinstance(e, dict) for e in history):
            raise InvalidRun("a run's history is a list of entries")
        run = {**run, "identity": {**(run.get("identity") or {}), "user": user}}
        entries = [entry_properties(run_id, bundle_id, seq, entry) for seq, entry in enumerate(history)]

        def tx_fn(tx: Tx) -> JSON:
            held = tx.run(HELD, bundle=bundle_id)
            if not held:
                raise UnknownBundle(f"the store holds no bundle {bundle_id}; upload it first (POST /bundles)")
            if settle:
                published = tx.run(REVISION_OF, bundle=bundle_id)
                run["draft"] = not published
                run["revision"] = published[0]["revision"] if published else None
            reply = {"run_id": run_id, "user": user, "draft": bool(run.get("draft")), "revision": run.get("revision")}
            props = run_properties(run)
            tx.run(UPSERT_RUN, run_id=run_id, props=props)
            tx.run(LINK_RUN, run_id=run_id, bundle=bundle_id)
            if props.get("parent_run") and props.get("parent_step"):
                tx.run(LINK_TO_PARENT, run_id=run_id, parent=props["parent_run"], step=props["parent_step"],
                       **{"pass": props.get("parent_pass")})
            have = {row["seq"]: row["sha"] for row in tx.run(ENTRY_HASHES, run_id=run_id)}
            stale = sorted(seq for seq, sha in have.items() if seq >= len(entries) or entries[seq]["sha"] != sha)
            new = [e for e in entries if have.get(e["seq"]) != e["sha"]]
            if stale:
                tx.run(DROP_ENTRIES, run_id=run_id, seqs=stale)
            if not new:
                return reply
            tx.run(CREATE_ENTRIES, run_id=run_id, rows=new)
            written = {e["seq"] for e in new}
            at = [{"seq": e["seq"], "step": e.get("step")} for e in new]
            tx.run(LINK_STEPS, run_id=run_id, bundle=bundle_id, rows=[r for r, e in zip(at, new) if e.get("kind") not in LOOP_KINDS])
            tx.run(LINK_LOOPS, run_id=run_id, bundle=bundle_id, rows=[r for r, e in zip(at, new) if e.get("kind") in LOOP_KINDS])
            pairs = {(seq - 1, seq) for seq in written if seq > 0}
            pairs |= {(seq, seq + 1) for seq in written if seq + 1 < len(entries) and seq + 1 not in written}
            tx.run(LINK_THEN, run_id=run_id, pairs=[list(p) for p in sorted(pairs)])
            tx.run(LINK_TO_CHILDREN, run_id=run_id)
            answers = [row for seq in sorted(written) for row in answer_rows(run_id, bundle_id, seq, history[seq])]
            if answers:
                tx.run(CREATE_ANSWERS, run_id=run_id, rows=[{"seq": a["seq"], "properties": a["properties"]} for a in answers])
                for kind, link in (("Decide", LINK_QUESTIONS), ("Aggregate", LINK_AGGREGATIONS)):
                    targets = [{"seq": a["seq"], "name": a["name"], "target": a["target"]} for a in answers if a["kind"] == kind]
                    if targets:
                        tx.run(link, run_id=run_id, bundle=bundle_id, rows=targets)
            return reply
        return self.graph.write(tx_fn)

    def run(self, run_id: str) -> JSON:
        """One run's record, as it was posted (with the server's `user`), and `children`: the runs
        its scripts started, with the step and pass that started each, when it has any."""
        def tx_fn(tx: Tx) -> JSON:
            rows = tx.run(FETCH_RUN, run_id=run_id)
            if not rows:
                raise NotFound(f"no run {run_id}")
            children = [{**c, "draft": bool(c.get("draft")), "tokens": c.get("tokens") or 0}
                        for c in tx.run(FETCH_CHILDREN, run_id=run_id)]
            record = {**json.loads(rows[0]["json"]), "history": [json.loads(r["json"]) for r in tx.run(FETCH_ENTRIES, run_id=run_id)]}
            return {**record, "children": children} if children else record
        return self.graph.reading(tx_fn)

    def runs(self, name: str | None = None, status: str | None = None, agent: str | None = None, session: str | None = None,
             user: str | None = None, draft: bool | None = None, limit: int = 50) -> list[JSON]:
        """Runs, most recently started first: one row each, with `identity` as the record has it."""
        rows = self.graph.read(LIST_RUNS, name=name, status=status, agent=agent, session=session, user=user, draft=draft, limit=limit)
        return [{"run_id": r["run_id"], "name": r["name"], "revision": r["revision"], "bundle_id": r["bundle_id"], "status": r["status"],
                 "draft": bool(r["draft"]),
                 "identity": {"agent": r["agent"], "session": r["session"], "user": r["user"],
                              **({"agent_version": r["agent_version"]} if r.get("agent_version") else {})},
                 "started": r["started"], "finished": r["finished"], "created": r["created"], "updated": r["updated"],
                 "entries": r["entries"]} for r in rows]

    # ---------------------------------------------------------------- export

    def export_runs(self, path: Path, name: str | None = None, since: str | None = None, agent: str | None = None,
                    session: str | None = None, user: str | None = None, draft: bool | None = None) -> JSON:
        """Write the runs that match, and the procedures they ran, as one Relate file at `path`:
        a store of its own, with each run's record, the graph of every bundle among them and
        those bundles' revisions, so the queries of `docs/language/queries.md` answer on it as
        they do here. `since` is a date or a timestamp (ISO 8601) a run started at or after.
        `{"runs", "bundles", "procedures"}`: how many runs, in how many bundles, of how many
        procedures (names; a procedure's revisions and drafts are a bundle each); `NotFound`
        when no run matches."""
        from aip.compiler import relate
        from aip.server.backends.relate import ConnectionGraph

        found = self.graph.read(EXPORT_RUNS, name=name, status=None, agent=agent, session=session, user=user, draft=draft, since=since)
        if not found:
            raise NotFound("no runs match" + (f" since {since}" if since else ""))
        bundle_ids = list(dict.fromkeys(row["bundle_id"] for row in found))
        names = set()
        with relate.create(path) as conn:
            target = Store(ConnectionGraph(conn))
            for bundle_id in bundle_ids:
                held = self.graph.read(BUNDLE_ROW, bundle=bundle_id)[0]
                names.add(held["name"])
                target.adopt(bundle_id, self.bundle_graph(bundle_id), held, self.graph.read(REVISIONS_OF, bundle=bundle_id))
            for row in found:
                run = self.run(row["run_id"])
                target.record(run, user=(run.get("identity") or {}).get("user"), settle=False)
        return {"runs": len(found), "bundles": len(bundle_ids), "procedures": len(names)}

    def adopt(self, bundle_id: str, graph: BundleGraph, row: JSON, revisions: list[JSON]) -> None:
        """Hold a bundle as another store holds it: its graph, when it was stored, and the
        revisions it is published as there (the file's side of `export_runs`)."""
        def tx_fn(tx: Tx) -> None:
            if tx.run(HELD, bundle=bundle_id):
                return
            write_graph(tx, graph, bundle_id)
            tx.run(HOLD, bundle=bundle_id, name=row["name"], description=row["description"] or "", at=row["stored_at"],
                   described=row["described"])
            for r in revisions:
                tx.run(TOUCH_NAME, name=r["name"], at=r["published_at"])
                tx.run(CREATE_REVISION, name=r["name"], bundle=bundle_id, id=f"{r['name']}@{r['revision']}", revision=r["revision"],
                       number=r["number"], at=r["published_at"])
                if r["retired"]:
                    tx.run(RETIRE, id=f"{r['name']}@{r['revision']}")
        self.graph.write(tx_fn)

    # ------------------------------------------------------------ audit queries

    def rows(self, cypher: str, /, **params: Any) -> list[JSON]:
        """Rows of a read query over the store (the audit queries), run in a transaction that
        is never committed, so a query cannot change the store. A row may hold whatever the
        Cypher returns: a node or a relationship comes back as a map (`plain`)."""
        return self.graph.reading(lambda tx: [plain(row) for row in tx.run(cypher, **params)])

    def parses(self, cypher: str, /, **params: Any) -> None:
        """Have the engine plan a statement without running it (`EXPLAIN`); whatever it raises
        for one it cannot parse is the caller's to report."""
        self.graph.reading(lambda tx: tx.run("EXPLAIN " + cypher, **params))

    def stored_queries(self) -> list[JSON]:
        """The queries someone stored: `{"name", "description", "cypher", "stored_at"}`, by name."""
        return self.graph.read(STORED_QUERIES)

    def save_query(self, name: str, description: str, cypher: str) -> None:
        self.graph.write(lambda tx: tx.run(SAVE_QUERY, name=name, description=description, cypher=cypher, at=utc_now()))

    def delete_query(self, name: str) -> bool:
        """Remove a stored query; False when there is none of that name."""
        if not any(q["name"] == name for q in self.stored_queries()):
            return False
        self.graph.write(lambda tx: tx.run(DELETE_QUERY, name=name))
        return True

    # ------------------------------------------------------------ everything else

    def resolved_bundles(self, name: str | None = None) -> list[str]:
        """The bundle id each published name resolves to (one name's when given)."""
        out = []
        for entry in self.catalog():
            if entry["resolves"] is not None and name in (None, entry["name"]):
                out.append(next(r["bundle_id"] for r in entry["revisions"] if r["revision"] == entry["resolves"]))
        return out

    def offered(self) -> list[str]:
        """The ids of the built-in bundles this store has been offered (`aip.server.builtins`)."""
        rows = self.graph.read(OFFERED)
        return list(rows[0]["offered"] or []) if rows else []

    def set_offered(self, bundle_ids: list[str]) -> None:
        self.graph.write(lambda tx: tx.run(SET_OFFERED, offered=sorted(bundle_ids)))

    def clear(self) -> None:
        """Delete everything this module writes (tests)."""
        self.graph.write(lambda tx: tx.run(CLEAR))

    def close(self) -> None:
        self.graph.close()


__all__ = ["BUNDLE_LABELS", "SERVER_LABELS", "SCHEMA", "Graph", "InvalidRun", "NotFound", "RetiredRevision", "Store", "Tx",
           "UnknownBundle", "answer_rows", "entry_properties", "plain", "run_properties"]
