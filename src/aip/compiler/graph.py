"""The graph of a procedure: what a bundle holds beside the source (spec section 3), what
`aip compile --json` prints for an editor, and what a server projects into its store.

`build_graph(program, files, bundle_id, compiler_version)` derives it from the checked syntax
tree; it never decides anything the checker has not already accepted, and the source stays the
program (the bundle carries it byte for byte on the `Procedure` node). `docs/language/bundle.md`
is the schema in prose; this module is its only implementation, and a label, property or edge
added to one is added to the other in the same commit.

Every node has `id`, unique within the bundle (`step:triage`, `loop:revise`, `data:message`,
`question:triage.tone`, `aggregation:summarize_check.all_hold`, `file:assets/config.json`,
`procedure`), and `bundle_id`, so a store holding many bundles can match a node by the pair.
Steps, loops, questions and aggregations carry their source span (`line`, `column`, `end_line`,
`end_column`); flow edges carry the span of the clause that wrote them. Properties whose value
would be null are left out.

Data flows left to right: `(Step)-[:PRODUCES]->(Data)-[:READ_BY]->(Step)`. A route's `READ_BY`
edge carries `source`, the class of the answer it reads as the checker classified it (spec 2.2),
which `build_graph` is handed and never computes."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass, field

from aip.compiler import syntax as s
from aip.compiler.language import LANGUAGE_VERSION

PROCEDURE_ID = "procedure"
# The runtime's keys (spec 2.6): `index` inside a body, `iterations` after a loop, and each
# loop's own name, an object holding its own `index` and `iterations` (`revise.iterations`).
RUNTIME_KEYS = ("index", "iterations")


@dataclass
class FileEntry:
    """One file under `assets/`, `references/` or `scripts/`: its POSIX path relative to the
    program directory, its bytes, and the permission bits to restore on export."""
    path: str
    data: bytes
    mode: int = 0o644

    @property
    def size(self) -> int:
        return len(self.data)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    @property
    def text(self) -> str | None:
        """The bytes as text when they are UTF-8 (and so round-trip), else None."""
        try:
            text = self.data.decode("utf-8")
        except UnicodeDecodeError:
            return None
        return text if text.encode("utf-8") == self.data else None

    def properties(self, content: bool = True) -> dict:
        props = {"path": self.path, "size": self.size, "mode": self.mode, "sha256": self.sha256}
        if content:
            text = self.text
            if text is not None:
                props["text"] = text
            else:
                props["base64"] = base64.b64encode(self.data).decode("ascii")
        return props

    @classmethod
    def from_properties(cls, props: dict) -> "FileEntry":
        """The inverse of `properties(content=True)`, as read back from a store."""
        if props.get("text") is not None:
            data = props["text"].encode("utf-8")
        else:
            data = base64.b64decode(props.get("base64") or "")
        return cls(props["path"], data, int(props.get("mode", 0o644)))


@dataclass
class GraphNode:
    id: str
    labels: tuple[str, ...]
    properties: dict

    def to_dict(self, content: bool = True) -> dict:
        props = self.properties
        if not content:
            props = {k: v for k, v in props.items() if k not in ("source", "text", "base64")}
        return {"id": self.id, "labels": list(self.labels), "properties": props}


@dataclass
class GraphEdge:
    type: str
    start: str
    end: str
    properties: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"type": self.type, "start": self.start, "end": self.end, "properties": self.properties}


@dataclass
class Graph:
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)

    def node(self, id: str) -> GraphNode | None:
        return next((n for n in self.nodes if n.id == id), None)

    def with_label(self, label: str) -> list[GraphNode]:
        return [n for n in self.nodes if label in n.labels]

    def edges_of(self, type: str | None = None, start: str | None = None, end: str | None = None) -> list[GraphEdge]:
        return [e for e in self.edges if (type is None or e.type == type) and (start is None or e.start == start)
                and (end is None or e.end == end)]

    def to_dict(self, content: bool = True) -> dict:
        """The graph as JSON data; without `content` the source and the file bytes are left out,
        which is the form `aip compile --json` prints."""
        return {"nodes": [n.to_dict(content) for n in self.nodes], "edges": [e.to_dict() for e in self.edges]}

    def canonical(self, ignore: tuple[str, ...] = ()) -> tuple:
        """A value two graphs that say the same thing share, whatever order they were built in.
        `ignore` names node properties left out of the comparison."""
        nodes = sorted((n.id, tuple(sorted(n.labels)), _freeze({k: v for k, v in n.properties.items() if k not in ignore}))
                       for n in self.nodes)
        edges = sorted((e.type, e.start, e.end, _freeze(e.properties)) for e in self.edges)
        return tuple(nodes), tuple(edges)


def _freeze(value):
    if isinstance(value, dict):
        return tuple(sorted((k, _freeze(v)) for k, v in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    if isinstance(value, float) and value.is_integer():
        return value  # 1.0 stays a float; the engine keeps the type
    return value


# ---------------------------------------------------------------- building

def _span(node: s.Node) -> dict:
    return {"line": node.line, "column": node.column, "end_line": node.end_line, "end_column": node.end_column}


def _node_name(item) -> str:
    if isinstance(item, s.Step):
        return "start" if item.kind == "Start" else "end" if item.kind == "End" else item.name
    return item.name


def _node_id(item) -> str:
    return ("step:" if isinstance(item, s.Step) else "loop:") + _node_name(item)


def _clean(props: dict) -> dict:
    return {k: v for k, v in props.items() if v is not None}


class _Builder:
    def __init__(self, program: s.Program, files: list[FileEntry], bundle_id: str, compiler_version: str,
                 sources: dict[str, str] | None):
        self.p = program
        self.files = files
        self.bundle_id = bundle_id
        self.compiler_version = compiler_version
        self.sources = sources or {}
        self.names = program.named_strings
        self.graph = Graph()
        self.by_id: dict[str, GraphNode] = {}
        self.index: dict[str, str] = {}        # step or loop name -> node id
        self.seen_edges: set = set()
        self.key_type: dict[str, str | None] = {}
        self.key_description: dict[str, str | None] = {}
        self.key_labels: dict[str, list[str] | None] = {}
        self.loops_at_level: dict[tuple[str, ...], list[str]] = {}
        self.loops: set[str] = set()           # the loops' names, each the runtime's key for that loop

    # ------------------------------------------------------------ primitives

    def text(self, value: s.Str | None) -> str | None:
        if value is None:
            return None
        if isinstance(value, s.NameRef):
            ns = self.names.get(value.name)
            return ns.text.value if ns is not None else None
        return value.value

    def literal(self, value: s.Str) -> s.Text | None:
        if isinstance(value, s.Text):
            return value
        ns = self.names.get(value.name)
        return ns.text if ns is not None else None

    def node(self, id: str, labels: tuple[str, ...], props: dict) -> GraphNode:
        node = GraphNode(id, labels, _clean({"id": id, "bundle_id": self.bundle_id, **props}))
        self.graph.nodes.append(node)
        self.by_id[id] = node
        return node

    def edge(self, type: str, start: str, end: str, props: dict | None = None, at: s.Node | None = None) -> None:
        props = _clean(props or {})
        key = (type, start, end, _freeze(props))
        if key in self.seen_edges:
            return
        self.seen_edges.add(key)
        if at is not None:
            props = {**props, **_span(at)}
        self.graph.edges.append(GraphEdge(type, start, end, props))

    def key(self, name: str, type: str | None = None, description: str | None = None, labels: list[str] | None = None) -> str:
        """The `Data` node for the key `name`, created on first use; a declared type, description
        or label list fills in what earlier uses did not say (the checker has made every
        declaration agree)."""
        id = f"data:{name}"
        if id not in self.by_id:
            self.node(id, ("Data",), {"name": name, "runtime": True if name in RUNTIME_KEYS or name in self.loops else None})
            self.edge("SUPPLIES", PROCEDURE_ID, id)
            self.key_type[name] = "integer" if name in RUNTIME_KEYS else "object" if name in self.loops else None
            self.key_description[name] = None
            self.key_labels[name] = None
        if type is not None and self.key_type[name] is None:
            self.key_type[name] = type
        if description is not None and self.key_description[name] is None:
            self.key_description[name] = description
        if labels and self.key_labels[name] is None:
            self.key_labels[name] = list(labels)
        return id

    # ------------------------------------------------------------ the passes

    def build(self) -> Graph:
        self.index_items(self.p.items, ())
        header = {"use_when": [], "do_not_use_when": [], "avoid": []}
        requires: s.Requires | None = None
        for h in self.p.header:
            if isinstance(h, s.Requires):
                requires = h
            else:
                header[h.keyword.lower()].extend(t for t in (self.text(x) for x in h.strings) if t is not None)
        self.node(PROCEDURE_ID, ("Procedure",), {
            "name": self.p.name, "description": self.text(self.p.description),
            "language_version": LANGUAGE_VERSION, "compiler_version": self.compiler_version,
            "source": None,  # filled in by the bundle, which owns the bytes
            "use_when": header["use_when"] or None, "do_not_use_when": header["do_not_use_when"] or None,
            "avoid": header["avoid"] or None,
            "requires_interpreter": requires.interpreter if requires else None,
            "requires_version": requires.version if requires else None,
            **_span(self.p)})
        for f in self.files:
            self.node(f"file:{f.path}", ("File",), f.properties())
            self.edge("HAS_FILE", PROCEDURE_ID, f"file:{f.path}")
        self.items(self.p.items, ())
        for name, type in self.key_type.items():
            props = self.by_id[f"data:{name}"].properties
            if type is not None:
                props["type"] = type
            if self.key_description.get(name) is not None:
                props["description"] = self.key_description[name]
            if self.key_labels.get(name):
                props["labels"] = self.key_labels[name]
        return self.graph

    def index_items(self, items, path: tuple[str, ...]) -> None:
        for item in items:
            if isinstance(item, s.NamedString):
                continue
            self.index[_node_name(item)] = _node_id(item)
            if not isinstance(item, s.Step):
                self.loops_at_level.setdefault(path, []).append(_node_id(item))
                self.loops.add(item.name)
                self.index_items(item.body, path + (item.name,))

    def items(self, items, path: tuple[str, ...]) -> None:
        for item in items:
            if isinstance(item, s.Step):
                self.step(item, path)
            elif isinstance(item, (s.ForLoop, s.Loop)):
                self.loop(item, path)

    # ------------------------------------------------------------ steps

    def step(self, st: s.Step, path: tuple[str, ...]) -> None:
        name = _node_name(st)
        id = _node_id(st)
        props = {"name": name, "kind": st.kind, "description": self.text(st.description), **_span(st)}
        if st.kind == "Decide":
            props.update(history=st.flag("History"), produces=st.produces[0].key.name if st.produces else None)
        elif st.kind == "Route":
            props.update(check_below=st.check.below if st.check is not None else None)
        elif st.kind == "Aggregate":
            props.update(produces=st.produces[0].key.name if st.produces else None)
        elif st.kind == "Execute":
            props.update(script=st.script, command=self.text(st.command))
        elif st.kind == "Task_Agent":
            props.update(prompt=st.prompt)
        self.node(id, ("Step", st.kind), props)
        self.edge("HAS_STEP", PROCEDURE_ID, id)
        if st.kind == "Start":
            self.edge("STARTS_AT", PROCEDURE_ID, id)
        if st.kind == "End":
            self.edge("ENDS_AT", PROCEDURE_ID, id)
        source = self.sources.get(name) if st.kind == "Route" else None
        for d in st.reads:
            self.read(id, d.key, path, d, type=d.type, source=source)
        for d in st.inputs:
            self.edge("PRODUCES", id, self.key(d.key.name, d.type, self.text(d.description), d.labels), at=d)
        for d in st.produces:
            type = "decision" if st.kind == "Decide" else "aggregation" if st.kind == "Aggregate" else d.type
            self.edge("PRODUCES", id, self.key(d.key.name, type, self.text(d.description), d.labels), at=d)
        if st.kind == "Decide":
            for order, q in enumerate(st.questions):
                qid = f"question:{name}.{q.name}"
                self.node(qid, ("Question",), {
                    "name": q.name, "type": q.type, "labels": list(q.labels) or None, "instruction": self.text(q.instruction),
                    "criteria_labels": [c.label for c in q.criteria] or None,
                    "criteria_texts": [self.text(c.text) for c in q.criteria] or None, "order": order, **_span(q)})
                self.edge("ASKS", id, qid, {"order": order})
                self.interpolations(id, q.instruction, path)
                for c in q.criteria:
                    self.interpolations(id, c.text, path)
        elif st.kind == "Aggregate":
            for order, a in enumerate(st.aggregations):
                aid = f"aggregation:{name}.{a.name}"
                cond = a.condition
                self.node(aid, ("Aggregation",), {
                    "name": a.name, "mode": a.mode, "source": cond.answer.dotted, "operator": cond.operator,
                    "value": cond.value, "confidence_above": cond.confidence_above, "order": order, **_span(a)})
                self.edge("AGGREGATES", id, aid, {"order": order})
                self.edge("OVER", aid, self.key(cond.answer.name), {"field": ".".join(cond.answer.path[1:]) or None})
        elif st.kind == "Task_Agent" and st.prompt is None:
            self.interpolations(id, st.description, path)
        if st.script is not None:
            self.edge("RUNS", id, f"file:{st.script}")
        if st.prompt is not None:
            self.edge("PROMPTED_BY", id, f"file:{st.prompt}")
        for u in st.uses:
            self.edge("USES", id, f"file:{u.path}", {"description": self.text(u.description)}, at=u)
        if st.kind == "Route":
            if st.check is not None:
                self.flow("BELOW", id, st.check.target, path, {"below": st.check.below}, at=st.check)
            for b in st.branches:
                self.flow("BRANCH", id, b.target, path, {"value": b.value}, at=b)
        elif st.flow is not None:
            self.flow(None, id, st.flow, path, at=st.flow)

    def read(self, step_id: str, ref: s.KeyRef, path: tuple[str, ...], at: s.Node, *, type: str | None = None,
             interpolated: bool = False, source: str | None = None) -> None:
        """A `Read` or an interpolation: `(Data)-[:READ_BY]->(Step)`, with the field after the key,
        `interpolated` for a `{key}`, and on a route the answer's `source` class."""
        root = ref.name
        key = self.key(root, type if len(ref.path) == 1 else None)
        if root == "index" and path:
            self.edge("PRODUCES", f"loop:{path[-1]}", key)
        elif root == "iterations":
            for loop_id in self.loops_at_level.get(path, []):
                self.edge("PRODUCES", loop_id, key)
        elif root in self.loops:  # `revise.index`, `revise.iterations`: the loop's own key
            self.edge("PRODUCES", f"loop:{root}", key)
        self.edge("READ_BY", key, step_id, {"field": ".".join(ref.path[1:]) or None, "interpolated": interpolated or None,
                                            "source": source}, at=at)

    def interpolations(self, step_id: str, text: s.Str, path: tuple[str, ...]) -> None:
        literal = self.literal(text)
        if literal is None:
            return
        for f in literal.fields:
            self.read(step_id, s.KeyRef(f.path, line=f.line, column=f.column, end_line=f.end_line, end_column=f.end_column),
                      path, f, interpolated=True)

    def flow(self, type: str | None, start: str, flow: s.Flow, path: tuple[str, ...], props: dict | None = None,
             at: s.Node | None = None) -> None:
        """A `Next_Step` or `Continue`, or a route branch (`type` given) whose target may
        be `Continue`. `Continue` points at the enclosing loop with `continues: true`."""
        props = dict(props or {})
        if flow.kind == "Continue":
            if not path:
                return  # continue_outside_loop: the checker has refused the program
            target = f"loop:{path[-1]}"
            if type is None:
                type = "CONTINUES"
            else:
                props["continues"] = True
        else:
            target = self.index.get(flow.step) if flow.step != "end" else self.index.get("end")
            if target is None:
                return  # unknown_step: refused by the checker
            if type is None:
                type = "NEXT"
        self.edge(type, start, target, props, at=at)

    # ------------------------------------------------------------ loops

    def loop(self, loop: s.ForLoop | s.Loop, path: tuple[str, ...]) -> None:
        id = _node_id(loop)
        inner = path + (loop.name,)
        if isinstance(loop, s.ForLoop):
            props = {"name": loop.name, "kind": "For", "mode": "Over", "item": loop.item, "at_most": loop.at_most,
                     "collect_key": loop.collect.key if loop.collect else None,
                     "collect_into": loop.collect.into if loop.collect else None, **_span(loop)}
            labels: tuple[str, ...] = ("Loop", "For")
        else:
            cond = loop.until
            props = {"name": loop.name, "kind": "Loop", "mode": loop.mode, "item": loop.item, "at_most": loop.at_most,
                     "times": loop.times, "at_cap": loop.at_cap,
                     "until_answer": cond.answer.dotted if cond else None, "until_operator": cond.operator if cond else None,
                     "until_value": cond.value if cond else None,
                     "until_confidence_above": cond.confidence_above if cond else None, **_span(loop)}
            labels = ("Loop",)
        self.node(id, labels, props)
        self.edge("HAS_LOOP", PROCEDURE_ID, id)
        over = loop.over
        if over is not None:
            self.edge("OVER", id, self.key(over.name), {"field": ".".join(over.path[1:]) or None}, at=over)
        if loop.item is not None:
            self.edge("BINDS", id, self.key(loop.item))
        if isinstance(loop, s.ForLoop) and loop.collect is not None:
            self.edge("COLLECTS", id, self.key(loop.collect.key), at=loop.collect)
            self.edge("PRODUCES", id, self.key(loop.collect.into, "list"), at=loop.collect)
        if isinstance(loop, s.Loop) and loop.until is not None:
            cond = loop.until
            self.edge("WATCHES", id, self.key(cond.answer.name), {
                "field": ".".join(cond.answer.path[1:]) or None, "operator": cond.operator, "value": cond.value,
                "confidence_above": cond.confidence_above}, at=cond)
        body = [i for i in loop.body if not isinstance(i, s.NamedString)]
        for order, item in enumerate(body):
            self.edge("CONTAINS", id, _node_id(item), {"order": order})
            if order == 0:
                self.edge("ENTERS", id, _node_id(item))
        if loop.exit is not None:
            self.flow(None, id, loop.exit, path, at=loop.exit)
        self.items(loop.body, inner)


def build_graph(program: s.Program, files: list[FileEntry], bundle_id: str, compiler_version: str,
                sources: dict[str, str] | None = None) -> Graph:
    """The graph of a checked program. `files` are the program's resource files, `bundle_id` the
    id the bundle computes from the source and those files (`aip.compiler.bundle.bundle_id`), and
    `sources` the checker's source class per route (`aip.compiler.check(..., sources=)`), written on
    each route's `READ_BY` edge."""
    return _Builder(program, files, bundle_id, compiler_version, sources).build()
