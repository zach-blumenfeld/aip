"""A procedure as a plain Agent Skill (`aip export <target> --skill DIR`, plan K2).

The escape hatch for an agent with no runtime: the bundle written out as a `SKILL.md` an agent
reads and follows by hand, with the bundle's files beside it. Nothing here runs anything, and the
page says so: no step is recorded, no decision model is asked, and a `Decide`, a confidence check
or an aggregation's bar is the agent's own judgment.

`render_skill(graph)` is one function over the bundle's graph (`docs/language/bundle.md`), the
nodes and edges the extension and the console draw: the header becomes the frontmatter and the
opening sections, and the steps are walked in control-flow order from `Start`, each once,
numbered, a loop's body right after its loop, `End` last. Each step says what it reads, what it
produces and where to go next; a route lists its branches, a loop its passes and its exit.
`export_skill(bundle, out)` writes that page and the files.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path, PurePosixPath

from aip.compiler.bundle import Bundle, BundleError
from aip.compiler.graph import PROCEDURE_ID, Graph, GraphEdge, GraphNode

SKILL_FILE = "SKILL.md"
# The Agent Skills limits: a name of lowercase letters, digits and hyphens, at most 64
# characters; a description of at most 1024.
NAME_LIMIT = 64
DESCRIPTION_LIMIT = 1024

FLOW = ("NEXT", "BELOW", "BRANCH", "CONTINUES")
KIND_WORDS = {"Start": "start", "Decide": "your judgment", "Route": "route", "Aggregate": "aggregate",
              "Execute": "run a script", "Task_Agent": "your task", "End": "end"}


def skill_name(procedure: str) -> str:
    """The Agent Skills name of a procedure: `billing_support` is `billing-support`."""
    name = re.sub(r"[^a-z0-9]+", "-", procedure.lower()).strip("-")
    return (name or "procedure")[:NAME_LIMIT].rstrip("-")


def _one_line(text: str | None) -> str:
    return " ".join((text or "").split())


def _code(name: str) -> str:
    return f"`{name}`"


def _span_key(e: GraphEdge) -> tuple:
    return (e.properties.get("line") or 0, e.properties.get("column") or 0)


class _Walk:
    """The graph, read for the page: control-flow order, numbers, and the facts each step needs."""

    def __init__(self, graph: Graph):
        self.g = graph
        self.nodes = {n.id: n for n in graph.nodes}
        self.out: dict[str, list[GraphEdge]] = {}
        self.into: dict[str, list[GraphEdge]] = {}
        for e in graph.edges:
            self.out.setdefault(e.start, []).append(e)
            self.into.setdefault(e.end, []).append(e)
        self.parent: dict[str, str] = {}       # a body member -> its loop
        for e in graph.edges:
            if e.type == "CONTAINS":
                self.parent[e.end] = e.start
        self.order: list[str] = []
        self.number: dict[str, int] = {}
        start = next(e.end for e in graph.edges if e.type == "STARTS_AT")
        end = next((e.end for e in graph.edges if e.type == "ENDS_AT"), None)
        self.end = end
        self._walk(start, None)
        if end is not None and end not in self.number:
            self._place(end)

    # ---------------------------------------------------------------- order

    def edges(self, start: str, *types: str) -> list[GraphEdge]:
        return sorted((e for e in self.out.get(start, []) if e.type in types), key=_span_key)

    def _place(self, id: str) -> None:
        self.number[id] = len(self.order) + 1
        self.order.append(id)

    def _walk(self, first: str, loop: str | None) -> None:
        """Breadth first from `first` over the flow inside one body (or the top level), placing a
        loop's body right after the loop and leaving `End` for last."""
        queue = [first]
        seen = {first}
        while queue:
            id = queue.pop(0)
            if id == self.end:
                continue
            self._place(id)
            if id.startswith("loop:"):
                entry = self.edges(id, "ENTERS")
                if entry:
                    self._walk(entry[0].end, id)
                for e in sorted(self.edges(id, "CONTAINS"), key=lambda e: e.properties.get("order", 0)):
                    if e.end not in self.number:   # not reached from the entry: placed anyway
                        self._walk(e.end, id)
            for e in self.edges(id, *FLOW):
                target = e.end
                if e.type == "CONTINUES" or e.properties.get("continues"):
                    continue
                if self.parent.get(target) != loop or target in seen:
                    continue
                seen.add(target)
                queue.append(target)

    # ---------------------------------------------------------------- facts

    def name(self, id: str) -> str:
        return self.nodes[id].properties.get("name", id)

    def ref(self, id: str) -> str:
        n = self.nodes[id]
        if "Start" in n.labels:
            return f"step {self.number[id]}, Start"
        if "End" in n.labels:
            return f"step {self.number[id]}, End"
        what = "the loop " if "Loop" in n.labels else ""
        return f"step {self.number[id]}, {what}{_code(self.name(id))}"

    def go(self, e: GraphEdge) -> str:
        """Where a flow edge leads, as an instruction."""
        if e.type == "CONTINUES" or e.properties.get("continues"):
            loop = e.end
            return f"this pass of {_code(self.name(loop))} is over: go back to step {self.number[loop]}"
        return f"go to {self.ref(e.end)}"

    def data(self, id: str) -> GraphNode:
        return self.nodes[id]

    def reads(self, step: str) -> list[str]:
        out = []
        for e in sorted(self.into.get(step, []), key=_span_key):
            if e.type != "READ_BY" or e.properties.get("interpolated"):
                continue
            key = self.name(e.start) + ("." + e.properties["field"] if e.properties.get("field") else "")
            if key not in out:
                out.append(key)
        return out

    def interpolated(self, step: str) -> list[str]:
        out = []
        for e in self.into.get(step, []):
            if e.type == "READ_BY" and e.properties.get("interpolated"):
                key = self.name(e.start) + ("." + e.properties["field"] if e.properties.get("field") else "")
                if key not in out:
                    out.append(key)
        return out

    def produces(self, id: str) -> list[GraphNode]:
        return [self.nodes[e.end] for e in sorted(self.edges(id, "PRODUCES"), key=_span_key)
                if not self.nodes[e.end].properties.get("runtime")]

    def files(self, step: str, type: str) -> list[GraphEdge]:
        return self.edges(step, type)

    def within(self, id: str, loop: str) -> bool:
        while id in self.parent:
            id = self.parent[id]
            if id == loop:
                return True
        return False

    def watchers(self, step: str) -> list[tuple[GraphNode, GraphEdge]]:
        """The `Until` loops whose answer this step produces: the step tests their condition."""
        made = {e.end for e in self.edges(step, "PRODUCES")}
        out = []
        for loop in self.g.with_label("Loop"):
            for w in self.edges(loop.id, "WATCHES"):
                if w.end in made and self.within(step, loop.id):
                    out.append((loop, w))
        return out


# -------------------------------------------------------------------- text

def _type(d: GraphNode) -> str:
    p = d.properties
    labels = p.get("labels")
    type = p.get("type")
    if type == "choice" and labels:
        return "one of " + ", ".join(labels)
    if type == "score" and labels:
        return "a level of " + ", ".join(labels)
    if type == "true_or_false":
        return "true or false"
    return type or ""


def _key_line(d: GraphNode) -> str:
    t = _type(d)
    text = _code(d.properties["name"]) + (f" ({t})" if t else "")
    if d.properties.get("description"):
        text += ": " + _one_line(d.properties["description"])
    return text


def _condition(answer: str, operator: str | None, value, confidence: float | None) -> str:
    if operator == "==":
        text = f"{_code(answer)} is {_code(_value(value))}"
    elif operator == "!=":
        text = f"{_code(answer)} is not {_code(_value(value))}"
    else:
        text = f"{_code(answer)} is true"
    if confidence is not None:
        text += f", and you are more than {confidence} sure of it"
    return text


def _value(value) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


def _indent(text: str, by: str = "  ") -> str:
    return "\n".join(by + line if line else line for line in text.splitlines())


def _quote(text: str) -> list[str]:
    return ["> " + line if line else ">" for line in text.strip("\n").splitlines()]


def render_skill(graph: Graph, *, bundle_id: str | None = None, run_with: str | None = None) -> str:
    """The `SKILL.md` of a procedure, from its graph. `run_with` is the target named in the line
    that says how to run it under `aip` instead (the published name it was exported from); without
    it the line names no target."""
    w = _Walk(graph)
    proc = graph.node(PROCEDURE_ID).properties
    name = proc["name"]
    description = _one_line(proc.get("description"))
    use_when = [_one_line(t) for t in proc.get("use_when") or []]
    meta_description = description + (" Use when: " + " ".join(use_when) if use_when else "")
    if len(meta_description) > DESCRIPTION_LIMIT:
        meta_description = meta_description[:DESCRIPTION_LIMIT - 1].rstrip() + "…"
    bundle_id = bundle_id or proc.get("bundle_id")
    lines = ["---", f"name: {skill_name(name)}", f"description: {json.dumps(meta_description, ensure_ascii=False)}", "metadata:",
             f"  aip-procedure: {json.dumps(name)}", f"  aip-bundle: {json.dumps(bundle_id)}",
             f"  aip-language: {json.dumps(proc.get('language_version'))}", "---", "",
             f"# {name}", "", "\n".join(l.strip() for l in (proc.get("description") or "").strip().splitlines()), ""]
    run = (f"`aip run {run_with} --inputs '{{...}}'`" if run_with
           else "`aip run` on its folder, its bundle or its published name")
    lines += [
        f"This is the AIP procedure {_code(name)} (bundle `{(bundle_id or '')[:12]}`), written out by `aip export --skill`",
        "to be followed by hand. Nothing checks that you follow it: no step is recorded, no decision",
        "model is asked, and where the procedure asks a question, checks a confidence or applies a bar,",
        "your own judgment stands in for the model's. Where `aip` is installed, run the procedure with",
        f"{run} instead; it asks you only for the steps that are yours.", ""]
    for heading, key in (("Use when", "use_when"), ("Do not use when", "do_not_use_when"), ("Avoid", "avoid")):
        if proc.get(key):
            lines += [f"## {heading}", ""] + [f"- {_one_line(t)}" for t in proc[key]] + [""]
    if proc.get("requires_interpreter"):
        need = (proc["requires_interpreter"] + " " + (proc.get("requires_version") or "")).strip()
        lines += ["## Requires", "", f"{need}, to run the scripts under `scripts/`.", ""]
    lines += ["## How to follow it", "",
              "Start at step 1 and follow the steps by number as each one says. Keep every value a step",
              "produces under its name: later steps read it by that name, and `a.b` is the field `b` of `a`.",
              "In a question or a prompt, `{key}` stands for the value of `key`, and `{assets[stem]}` for the",
              "text of the file the step uses whose name, without its extension, is `stem`. Paths are relative",
              "to this folder.", "", "## Steps", ""]
    for id in w.order:
        lines += _step(w, id) + [""]
    return "\n".join(lines).rstrip() + "\n"


def _flow_lines(w: _Walk, id: str) -> list[str]:
    out = []
    for e in w.edges(id, "NEXT", "CONTINUES"):
        out.append(f"- Then {w.go(e)}.")
    return out


def _uses(w: _Walk, id: str) -> list[str]:
    uses = w.files(id, "USES")
    if not uses:
        return []
    out = ["- Uses:"]
    for e in uses:
        path = w.nodes[e.end].properties["path"]
        text = _one_line(e.properties.get("description"))
        out.append(f"  - `{path}`" + (f": {text}" if text else ""))
    return out


def _until(w: _Walk, id: str) -> list[str]:
    out = []
    for loop, e in w.watchers(id):
        p = loop.properties
        answer = w.name(e.end) + ("." + e.properties["field"] if e.properties.get("field") else "")
        cond = _condition(answer, e.properties.get("operator"), e.properties.get("value"), e.properties.get("confidence_above"))
        exits = w.edges(loop.id, "NEXT", "CONTINUES")
        where = w.go(exits[0]) if exits else "leave it"
        out.append(f"- Now test the loop {_code(p['name'])}: if {cond}, leave the loop: {where}.")
    return out


def _step(w: _Walk, id: str) -> list[str]:
    n = w.nodes[id]
    p = n.properties
    num = w.number[id]
    depth = 0
    walk = id
    while walk in w.parent:
        depth += 1
        walk = w.parent[walk]
    hashes = "#" * min(3 + depth, 6)
    if "Loop" in n.labels:
        return _loop(w, id, hashes)
    kind = p["kind"]
    if kind == "Start":
        title = f"{hashes} {num}. Start"
    elif kind == "End":
        title = f"{hashes} {num}. End"
    else:
        title = f"{hashes} {num}. {_code(p['name'])} ({KIND_WORDS[kind]})"
    out = [title, ""]
    if p.get("description") and not (kind == "Task_Agent" and not p.get("prompt")):
        out += [_one_line(p["description"]), ""]
    reads = w.reads(id)
    if kind == "Start":
        made = w.produces(id)
        out += ["The inputs, which whoever asked for the procedure gives you:"] if made else ["The procedure takes no input."]
        out += [f"- {_key_line(d)}" for d in made]
        return out + [""] + [l[2:] for l in _flow_lines(w, id)]
    if kind == "End":
        out += ["The procedure is done. Report these, each that this path produced:"] if reads else ["The procedure is done."]
        return out + [f"- {_code(r)}" for r in reads]
    if reads:
        out.append("- Reads: " + ", ".join(_code(r) for r in reads))
    if kind == "Decide":
        out += _decide(w, id)
    elif kind == "Route":
        out += _route(w, id)
        return out
    elif kind == "Aggregate":
        out += _aggregate(w, id)
    elif kind == "Execute":
        out += _execute(w, id)
    elif kind == "Task_Agent":
        out += _task(w, id)
    out += _until(w, id)
    return out + _flow_lines(w, id)


def _decide(w: _Walk, id: str) -> list[str]:
    p = w.nodes[id].properties
    out = ["- Answer these questions yourself, about what the step reads. In the runtime a decision model",
           "  answers them with a confidence; here the answer and how sure you are of it are your judgment."]
    if p.get("history"):
        out.append("  Take everything done so far in this procedure into account.")
    for e in sorted(w.edges(id, "ASKS"), key=lambda e: e.properties.get("order", 0)):
        q = w.nodes[e.end].properties
        t = q.get("type")
        kind = {"true_or_false": "true or false", "choice": "one of " + ", ".join(q.get("labels") or []),
                "score": "a level of " + ", ".join(q.get("labels") or [])}.get(t, t or "")
        out.append(f"  - {_code(q['name'])} ({kind}): {_one_line(q.get('instruction'))}")
        for label, text in zip(q.get("criteria_labels") or [], q.get("criteria_texts") or []):
            out.append(f"    - {_code(label)}: {_one_line(text)}")
    produced = p.get("produces")
    if produced:
        out.append(f"- Produces {_code(produced)}, your answers by question: {_code(produced + '.<question>')}.")
    return out


def _route(w: _Walk, id: str) -> list[str]:
    out = ["- Go by the value you read:"]
    for e in w.edges(id, "BELOW", "BRANCH"):
        if e.type == "BELOW":
            out.append(f"  - First: if you are less than {e.properties['below']} sure of that value, {w.go(e)}.")
        else:
            out.append(f"  - {_code(_value(e.properties['value']))}: {w.go(e)}.")
    return out


def _aggregate(w: _Walk, id: str) -> list[str]:
    p = w.nodes[id].properties
    words = {"All": "every", "Any": "at least one", "None": "no"}
    out = []
    for e in sorted(w.edges(id, "AGGREGATES"), key=lambda e: e.properties.get("order", 0)):
        a = w.nodes[e.end].properties
        cond = _condition("it", a.get("operator"), a.get("value"), a.get("confidence_above")).replace("`it`", "it", 1)
        out.append(f"  - {_code(a['name'])}: true when {words.get(a.get('mode'), a.get('mode'))} answer in {_code(a['source'])} "
                   f"holds, where an answer holds when {cond}; otherwise false.")
    produced = p.get("produces")
    head = f"- Produces {_code(produced)}, with one true or false value for each of:" if produced else "- Works out:"
    return [head] + out


def _execute(w: _Walk, id: str) -> list[str]:
    p = w.nodes[id].properties
    script = p.get("script")
    proc = w.g.node(PROCEDURE_ID).properties
    interpreter = proc.get("requires_interpreter") or "the interpreter its first line names"
    stems = [PurePosixPath(w.nodes[e.end].properties["path"]).stem for e in w.files(id, "USES")]
    made = w.produces(id)
    payload = {"state": {r.rsplit(".", 1)[-1]: "..." for r in w.reads(id)},
               "assets": {s: "<the file's text>" for s in stems},
               "expects": {d.properties["name"]: d.properties.get("type") or "any" for d in made}}
    out = [f"- Run `{script}` with {interpreter}, from this folder, giving it on stdin one JSON object:",
           f"  `{json.dumps(payload)}`",
           "  (`state` holds what the step reads, each under the last word of its name). It prints one JSON",
           "  object, the values this step produces. If it exits with an error, stop: the procedure failed here.",
           "  Do not do the script's work by hand."]
    out += _uses(w, id)
    if made:
        out.append("- Produces:")
        out += [f"  - {_key_line(d)}" for d in made]
    return out


def _task(w: _Walk, id: str) -> list[str]:
    p = w.nodes[id].properties
    out = []
    prompt = w.files(id, "PROMPTED_BY")
    if prompt:
        path = w.nodes[prompt[0].end].properties["path"]
        out.append(f"- Do what `{path}` says, filling in each `{{key}}` with its value.")
    else:
        out += ["- Do this:", ""] + _indent("\n".join(_quote(p.get("description") or "")), "  ").splitlines() + [""]
    out += _uses(w, id)
    made = w.produces(id)
    if made:
        out.append("- Produces:")
        out += [f"  - {_key_line(d)}" for d in made]
    return out


def _loop(w: _Walk, id: str, hashes: str) -> list[str]:
    n = w.nodes[id]
    p = n.properties
    num = w.number[id]
    body = [m for m in w.order if w.parent.get(m) == id]
    inside = [m for m in w.order if w.within(m, id)]
    first, last = w.number[inside[0]], w.number[inside[-1]]
    entry = w.edges(id, "ENTERS")
    start = w.ref(entry[0].end) if entry else f"step {first}"
    if first == last:
        steps = start
    else:
        steps = (f"steps {first} and {last}" if last == first + 1 else f"steps {first} to {last}") + f", from {start}"
    exits = w.edges(id, "NEXT", "CONTINUES")
    after = w.go(exits[0]) if exits else "go on"
    over = w.edges(id, "OVER")
    lst = (w.name(over[0].end) + ("." + over[0].properties["field"] if over[0].properties.get("field") else "")) if over else None
    out = [f"{hashes} {num}. The loop {_code(p['name'])}", ""]
    if p.get("mode") == "Over":
        cap = f"at most {p.get('at_most')} of them (if it holds more, stop: the procedure fails)"
        out.append(f"Go through {_code(lst)} one item at a time, {cap}. For each item, with it as {_code(p.get('item'))}, "
                   f"do one pass of {steps}.")
        if p.get("kind") == "For":
            out[-1] += " Each pass stands on its own: it sees the item and what existed before the loop, never what another pass produced."
            if p.get("collect_key"):
                out += ["", f"Keep each pass's {_code(p['collect_key'])}, in the list's order, as the list {_code(p['collect_into'])}; "
                        "everything else a pass produced is gone after the loop."]
            else:
                out += ["", "What a pass produces is gone after the loop."]
        else:
            out[-1] += " Each pass sees what the one before it produced."
        out += ["", f"When every item has had its pass, {after}."]
    elif p.get("mode") == "Times":
        out += [f"Do {steps}, {p.get('times')} times. Each pass sees what the one before it produced.", "",
                f"After the last pass, {after}."]
    else:
        e = w.edges(id, "WATCHES")[0]
        answer = w.name(e.end) + ("." + e.properties["field"] if e.properties.get("field") else "")
        cond = _condition(answer, e.properties.get("operator"), e.properties.get("value"), e.properties.get("confidence_above"))
        cap = "stop: the procedure fails" if p.get("at_cap", "Else_Fail") == "Else_Fail" else after
        out += [f"Repeat {steps}, until {cond}, at most {p.get('at_most')} passes. Each pass sees what the one before it "
                "produced. Test the condition before every pass, the first included, and again where a step below says so.", "",
                f"When it holds, leave the loop: {after}. If {p.get('at_most')} passes end without it, {cap}."]
    if body:
        out += ["", "Its steps:"]
    return out


# -------------------------------------------------------------------- writing

def export_skill(bundle: Bundle, out: Path | str, force: bool = False, run_with: str | None = None) -> Path:
    """Write `SKILL.md` and the bundle's files at `out`, which must not exist or must be empty,
    unless `force`."""
    target = Path(out)
    if target.exists() and any(target.iterdir()) and not force:
        raise BundleError("export_target", f"{target} exists and is not empty; choose another directory or pass --force")
    target.mkdir(parents=True, exist_ok=True)
    (target / SKILL_FILE).write_text(render_skill(bundle.graph, bundle_id=bundle.id, run_with=run_with), encoding="utf-8")
    for f in bundle.files:
        path = target / Path(*PurePosixPath(f.path).parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f.data)
        try:
            os.chmod(path, f.mode)
        except OSError:  # pragma: no cover  (a filesystem without modes)
            pass
    return target
