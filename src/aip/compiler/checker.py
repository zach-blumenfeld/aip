"""The checker: every rule of the language that needs the whole program (spec sections 2.2 to
2.5), reported as diagnostics with source positions.

`check(program, folder)` returns a list of `Diagnostic`, one shape for every finding: `code`,
`severity` (`error`, `warning` or `info`), `message`, `file`, `line`, `column`, `end_line`,
`end_column` and `step`, the step or loop the finding is in. `CODES` lists every code with its
severity; the table in the spec's section 2.2 is the same list in prose, and a code added to one
is added to the other in the same commit. Compilation fails on any error.

What the checker does, in order. It indexes the steps and loops (names, one `Start`, one `End`,
nothing reserved). It checks each step on its own: the clauses its kind needs, its questions and
their labels, its files on disk. Then it walks the flow graph region by region, where a region is
the top level or a loop body, with the loops inside it as single nodes: it resolves every
`Next_Step`, branch, `Continue` and `Again` (a flow may not enter or leave a body except through
the loop's own lines), finds the steps nothing reaches and the cycles that pass through no loop,
and runs the state analysis over the region in topological order. That analysis carries two
states to every node: the keys definitely available on every path (for `Read`, the interpolations,
routes, conditions and aggregation sources) and the producers that may have written each key on
some path (for `duplicate_producer`), with the type every declaration must agree on. A loop's
effect on the state is computed from its body's exit points, as section 2.3 describes: a `For`
leaves only what it collects, a `Loop` leaves what every exit has written.

One mistake, one error. A finding that is only the consequence of another is not reported: a
region with a flow that did not resolve (`unknown_step`, a missing `Next_Step` or loop exit, a
flow across a loop's braces) reports no `unreachable_step`, since nothing can be said about what
the flow would have reached; a `Decide` or `Aggregate` with no `Produce` silences `unknown_key`
at the readers of the key it never named; a route whose branch lines name values the answer does
not have reports them in one `unknown_label` and no `missing_branch`; a second producer of a key
reports `duplicate_producer` and not the `type_mismatch` that follows from it."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from aip.compiler import syntax as s
from aip.compiler.errors import ParseError
from aip.compiler.keywords import ANSWER_TYPES

SOURCE_FILE = "procedure.aip"
RESOURCE_DIRS = ("assets", "references", "scripts")
# The runtime's keys (spec 2.6): `index` inside a loop body, `iterations` after a loop, and each
# loop's own name, an object holding its `index` inside its body and its `iterations` after it.
RESERVED_KEYS = ("index", "iterations")
# `start` is not a step name: Start has no name and nothing points at it (`end` is checked by the parser).
RESERVED_STEPS = ("start",)

# Every diagnostic code with its severity. The spec's section 2.2 lists the same codes.
CODES: dict[str, str] = {
    # the procedure's shape
    "missing_start": "error",
    "missing_end": "error",
    "duplicate_step": "error",
    "duplicate_name": "error",
    "unknown_name": "error",
    "start_in_loop": "error",
    "end_in_loop": "error",
    "reserved_key": "error",
    "missing_clause": "error",
    "missing_type": "error",
    "missing_next_step": "error",
    "decide_reads_nothing": "warning",
    "question_labels": "error",
    "duplicate_question": "error",
    "duplicate_aggregation": "error",
    # flow
    "unknown_step": "error",
    "unreachable_step": "error",
    "cycle_without_loop": "error",
    "jump_into_body": "error",
    "flow_leaves_body": "error",
    "continue_outside_loop": "error",
    "again_outside_loop": "error",
    "again_target": "error",
    # loops
    "missing_cap": "error",
    "empty_loop": "error",
    "missing_loop_exit": "error",
    # the state
    "unknown_key": "error",
    "unavailable_key": "error",
    "unknown_field": "error",
    "duplicate_producer": "error",
    "type_mismatch": "error",
    # routes, conditions and aggregations
    "route_reads_one": "error",
    "condition_on_plain_value": "error",
    "missing_branch": "error",
    "duplicate_branch": "error",
    "unknown_label": "error",
    "comparison_required": "error",
    "confidence_on_aggregate": "error",
    "confidence_on_agent_answer": "error",
    "confidence_on_input": "error",
    "source_not_read": "error",
    # resources
    "missing_file": "error",
    "missing_requires": "error",
    # names
    "unused_name": "info",
}


@dataclass
class Diagnostic:
    """One finding. `step` is the step or loop it belongs to (`start`, `end`, or the name)."""
    code: str
    severity: str
    message: str
    file: str | None
    line: int
    column: int
    end_line: int
    end_column: int
    step: str | None

    def to_dict(self) -> dict:
        return {"code": self.code, "severity": self.severity, "message": self.message, "file": self.file,
                "line": self.line, "column": self.column, "end_line": self.end_line, "end_column": self.end_column,
                "step": self.step}

    def __str__(self) -> str:
        where = f"{self.line}:{self.column}"
        if self.file:
            where = f"{self.file}:{where}"
        return f"{where}: {self.severity} {self.code}: {self.message}"


# ---------------------------------------------------------------- source classes

# The class of an answer by the kind of the step that produced it (spec 2.2): what a route's
# `Confidence_Below` or a condition's `With Confidence_Above` may sit on is `measured` (a
# decision model's answer, which always carries a confidence) or `scripted` (a script's, which
# may); an `agent`'s answer, an `input` and an `aggregated` answer never carry one, so a check
# on them is an error. The order is the precedence when the arms of a route produce one key
# from steps of different kinds: the least measured class names the answer, so governance sees
# a route an agent may steer as `agent`.
SOURCE_CLASSES = {"Task_Agent": "agent", "Start": "input", "Aggregate": "aggregated", "Execute": "scripted", "Decide": "measured"}
SOURCE_PRECEDENCE = ("agent", "input", "aggregated", "scripted", "measured")
# The code a confidence check on each class reports; None where it is allowed.
CONFIDENCE_ERRORS = {"agent": "confidence_on_agent_answer", "input": "confidence_on_input", "aggregated": "confidence_on_aggregate",
                     "scripted": None, "measured": None}


def source_class(classes) -> str:
    """The one class for an answer whose producers have the given classes (`SOURCE_PRECEDENCE`);
    `measured` for none."""
    found = set(classes)
    return next((c for c in SOURCE_PRECEDENCE if c in found), "measured")


# ---------------------------------------------------------------- types and the state

# An answer's `value`: a boolean, or the label (a `score`'s value is its level's label, spec 2.4).
VALUE_KIND = {"true_or_false": "boolean", "choice": "string", "score": "string"}


@dataclass(frozen=True)
class Type:
    """The type of a key as the checker knows it. `kind` is a word of the type vocabulary, or None
    for a value whose type the program does not say (an item of a plain list). Answer types carry
    their `labels` when the question is known; a decision or an aggregation carries its `fields`; a
    list its `element`. `loop` is the kind of a loop's own key (`revise.index`, `revise.iterations`),
    which is the runtime's and not a word of the vocabulary. `sources` names the steps whose answers these are, for the source classes
    of 2.2 (the Decide, the script, the agent task, the Aggregate)."""
    kind: str | None = None
    labels: tuple[str, ...] | None = None
    fields: tuple[tuple[str, "Type"], ...] | None = None
    element: "Type | None" = None
    sources: tuple[str, ...] = ()

    @property
    def is_answer(self) -> bool:
        return self.kind in ANSWER_TYPES

    def field(self, name: str) -> "Type | None":
        if self.fields is not None:
            for n, t in self.fields:
                if n == name:
                    return t
            return None
        if self.kind in ("decision", "aggregation"):
            return Type()  # declared, not produced by a step here: its fields are not known
        if self.kind == "list":
            inner = (self.element or Type()).field(name)
            return None if inner is None else Type("list", element=inner, sources=inner.sources)
        if self.kind is None:
            return Type()
        if self.is_answer:
            if name == "value":
                return Type(VALUE_KIND[self.kind], sources=self.sources)
            if name == "confidence":
                return Type("float", sources=self.sources)
        return None

    def noun(self) -> str:
        """The type in a word or two, for a sentence that names the producers itself."""
        if self.kind == "decision":
            return "a decision"
        if self.kind == "aggregation":
            return "an aggregation"
        return self.describe()

    def describe(self) -> str:
        if self.kind is None:
            return "of unknown type"
        if self.kind == "loop":
            return "a loop's own key"
        if self.kind == "list":
            return "a list" if self.element is None else f"a list of {self.element.plural()}"
        if self.kind == "decision":
            return f"the decision {self.sources[0]} produces" if self.sources else "a decision"
        if self.kind == "aggregation":
            return f"the aggregation {self.sources[0]} produces" if self.sources else "an aggregation"
        if self.is_answer:
            return f"a {self.kind} answer"
        return f"an {self.kind}" if self.kind[0] in "aeiou" else f"a {self.kind}"

    def plural(self) -> str:
        if self.kind is None:
            return "values of unknown type"
        if self.kind == "list":
            return "lists"
        if self.kind == "decision":
            return f"decisions from {self.sources[0]}" if self.sources else "decisions"
        if self.kind == "aggregation":
            return "aggregations"
        if self.is_answer:
            return f"{self.kind} answers"
        return f"{self.kind}s"


def _merge_type(a: Type, b: Type) -> tuple[Type, bool]:
    """The type two paths agree on, and whether they disagree on the kind."""
    if a.kind is None:
        return b, False
    if b.kind is None:
        return a, False
    if a.kind != b.kind:
        return a, True
    element, conflict = a.element, False
    if a.kind == "list" and a.element is not None and b.element is not None:
        element, conflict = _merge_type(a.element, b.element)
    sources = a.sources + tuple(x for x in b.sources if x not in a.sources)
    return Type(a.kind, a.labels if a.labels is not None else b.labels, a.fields if a.fields is not None else b.fields,
                element, sources), conflict


@dataclass(frozen=True)
class Entry:
    """A key in the state: its type, every step or loop that may have written its current value,
    and `inside`, the producers within the region being analysed (a loop body is a new region,
    so a key written before the loop has no inside producer there and may be rewritten)."""
    type: Type
    producers: frozenset[str]
    inside: frozenset[str]


State = dict[str, Entry]


def _join(states: list[State]) -> State:
    """The may-state: a key is in it when any path wrote it."""
    out: State = {}
    for st in states:
        for k, e in st.items():
            prior = out.get(k)
            if prior is None:
                out[k] = e
            else:
                t, _ = _merge_type(prior.type, e.type)
                out[k] = Entry(t, prior.producers | e.producers, prior.inside | e.inside)
    return out


def _reset(state: State) -> State:
    """The state at the entry of a loop body: nothing has been written in this pass yet."""
    return {k: Entry(e.type, e.producers, frozenset()) for k, e in state.items()}


@dataclass
class RegionResult:
    continues: list[tuple[State, State]] = field(default_factory=list)
    agains: list[tuple[State, State]] = field(default_factory=list)
    # key -> the states after each node of the region that produced it (a step, or a nested loop
    # whose body left it): where an enclosing `Until` is tested again (spec 2.6)
    produce_points: dict[str, list[tuple[State, State]]] = field(default_factory=dict)


def _node_name(item) -> str:
    if isinstance(item, s.Step):
        return "start" if item.kind == "Start" else "end" if item.kind == "End" else item.name
    return item.name


def _label(item) -> str:
    if isinstance(item, s.Step):
        return item.kind if item.name is None else f"{item.kind} {item.name}"
    return f"{'For' if isinstance(item, s.ForLoop) else 'Loop'} {item.name}"


def _head_word(item) -> str:
    return item.kind if isinstance(item, s.Step) else ("For" if isinstance(item, s.ForLoop) else "Loop")


def _topo(entry: str, edges: dict[str, list[str]]) -> tuple[list[str], list[tuple[str, str]]]:
    """The nodes reachable from `entry` in topological order, and the back edges (cycles)."""
    order: list[str] = []
    back: list[tuple[str, str]] = []
    colour: dict[str, int] = {}

    def visit(n: str):
        colour[n] = 1
        for t in edges.get(n, ()):
            c = colour.get(t, 0)
            if c == 0:
                visit(t)
            elif c == 1:
                back.append((n, t))
        colour[n] = 2
        order.append(n)

    visit(entry)
    order.reverse()
    return order, back


def _reaches(edges: dict[str, list[str]], start: str, goal: str) -> bool:
    seen, todo = set(), [start]
    while todo:
        n = todo.pop()
        if n == goal:
            return True
        if n in seen:
            continue
        seen.add(n)
        todo.extend(edges.get(n, ()))
    return False


def _list(words) -> str:
    words = list(words)
    return ", ".join(words[:-1]) + " and " + words[-1] if len(words) > 1 else "".join(words)


# ---------------------------------------------------------------- the checker

class Checker:
    def __init__(self, program: s.Program, folder: Path | None, file: str | None, files: set[str] | None = None):
        self.p = program
        self.folder = folder
        self.files = files  # the program's files by POSIX path, when they are in hand rather than on disk
        self.file = file
        self.out: list[Diagnostic] = []
        self.seen: set[tuple] = set()
        self.nodes: dict[str, s.Step | s.ForLoop | s.Loop] = {}
        self.region_of: dict[str, tuple[str, ...]] = {}   # node -> the loops around it, outermost first
        self.names: dict[str, s.NamedString] = {}
        self.used_names: set[str] = set()
        self.anywhere: dict[str, list[str]] = {}          # key -> every producer in the file
        self.for_keys: dict[str, str] = {}                # key -> the For whose body produces it
        self.first_execute: s.Step | None = None
        self.path: tuple[str, ...] = ()
        self.sources: dict[str, str] = {}                 # route name -> the source class of the answer it reads
        self.loops: set[str] = set()                      # the loops' names: each is the runtime's key for that loop
        self.keyless = False                              # a Decide or Aggregate names no key: its readers' unknown_key is its consequence
        self.broken = False                               # a flow of the region being read did not resolve

    # ------------------------------------------------------------ reporting

    def report(self, code: str, node: s.Node, message: str, step: str | None = None, end: tuple[int, int] | None = None):
        end_line, end_column = end if end else (node.end_line, node.end_column)
        key = (code, node.line, node.column, message)
        if key in self.seen:
            return
        self.seen.add(key)
        self.out.append(Diagnostic(code, CODES[code], message, self.file, node.line, node.column, end_line, end_column, step))

    def report_head(self, code: str, item, message: str):
        """A finding about a step or loop as a whole, anchored to its opening keyword."""
        self.report(code, item, message, _node_name(item), end=(item.line, item.column + len(_head_word(item))))

    # ------------------------------------------------------------ the passes

    def run(self) -> list[Diagnostic]:
        self.index(self.p.items, ())
        self.loops = {n for n, node in self.nodes.items() if not isinstance(node, s.Step)}
        if "start" not in self.nodes:
            self.report("missing_start", self.p, "the procedure has no Start step; one Start names the inputs and the first step",
                        end=(self.p.line, self.p.column + len("Procedure")))
        if "end" not in self.nodes:
            self.report("missing_end", self.p, "the procedure has no End step; one End names the result keys",
                        end=(self.p.line, self.p.column + len("Procedure")))
        self.use_str(self.p.description)
        for h in self.p.header:
            if isinstance(h, s.HeaderClause):
                for text in h.strings:
                    self.use_str(text)
        for step in self.p.steps():
            self.check_step(step)
        if self.first_execute is not None and not any(isinstance(h, s.Requires) for h in self.p.header):
            self.report_head("missing_requires", self.first_execute,
                             f"Execute {self.first_execute.name} runs a script, but the header declares no Requires; "
                             "add Requires <interpreter> <version>, such as Requires python 3.10")
        if self.region_of.get("start") == ():
            self.region(self.p.items, None, (), {}, {}, None)
        for name, ns in self.names.items():
            if name not in self.used_names:
                self.report("unused_name", ns, f"the named string {name} is never used", end=(ns.line, ns.column + len(name)))
        self.out.sort(key=lambda d: (d.line, d.column, d.code))
        return self.out

    def index(self, items, path: tuple[str, ...]):
        for item in items:
            if isinstance(item, s.NamedString):
                if item.name in self.names:
                    self.report("duplicate_name", item, f"the name {item.name} is defined twice; a named string has one definition",
                                end=(item.line, item.column + len(item.name)))
                else:
                    self.names[item.name] = item
                continue
            name = _node_name(item)
            if name in self.nodes:
                other = self.nodes[name]
                if isinstance(item, s.Step) and item.name is None:
                    message = f"a procedure has one {item.kind} step; the first is on line {other.line}"
                else:
                    message = f"the name {name} is already taken by {_label(other)} on line {other.line}; steps and loops share one namespace"
                self.report_head("duplicate_step", item, message)
            else:
                self.nodes[name] = item
                self.region_of[name] = path
            if isinstance(item, s.Step):
                if item.kind == "Start" and path:
                    self.report_head("start_in_loop", item, f"Start is inside {path[-1]}; the Start step is written at top level")
                if item.kind == "End" and path:
                    self.report_head("end_in_loop", item, f"End is inside {path[-1]}; End is not reachable inside a loop body and is written at top level")
                for d in item.inputs + item.produces:
                    self.anywhere.setdefault(d.key.name, []).append(name)
                    enclosing_for = next((p for p in reversed(path) if isinstance(self.nodes.get(p), s.ForLoop)), None)
                    if enclosing_for is not None:
                        self.for_keys.setdefault(d.key.name, enclosing_for)
            else:
                if name in RESERVED_KEYS:
                    self.report_head("reserved_key", item, f"a loop cannot be called {name}: index and iterations are the runtime's keys, "
                                     f"and a loop's name is the key that holds its own ({name}.index would read as neither)")
                if isinstance(item, s.ForLoop) and item.collect is not None:
                    self.anywhere.setdefault(item.collect.into, []).append(name)
                self.index(item.body, path + (name,))

    # ------------------------------------------------------------ one step on its own

    def check_step(self, st: s.Step):
        name = _node_name(st)
        self.use_str(st.description, name)
        for u in st.uses:
            if u.description is not None:
                self.use_str(u.description, name)
            self.check_file(u.path, u, name, "Use")
        if st.command is not None:
            self.use_str(st.command, name)
        if st.kind == "Decide":
            if not st.questions:
                self.report_head("missing_clause", st, f"Decide {name} asks no question; add an Answer_Questions block with one question per line")
            seen: set[str] = set()
            for q in st.questions:
                if q.name in seen:
                    self.report("duplicate_question", q, f"the question {q.name} is asked twice in {name}", name,
                                end=(q.line, q.column + len(q.name)))
                seen.add(q.name)
                self.check_labels(q, name)
                self.use_str(q.instruction, name)
                for c in q.criteria:
                    self.use_str(c.text, name)
            if not st.produces:
                self.keyless = True
                self.report_head("missing_clause", st, f"Decide {name} names no key; Produce <key> names the one key whose fields are its answers")
            if not st.reads:
                self.report_head("decide_reads_nothing", st, f"Decide {name} has no Read, so the model judges nothing but its questions; Read "
                                 "names what it judges (a {key} in a question composes the question and is not handed over as data)")
        elif st.kind == "Aggregate":
            if not st.aggregations:
                self.report_head("missing_clause", st, f"Aggregate {name} has no aggregations; add an Aggregations block with one per line")
            seen = set()
            for a in st.aggregations:
                if a.name in seen:
                    self.report("duplicate_aggregation", a, f"the aggregation {a.name} is defined twice in {name}", name,
                                end=(a.line, a.column + len(a.name)))
                seen.add(a.name)
            if not st.produces:
                self.keyless = True
                self.report_head("missing_clause", st, f"Aggregate {name} names no key; Produce <key> names the one key whose fields are its aggregations")
        elif st.kind == "Execute":
            if self.first_execute is None:
                self.first_execute = st
            scripts = [c for c in st.clauses if isinstance(c, s.ScriptClause)]
            if not scripts:
                self.report_head("missing_clause", st, f"Execute {name} names no script; add Run_Script <path>")
            for c in scripts:
                self.check_file(c.path, c, name, "Run_Script")
        elif st.kind == "Task_Agent":
            for c in st.clauses:
                if isinstance(c, s.PromptClause):
                    self.check_file(c.path, c, name, "Prompt")
        elif st.kind == "Route" and not st.branches and st.check is None:
            self.report_head("missing_branch", st, f"Route {name} names no branch; one <value> -> <step> line per value the answer can take")
        if st.kind in ("Execute", "Task_Agent"):
            for d in st.produces:
                if d.type is None:
                    self.report("missing_type", d, f"Produce {d.key.name} needs a type: {d.key.name}: <type>", name)
        if st.kind in ("Start", "Execute", "Task_Agent"):
            for d in st.inputs + st.produces:
                if d.type is not None:
                    self.check_key_labels(d, name)
        for d in st.inputs + st.produces:
            if d.key.name in RESERVED_KEYS:
                self.report("reserved_key", d, f"{d.key.name} is the runtime's: index names the pass inside a loop body and "
                            "iterations the passes a loop ran; a step cannot produce it", name)
            elif d.key.name in self.loops:
                self.report("duplicate_name", d, self.loop_key_clash(d.key.name, "key"), name, end=(d.line, d.column + len(d.key.name)))
        if st.kind in ("Start", "Decide", "Aggregate", "Execute", "Task_Agent") and st.flow is None:
            self.report_head("missing_next_step", st, f"{_label(st)} does not say where it goes; end it with Next_Step <step>"
                             + (", or Continue or Again <step> inside a loop body" if st.kind != "Start" else ""))

    def loop_key_clash(self, name: str, what: str) -> str:
        return (f"the {what} {name} shares its name with {_label(self.nodes[name])}, and a loop's name is the runtime's key for that loop "
                f"({name}.index in its body, {name}.iterations after it); give one of them a different name")

    def check_labels(self, q: s.Question, step: str):
        if q.type == "true_or_false":
            if q.labels:
                self.report("question_labels", q, f"{q.name} is a true_or_false question and has no labels; its values are true and false", step)
            valid: tuple[str, ...] = ("true", "false")
        else:
            word = "labels" if q.type == "choice" else "levels"
            if len(q.labels) < 2:
                self.report("question_labels", q, f"{q.name} is a {q.type} question and lists its {word} in brackets, at least two: "
                            f"{q.name}: {q.type} [a, b] \"...\"", step)
            for i, label in enumerate(q.labels):
                if label in q.labels[:i]:
                    self.report("question_labels", q, f"the {word[:-1]} {label} is listed twice on {q.name}", step)
            valid = tuple(q.labels)
        for c in q.criteria:
            if c.label not in valid:
                self.report("unknown_label", c, f"the criterion {c.label} names no value of {q.name}; its values are {_list(valid)}", step,
                            end=(c.line, c.column + len(c.label)))

    def check_key_labels(self, d: s.Declaration, step: str):
        """A `choice` or `score` key declared where it is produced lists its labels, as a question
        does; any other type has none (spec 2.4)."""
        k = d.key.name
        if d.type in ("choice", "score"):
            word = "labels" if d.type == "choice" else "levels"
            if len(d.labels) < 2:
                self.report("question_labels", d, f"{k} is a {d.type} key and lists its {word} in brackets, at least two: "
                            f"{k}: {d.type} [a, b]", step)
            for i, label in enumerate(d.labels):
                if label in d.labels[:i]:
                    self.report("question_labels", d, f"the {word[:-1]} {label} is listed twice on {k}", step)
        elif d.labels:
            what = "a true_or_false key, whose values are true and false" if d.type == "true_or_false" else f"{Type(d.type).describe()}"
            self.report("question_labels", d, f"{k} is {what}; labels are for a choice or a score", step)

    def check_file(self, path: str, node: s.Node, step: str, clause: str):
        pp = PurePosixPath(path)
        if pp.is_absolute() or ".." in pp.parts or len(pp.parts) < 2 or pp.parts[0] not in RESOURCE_DIRS:
            self.report("missing_file", node, f"{clause} {path}: a file of the program lives under {_list(d + '/' for d in RESOURCE_DIRS)}, "
                        "and only those directories are bundled", step)
        elif self.files is not None:
            if str(pp) not in self.files:
                self.report("missing_file", node, f"{clause} {path}: the file does not exist", step)
        elif self.folder is not None and not (self.folder / Path(*pp.parts)).is_file():
            self.report("missing_file", node, f"{clause} {path}: the file does not exist", step)

    def use_str(self, text: s.Str, step: str | None = None):
        if isinstance(text, s.NameRef):
            if text.name in self.names:
                self.used_names.add(text.name)
            else:
                self.report("unknown_name", text, f"no named string {text.name}; a name is defined at top level as {text.name} = \"...\"", step)

    def text_of(self, text: s.Str) -> s.Text | None:
        if isinstance(text, s.Text):
            return text
        ns = self.names.get(text.name)
        return ns.text if ns is not None else None

    # ------------------------------------------------------------ regions and flow

    def region(self, items, loop, path: tuple[str, ...], must_in: State, may_in: State, parent_edges) -> RegionResult:
        """Analyse the top level (`loop` is None) or a loop body: flows, reachability, cycles,
        then the state at every node in topological order."""
        result = RegionResult()
        nodes = {_node_name(i): i for i in items if not isinstance(i, s.NamedString)}
        if loop is None:
            entry = "start"
        else:
            if not nodes:
                self.report_head("empty_loop", loop, f"{_label(loop)} has no steps; a pass starts at the first step written in the body")
                return result
            entry = next(iter(nodes))
        self.broken = False
        succ = {n: self.successors(node, nodes, loop, path, parent_edges) for n, node in nodes.items()}
        broken = self.broken  # a flow here did not resolve, so "nothing reaches X" would be its consequence, not a finding
        edges = {n: [t for k, t, _ in succ[n] if k == "edge"] for n in nodes}
        order, back = _topo(entry, edges)
        reached = set(order)
        for n, node in nodes.items():
            if n not in reached and not broken:
                how = (f"a loop is entered with Next_Step {n}" if not isinstance(node, s.Step)
                       else "a step is reached by a Next_Step, a route branch, or Again")
                self.report_head("unreachable_step", node, f"nothing reaches {_label(node)}; {how}")
        for a, b in back:
            flow = next(f for k, t, f in succ[a] if k == "edge" and t == b)
            self.report("cycle_without_loop", flow, f"{_label(nodes[a])} goes back to {_label(nodes[b])}, closing a cycle that passes "
                        "through no loop body; a repetition is written as a Loop or a For", a)
        incoming: dict[str, list[tuple[State, State]]] = {entry: [(must_in, may_in)]}
        self.path = path
        for n in order:
            ins = incoming.get(n)
            if not ins:
                continue
            node = nodes[n]
            m_in = self.meet([m for m, _ in ins], node)
            y_in = _join([y for _, y in ins])
            if isinstance(node, s.Step):
                m_out, y_out, produced = self.visit_step(node, m_in, y_in)
            else:
                m_out, y_out, produced = self.visit_loop(node, m_in, y_in, path, edges)
                self.path = path
            for key in produced:
                result.produce_points.setdefault(key, []).append((m_out, y_out))
            for kind, target, _ in succ[n]:
                if kind == "edge":
                    incoming.setdefault(target, []).append((m_out, y_out))
                elif kind == "continue":
                    result.continues.append((m_out, y_out))
                elif kind == "again":
                    result.agains.append((m_out, y_out))
        return result

    def successors(self, node, names: dict, loop, path: tuple[str, ...], parent_edges) -> list[tuple[str, str | None, s.Flow]]:
        """Where a node goes, each flow resolved and checked: ('edge', target) within the region,
        ('continue', None) or ('again', target) in a body."""
        name = _node_name(node)
        flows: list[s.Flow] = []
        if isinstance(node, s.Step):
            if node.kind == "Route":
                if node.check is not None:
                    flows.append(node.check.target)
                flows.extend(b.target for b in node.branches)
            elif node.kind != "End" and node.flow is not None:
                flows.append(node.flow)
            if node.kind != "End" and not flows:
                self.broken = True  # missing_next_step, or a route with no branch: reported where the step is checked
        elif node.exit is not None:
            flows.append(node.exit)
        else:
            self.broken = True
            self.report_head("missing_loop_exit", node, f"{_label(node)} does not say where the run goes when it exits; its block ends with "
                             "Next_Step <step>" + (", or Continue to end the enclosing pass" if path else ""))
        out: list[tuple[str, str | None, s.Flow]] = []
        for flow in flows:
            if flow.kind == "Continue":
                if loop is None:
                    message = ("the exit of a top-level loop is Next_Step <step>; Continue as a loop's exit is for a loop nested in another loop's body"
                               if not isinstance(node, s.Step) else "Continue ends a pass and is only written inside a loop body")
                    self.report("continue_outside_loop", flow, message, name)
                else:
                    out.append(("continue", None, flow))
            elif flow.kind == "Again":
                if loop is None:
                    self.report("again_outside_loop", flow, "Again re-enters an earlier step from inside a loop body and is only written there", name)
                elif isinstance(loop, s.ForLoop):
                    self.report("again_target", flow, f"Again is for Loop passes, which build on each other; a pass of For {loop.name} is "
                                "independent and ends with Continue", name)
                else:
                    target = flow.step
                    if target in RESERVED_STEPS or target not in self.nodes:
                        self.report("unknown_step", flow, f"Again {target}: no step or loop is called {target}", name)
                    elif target == loop.name:
                        self.report("again_target", flow, f"Again {target} names the loop it is in; to end the pass write Continue", name)
                    elif self.region_of[target] != path[:-1] or not _reaches(parent_edges or {}, target, loop.name):
                        self.report("again_target", flow, f"Again {target}: the step must be at the level of Loop {loop.name} and the flow "
                                    f"from it must reach the loop again; {target} is {self.where(target)}", name)
                    else:
                        out.append(("again", target, flow))
            else:
                target = flow.step
                if target in RESERVED_STEPS:
                    self.report("unknown_step", flow, f"Next_Step {target}: Start has no name and nothing points at it", name)
                elif target in names:
                    out.append(("edge", target, flow))
                elif target == "end" and "end" not in self.nodes:
                    pass  # missing_end says it
                elif target not in self.nodes:
                    self.report("unknown_step", flow, f"Next_Step {target}: no step or loop is called {target}", name)
                else:
                    target_path = self.region_of[target]
                    if target_path == path[:len(target_path)]:
                        where = "End is not reachable inside a loop body" if target == "end" else f"{target} is {self.where(target)}"
                        self.report("flow_leaves_body", flow, f"{_label(node)} is inside {path[-1]}, and a step in a loop body leaves it only "
                                    f"with Continue, Again <step>, or the loop's own exit line; {where}", name)
                    else:
                        common = 0
                        while common < min(len(path), len(target_path)) and path[common] == target_path[common]:
                            common += 1
                        body = target_path[common]
                        self.report("jump_into_body", flow, f"Next_Step {target} points into the body of {body}; a loop body is entered only "
                                    f"through the loop itself (Next_Step {body})", name)
        if len(out) < len(flows):
            self.broken = True
        return out

    def where(self, node: str) -> str:
        path = self.region_of.get(node, ())
        return "at top level" if not path else f"inside {path[-1]}"

    # ------------------------------------------------------------ the state at a step

    def meet(self, states: list[State], node) -> State:
        """The must-state: the keys every path brings, with one type each."""
        if len(states) == 1:
            return dict(states[0])
        keys = set(states[0])
        for st in states[1:]:
            keys &= set(st)
        out: State = {}
        for k in sorted(keys):
            entries = [st[k] for st in states]
            t, conflict = entries[0].type, False
            for e in entries[1:]:
                t, c = _merge_type(t, e.type)
                conflict |= c
            if conflict:
                kinds: dict[str, set[str]] = {}
                for e in entries:
                    kinds.setdefault(e.type.noun(), set()).update(e.producers)
                self.report_head("type_mismatch", node, f"{k} reaches {_label(node)} with different types on different paths: "
                                 + "; ".join(f"{d} from {_list(sorted(p))}" for d, p in sorted(kinds.items(), key=lambda kv: sorted(kv[1]))))
            producers = frozenset().union(*(e.producers for e in entries))
            inside = frozenset().union(*(e.inside for e in entries))
            out[k] = Entry(t, producers, inside)
        return out

    def visit_step(self, st: s.Step, m_in: State, y_in: State) -> tuple[State, State, set[str]]:
        name = _node_name(st)
        must, may = dict(m_in), dict(y_in)
        if st.kind == "Start":
            return must, may, self.produce(st, st.inputs, must, may, name)
        if st.kind == "Route":
            self.check_route(st, m_in, name)
            return must, may, set()
        if st.kind == "End":
            # The result is what the run produced: End may name a key only some paths produce, and
            # the result carries the ones the path taken did (it must still be produced somewhere).
            self.check_reads(st, y_in, name)
            return must, may, set()
        self.check_reads(st, m_in, name)
        if st.kind == "Decide":
            for q in st.questions:
                self.check_text(q.instruction, m_in, name)
                for c in q.criteria:
                    self.check_text(c.text, m_in, name)
        elif st.kind == "Aggregate":
            self.check_aggregate(st, m_in, name)
        elif st.kind == "Task_Agent" and st.prompt is None:
            self.check_text(st.description, m_in, name)
        return must, may, self.produce(st, st.produces, must, may, name)

    def produce(self, st: s.Step, decls: list[s.Declaration], must: State, may: State, name: str) -> set[str]:
        produced: set[str] = set()
        for d in decls:
            k = d.key.name
            if k in RESERVED_KEYS or k in self.loops:
                continue
            t = self.declared_type(st, d, name)
            prior = may.get(k)
            inside: frozenset[str] = frozenset()
            if prior is not None:
                if prior.inside:
                    self.report("duplicate_producer", d, f"{k} is already produced by {_list(sorted(prior.inside))} on a path to {name}, and a "
                                "key has one producer per path; put the second in a loop if it is a rewrite, or give it a different name", name)
                    produced.add(k)
                    continue  # the first producer's key stands, so its readers report nothing more
                if prior.type.kind is not None and t.kind is not None and prior.type.kind != t.kind:
                    self.report("type_mismatch", d, f"{k} is {t.noun()} here, but {_list(sorted(prior.producers))} produced it as "
                                f"{prior.type.noun()}; every declaration of a key agrees on its type", name)
                inside = prior.inside
            entry = Entry(t, frozenset({name}), inside | {name})
            must[k] = entry
            may[k] = entry
            produced.add(k)
        return produced

    @staticmethod
    def declared_type(st: s.Step, d: s.Declaration, name: str) -> Type:
        if st.kind == "Decide":
            fields = tuple((q.name, Type(q.type, labels=tuple(q.labels) or ("true", "false"), sources=(name,))) for q in st.questions)
            return Type("decision", fields=fields, sources=(name,))
        if st.kind == "Aggregate":
            fields = tuple((a.name, Type("true_or_false", labels=("true", "false"), sources=(name,))) for a in st.aggregations)
            return Type("aggregation", fields=fields, sources=(name,))
        if d.type is None:
            return Type()
        labels = ("true", "false") if d.type == "true_or_false" else tuple(d.labels) if d.labels else None
        return Type(d.type, labels=labels, sources=(name,))

    def check_reads(self, st: s.Step, m_in: State, name: str):
        for d in st.reads:
            t = self.resolve(d.key.path, m_in, d, name)
            if t is not None and d.type is not None and t.kind is not None and t.kind != d.type:
                producers = m_in[d.key.name].producers
                self.report("type_mismatch", d, f"{d.key.dotted} is read as {Type(d.type).describe()}, but {_list(sorted(producers))} "
                            f"produced it as {t.noun()}; every declaration of a key agrees on its type", name)

    def check_text(self, text: s.Str, state: State, step: str):
        """`{key}` and `{decision.question}` in a question or a prompt count as reads."""
        literal = self.text_of(text)
        if literal is None:
            return
        for f in literal.fields:
            self.resolve(f.path, state, f, step)

    def resolve(self, path: list[str], state: State, node: s.Node, step: str) -> Type | None:
        """The type a key path names in `state`, or None after reporting why not."""
        root = path[0]
        entry = state.get(root)
        if entry is None:
            self.report_missing(root, node, step)
            return None
        t = entry.type
        for i, seg in enumerate(path[1:], 1):
            nt = t.field(seg)
            if nt is None:
                prefix = ".".join(path[:i])
                if t.kind == "loop":
                    have = t.fields[0][0]
                    message = (f"{prefix}.{seg}: {prefix} is the key of the loop {prefix}, which holds {prefix}.index inside its body and "
                               f"{prefix}.iterations after it exits; here it has {have}")
                elif t.fields is not None:
                    what = "question" if t.kind == "decision" else "aggregation"
                    message = f"{prefix} has no {what} {seg}; it has {_list(n for n, _ in t.fields)}"
                elif t.is_answer:
                    message = f"{prefix} is {t.describe()}; its fields are value and confidence"
                else:
                    message = f"{prefix} is {t.describe()} and has no field {seg}"
                self.report("unknown_field", node, message, step)
                return None
            t = nt
        return t

    def report_missing(self, root: str, node: s.Node, step: str):
        if root == "index":
            self.report("unavailable_key", node, "index names the pass and is available only inside a loop body", step)
        elif root == "iterations":
            self.report("unavailable_key", node, "iterations says how many passes a loop ran and is available only after one", step)
        elif root in self.loops:
            self.report("unavailable_key", node, f"{root} is the key of the loop {root}: {root}.index is available inside its body and "
                        f"{root}.iterations after it exits, on the paths that ran it; neither is available at {step}", step)
        elif root in self.anywhere:
            producers = self.anywhere[root]
            enclosing_for = self.for_keys.get(root)
            if enclosing_for is not None and enclosing_for not in self.path:
                self.report("unavailable_key", node, f"{root} is produced inside For {enclosing_for}, whose keys are per-pass and gone when "
                            f"the loop exits; Collect {root} Into <list> keeps them", step)
            else:
                verb = "does" if len(producers) == 1 else "do"
                self.report("unavailable_key", node, f"{root} is not available at {step}: {_list(producers)} {verb} not run before it "
                            "on every path", step)
        elif not self.keyless:
            self.report("unknown_key", node, f"nothing produces {root}; a key is an input of Start or a Produce of a step", step)

    # ------------------------------------------------------------ routes, conditions, aggregations

    def classify(self, sources: tuple[str, ...]) -> dict[str, list[str]]:
        """The source classes of an answer (spec 2.2, `SOURCE_CLASSES`), each with the steps that
        produce it under that class."""
        classes: dict[str, list[str]] = {}
        for src in sources:
            node = self.nodes.get(src)
            kind = node.kind if isinstance(node, s.Step) else None
            classes.setdefault(SOURCE_CLASSES.get(kind, "measured"), []).append(src)
        return classes

    def check_confidence(self, node: s.Node, dotted: str, classes: dict[str, list[str]], step: str, what: str, where: str):
        """A `Confidence_Below` or `With Confidence_Above` on an answer: allowed on a decision
        model's or a script's, an error on an agent's, an input or an aggregation (spec 2.4)."""
        on_a_path = " on one path" if len(classes) > 1 else ""
        for cls, culprits in classes.items():
            code = CONFIDENCE_ERRORS[cls]
            if code is None:
                continue
            if cls == "aggregated":
                message = (f"{dotted} is an aggregation{on_a_path}, which has no confidence by design (spec 2.5), so {what} "
                           f"cannot apply to it; {where}")
            elif cls == "agent":
                message = (f"{dotted} is the agent's answer{on_a_path} (produced by {_list(culprits)}), which has a value and no "
                           f"confidence, so {what} cannot apply to it; {where}, or ask a decision model in a Decide")
            else:
                message = (f"{dotted} is an input of Start{on_a_path}, which has no confidence, so {what} cannot apply to it; {where}")
            self.report(code, node, message, step)

    @staticmethod
    def not_an_answer(dotted: str, t: Type, where: str) -> str:
        if t.kind in ("decision", "aggregation"):
            example = f"{dotted}.{t.fields[0][0]}" if t.fields else f"{dotted}.<name>"
            return f"{dotted} is {t.describe()} as a whole; {where} is on one answer, such as {example}"
        if t.kind == "list":
            return f"{dotted} is {t.describe()}; {where} is on one answer"
        if t.kind is None:
            return f"the type of {dotted} is not known (an item of a plain list); {where} is on an answer (true_or_false, choice or score)"
        return (f"{dotted} is {t.describe()}; {where} is on an answer (true_or_false, choice or score), never a plain value. "
                "A script or an agent task that drives one produces an answer type")

    def check_route(self, st: s.Step, m_in: State, name: str):
        reads = st.reads
        if len(reads) != 1:
            self.report_head("route_reads_one", st, f"Route {name} reads {len(reads)} keys; a route reads one answer and branches on its value")
            for d in reads[1:]:
                self.resolve(d.key.path, m_in, d, name)
            if not reads:
                return
        read = reads[0]
        t = self.resolve(read.key.path, m_in, read, name)
        if t is None:
            return
        dotted = read.key.dotted
        if not t.is_answer:
            self.report("condition_on_plain_value", read, self.not_an_answer(dotted, t, "a route"), name)
            return
        seen: set[str] = set()
        unknown = [b for b in st.branches if t.labels is not None and b.value not in t.labels]
        if unknown:
            values = list(dict.fromkeys(b.value for b in unknown))
            verb = "is not a value" if len(values) == 1 else "are not values"
            self.report("unknown_label", unknown[0], f"{_list(values)} {verb} of {dotted}; its values are {_list(t.labels)}", name)
        for b in st.branches:
            if b.value in seen:
                self.report("duplicate_branch", b, f"{b.value} already has a branch in {name}", name)
            seen.add(b.value)
        if t.labels is not None and not unknown:
            missing = [label for label in t.labels if label not in seen]
            if missing:
                self.report_head("missing_branch", st, f"Route {name} has no branch for {_list(missing)}; a route names every value "
                                 f"{dotted} can take")
        classes = self.classify(t.sources)
        self.sources[name] = source_class(classes)
        if st.check is not None:
            self.check_confidence(st.check, dotted, classes, name, "Confidence_Below", "route on its value alone")

    def check_aggregate(self, st: s.Step, m_in: State, name: str):
        read_roots = {r.key.name for r in st.reads}
        for agg in st.aggregations:
            cond = agg.condition
            if cond.answer.name not in read_roots:
                self.report("source_not_read", cond.answer, f"the source {cond.answer.dotted} is not in Read; an Aggregate reads what it aggregates", name)
            t = self.resolve(cond.answer.path, m_in, cond.answer, name)
            if t is None:
                continue
            for dotted, answer in self.answers_of(t, cond.answer, name):
                self.check_condition(answer, cond, dotted, name, f"the aggregation {agg.name}")

    def answers_of(self, t: Type, node: s.KeyRef, step: str) -> list[tuple[str, Type]]:
        """The answers an aggregation source names: one, a decision's, an aggregation's, or those
        of a collected list, each with the path that names it for messages."""
        dotted = node.dotted
        if t.is_answer:
            return [(dotted, t)]
        if t.kind in ("decision", "aggregation"):
            return [(f"{dotted}.{n}", ft) for n, ft in (t.fields or ())]
        if t.kind == "list":
            if t.element is None or t.element.kind is None:
                self.report("condition_on_plain_value", node, f"{dotted} is a list whose elements are not known to be answers; an aggregation's "
                            "source is an answer, a decision, a field through a collected list, or a list collected from an answer key", step)
                return []
            return [(f"{dotted}[]" + d[len(dotted):], ft) for d, ft in self.answers_of(t.element, node, step)]
        self.report("condition_on_plain_value", node, self.not_an_answer(dotted, t, "an aggregation"), step)
        return []

    def check_condition(self, t: Type, cond: s.Condition, dotted: str, step: str, where: str):
        if t.kind == "true_or_false":
            if cond.operator is not None and cond.value not in ("true", "false"):
                self.report("unknown_label", cond, f"{dotted} is a true_or_false answer; compare it with true or false, not {cond.value}", step)
        elif t.is_answer:
            word = "label" if t.kind == "choice" else "level"
            if cond.operator is None:
                have = f" ({_list(t.labels)})" if t.labels else ""
                self.report("comparison_required", cond, f"{dotted} is a {t.kind} answer, which has no yes or no of its own; write "
                            f"{dotted} == <{word}> or != <{word}>{have}", step)
            elif t.labels is not None and cond.value not in t.labels:
                self.report("unknown_label", cond, f"{cond.value} is not a {word} of {dotted}; its {word}s are {_list(t.labels)}", step)
        if cond.confidence_above is not None:
            self.check_confidence(cond, dotted, self.classify(t.sources), step, "With Confidence_Above",
                                  f"drop the bar and let every answer count as it is in {where}")

    # ------------------------------------------------------------ loops

    def visit_loop(self, loop, m_in: State, y_in: State, path: tuple[str, ...], edges) -> tuple[State, State, set[str]]:
        name = loop.name
        inner = path + (name,)
        body_must, body_may = _reset(m_in), _reset(y_in)
        pass_keys = ["index", name]
        if isinstance(loop, s.ForLoop):
            self.check_cap(loop, loop.at_most, "At_Most")
            self.bind_item(loop, loop.item, self.over_type(loop.over, m_in, name), m_in, y_in, body_must, body_may)
            pass_keys.append(loop.item)
            if loop.collect is not None:
                c = loop.collect
                if c.into in RESERVED_KEYS:
                    self.report("reserved_key", c, f"{c.into} is the runtime's and cannot be collected into", name)
                elif c.into in self.loops:
                    self.report("duplicate_name", c, self.loop_key_clash(c.into, "list"), name)
                elif c.into in y_in or c.into == loop.item:
                    other = _list(sorted(y_in[c.into].producers)) if c.into in y_in else f"the item of For {name}"
                    self.report("duplicate_producer", c, f"Collect Into {c.into}: {c.into} is already produced by {other}; a key has one "
                                "producer per path, so collect into a new name", name)
        else:
            if loop.mode == "Times":
                self.check_cap(loop, loop.times, "Times")
            else:
                self.check_cap(loop, loop.at_most, "At_Most")
            if loop.mode == "Over":
                self.bind_item(loop, loop.item, self.over_type(loop.over, m_in, name), m_in, y_in, body_must, body_may)
                pass_keys.append(loop.item)
        # The pass's number, under the loop's own name and under the bare shorthand, which an
        # inner loop's body rebinds to its own.
        body_must["index"] = body_may["index"] = Entry(Type("integer"), frozenset({name}), frozenset({name}))
        body_must[name] = body_may[name] = Entry(Type("loop", fields=(("index", Type("integer")),)), frozenset({name}), frozenset({name}))
        body = self.region(loop.body, loop, inner, body_must, body_may, edges)
        self.path = path
        if isinstance(loop, s.ForLoop):
            must_out, may_out = dict(m_in), dict(y_in)
            produced: set[str] = set()
            if loop.collect is not None and loop.collect.into not in RESERVED_KEYS and loop.collect.into not in self.loops:
                element = self.collected(loop, body, name)
                entry = Entry(Type("list", element=element, sources=element.sources), frozenset({name}), frozenset({name}))
                must_out[loop.collect.into] = may_out[loop.collect.into] = entry
                produced.add(loop.collect.into)
        else:
            exits = list(body.continues) + list(body.agains)
            if loop.mode == "Until":
                exits += self.check_until(loop, m_in, y_in, body, name)
            if not exits:
                exits = [(body_must, body_may)]
            must_out = self.meet([m for m, _ in exits], loop)
            may_out = _join([y for _, y in exits])
            for k in pass_keys:
                must_out.pop(k, None)
                may_out.pop(k, None)
            produced = {k for k, e in may_out.items() if e.inside}
            for state, outer in ((must_out, m_in), (may_out, y_in)):
                for k, e in list(state.items()):
                    outside = outer[k].inside if k in outer else frozenset()
                    state[k] = Entry(e.type, e.producers, e.inside | outside)
        # How many passes ran, under the loop's own name (which a later loop does not overwrite)
        # and under the bare shorthand, which is the last loop's that exited.
        must_out["iterations"] = may_out["iterations"] = Entry(Type("integer"), frozenset({name}), frozenset({name}))
        must_out[name] = may_out[name] = Entry(Type("loop", fields=(("iterations", Type("integer")),)), frozenset({name}), frozenset({name}))
        return must_out, may_out, produced

    def check_cap(self, loop, cap: int | None, keyword: str):
        if cap is None:
            self.report_head("missing_cap", loop, f"{_label(loop)} has no At_Most; every loop names the most passes it may run, so that a run "
                             "ends in a number of steps computable from the file")
        elif cap < 1:
            self.report_head("missing_cap", loop, f"{keyword} {cap} on {_label(loop)}: the cap is at least 1")

    def over_type(self, over: s.KeyRef, m_in: State, name: str) -> Type:
        t = self.resolve(over.path, m_in, over, name)
        if t is None or t.kind is None:
            return Type()
        if t.kind != "list":
            self.report("type_mismatch", over, f"Over needs a list; {over.dotted} is {t.describe()}", name)
            return Type()
        return t.element or Type()

    def bind_item(self, loop, item: str, t: Type, m_in: State, y_in: State, body_must: State, body_may: State):
        name = loop.name
        if item in RESERVED_KEYS:
            self.report_head("reserved_key", loop, f"the item cannot be called {item}; index and iterations are the runtime's")
        elif item in self.loops:
            self.report_head("duplicate_name", loop, self.loop_key_clash(item, "item"))
            return
        elif item in y_in:
            self.report_head("duplicate_producer", loop, f"the item {item} of {_label(loop)} is named like the key {item} produced by "
                             f"{_list(sorted(y_in[item].producers))}; name the item differently")
        body_must[item] = body_may[item] = Entry(t, frozenset({name}), frozenset({name}))

    def collected(self, loop: s.ForLoop, body: RegionResult, name: str) -> Type:
        c = loop.collect
        ends = body.continues
        if not ends:
            return Type()
        in_body = c.key == loop.item or any(c.key in y and y[c.key].inside for _, y in ends)
        if not in_body:
            self.report("unknown_key", c, f"Collect {c.key}: no step in For {name} produces {c.key}; Collect gathers a key the body produces, "
                        "one value per pass", name)
            return Type()
        missing = [m for m, _ in ends if c.key not in m or (c.key != loop.item and not m[c.key].inside)]
        if missing:
            self.report("unavailable_key", c, f"Collect {c.key}: a pass of For {name} may end without producing {c.key}; every path through "
                        "the body to Continue must produce it", name)
        element = Type()
        for m, _ in ends:
            if c.key in m:
                element, _ = _merge_type(element, m[c.key].type)
        return element

    def check_until(self, loop: s.Loop, m_in: State, y_in: State, body: RegionResult, name: str) -> list[tuple[State, State]]:
        """The exit points an `Until` adds: after every body node that produces the answer, and the
        head before any pass when the answer may exist before the loop (the condition is tested at
        the head, so a loop whose answer already holds runs no pass). Also checks the condition."""
        cond = loop.until
        root = cond.answer.name
        points = body.produce_points.get(root, [])
        before = root in m_in
        if not before and not points:
            if root in self.anywhere:
                self.report("unavailable_key", cond.answer, f"Until watches {cond.answer.dotted}, but {root} is produced neither before "
                            f"Loop {name} nor by a step in its body", name)
            else:
                self.report_missing(root, cond.answer, name)
            return []
        state = m_in if before else points[0][0]
        t = self.resolve(cond.answer.path, state, cond.answer, name)
        if t is not None:
            if not t.is_answer:
                self.report("condition_on_plain_value", cond.answer, self.not_an_answer(cond.answer.dotted, t, "Until"), name)
            else:
                self.check_condition(t, cond, cond.answer.dotted, name, f"the Until of Loop {name}")
        exits = list(points)
        if root in y_in:
            exits.append((m_in, y_in))
        return exits


# ---------------------------------------------------------------- entry points

def check(program: s.Program, folder: Path | str | None = None, file: str | None = None, *,
          files: set[str] | None = None, sources: dict[str, str] | None = None) -> list[Diagnostic]:
    """Every diagnostic for a parsed program, sorted by position. `folder` is the program
    directory, for the checks on files; `files` are the program's file paths when they are in
    hand instead (a bundle's); without either those checks are skipped. A dict passed as
    `sources` is filled with the source class of the answer each route reads (route name to
    one of `SOURCE_PRECEDENCE`), which the graph writes on the route's `READ_BY` edge."""
    checker = Checker(program, Path(folder) if folder is not None else None, file, files)
    diagnostics = checker.run()
    if sources is not None:
        sources.update(checker.sources)
    return diagnostics


def check_source(source: str, file: str | None = None, folder: Path | str | None = None, *,
                 sources: dict[str, str] | None = None) -> tuple[s.Program | None, list[Diagnostic]]:
    """Parse and check source text. A syntax error is the one diagnostic (`syntax_error`)."""
    from aip.compiler.parser import parse

    try:
        program = parse(source, file)
    except ParseError as exc:
        return None, [Diagnostic(**exc.to_diagnostic())]
    return program, check(program, folder, file, sources=sources)


def check_path(path: Path | str) -> tuple[s.Program | None, list[Diagnostic]]:
    """Check a program directory, or its `procedure.aip`."""
    path = Path(path)
    file = path / SOURCE_FILE if path.is_dir() else path
    return check_source(file.read_text(encoding="utf-8"), str(file), file.parent)


def has_errors(diagnostics: list[Diagnostic]) -> bool:
    return any(d.severity == "error" for d in diagnostics)
