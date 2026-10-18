"""Governance (design §7 and §10.5): the corpus questions a server answers over its catalog and runs.

Five named queries, served as `GET /governance/{query}` with `name` (optional filter), `window`
(the last N runs considered), and `limit` (rows returned); each returns a list of flat rows.

Decisions are resolved by clients, and each decision entry in a run's history carries its
`attribution`: `{"resolver": "typesafe"|"manual", "model", "confidence", "reviewed"}`, plus
`proposed`, the model's answers, when the agent reviewed them. The two decision queries read it.

- `overridden-decisions`: per (name, decision step, question, resolver), how many model answers
  were recorded and how many the agent changed at review (`proposed` differs from the answer).
  Manual answers have no model answer and never count.
- `manual-decisions`: per (name, decision step), how many decisions were answered with no
  model (`resolver: manual`) out of all its recorded decisions.
- `failing-scripts`: per execution step, how many of the windowed runs it ran in and how many of
  those attempts ended in an error, with the latest error message and, when the client reported
  the script's exit, its `exit_code` and `stderr` (null for a timeout or unmet requirements).
- `missing-fields`: names whose resolved revision has an empty `do_not_use_when` or `anti_patterns`.
- `untaken-branches`: router branches no windowed run followed, for revisions that ran at all.
  The filesystem backend declines this one (`NotSupported`, 501 over HTTP); the Neo4j backend
  answers it from the graph.

The filesystem backend answers by scanning run files with the helpers here; the Neo4j backend
projects the same facts at append time (`Answer` nodes) and runs Cypher
(`aip.server.backends.neo4j.queries`). Both give the same rows for the same history.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Tuple

from aip.server.records import RunRecord

JSON = Dict[str, Any]

QUERIES: Dict[str, str] = {
    "overridden-decisions": "Decision questions whose model answers the client overrode, most overridden first.",
    "manual-decisions": "Decision steps answered with no decision model, most manual answers first.",
    "failing-scripts": "Execution steps that failed in the last N runs, most failures first, with the latest error.",
    "missing-fields": "Names whose resolved revision has an empty do_not_use_when or anti_patterns.",
    "untaken-branches": "Router branches no run in the last N took (graph backends only).",
}

MISSING_FIELDS = ("do_not_use_when", "anti_patterns")

DEFAULT_WINDOW = 100
DEFAULT_LIMIT = 50


# ------------------------------------------------------------------- one run's history


def attribution(entry: JSON) -> JSON | None:
    """A decision entry's attribution (a manual one for an entry recorded without it); None otherwise."""
    if entry.get("kind") != "decision":
        return None
    return entry.get("attribution") or {"resolver": "manual", "model": None, "confidence": None, "reviewed": False}


def model_answers(entry: JSON) -> List[JSON]:
    """A decision entry's model answers, one row per question: `{question, resolver, model, value,
    accepted, reviewed, overridden}`, where `value` is what the model proposed and `accepted` what
    the run recorded; `[]` for a manual answer or any other entry."""
    who = attribution(entry)
    if who is None or who.get("resolver") == "manual":
        return []
    answers = (entry.get("result") or {}).get("answers") or {}
    proposed = who.get("proposed") or answers
    return [{"question": q, "resolver": who.get("resolver"), "model": who.get("model"), "value": proposed.get(q, v),
             "accepted": v, "reviewed": bool(who.get("reviewed")), "overridden": proposed.get(q, v) != v}
            for q, v in answers.items()]


def is_script_attempt(entry: JSON) -> tuple[bool, bool]:
    """(ran, failed) for a history entry: an execution entry ran; an error entry recorded against
    an execution step (`step_kind`) ran and failed."""
    kind = entry.get("kind")
    if kind == "execution":
        return True, False
    if kind == "error" and entry.get("step_kind") == "execution":
        return True, True
    return False, False


# ----------------------------------------------------------------- over many runs


def overridden_decisions(runs: Iterable[RunRecord], limit: int = DEFAULT_LIMIT) -> List[JSON]:
    counts: Dict[tuple, List[int]] = {}
    for run in runs:
        for entry in run.history:
            for row in model_answers(entry):
                c = counts.setdefault((run.name, entry.get("step"), row["question"], row["resolver"]), [0, 0])
                c[0] += 1
                c[1] += int(row["overridden"])
    rows = [{"name": n, "step": s, "question": q, "resolver": r, "decided": d, "overridden": o, "rate": o / d}
            for (n, s, q, r), (d, o) in counts.items() if o]
    rows.sort(key=lambda r: (-r["overridden"], -r["rate"], r["name"], r["step"], r["question"]))
    return rows[:limit]


def manual_decisions(runs: Iterable[RunRecord], limit: int = DEFAULT_LIMIT) -> List[JSON]:
    counts: Dict[tuple, List[int]] = {}
    for run in runs:
        for entry in run.history:
            who = attribution(entry)
            if who is None:
                continue
            c = counts.setdefault((run.name, entry.get("step")), [0, 0])
            c[0] += 1
            c[1] += int(who.get("resolver") == "manual")
    rows = [{"name": n, "step": s, "decided": d, "manual": m, "rate": m / d} for (n, s), (d, m) in counts.items() if m]
    rows.sort(key=lambda r: (-r["manual"], -r["rate"], r["name"], r["step"]))
    return rows[:limit]


def failing_scripts(runs: Iterable[RunRecord], script_of: Callable[[str, str, str], str | None],
                    limit: int = DEFAULT_LIMIT) -> List[JSON]:
    """`runs` newest first; `script_of(name, revision, step)` names the step's script when known."""
    counts: Dict[tuple, JSON] = {}
    for run in runs:
        for entry in run.history:
            ran, failed = is_script_attempt(entry)
            if not ran:
                continue
            c = counts.setdefault((run.name, entry.get("step")),
                                  {"ran": 0, "failed": 0, "last": None, "script": None})
            c["ran"] += 1
            if failed:
                c["failed"] += 1
                if c["last"] is None:
                    c["last"] = entry.get("result") or {}
            if c["script"] is None:
                c["script"] = script_of(run.name, run.revision, entry.get("step"))
    rows = [{"name": n, "step": s, "script": c["script"], "ran": c["ran"], "failed": c["failed"],
             "rate": c["failed"] / c["ran"], "last_error": c["last"].get("error"),
             "exit_code": c["last"].get("exit_code"), "stderr": c["last"].get("stderr")}
            for (n, s), c in counts.items() if c["failed"]]
    rows.sort(key=lambda r: (-r["failed"], -r["rate"], r["name"], r["step"]))
    return rows[:limit]


def missing_fields(procedures: Iterable[Tuple[str, str, JSON]], limit: int = DEFAULT_LIMIT) -> List[JSON]:
    """`procedures` yields (name, revision, procedure row) for each name's resolved revision."""
    rows = []
    for name, revision, procedure in procedures:
        missing = [f for f in MISSING_FIELDS if not (procedure or {}).get(f)]
        if missing:
            rows.append({"name": name, "revision": revision, "missing": missing})
    rows.sort(key=lambda r: r["name"])
    return rows[:limit]


__all__ = ["DEFAULT_LIMIT", "DEFAULT_WINDOW", "MISSING_FIELDS", "QUERIES", "attribution", "failing_scripts",
           "is_script_attempt", "manual_decisions", "missing_fields", "model_answers", "overridden_decisions"]
