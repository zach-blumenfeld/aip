"""The keywords of the language, each with its canonical spelling and its aliases.

The list mirrors the glossary in `docs/language/spec.md` (section 6), which is the one place
the keywords are maintained in prose; this table is its executable copy. Keywords are matched
in any case, so `Next_Step`, `next_step` and `NEXT_STEP` are one keyword, and the formatter
writes the canonical spelling. A keyword is recognised by its position: a word that opens a
step, a loop or a clause is a keyword when it matches one; a word where a name is expected (a
key, a step name, a label) is a name, so a key may be called `task` or `history`."""

from __future__ import annotations

# canonical spelling -> aliases (canonical excluded). Every lookup goes through `keyword()`.
ALIASES: dict[str, tuple[str, ...]] = {
    # the procedure header
    "Procedure": (),
    "Use_When": ("Trigger_When",),
    "Do_Not_Use_When": (),
    "Requires": (),
    "Avoid": ("Anti_Pattern",),
    # step kinds
    "Start": (),
    "Decide": (),
    "Route": (),
    "Aggregate": (),
    "Execute": (),
    "Task_Agent": ("Task", "Agent_Task"),
    "End": (),
    # the particle after a step kind
    "With": ("w/",),
    "On": (),
    # clauses
    "Read": ("Reads", "Input"),
    "Answer_Questions": ("Questions",),
    "History": (),
    "Confidence_Below": (),
    "Confidence_Above": ("Confidence", "Conf"),
    "Aggregations": (),
    "Produce": ("Produces", "Return", "Output"),
    "When": (),
    "Run_Script": ("Run", "Script"),
    "Command": (),
    "Prompt": ("Template",),
    "Use": ("Uses", "Asset", "Reference"),
    "Next_Step": ("Next", "Go_To"),
    "Continue": ("Next_Pass",),
    # loops
    "For": ("For_Each",),
    "Loop": (),
    "Over": (),
    "As": (),
    "At_Most": ("Max",),
    "Collect": (),
    "Into": (),
    "Until": (),
    "Times": (),
    "Else_Fail": (),
    "Else_Exit": (),
    # aggregation modes
    "All": (),
    "Any": (),
    "None": (),
}

_LOOKUP: dict[str, str] = {}
for _canonical, _aliases in ALIASES.items():
    _LOOKUP[_canonical.lower()] = _canonical
    for _alias in _aliases:
        _LOOKUP[_alias.lower()] = _canonical


def keyword(word: str) -> str | None:
    """The canonical keyword `word` spells in any case or alias, or None when it is not one."""
    return _LOOKUP.get(word.lower())


def is_keyword(word: str, *canonical: str) -> bool:
    """Whether `word` spells one of the given canonical keywords."""
    return keyword(word) in canonical


STEP_KINDS = ("Start", "Decide", "Route", "Aggregate", "Execute", "Task_Agent", "End")
LOOP_KINDS = ("For", "Loop")
HEADER_CLAUSES = ("Use_When", "Do_Not_Use_When", "Requires", "Avoid")
FLOW_CLAUSES = ("Next_Step", "Continue")

# Types are lowercase and never keywords; `type_name()` folds the aliases.
TYPE_ALIASES: dict[str, tuple[str, ...]] = {
    "string": (),
    "integer": (),
    "float": ("number",),
    "boolean": (),
    "list": ("array",),
    "object": (),
    "true_or_false": (),
    "choice": (),
    "score": (),
    "decision": (),
    "aggregation": (),
}
ANSWER_TYPES = ("true_or_false", "choice", "score")

_TYPES: dict[str, str] = {}
for _canonical, _aliases in TYPE_ALIASES.items():
    _TYPES[_canonical] = _canonical
    for _alias in _aliases:
        _TYPES[_alias] = _canonical


def type_name(word: str) -> str | None:
    """The canonical type `word` names (folding `number` and `array`), or None."""
    return _TYPES.get(word)


def _distance(a: str, b: str) -> int:
    """The edit distance between two words (insertions, deletions, substitutions)."""
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        previous, row[0] = row[0], i
        for j, cb in enumerate(b, 1):
            previous, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, previous + (ca != cb))
    return row[-1]


def nearest(word: str, candidates) -> str | None:
    """The canonical keyword among `candidates` that `word` most likely misspells: one whose
    spelling, or an alias's, is within two edits of it (one for a word of four letters or fewer),
    in any case. None when nothing is that close, or when `word` already spells a keyword."""
    if keyword(word) is not None:
        return None
    best: tuple[int, str] | None = None
    for canonical in candidates:
        for spelling in (canonical, *ALIASES.get(canonical, ())):
            d = _distance(word.lower(), spelling.lower())
            if d <= (1 if len(spelling) <= 4 else 2) and (best is None or d < best[0]):
                best = (d, canonical)
    return None if best is None else best[1]
