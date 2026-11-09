"""A recursive-descent parser for `procedure.aip` (spec section 2.1 and the glossary).

`parse(source)` returns a `syntax.Program` or raises `ParseError` with the line and column of
the first problem and what was expected there. The parser enforces what is grammar: the shape
of every step kind and loop header, which clauses a kind may carry and their order (`Read`, the
lines of the kind, `Produce`, the flow), the closed type vocabulary, and the reserved name
`end`. Everything that needs the whole program (reachability, availability, one producer per
path, the labels a route must name) is the checker's, in the plan's L2.

Comments are kept. A comment above a line belongs to that line's node (`leading`); a comment at
the end of a line belongs to the node that line ends (`trailing`); comments before a closing
brace belong to the block (`end_comments`). A comment somewhere else, say between two keys of a
`Read`, moves up to the next line it can sit above, so the formatter never drops one."""

from __future__ import annotations

import re

from aip_spec import syntax as s
from aip_spec.errors import ParseError
from aip_spec.keywords import (
    ANSWER_TYPES, FLOW_CLAUSES, HEADER_CLAUSES, LOOP_KINDS, STEP_KINDS, TYPE_ALIASES, keyword, type_name,
)
from aip_spec.lexer import EOF, PUNCT, STRING, WORD, Comment, Token, tokenize

IDENT = re.compile(r"[a-z][a-z0-9_]*")
DOTTED = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*")
NUMBER = re.compile(r"[0-9]+(?:\.[0-9]+)?")
VALUE = re.compile(r"[a-z0-9_]+")  # a label, a level, true or false
VERSION = re.compile(r"[0-9][0-9A-Za-z_.+-]*")  # 3.10, 22.04, 1.2.3-rc1
FIELD = re.compile(r"\{([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*)\}")

# The part of the card each clause belongs to: 0 reads, 1 the lines of the kind, 2 produces,
# 3 where the step goes. `Input` is a Start input line, `Branch` a route's `<value> -> <step>`.
_RANK = {
    "Read": 0, "Input": 0,
    "Answer_Questions": 1, "Agent_Fallback": 1, "History": 1, "Aggregations": 1, "Confidence_Below": 1, "Branch": 1,
    "Run_Script": 1, "Command": 1, "Prompt": 1, "Use": 1,
    "Produce": 2,
    "Next_Step": 3, "Continue": 3, "Again": 3,
}
_ALLOWED = {
    "Start": ("Input", "Next_Step"),
    "Decide": ("Read", "Answer_Questions", "Agent_Fallback", "History", "Produce", "Next_Step", "Continue", "Again"),
    "Route": ("Read", "Confidence_Below", "Branch"),
    "Aggregate": ("Read", "Aggregations", "Produce", "Next_Step", "Continue", "Again"),
    "Execute": ("Read", "Run_Script", "Command", "Use", "Produce", "Next_Step", "Continue", "Again"),
    "Task_Agent": ("Read", "Prompt", "Use", "Produce", "Next_Step", "Continue", "Again"),
    "End": ("Read",),
}
_SHOWN = {"Input": "<key>: <type>", "Branch": "<value> -> <step>"}


def _clauses_of(kind: str) -> str:
    return ", ".join(_SHOWN.get(c, c) for c in _ALLOWED[kind])


def parse(source: str, file: str | None = None) -> s.Program:
    """Parse the text of a `procedure.aip`. `file` is only for error messages."""
    return Parser(source, file).program()


class Parser:
    def __init__(self, source: str, file: str | None = None):
        self.file = file
        try:
            self.tokens = tokenize(source)
        except ParseError as exc:
            exc.file = file
            raise
        self.i = 0
        self.last: Token | None = None
        self.stray: list[Comment] = []
        self.trailing_target: s.Node | None = None

    # ------------------------------------------------------------ tokens

    def peek(self, k: int = 0) -> Token:
        return self.tokens[min(self.i + k, len(self.tokens) - 1)]

    def next(self) -> Token:
        tok = self.tokens[self.i]
        if tok.kind != EOF:
            self.i += 1
        if tok.comments:
            self.stray.extend(tok.comments)
            tok.comments = []
        self.last = tok
        return tok

    def error(self, expected: str, tok: Token | None = None) -> ParseError:
        tok = self.peek() if tok is None else tok
        return ParseError(f"expected {expected}, got {tok.describe()}", tok.line, tok.column, expected=expected,
                          found=tok.text, end_line=tok.end_line, end_column=tok.end_column, file=self.file)

    def fail(self, message: str, tok: Token | None = None) -> ParseError:
        tok = self.peek() if tok is None else tok
        return ParseError(message, tok.line, tok.column, found=tok.text, end_line=tok.end_line,
                          end_column=tok.end_column, file=self.file)

    def is_punct(self, text: str, k: int = 0) -> bool:
        tok = self.peek(k)
        return tok.kind == PUNCT and tok.text == text

    def is_word(self, k: int = 0) -> bool:
        return self.peek(k).kind == WORD

    def kw(self, k: int = 0) -> str | None:
        """The canonical keyword of the k-th token ahead, if it is a word that spells one."""
        tok = self.peek(k)
        return keyword(tok.text) if tok.kind == WORD else None

    def expect_punct(self, text: str, context: str) -> Token:
        if not self.is_punct(text):
            raise self.error(f"'{text}' {context}")
        return self.next()

    def expect_kw(self, canonical: str, context: str) -> Token:
        if self.kw() != canonical:
            raise self.error(f"'{canonical}' {context}")
        return self.next()

    # ------------------------------------------------------------ comments

    def take(self) -> list[str]:
        """The comments above the next token, as the leading list of the node it starts (an empty
        string marks a blank line). A comment on the same line as the last token consumed is the
        trailing comment of the last line node instead."""
        tok = self.peek()
        comments = self.stray + tok.comments
        self.stray, tok.comments = [], []
        if comments and self.last is not None and comments[0].line == self.last.end_line:
            trailing, comments = comments[0], comments[1:]
            if self.trailing_target is not None and self.trailing_target.trailing is None:
                self.trailing_target.trailing = trailing.text
            else:
                comments.insert(0, trailing)
        return self._with_gaps(comments, tok.line)

    @staticmethod
    def _with_gaps(comments: list[Comment], next_line: int) -> list[str]:
        out: list[str] = []
        for n, c in enumerate(comments):
            if n and c.line - comments[n - 1].line > 1:
                out.append("")
            out.append(c.text)
        if comments and next_line - comments[-1].line > 1:
            out.append("")
        return out

    def at(self, node, start: Token):
        """Set the node's span: from `start` to the last token consumed."""
        node.line, node.column = start.line, start.column
        node.end_line, node.end_column = self.last.end_line, self.last.end_column
        return node

    def line_node(self, node, start: Token, leading: list[str]):
        """A node that owns a line: it takes the comments above it and the next same-line comment."""
        node.leading = leading
        self.trailing_target = node
        return self.at(node, start)

    # ------------------------------------------------------------ atoms

    def ident(self, what: str) -> str:
        tok = self.peek()
        if tok.kind == WORD and IDENT.fullmatch(tok.text):
            self.next()
            return tok.text
        raise self.error(what)

    def keyref(self, what: str) -> s.KeyRef:
        tok = self.peek()
        if tok.kind == WORD and DOTTED.fullmatch(tok.text):
            self.next()
            return self.at(s.KeyRef(tok.text.split(".")), tok)
        raise self.error(what)

    def number(self, what: str) -> float:
        tok = self.peek()
        if tok.kind == WORD and NUMBER.fullmatch(tok.text):
            self.next()
            return float(tok.text)
        raise self.error(what)

    def integer(self, what: str) -> int:
        tok = self.peek()
        if tok.kind == WORD and tok.text.isdigit():
            self.next()
            return int(tok.text)
        raise self.error(what)

    def value(self, what: str) -> str:
        tok = self.peek()
        if tok.kind == WORD and VALUE.fullmatch(tok.text):
            self.next()
            return tok.text
        raise self.error(what)

    def path(self, what: str) -> str:
        tok = self.peek()
        if tok.kind == STRING:
            self.next()
            return tok.value
        if tok.kind == WORD and keyword(tok.text) is None:
            self.next()
            return tok.text
        raise self.error(what)

    def type(self) -> str:
        tok = self.peek()
        canonical = type_name(tok.text) if tok.kind == WORD else None
        if canonical is None:
            raise self.error(f"a type ({', '.join(TYPE_ALIASES)})")
        self.next()
        return canonical

    def text(self, tok: Token) -> s.Text:
        fields = []
        for m in FIELD.finditer(tok.text):
            before = tok.text[: m.start()]
            newlines = before.count("\n")
            line = tok.line + newlines
            column = tok.column + m.start() if not newlines else m.start() - before.rfind("\n")
            fields.append(s.Interpolation(m.group(1).split("."), line=line, column=column, end_line=line,
                                          end_column=column + len(m.group(0))))
        return self.at(s.Text(tok.value, raw=tok.text, fields=fields), tok)

    def string_ahead(self, k: int = 0) -> bool:
        """Whether the k-th token ahead can be a string: a literal, or a word naming one."""
        tok = self.peek(k)
        if tok.kind == STRING:
            return True
        return tok.kind == WORD and IDENT.fullmatch(tok.text) is not None and keyword(tok.text) is None \
            and not self.is_punct("=", k + 1) and not self.is_punct(":", k + 1) and not self.is_punct("->", k + 1)

    def string(self, what: str) -> s.Str:
        tok = self.peek()
        if tok.kind == STRING:
            self.next()
            return self.text(tok)
        if self.string_ahead():
            self.next()
            return self.at(s.NameRef(tok.text), tok)
        raise self.error(what)

    # ------------------------------------------------------------ the program

    def program(self) -> s.Program:
        leading = self.take()
        start = self.peek()
        if self.kw() != "Procedure":
            raise self.error("'Procedure <name>' to open the file")
        self.next()
        name = self.ident("the procedure's name (lowercase letters, digits and underscores)")
        program = s.Program(name, None, [], [])  # type: ignore[arg-type]  # the description follows
        program.leading = leading
        self.trailing_target = program
        lead = self.take()
        tok = self.peek()
        program.description = self.line_node(self.string("the procedure's description, a string"), tok, lead)
        while self.kw() in HEADER_CLAUSES:
            program.header.append(self.header_clause())
        while self.peek().kind != EOF:
            program.items.append(self.item(in_loop=False))
        program.end_comments = self.take()
        self.next()
        return self.at(program, start)

    def header_clause(self):
        leading = self.take()
        tok = self.next()
        kw = keyword(tok.text)
        if kw == "Requires":
            if not self.is_word() or keyword(self.peek().text):
                raise self.error("an interpreter after 'Requires', such as 'python 3.10'")
            interpreter = self.next().text
            if not self.is_word() or not VERSION.fullmatch(self.peek().text):
                raise self.error(f"a version after 'Requires {interpreter}'")
            version = self.next().text
            return self.line_node(s.Requires(interpreter, version), tok, leading)
        clause = s.HeaderClause(kw, [])
        clause.leading = leading
        self.trailing_target = clause
        while self.string_ahead():
            lead = self.take()
            first = self.peek()
            clause.strings.append(self.line_node(self.string("a string"), first, lead))
        if not clause.strings:
            raise self.error(f"a string after '{kw}'")
        return self.at(clause, tok)

    def item(self, in_loop: bool):
        kw = self.kw()
        if kw in STEP_KINDS:
            return self.step()
        if kw in LOOP_KINDS:
            return self.loop()
        if not in_loop and self.is_word() and kw is None and self.is_punct("=", 1):
            return self.named_string()
        if in_loop:
            raise self.error("a step, a loop, or the loop's exit ('Next_Step <step>' or 'Continue')")
        if self.is_word() and kw is None and self.is_punct(":", 1):
            raise self.fail(f"a clause ({self.peek().text}: ...) outside a step; expected a step, a loop or a named string")
        if self.is_word() and kw is None and self.peek(1).kind == STRING:
            raise self.error(f"'=' after the name {self.peek().text} (a named string is written {self.peek().text} = \"...\")", self.peek(1))
        raise self.error("a step (Start, Decide, Route, Aggregate, Execute, Task_Agent, End), a loop (For, Loop) or a named string")

    def named_string(self) -> s.NamedString:
        leading = self.take()
        tok = self.next()
        self.expect_punct("=", f"after the name {tok.text}")
        if self.peek().kind != STRING:
            raise self.error(f"a string for {tok.text} (a name holds a string and nothing else)")
        text = self.text(self.next())
        return self.line_node(s.NamedString(tok.text, text), tok, leading)

    # ------------------------------------------------------------ steps

    def step(self) -> s.Step:
        leading = self.take()
        start = self.next()
        kind = keyword(start.text)
        particle = None
        if self.kw() in ("With", "On"):
            particle = self.kw()
            self.next()
        name = None
        if kind in ("Start", "End"):
            if self.is_word() and (self.peek(1).kind == STRING or self.is_word(1)):
                raise self.fail(f"{kind} has no name; a procedure has one {kind} step")
        else:
            name = self.ident(f"a name for the {kind} step")
            if name == "end":
                raise self.fail("'end' names the End step and cannot name another step", self.last)
        description = self.string(f"the description of {kind if name is None else name}, a string")
        self.expect_punct("{", "to open the step's block")
        step = s.Step(kind, name, description, [], particle)
        step.leading = leading
        self.trailing_target = step
        rank, previous = -1, None
        while not self.is_punct("}"):
            if self.peek().kind == EOF:
                raise self.error(f"'}}' to close {kind if name is None else name}")
            leading = self.take()
            first = self.peek()
            clause, slot = self.clause(step, leading, first)
            if _RANK[slot] < rank:
                raise self.fail(f"'{_SHOWN.get(slot, slot)}' comes before '{_SHOWN.get(previous, previous)}' in a step: "
                                "Read, the lines of its kind, Produce, then where it goes", first)
            rank, previous = _RANK[slot], slot
            step.clauses.append(clause)
        step.end_comments = self.take()
        self.next()
        return self.at(step, start)

    def clause(self, step: s.Step, leading: list[str], tok: Token) -> tuple[s.Clause, str]:
        kw = self.kw()
        if step.kind == "Start" and (kw == "Read" or (self.is_word() and self.is_punct(":", 1))):
            kw = "Input"
        if step.kind == "Route" and kw != "Confidence_Below" and ((self.is_word() and self.is_punct("->", 1)) or kw == "When"):
            kw = "Branch"
        if kw is None:
            raise self.error(f"a clause of {step.kind} ({_clauses_of(step.kind)})")
        if kw not in _ALLOWED[step.kind]:
            raise self.fail(f"'{kw}' is not a clause of {step.kind}; {step.kind} takes {_clauses_of(step.kind)}")
        if kw == "Input":
            if self.kw() == "Read":
                self.next()
            decl = self.declaration(dotted=False, leading=[])
            if decl.type is None:
                raise self.error(f"':' and a type for the input {decl.key.dotted}")
            node = s.InputClause(decl)
        elif kw == "Read":
            self.next()
            node = s.ReadClause(self.declarations(dotted=True))
        elif kw == "Produce":
            self.next()
            if step.kind in ("Decide", "Aggregate"):
                key_tok = self.peek()
                key = self.keyref(f"the one key {step.name} produces")
                if self.is_punct(":"):
                    what = "questions" if step.kind == "Decide" else "aggregations"
                    raise self.fail(f"{step.kind}'s Produce names one key and no type; the key's fields are its {what}")
                node = s.ProduceClause([self.at(s.Declaration(key), key_tok)])
            else:
                node = s.ProduceClause(self.declarations(dotted=False))
        elif kw in FLOW_CLAUSES:
            node = s.FlowClause(self.flow())
        elif kw == "Answer_Questions":
            node = self.questions(leading)
        elif kw in ("Agent_Fallback", "History"):
            self.next()
            flag = self.peek()
            if flag.kind != WORD or flag.text not in ("true", "false"):
                raise self.error(f"'true' or 'false' after '{kw}'")
            self.next()
            node = s.FlagClause(kw, flag.text == "true")
        elif kw == "Aggregations":
            node = self.aggregations(leading)
        elif kw == "Confidence_Below":
            self.next()
            below = self.number("a confidence bound after 'Confidence_Below', such as 0.6")
            self.expect_punct("->", "after the bound")
            node = s.CheckClause(below, self.target())
        elif kw == "Branch":
            if self.kw() == "When":
                self.next()
            branch_value = self.value("a value (a label, a level, true or false) before '->'")
            self.expect_punct("->", f"after the value {branch_value}")
            node = s.BranchClause(branch_value, self.target())
        elif kw == "Run_Script":
            self.next()
            node = s.ScriptClause(self.path("the script's path after 'Run_Script'"))
        elif kw == "Command":
            self.next()
            node = s.CommandClause(self.string("the command, a string"))
        elif kw == "Prompt":
            self.next()
            node = s.PromptClause(self.path("the prompt file's path after 'Prompt'"))
        else:  # Use
            self.next()
            items = [self.use_item()]
            while self.is_punct(","):
                self.next()
                items.append(self.use_item())
            node = s.UseClause(items)
        return self.line_node(node, tok, leading), kw

    def declaration(self, dotted: bool, leading: list[str]) -> s.Declaration:
        tok = self.peek()
        key = self.keyref("a key" if dotted else "a key (lowercase letters, digits and underscores)")
        if not dotted and len(key.path) > 1:
            raise self.fail(f"a key, not a field: '{key.dotted}' can be read but not produced", tok)
        decl = s.Declaration(key)
        if self.is_punct(":"):
            self.next()
            decl.type = self.type()
            if self.string_ahead():
                decl.description = self.string("a description")
        return self.line_node(decl, tok, leading)

    def declarations(self, dotted: bool) -> list[s.Declaration]:
        """`a, b.c`, or `a: type "d", b: type`, or one `key: type` per continuation line."""
        keys = [self.declaration(dotted, [])]
        while True:
            if self.is_punct(","):
                self.next()
                keys.append(self.declaration(dotted, self.take()))
            elif self.is_word() and self.is_punct(":", 1):
                keys.append(self.declaration(dotted, self.take()))
            else:
                return keys

    def flow(self) -> s.Flow:
        tok = self.next()
        kw = keyword(tok.text)
        if kw == "Continue":
            return self.at(s.Flow("Continue"), tok)
        step = self.ident(f"a step name after '{kw}'")
        return self.at(s.Flow(kw, step), tok)

    def target(self) -> s.Flow:
        tok = self.peek()
        if self.kw() == "Continue":
            self.next()
            return self.at(s.Flow("Continue"), tok)
        step = self.ident("a step name or 'Continue' after '->'")
        return self.at(s.Flow("Next_Step", step), tok)

    def use_item(self) -> s.UseItem:
        tok = self.peek()
        item = s.UseItem(self.path("a file path after 'Use'"))
        if self.string_ahead():
            item.description = self.string("a description")
        return self.at(item, tok)

    def questions(self, leading: list[str]) -> s.QuestionsClause:
        self.next()
        self.expect_punct("{", "to open the questions")
        clause = s.QuestionsClause([])
        clause.leading = leading
        self.trailing_target = clause
        while not self.is_punct("}"):
            if self.peek().kind == EOF:
                raise self.error("'}' to close the questions")
            clause.questions.append(self.question())
        clause.end_comments = self.take()
        self.next()
        return clause

    def question(self) -> s.Question:
        leading = self.take()
        tok = self.peek()
        name = self.ident("a question name (lowercase letters, digits and underscores)")
        self.expect_punct(":", f"after the question name {name}")
        type_tok = self.peek()
        canonical = type_name(type_tok.text) if type_tok.kind == WORD else None
        if canonical not in ANSWER_TYPES:
            raise self.error("an answer type (true_or_false, choice or score)")
        self.next()
        labels: list[str] = []
        if self.is_punct("["):
            self.next()
            while True:
                labels.append(self.value("a label (lowercase letters, digits and underscores)"))
                if self.is_punct(","):
                    self.next()
                    continue
                self.expect_punct("]", "to close the labels")
                break
        instruction = self.string(f"the instruction for {name}, a string")
        question = self.line_node(s.Question(name, canonical, labels, instruction), tok, leading)
        while self.is_word() and self.is_punct(":", 1) and self.criterion_ahead():
            question.criteria.append(self.criterion())
        return question

    def criterion_ahead(self) -> bool:
        after = self.peek(2)
        if after.kind == STRING:
            return True
        return after.kind == WORD and type_name(after.text) not in ANSWER_TYPES and keyword(after.text) is None

    def criterion(self) -> s.Criterion:
        leading = self.take()
        tok = self.peek()
        label = self.value("a label before ':'")
        self.next()  # the colon
        text = self.string(f"the criterion for {label}, a string")
        return self.line_node(s.Criterion(label, text), tok, leading)

    def aggregations(self, leading: list[str]) -> s.AggregationsClause:
        self.next()
        self.expect_punct("{", "to open the aggregations")
        clause = s.AggregationsClause([])
        clause.leading = leading
        self.trailing_target = clause
        while not self.is_punct("}"):
            if self.peek().kind == EOF:
                raise self.error("'}' to close the aggregations")
            lead = self.take()
            first = self.peek()
            name = self.ident("an aggregation name (lowercase letters, digits and underscores)")
            self.expect_punct(":", f"after the aggregation name {name}")
            mode = self.kw()
            if mode not in ("All", "Any", "None"):
                raise self.error("'All', 'Any' or 'None'")
            self.next()
            condition = self.condition("the answers to aggregate")
            clause.aggregations.append(self.line_node(s.Aggregation(name, mode, condition), first, lead))
        clause.end_comments = self.take()
        self.next()
        return clause

    def condition(self, what: str) -> s.Condition:
        tok = self.peek()
        condition = s.Condition(self.keyref(what))
        if self.is_punct("==") or self.is_punct("!="):
            condition.operator = self.next().text
            condition.value = self.value(f"a value (a label, a level, true or false) after '{condition.operator}'")
        if self.kw() == "With":
            self.next()
            self.expect_kw("Confidence_Above", "after 'With'")
            condition.confidence_above = self.number("a probability after 'Confidence_Above', such as 0.7")
        return self.at(condition, tok)

    # ------------------------------------------------------------ loops

    def loop(self):
        leading = self.take()
        start = self.next()
        kind = keyword(start.text)
        name = self.ident(f"a name for the {kind} loop")
        if kind == "For":
            self.expect_kw("Over", f"after 'For {name}'")
            over = self.keyref("the list to loop over")
            self.expect_kw("As", "to name the item")
            item = self.ident("a name for the item")
            node = s.ForLoop(name, over, item, None, None, [], None)
            options = ("At_Most", "Collect")
        else:
            kw = self.kw()
            if kw == "Until":
                self.next()
                node = s.Loop(name, "Until", self.condition("the answer the loop waits for"), None, None, None, None, None, [], None)
            elif kw == "Over":
                self.next()
                over = self.keyref("the list to loop over")
                self.expect_kw("As", "to name the item")
                node = s.Loop(name, "Over", None, None, over, self.ident("a name for the item"), None, None, [], None)
            elif self.is_word() and self.peek().text.isdigit():
                times = self.integer("a number of passes")
                self.expect_kw("Times", "after the number of passes")
                node = s.Loop(name, "Times", None, times, None, None, None, None, [], None)
            else:
                raise self.error(f"'Until <condition>', 'Over <list> As <item>' or '<n> Times' after 'Loop {name}'")
            options = ("At_Most", "Else_Fail", "Else_Exit") if node.mode == "Until" else ("At_Most",)
        while not self.is_punct("{"):
            if self.is_punct(","):
                self.next()
                continue
            kw = self.kw()
            if kw not in options:
                raise self.error(f"'{{' to open the loop, or one of {', '.join(options)}")
            self.next()
            if kw == "At_Most":
                node.at_most = self.integer("a whole number after 'At_Most'")
            elif kw == "Collect":
                key = self.ident("the key to collect from each pass")
                self.expect_kw("Into", f"after 'Collect {key}'")
                node.collect = s.Collect(key, self.ident("the list to collect into"))
            else:
                node.at_cap = kw
        self.next()
        node.leading = leading
        self.trailing_target = node
        while not self.is_punct("}"):
            if self.peek().kind == EOF:
                raise self.error(f"'}}' to close the loop {name}")
            if self.kw() in ("Next_Step", "Continue"):
                lead = self.take()
                tok = self.peek()
                node.exit = self.line_node(self.flow(), tok, lead)
                if not self.is_punct("}"):
                    raise self.error("'}': the loop's exit is the last line of its block")
                break
            node.body.append(self.item(in_loop=True))
        node.end_comments = self.take()
        self.next()
        return self.at(node, start)
