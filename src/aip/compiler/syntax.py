"""The syntax tree of a procedure, as `aip.compiler.parse` builds it and `aip.compiler.format_program`
writes it back.

Every node carries its source span (1-based `line` and `column`, and the end position after its
last token) and the comments written around it: `leading`, the comment lines above it, where an
empty string marks a blank line between them, and `trailing`, a comment on the end of its first
line. Spans never take part in equality, so two trees compare equal when they say the same thing
wherever it was written; comments do, so a formatter that lost one would fail the round trip.

A step holds its clauses in the order written, which the parser has already checked is the
card's order (`Read`, the lines of the kind, `Produce`, the flow); the properties on `Step`
gather what later passes ask most (`reads`, `produces`, `flow`). Keywords are stored in their
canonical spelling; `particle` keeps the `With` or `On` an author wrote after a step kind,
which the formatter keeps."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator


def _span():
    return field(default=0, kw_only=True, compare=False, repr=False)


@dataclass
class Node:
    line: int = _span()
    column: int = _span()
    end_line: int = _span()
    end_column: int = _span()
    leading: list[str] = field(default_factory=list, kw_only=True, repr=False)
    trailing: str | None = field(default=None, kw_only=True, repr=False)


# ---------------------------------------------------------------- values

@dataclass
class Interpolation(Node):
    """A `{key}` or `{decision.question}` inside a string."""
    path: list[str]


@dataclass
class Text(Node):
    """A string literal. `value` is what it says; `raw` is the literal as written (quotes and
    escapes included), which the formatter writes back so a file's strings are never
    re-escaped. `fields` are its interpolations, positioned in the source."""
    value: str
    raw: str = field(default="", compare=False, repr=False)
    fields: list[Interpolation] = field(default_factory=list, compare=False, repr=False)

    def literal(self) -> str:
        if self.raw:
            return self.raw
        if "\n" in self.value or '"' in self.value:
            return '"""' + self.value + '"""'
        return '"' + self.value.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t") + '"'


@dataclass
class NameRef(Node):
    """A named string used where a string is expected (`Decide classify classify_question`)."""
    name: str


Str = Text | NameRef


@dataclass
class KeyRef(Node):
    """A key, or a field of one: `message`, `triage_decision.tone`, `verdicts.follows`."""
    path: list[str]

    @property
    def name(self) -> str:
        return self.path[0]

    @property
    def dotted(self) -> str:
        return ".".join(self.path)


@dataclass
class Declaration(Node):
    """`name`, or `name: type`, or `name: type "description"`, in `Read`, `Produce` and the
    inputs of `Start`. `key` may be dotted in a `Read`. A `choice` or `score` key declared where
    it is produced (a `Produce` of an `Execute` or `Task_Agent`, a `Start` input) lists its
    `labels` after the type, `tone: choice [angry, calm] "..."`, as a question does (spec 2.4)."""
    key: KeyRef
    type: str | None = None
    description: Str | None = None
    labels: list[str] = field(default_factory=list)


@dataclass
class Condition(Node):
    """`<answer> [== value | != value] [With Confidence_Above p]`: a loop's `Until`, and the
    test on every answer of an aggregation line."""
    answer: KeyRef
    operator: str | None = None  # "==" or "!="
    value: str | None = None
    confidence_above: float | None = None


# ---------------------------------------------------------------- clauses

@dataclass
class Clause(Node):
    pass


@dataclass
class ReadClause(Clause):
    keys: list[Declaration]


@dataclass
class InputClause(Clause):
    """One input of `Start`: `name: type "description"`."""
    input: Declaration


@dataclass
class Criterion(Node):
    label: str
    text: Str


@dataclass
class Question(Node):
    name: str
    type: str  # true_or_false, choice or score
    labels: list[str]
    instruction: Str
    criteria: list[Criterion] = field(default_factory=list)


@dataclass
class QuestionsClause(Clause):
    questions: list[Question]
    end_comments: list[str] = field(default_factory=list)


@dataclass
class FlagClause(Clause):
    """`History true` (the one flag a `Decide` has)."""
    keyword: str
    value: bool


@dataclass
class Aggregation(Node):
    name: str
    mode: str  # All, Any or None
    condition: Condition


@dataclass
class AggregationsClause(Clause):
    aggregations: list[Aggregation]
    end_comments: list[str] = field(default_factory=list)


@dataclass
class Flow(Node):
    """Where a step goes: `Next_Step <step>` or `Continue`; also a route
    branch's target, which is a step or `Continue`."""
    kind: str  # Next_Step or Continue
    step: str | None = None


@dataclass
class CheckClause(Clause):
    """`Confidence_Below <bound> -> <target>` on a route."""
    below: float
    target: Flow


@dataclass
class BranchClause(Clause):
    """`<value> -> <target>` on a route (`When <value>` is the same)."""
    value: str
    target: Flow


@dataclass
class ProduceClause(Clause):
    keys: list[Declaration]


@dataclass
class ScriptClause(Clause):
    path: str


@dataclass
class CommandClause(Clause):
    command: Str


@dataclass
class PromptClause(Clause):
    path: str


@dataclass
class UseItem(Node):
    path: str
    description: Str | None = None


@dataclass
class UseClause(Clause):
    items: list[UseItem]


@dataclass
class FlowClause(Clause):
    flow: Flow


# ---------------------------------------------------------------- steps and loops

@dataclass
class Step(Node):
    kind: str  # Start, Decide, Route, Aggregate, Execute, Task_Agent or End
    name: str | None
    description: Str
    clauses: list[Clause]
    particle: str | None = None  # the With or On written after the kind
    end_comments: list[str] = field(default_factory=list)

    def _of(self, cls):
        return [c for c in self.clauses if isinstance(c, cls)]

    @property
    def reads(self) -> list[Declaration]:
        return [k for c in self._of(ReadClause) for k in c.keys]

    @property
    def inputs(self) -> list[Declaration]:
        return [c.input for c in self._of(InputClause)]

    @property
    def produces(self) -> list[Declaration]:
        return [k for c in self._of(ProduceClause) for k in c.keys]

    @property
    def questions(self) -> list[Question]:
        return [q for c in self._of(QuestionsClause) for q in c.questions]

    @property
    def aggregations(self) -> list[Aggregation]:
        return [a for c in self._of(AggregationsClause) for a in c.aggregations]

    @property
    def uses(self) -> list[UseItem]:
        return [u for c in self._of(UseClause) for u in c.items]

    @property
    def check(self) -> CheckClause | None:
        found = self._of(CheckClause)
        return found[0] if found else None

    @property
    def branches(self) -> list[BranchClause]:
        return self._of(BranchClause)

    @property
    def flow(self) -> Flow | None:
        found = self._of(FlowClause)
        return found[-1].flow if found else None

    def flag(self, keyword: str) -> bool:
        """`History`: the value written, or False when absent."""
        return any(c.value for c in self._of(FlagClause) if c.keyword == keyword)

    @property
    def script(self) -> str | None:
        found = self._of(ScriptClause)
        return found[0].path if found else None

    @property
    def prompt(self) -> str | None:
        found = self._of(PromptClause)
        return found[0].path if found else None

    @property
    def command(self) -> Str | None:
        found = self._of(CommandClause)
        return found[0].command if found else None


@dataclass
class Collect(Node):
    key: str
    into: str


@dataclass
class ForLoop(Node):
    """`For <name> Over <list> As <item>, At_Most <n> [, Collect <key> Into <list>] { ... }`."""
    name: str
    over: KeyRef
    item: str
    at_most: int | None
    collect: Collect | None
    body: list[Step | ForLoop | Loop]
    exit: Flow | None  # the block-level Next_Step or Continue, when written
    end_comments: list[str] = field(default_factory=list)


@dataclass
class Loop(Node):
    """`Loop <name> Until <condition>, At_Most <n> [, Else_Fail|Else_Exit] { ... }`,
    `Loop <name> <n> Times { ... }`, or `Loop <name> Over <list> As <item>, At_Most <n> { ... }`."""
    name: str
    mode: str  # Until, Times or Over
    until: Condition | None
    times: int | None
    over: KeyRef | None
    item: str | None
    at_most: int | None
    at_cap: str | None  # Else_Fail or Else_Exit, when written
    body: list[Step | ForLoop | Loop]
    exit: Flow | None
    end_comments: list[str] = field(default_factory=list)


Block = ForLoop | Loop


# ---------------------------------------------------------------- the program

@dataclass
class HeaderClause(Node):
    """`Use_When`, `Do_Not_Use_When` or `Avoid`, with one or more strings."""
    keyword: str
    strings: list[Str]


@dataclass
class Requires(Node):
    interpreter: str
    version: str


@dataclass
class NamedString(Node):
    name: str
    text: Text
    before_header: bool = False   # written above the `Procedure` line; the formatter keeps it there


Item = NamedString | Step | ForLoop | Loop


@dataclass
class Program(Node):
    name: str
    description: Str
    header: list[HeaderClause | Requires]
    items: list[Item]
    end_comments: list[str] = field(default_factory=list)

    @property
    def named_strings(self) -> dict[str, NamedString]:
        return {i.name: i for i in self.items if isinstance(i, NamedString)}

    def steps(self) -> Iterator[Step]:
        """Every step in the file, loop bodies included, in file order."""
        yield from _steps(self.items)

    def loops(self) -> Iterator[Block]:
        yield from _loops(self.items)

    def step(self, name: str) -> Step | None:
        for s in self.steps():
            if s.name == name or (name == "end" and s.kind == "End") or (name == "start" and s.kind == "Start"):
                return s
        return None


def _steps(items) -> Iterator[Step]:
    for item in items:
        if isinstance(item, Step):
            yield item
        elif isinstance(item, (ForLoop, Loop)):
            yield from _steps(item.body)


def _loops(items) -> Iterator[Block]:
    for item in items:
        if isinstance(item, (ForLoop, Loop)):
            yield item
            yield from _loops(item.body)
