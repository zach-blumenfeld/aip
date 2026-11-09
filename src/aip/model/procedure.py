"""The compiled procedure as the runtime reads it: a bundle's graph behind a Relate connection,
one Cypher query per thing a step needs (spec 4; `docs/language/runtime.md`, Loading).

`Procedure.load(bundle)` writes a verified bundle into an in-memory Relate store and answers
from there; `Procedure(conn, bundle_id)` reads the same graph from any store `aip_spec.write_graph`
wrote it to, a server's catalog included, since every node is matched by `{bundle_id, id}`. The
queries are the schema of `docs/language/bundle.md` read back; nothing here decides what a step
means, only what the bundle says about it. A step is read once per run and kept; the graph never
changes under a run.

A Relate connection belongs to the thread that opened it, so a `Procedure` is used on one thread."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from aip_spec import Bundle, FileEntry, write_graph
from aip_spec.graph import PROCEDURE_ID

from aip.model.types import JSON

STEP_KINDS = ("Start", "Decide", "Route", "Aggregate", "Execute", "Task_Agent", "End")
FLOW_TYPES = ("NEXT", "CONTINUES", "AGAIN", "BRANCH", "BELOW")


@dataclass(frozen=True)
class Read:
    """A `READS` edge: the key, its declared type, the field after it (`tone` in
    `triage_decision.tone`), and whether it is an interpolation rather than a `Read`."""
    key: str
    type: str | None
    field: str | None = None
    interpolated: bool = False

    @property
    def path(self) -> list[str]:
        return [self.key, *self.field.split(".")] if self.field else [self.key]

    @property
    def dotted(self) -> str:
        return ".".join(self.path)

    @property
    def name(self) -> str:
        """The name the step sees the value under: the last segment of the path (spec 2.4)."""
        return self.path[-1]


@dataclass(frozen=True)
class Produce:
    key: str
    type: str | None
    description: str | None = None


@dataclass(frozen=True)
class Flow:
    """An outgoing flow edge: `NEXT`, `CONTINUES`, `AGAIN`, `BRANCH` (with `value`) or `BELOW`
    (with `below`); `to` is the target node's id, `continues` marks a branch to `Continue`."""
    type: str
    to: str
    value: str | None = None
    below: float | None = None
    continues: bool = False


@dataclass(frozen=True)
class Question:
    name: str
    type: str
    labels: list[str] | None
    instruction: str
    criteria: list[tuple[str, str]]
    order: int


@dataclass(frozen=True)
class Aggregation:
    name: str
    mode: str
    source: list[str]
    operator: str | None
    value: str | None
    confidence_above: float | None
    order: int

    @property
    def dotted(self) -> str:
        return ".".join(self.source)


@dataclass(frozen=True)
class FileUse:
    """A `RUNS`, `PROMPTED_BY` or `USES` edge to a file."""
    relation: str
    path: str
    description: str | None = None

    @property
    def folder(self) -> str:
        return self.path.split("/", 1)[0]

    @property
    def stem(self) -> str:
        return self.path.rsplit("/", 1)[-1].rsplit(".", 1)[0]


@dataclass
class Step:
    """One step as the graph describes it."""
    id: str
    name: str
    kind: str
    description: str
    properties: JSON
    reads: list[Read] = field(default_factory=list)
    produces: list[Produce] = field(default_factory=list)
    flows: list[Flow] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)
    aggregations: list[Aggregation] = field(default_factory=list)
    files: list[FileUse] = field(default_factory=list)

    @property
    def declared_reads(self) -> list[Read]:
        """The `Read` clause: what the step is given (interpolations are reads for lineage, not data)."""
        return [r for r in self.reads if not r.interpolated]

    @property
    def next(self) -> Flow | None:
        found = [f for f in self.flows if f.type in ("NEXT", "CONTINUES", "AGAIN")]
        return found[0] if found else None

    @property
    def branches(self) -> list[Flow]:
        return [f for f in self.flows if f.type == "BRANCH"]

    @property
    def check(self) -> Flow | None:
        found = [f for f in self.flows if f.type == "BELOW"]
        return found[0] if found else None

    def produced_key(self) -> str | None:
        """The one key a `Decide` or `Aggregate` writes."""
        return self.properties.get("produces")

    def file(self, relation: str) -> FileUse | None:
        found = [f for f in self.files if f.relation == relation]
        return found[0] if found else None

    def uses(self, folder: str) -> list[FileUse]:
        return [f for f in self.files if f.relation == "USES" and f.folder == folder]


class Procedure:
    """A bundle's graph behind a connection. `bundle_id` scopes every query."""

    def __init__(self, conn, bundle_id: str, *, owns_connection: bool = False):
        self.conn = conn
        self.bundle_id = bundle_id
        self._owns = owns_connection
        self._steps: dict[str, Step] = {}
        self._labels: dict[tuple[str, ...], list[str] | None] = {}
        header = self._one("MATCH (p:Procedure {bundle_id: $b, id: $id}) RETURN properties(p) AS p", id=PROCEDURE_ID)
        if header is None:
            raise ValueError(f"the store holds no procedure with bundle id {bundle_id}")
        self.header: JSON = {k: v for k, v in header["p"].items() if k != "source"}

    @classmethod
    def load(cls, bundle: Bundle) -> "Procedure":
        """A verified bundle loaded into an in-memory Relate store."""
        from aip_spec import relate

        conn = relate.connect(":memory:", read_only=False)
        write_graph(conn, bundle.graph, bundle.id)
        return cls(conn, bundle.id, owns_connection=True)

    def close(self) -> None:
        if self._owns and self.conn is not None:
            self.conn.close()
            self.conn = None

    def __enter__(self) -> "Procedure":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------ queries

    def _rows(self, query: str, **params) -> list[dict]:
        return [dict(r) for r in self.conn.execute(query, {"b": self.bundle_id, **params}).fetchall()]

    def _one(self, query: str, **params) -> dict | None:
        rows = self._rows(query, **params)
        return rows[0] if rows else None

    @property
    def name(self) -> str:
        return self.header["name"]

    @property
    def requires(self) -> tuple[str, str | None] | None:
        """`Requires <interpreter> <version>`, or None when the header has none."""
        interpreter = self.header.get("requires_interpreter")
        return (interpreter, self.header.get("requires_version")) if interpreter else None

    @property
    def start(self) -> str:
        row = self._one("MATCH (p:Procedure {bundle_id: $b})-[:STARTS_AT]->(s) RETURN s.id AS id")
        return row["id"]

    def step(self, id: str) -> Step:
        """The step with node id `id` (`step:<name>`), read once."""
        if id not in self._steps:
            self._steps[id] = self._read_step(id)
        return self._steps[id]

    def step_named(self, name: str) -> Step:
        return self.step(f"step:{name}")

    def is_loop(self, id: str) -> bool:
        return id.startswith("loop:")

    def _read_step(self, id: str) -> Step:
        row = self._one("MATCH (s:Step {bundle_id: $b, id: $id}) RETURN properties(s) AS p", id=id)
        if row is None:
            raise KeyError(f"no step {id} in bundle {self.bundle_id}")
        props = dict(row["p"])
        step = Step(id, props["name"], props["kind"], props.get("description") or "", props)
        step.reads = [Read(r["name"], r.get("type"), r.get("field"), bool(r.get("interpolated")))
                      for r in self._rows("MATCH (s {bundle_id: $b, id: $id})-[r:READS]->(k:Key) "
                                          "RETURN k.name AS name, k.type AS type, r.field AS field, r.interpolated AS interpolated, "
                                          "r.line AS line, r.column AS column ORDER BY r.line, r.column", id=id)]
        step.produces = [Produce(r["name"], r.get("type"), r.get("description"))
                         for r in self._rows("MATCH (s {bundle_id: $b, id: $id})-[e:PRODUCES]->(k:Key) "
                                             "RETURN k.name AS name, k.type AS type, k.description AS description, "
                                             "e.line AS line, e.column AS column ORDER BY e.line, e.column", id=id)]
        step.flows = [Flow(r["type"], r["to"], r["p"].get("value"), r["p"].get("below"), bool(r["p"].get("continues")))
                      for r in self._rows("MATCH (s {bundle_id: $b, id: $id})-[e:NEXT|CONTINUES|AGAIN|BRANCH|BELOW]->(t) "
                                          "RETURN type(e) AS type, properties(e) AS p, t.id AS to", id=id)]
        step.flows.sort(key=lambda f: (f.type, f.value or ""))
        step.questions = [Question(q["name"], q["type"], list(q["labels"]) if q.get("labels") else None, q.get("instruction") or "",
                                   list(zip(q.get("criteria_labels") or [], q.get("criteria_texts") or [])), q["order"])
                          for q in (r["q"] for r in self._rows(
                              "MATCH (s {bundle_id: $b, id: $id})-[a:ASKS]->(q:Question) RETURN properties(q) AS q ORDER BY a.order", id=id))]
        step.aggregations = [Aggregation(a["name"], a["mode"], a["source"].split("."), a.get("operator"), a.get("value"),
                                         a.get("confidence_above"), a["order"])
                             for a in (r["a"] for r in self._rows(
                                 "MATCH (s {bundle_id: $b, id: $id})-[e:AGGREGATES]->(a:Aggregation) RETURN properties(a) AS a "
                                 "ORDER BY e.order", id=id))]
        step.files = [FileUse(r["type"], r["path"], r.get("description"))
                      for r in self._rows("MATCH (s {bundle_id: $b, id: $id})-[e:RUNS|PROMPTED_BY|USES]->(f:File) "
                                          "RETURN type(e) AS type, f.path AS path, e.description AS description, "
                                          "e.line AS line, e.column AS column ORDER BY e.line, e.column", id=id)]
        return step

    def files(self) -> list[FileEntry]:
        """Every file the bundle carries, with its bytes."""
        rows = self._rows("MATCH (f:File {bundle_id: $b}) RETURN properties(f) AS f ORDER BY f.path")
        return [FileEntry.from_properties(r["f"]) for r in rows]

    def file_text(self, path: str) -> str:
        row = self._one("MATCH (f:File {bundle_id: $b, path: $path}) RETURN properties(f) AS f", path=path)
        if row is None:
            raise KeyError(f"no file {path} in bundle {self.bundle_id}")
        return FileEntry.from_properties(row["f"]).data.decode("utf-8")

    def key_type(self, name: str) -> str | None:
        row = self._one("MATCH (k:Key {bundle_id: $b, name: $name}) RETURN k.type AS type", name=name)
        return row["type"] if row else None

    def labels_of(self, path: list[str]) -> list[str] | None:
        """The labels of the answer a dotted path names (`triage_decision.tone` → the question's
        labels), following a collected list to its per-pass key; None for a `true_or_false`, a
        script's answer, or an unknown path."""
        key = tuple(path)
        if key not in self._labels:
            self._labels[key] = self._find_labels(list(path))
        return self._labels[key]

    def _find_labels(self, path: list[str]) -> list[str] | None:
        root, rest = path[0], path[1:]
        type = self.key_type(root)
        if type == "list":
            row = self._one("MATCH (l:Loop {bundle_id: $b})-[:PRODUCES]->(:Key {name: $name}), (l)-[:COLLECTS]->(k:Key) "
                            "RETURN k.name AS name", name=root)
            return self._find_labels([row["name"], *rest]) if row else None
        if type == "decision" and rest:
            row = self._one("MATCH (d:Decide {bundle_id: $b})-[:PRODUCES]->(:Key {name: $name}), (d)-[:ASKS]->(q:Question {name: $q}) "
                            "RETURN q.labels AS labels", name=root, q=rest[0])
            return list(row["labels"]) if row and row.get("labels") else None
        return None

    def describe(self) -> JSON:
        """The header and every step's kind, for `info`."""
        rows = self._rows("MATCH (s:Step {bundle_id: $b}) RETURN s.name AS name, s.kind AS kind ORDER BY s.line")
        return {"name": self.name, "bundle_id": self.bundle_id, "description": self.header.get("description", ""),
                "steps": {r["name"]: r["kind"] for r in rows}}


__all__ = ["Procedure", "Step", "Read", "Produce", "Flow", "Question", "Aggregation", "FileUse", "STEP_KINDS", "FLOW_TYPES"]
