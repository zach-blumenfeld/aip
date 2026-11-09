"""Write a syntax tree back as canonical `procedure.aip` text.

Canonical form: keywords in their canonical spelling (`Next_Step`, not `next` or `NEXT_STEP`;
`Task_Agent`, not `Task`), two-space indent, one clause per line, one blank line between the
items of the file and between the steps of a loop body, none between the clauses of a step.
Strings are written as the author wrote them (the same quotes, the same escapes), `With` or
`On` after a step kind stays, and comments stay where they were: above the line they preceded,
or at the end of it. `parse(format_program(parse(x)))` equals `parse(x)` for every `x` that parses."""

from __future__ import annotations

import re

from aip_spec import syntax as s

INDENT = "  "
_BARE_PATH = re.compile(r"[A-Za-z0-9_.](?:[A-Za-z0-9_./]|-(?!>))*")


def format_program(program: s.Program) -> str:
    """The canonical text of `program`, ending in one newline."""
    return "\n".join(Writer().program(program)) + "\n"


def format_source(source: str, file: str | None = None) -> str:
    """Parse `source` and write it back canonically. Raises ParseError as `parse` does."""
    from aip_spec.parser import parse

    return format_program(parse(source, file))


def _num(value: float) -> str:
    text = f"{value:.10g}"
    return text


def _str(value: s.Str) -> str:
    return value.literal() if isinstance(value, s.Text) else value.name


def _path(path: str) -> str:
    return path if _BARE_PATH.fullmatch(path) else '"' + path.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _condition(c: s.Condition) -> str:
    text = c.answer.dotted
    if c.operator:
        text += f" {c.operator} {c.value}"
    if c.confidence_above is not None:
        text += f" With Confidence_Above {_num(c.confidence_above)}"
    return text


def _flow(f: s.Flow) -> str:
    return f.kind if f.step is None else f"{f.kind} {f.step}"


def _typed(d: s.Declaration) -> str:
    """`key: type [labels]`, without the description."""
    text = f"{d.key.dotted}: {d.type}"
    if d.labels:
        text += f" [{', '.join(d.labels)}]"
    return text


def _declaration(d: s.Declaration) -> str:
    if not d.type:
        return d.key.dotted
    text = _typed(d)
    if d.description is not None:
        text += " " + _str(d.description)
    return text


class Writer:
    def __init__(self):
        self.lines: list[str] = []

    # ------------------------------------------------------------ lines

    def comments(self, comments: list[str], depth: int) -> None:
        for c in comments:
            self.lines.append(INDENT * depth + c if c else "")

    def line(self, text: str, depth: int, node: s.Node | None = None) -> None:
        """One line at `depth`, with the node's leading comments above it and its trailing comment after it."""
        if node is not None:
            self.comments(node.leading, depth)
        if node is not None and node.trailing:
            text = f"{text}  {node.trailing}"
        self.lines.append(INDENT * depth + text)

    def blank(self) -> None:
        if self.lines and self.lines[-1] != "":
            self.lines.append("")

    def close(self, end_comments: list[str], depth: int) -> None:
        self.comments(end_comments, depth + 1)
        self.lines.append(INDENT * depth + "}")

    # ------------------------------------------------------------ the program

    def program(self, p: s.Program) -> list[str]:
        self.comments(p.leading, 0)
        self.line(f"Procedure {p.name}", 0, _Trailing(p.trailing))
        self.line(_str(p.description), 1, p.description)
        if p.header:
            self.blank()
            for clause in p.header:
                self.header_clause(clause)
        # Consecutive named strings stay together, their `=` aligned; everything else gets a blank line.
        n = 0
        while n < len(p.items):
            self.blank()
            if isinstance(p.items[n], s.NamedString):
                run = []
                while n < len(p.items) and isinstance(p.items[n], s.NamedString):
                    run.append(p.items[n])
                    n += 1
                width = max(len(ns.name) for ns in run)
                for ns in run:
                    self.line(f"{ns.name.ljust(width)} = {ns.text.literal()}", 0, ns)
            else:
                self.item(p.items[n], 0)
                n += 1
        if p.end_comments:
            self.blank()
            self.comments(p.end_comments, 0)
        while self.lines and self.lines[-1] == "":
            self.lines.pop()
        return self.lines

    def header_clause(self, clause) -> None:
        if isinstance(clause, s.Requires):
            self.line(f"Requires {clause.interpreter} {clause.version}", 1, clause)
            return
        self.line(clause.keyword, 1, clause)
        for text in clause.strings:
            self.line(_str(text), 2, text)

    def item(self, item, depth: int) -> None:
        if isinstance(item, s.NamedString):
            self.line(f"{item.name} = {item.text.literal()}", depth, item)
        elif isinstance(item, s.Step):
            self.step(item, depth)
        else:
            self.loop(item, depth)

    # ------------------------------------------------------------ steps

    def step(self, step: s.Step, depth: int) -> None:
        head = step.kind
        if step.particle:
            head += f" {step.particle}"
        if step.name:
            head += f" {step.name}"
        self.line(f"{head} {_str(step.description)} {{", depth, step)
        self.clauses(step, depth + 1)
        self.close(step.end_comments, depth)

    def clauses(self, step: s.Step, depth: int) -> None:
        # Route branches line up on their arrows; Start inputs line up their descriptions.
        width = max((len(c.value) for c in step.clauses if isinstance(c, s.BranchClause)), default=0)
        inputs = [c.input for c in step.clauses if isinstance(c, s.InputClause)]
        input_width = max((len(_typed(d)) for d in inputs if d.description is not None), default=0)
        for clause in step.clauses:
            if isinstance(clause, s.ReadClause):
                self.keys("Read", clause, depth)
            elif isinstance(clause, s.InputClause):
                d = clause.input
                text = _typed(d)
                if d.description is not None:
                    text = f"{text.ljust(input_width)} {_str(d.description)}"
                self.line(text, depth, _merge(clause, d))
            elif isinstance(clause, s.ProduceClause):
                self.keys("Produce", clause, depth)
            elif isinstance(clause, s.FlowClause):
                self.line(_flow(clause.flow), depth, clause)
            elif isinstance(clause, s.FlagClause):
                self.line(f"{clause.keyword} {'true' if clause.value else 'false'}", depth, clause)
            elif isinstance(clause, s.CheckClause):
                self.line(f"Confidence_Below {_num(clause.below)} -> {_flow_target(clause.target)}", depth, clause)
            elif isinstance(clause, s.BranchClause):
                self.line(f"{clause.value.ljust(width)} -> {_flow_target(clause.target)}", depth, clause)
            elif isinstance(clause, s.ScriptClause):
                self.line(f"Run_Script {_path(clause.path)}", depth, clause)
            elif isinstance(clause, s.CommandClause):
                self.line(f"Command {_str(clause.command)}", depth, clause)
            elif isinstance(clause, s.PromptClause):
                self.line(f"Prompt {_path(clause.path)}", depth, clause)
            elif isinstance(clause, s.UseClause):
                items = [_path(u.path) + (f" {_str(u.description)}" if u.description is not None else "") for u in clause.items]
                self.line("Use " + ", ".join(items), depth, clause)
            elif isinstance(clause, s.QuestionsClause):
                self.questions(clause, depth)
            elif isinstance(clause, s.AggregationsClause):
                self.aggregations(clause, depth)
            else:  # pragma: no cover
                raise TypeError(f"unknown clause {clause!r}")

    def keys(self, keyword: str, clause: s.ReadClause | s.ProduceClause, depth: int) -> None:
        """`Read a, b` on one line; `Produce` with one typed key per line, continuation lines
        aligned under the first key, as the glossary allows."""
        decls = clause.keys
        self.comments(clause.leading, depth)
        commented = any(d.leading or d.trailing for d in decls[1:]) or (decls[0].trailing and len(decls) > 1)
        if len(decls) == 1 or not (commented or any(d.type for d in decls)):
            text = f"{keyword} " + ", ".join(_declaration(d) for d in decls)
            trailing = clause.trailing or decls[0].trailing
            self.lines.append(INDENT * depth + text + (f"  {trailing}" if trailing else ""))
            return
        # One key per line. A typed key continues the list by itself (`key: type`); an untyped
        # one needs the comma before it.
        pad = " " * (len(keyword) + 1)
        for n, d in enumerate(decls):
            for c in d.leading:
                self.lines.append(INDENT * depth + (pad if n else "") + c if c else "")
            head = f"{keyword} " if n == 0 else pad
            comma = "," if n + 1 < len(decls) and not decls[n + 1].type else ""
            trailing = d.trailing or (clause.trailing if n == len(decls) - 1 else None)
            self.lines.append(INDENT * depth + head + _declaration(d) + comma + (f"  {trailing}" if trailing else ""))

    def questions(self, clause: s.QuestionsClause, depth: int) -> None:
        self.line("Answer_Questions {", depth, clause)
        width = max((len(q.name) + 1 for q in clause.questions), default=0)
        for q in clause.questions:
            labels = f" [{', '.join(q.labels)}]" if q.labels else ""
            self.line(f"{(q.name + ':').ljust(width)} {q.type}{labels} {_str(q.instruction)}", depth + 1, q)
            cwidth = max((len(c.label) + 1 for c in q.criteria), default=0)
            for c in q.criteria:
                self.line(f"{(c.label + ':').ljust(cwidth)} {_str(c.text)}", depth + 2, c)
        self.close(clause.end_comments, depth)

    def aggregations(self, clause: s.AggregationsClause, depth: int) -> None:
        self.line("Aggregations {", depth, clause)
        width = max((len(a.name) + 1 for a in clause.aggregations), default=0)
        for a in clause.aggregations:
            self.line(f"{(a.name + ':').ljust(width)} {a.mode} {_condition(a.condition)}", depth + 1, a)
        self.close(clause.end_comments, depth)

    # ------------------------------------------------------------ loops

    def loop(self, loop: s.ForLoop | s.Loop, depth: int) -> None:
        if isinstance(loop, s.ForLoop):
            head = f"For {loop.name} Over {loop.over.dotted} As {loop.item}"
            if loop.at_most is not None:
                head += f", At_Most {loop.at_most}"
            if loop.collect is not None:
                head += f", Collect {loop.collect.key} Into {loop.collect.into}"
        else:
            head = f"Loop {loop.name}"
            if loop.mode == "Until":
                head += f" Until {_condition(loop.until)}"
            elif loop.mode == "Times":
                head += f" {loop.times} Times"
            else:
                head += f" Over {loop.over.dotted} As {loop.item}"
            if loop.at_most is not None:
                head += f", At_Most {loop.at_most}"
            if loop.at_cap is not None:
                head += f", {loop.at_cap}"
        self.line(f"{head} {{", depth, loop)
        for item in loop.body:
            self.item(item, depth + 1)
            self.blank()
        if loop.exit is not None:
            self.line(_flow(loop.exit), depth + 1, loop.exit)
        elif self.lines and self.lines[-1] == "":
            self.lines.pop()
        if loop.end_comments:
            self.comments(loop.end_comments, depth + 1)
        self.lines.append(INDENT * depth + "}")


def _flow_target(f: s.Flow) -> str:
    return "Continue" if f.kind == "Continue" else f.step


class _Trailing:
    """A stand-in node for a line whose comments come from elsewhere (the `Procedure` line's
    trailing comment lives on the program, whose leading comments are the file header)."""

    def __init__(self, trailing: str):
        self.leading: list[str] = []
        self.trailing = trailing


def _merge(clause: s.Node, inner: s.Node) -> _Trailing:
    """An input line's comments: the clause's leading, and whichever of the two has the trailing."""
    node = _Trailing(clause.trailing or inner.trailing)
    node.leading = clause.leading + inner.leading
    return node
