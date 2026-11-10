"""The compiled procedure as the runtime reads it: a bundle's graph behind a Relate connection,
one Cypher query per thing a step needs (spec 4; `docs/language/runtime.md`, Loading).

`Procedure.load(bundle)` writes a verified bundle into an in-memory Relate store and answers
from there; `Procedure(conn, bundle_id)` reads the same graph from any store `aip.compiler.write_graph`
wrote it to, a server's catalog included, since every node is matched by `{bundle_id, id}`. The
queries are the schema of `docs/language/bundle.md` read back; nothing here decides what a step
means, only what the bundle says about it. A step is read once per run and kept; the graph never
changes under a run.

A Relate connection belongs to the thread that opened it, so a `Procedure` is used on one thread."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from aip.compiler import Bundle, FileEntry, write_graph
from aip.compiler.graph import PROCEDURE_ID

from aip.model.types import JSON

STEP_KINDS = ("Start", "Decide", "Route", "Aggregate", "Execute", "Task_Agent", "End")
FLOW_TYPES = ("NEXT", "CONTINUES", "BRANCH", "BELOW")


@dataclass(frozen=True)
class Read:
    """A `READ_BY` edge (`(Data)-[:READ_BY]->(Step)`): the key, its declared type, the field
    after it (`tone` in `triage_decision.tone`), and whether it is an interpolation rather than
    a `Read`."""
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
    """A `PRODUCES` edge: the key, its type, its description, and for a `choice` or `score` key
    produced by an `Execute`, a `Task_Agent` or `Start` its declared labels (spec 2.4)."""
    key: str
    type: str | None
    description: str | None = None
    labels: list[str] | None = None


@dataclass(frozen=True)
class Flow:
    """An outgoing flow edge: `NEXT`, `CONTINUES`, `BRANCH` (with `value`) or `BELOW`
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


@dataclass(frozen=True)
class Until:
    """A `Loop`'s `Until` condition (`WATCHES` edge): the answer's path, the comparison and the bar."""
    path: list[str]
    operator: str | None
    value: str | None
    confidence_above: float | None

    @property
    def dotted(self) -> str:
        return ".".join(self.path)


@dataclass
class Loop:
    """One loop as the graph describes it (`docs/language/bundle.md`, `Loop`). `body` is the
    body's node ids in written order, `enters` the first of them, `exit` the loop's exit line
    (`NEXT` to a step or loop, or `CONTINUES` to the enclosing loop)."""
    id: str
    name: str
    kind: str                 # For | Loop
    mode: str                 # Over | Until | Times
    properties: JSON
    item: str | None = None
    at_most: int | None = None
    times: int | None = None
    at_cap: str | None = None  # Else_Fail | Else_Exit
    collect_key: str | None = None
    collect_into: str | None = None
    over: list[str] | None = None
    until: Until | None = None
    enters: str | None = None
    body: list[str] = field(default_factory=list)
    exit: Flow | None = None

    @property
    def cap(self) -> int | None:
        """The most passes the loop may run: `At_Most`, or the count of a `Times` loop."""
        return self.times if self.mode == "Times" else self.at_most

    @property
    def produced_keys(self) -> set[str]:
        """What the loop itself writes when it exits: `iterations`, and a `For`'s collected list."""
        keys = {"iterations"}
        if self.collect_into:
            keys.add(self.collect_into)
        return keys


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
        found = [f for f in self.flows if f.type in ("NEXT", "CONTINUES")]
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
        self._loops: dict[str, Loop] = {}
        self._labels: dict[tuple[str, ...], list[str] | None] = {}
        header = self._one("MATCH (p:Procedure {bundle_id: $b, id: $id}) RETURN properties(p) AS p", id=PROCEDURE_ID)
        if header is None:
            raise ValueError(f"the store holds no procedure with bundle id {bundle_id}")
        self.header: JSON = {k: v for k, v in header["p"].items() if k != "source"}

    @classmethod
    def load(cls, bundle: Bundle) -> "Procedure":
        """A verified bundle loaded into an in-memory Relate store."""
        from aip.compiler import relate

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
    def source(self) -> str:
        """The text of `procedure.aip`, which the bundle holds byte for byte."""
        row = self._one("MATCH (p:Procedure {bundle_id: $b, id: $id}) RETURN p.source AS source", id=PROCEDURE_ID)
        return (row or {}).get("source") or ""

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

    def loop(self, id: str) -> Loop:
        """The loop with node id `id` (`loop:<name>`), read once."""
        if id not in self._loops:
            self._loops[id] = self._read_loop(id)
        return self._loops[id]

    def _read_loop(self, id: str) -> Loop:
        row = self._one("MATCH (l:Loop {bundle_id: $b, id: $id}) RETURN properties(l) AS p", id=id)
        if row is None:
            raise KeyError(f"no loop {id} in bundle {self.bundle_id}")
        p = dict(row["p"])
        loop = Loop(id, p["name"], p["kind"], p["mode"], p, p.get("item"), p.get("at_most"), p.get("times"), p.get("at_cap"),
                    p.get("collect_key"), p.get("collect_into"))
        over = self._one("MATCH (l {bundle_id: $b, id: $id})-[o:OVER]->(k:Data) RETURN k.name AS name, o.field AS field", id=id)
        if over is not None:
            loop.over = [over["name"], *(over["field"].split(".") if over.get("field") else [])]
        watch = self._one("MATCH (l {bundle_id: $b, id: $id})-[w:WATCHES]->(k:Data) RETURN k.name AS name, properties(w) AS w", id=id)
        if watch is not None:
            w = watch["w"]
            loop.until = Until([watch["name"], *(w["field"].split(".") if w.get("field") else [])], w.get("operator"), w.get("value"),
                               w.get("confidence_above"))
        enters = self._one("MATCH (l {bundle_id: $b, id: $id})-[:ENTERS]->(t) RETURN t.id AS id", id=id)
        loop.enters = enters["id"] if enters else None
        loop.body = [r["id"] for r in self._rows("MATCH (l {bundle_id: $b, id: $id})-[c:CONTAINS]->(t) RETURN t.id AS id ORDER BY c.order",
                                                 id=id)]
        exit = self._one("MATCH (l {bundle_id: $b, id: $id})-[e:NEXT|CONTINUES]->(t) RETURN type(e) AS type, t.id AS to", id=id)
        loop.exit = Flow(exit["type"], exit["to"]) if exit else None
        return loop

    def _read_step(self, id: str) -> Step:
        row = self._one("MATCH (s:Step {bundle_id: $b, id: $id}) RETURN properties(s) AS p", id=id)
        if row is None:
            raise KeyError(f"no step {id} in bundle {self.bundle_id}")
        props = dict(row["p"])
        step = Step(id, props["name"], props["kind"], props.get("description") or "", props)
        step.reads = [Read(r["name"], r.get("type"), r.get("field"), bool(r.get("interpolated")))
                      for r in self._rows("MATCH (k:Data)-[r:READ_BY]->(s {bundle_id: $b, id: $id}) "
                                          "RETURN k.name AS name, k.type AS type, r.field AS field, r.interpolated AS interpolated, "
                                          "r.line AS line, r.column AS column ORDER BY r.line, r.column", id=id)]
        step.produces = [Produce(r["name"], r.get("type"), r.get("description"), list(r["labels"]) if r.get("labels") else None)
                         for r in self._rows("MATCH (s {bundle_id: $b, id: $id})-[e:PRODUCES]->(k:Data) "
                                             "RETURN k.name AS name, k.type AS type, k.description AS description, k.labels AS labels, "
                                             "e.line AS line, e.column AS column ORDER BY e.line, e.column", id=id)]
        step.flows = [Flow(r["type"], r["to"], r["p"].get("value"), r["p"].get("below"), bool(r["p"].get("continues")))
                      for r in self._rows("MATCH (s {bundle_id: $b, id: $id})-[e:NEXT|CONTINUES|BRANCH|BELOW]->(t) "
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
        row = self._one("MATCH (k:Data {bundle_id: $b, name: $name}) RETURN k.type AS type", name=name)
        return row["type"] if row else None

    def labels_of(self, path: list[str]) -> list[str] | None:
        """The labels of the answer a dotted path names: a question's for `triage_decision.tone`,
        the key's own for a `choice` or `score` an `Execute`, a `Task_Agent` or `Start` produced
        under labels (`Produce tone: choice [angry, calm]`), following a collected list to its
        per-pass key; None for a `true_or_false` or an unknown path."""
        key = tuple(path)
        if key not in self._labels:
            self._labels[key] = self._find_labels(list(path))
        return self._labels[key]

    def _find_labels(self, path: list[str]) -> list[str] | None:
        root, rest = path[0], path[1:]
        row = self._one("MATCH (k:Data {bundle_id: $b, name: $name}) RETURN k.type AS type, k.labels AS labels", name=root)
        type = row["type"] if row else None
        if type == "list":
            row = self._one("MATCH (l:Loop {bundle_id: $b})-[:PRODUCES]->(:Data {name: $name}), (l)-[:COLLECTS]->(k:Data) "
                            "RETURN k.name AS name", name=root)
            return self._find_labels([row["name"], *rest]) if row else None
        if type == "decision" and rest:
            row = self._one("MATCH (d:Decide {bundle_id: $b})-[:PRODUCES]->(:Data {name: $name}), (d)-[:ASKS]->(q:Question {name: $q}) "
                            "RETURN q.labels AS labels", name=root, q=rest[0])
            return list(row["labels"]) if row and row.get("labels") else None
        if type in ("choice", "score") and not rest and row.get("labels"):
            return list(row["labels"])
        return None

    def describe(self) -> JSON:
        """The header, every step with its kind and description in source order, and every loop
        with its header as written (`Until check_summary.all_hold, At_Most 3, Else_Fail`) and its
        body. A step or loop says which loop it stands in (`loop`, None at the top level) and
        the line it is written on, so the nesting can be drawn."""
        steps = self._rows("MATCH (s:Step {bundle_id: $b}) RETURN s.name AS name, s.kind AS kind, s.description AS description, "
                           "s.line AS line ORDER BY s.line")
        loops = self._rows("MATCH (l:Loop {bundle_id: $b}) RETURN l.id AS id, l.name AS name, l.kind AS kind, l.mode AS mode, "
                           "l.line AS line ORDER BY l.line")
        inside: dict[str, str] = {}
        bodies: dict[str, list[str]] = {}
        for row in loops:
            body = [id.split(":", 1)[1] for id in self.loop(row["id"]).body]
            bodies[row["name"]] = body
            inside.update({name: row["name"] for name in body})
        return {"name": self.name, "bundle_id": self.bundle_id, "description": self.header.get("description") or "",
                "use_when": list(self.header.get("use_when") or []), "do_not_use_when": list(self.header.get("do_not_use_when") or []),
                "avoid": list(self.header.get("avoid") or []),
                "requires": ({"interpreter": self.requires[0], "version": self.requires[1]} if self.requires else None),
                "steps": [{"name": r["name"], "kind": r["kind"], "description": r.get("description") or "", "loop": inside.get(r["name"]),
                           "line": r.get("line")} for r in steps],
                "loops": [{"name": r["name"], "kind": r["kind"], "mode": r["mode"], "header": loop_header(self.loop(r["id"])),
                           "body": bodies[r["name"]], "loop": inside.get(r["name"]), "line": r.get("line")} for r in loops]}


def loop_header(loop: Loop) -> str:
    """A loop's header after its name, as the formatter writes it: `Over tickets As ticket,
    At_Most 50, Collect reply Into replies`, `Until passed, At_Most 3, Else_Fail`, `3 Times`."""
    if loop.mode == "Until" and loop.until is not None:
        until = loop.until
        head = f"Until {until.dotted}"
        if until.operator:
            head += f" {until.operator} {until.value}"
        if until.confidence_above is not None:
            head += f" With Confidence_Above {until.confidence_above:g}"
    elif loop.mode == "Times":
        head = f"{loop.times} Times"
    else:
        head = f"Over {'.'.join(loop.over or [])} As {loop.item}"
    if loop.at_most is not None:
        head += f", At_Most {loop.at_most}"
    if loop.collect_key is not None:
        head += f", Collect {loop.collect_key} Into {loop.collect_into}"
    if loop.at_cap is not None:
        head += f", {loop.at_cap}"
    return head


__all__ = ["Procedure", "Step", "Loop", "Until", "Read", "Produce", "Flow", "Question", "Aggregation", "FileUse", "STEP_KINDS",
           "FLOW_TYPES", "loop_header"]
