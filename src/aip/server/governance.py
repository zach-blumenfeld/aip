"""Governance (design §7 and §10.5): the corpus questions a server answers over its catalog and runs.

Four named queries, served as `GET /governance/{query}` with `name` (optional filter), `window`
(the last N runs considered), and `limit` (rows returned); each returns a list of flat rows.

- `overridden-decisions`: per (name, decision step, question), how often the client changed a
  model answer before continuing. A model answer is settled by the first later history entry
  whose input carries that key (the step the client's payload reached: the next step, or the
  router before it when the key is what it branches on); it is overridden when the settled
  value differs from the collapsed answer. Manual decisions have no model answer and never count.
- `failing-scripts`: per execution step, how many of the windowed runs it ran in and how many of
  those attempts ended in an error, with the latest error message.
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

from aip.model.steps import Decision
from aip.server.records import RunRecord

JSON = Dict[str, Any]

QUERIES: Dict[str, str] = {
    "overridden-decisions": "Decision questions whose model answers the client overrode, most overridden first.",
    "failing-scripts": "Execution steps that failed in the last N runs, most failures first, with the latest error.",
    "missing-fields": "Names whose resolved revision has an empty do_not_use_when or anti_patterns.",
    "untaken-branches": "Router branches no run in the last N took (graph backends only).",
}

MISSING_FIELDS = ("do_not_use_when", "anti_patterns")

DEFAULT_WINDOW = 100
DEFAULT_LIMIT = 50


# ------------------------------------------------------------------- one run's history


def collapsed_answers(entry: JSON) -> Dict[str, Any]:
    """A model-answered decision entry's answers collapsed to what the client carries forward
    (noul -> bool, choice -> label, score -> level); `{}` for any other entry."""
    if entry.get("kind") != "decision" or entry.get("manual"):
        return {}
    answers = (entry.get("result") or {}).get("answers") or {}
    out: Dict[str, Any] = {}
    for name, answer in answers.items():
        try:
            out[name] = Decision.collapse(answer)
        except (KeyError, ValueError, TypeError):
            continue
    return out


def overrides(history: List[JSON]) -> List[JSON]:
    """Every model answer in a run that a later step's input settled:
    rows `{step, question, value, accepted, overridden}` in history order."""
    pending: List[Tuple[str, str, Any]] = []
    rows: List[JSON] = []
    for entry in history:
        payload = entry.get("input")
        if isinstance(payload, dict) and pending:
            still = []
            for step, question, value in pending:
                if question in payload:
                    rows.append({"step": step, "question": question, "value": value,
                                 "accepted": payload[question], "overridden": payload[question] != value})
                else:
                    still.append((step, question, value))
            pending = still
        for question, value in collapsed_answers(entry).items():
            pending.append((entry.get("step"), question, value))
    return rows


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
        for row in overrides(run.history):
            c = counts.setdefault((run.name, row["step"], row["question"]), [0, 0])
            c[0] += 1
            c[1] += int(row["overridden"])
    rows = [{"name": n, "step": s, "question": q, "decided": d, "overridden": o, "rate": o / d}
            for (n, s, q), (d, o) in counts.items() if o]
    rows.sort(key=lambda r: (-r["overridden"], -r["rate"], r["name"], r["step"], r["question"]))
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
                                  {"ran": 0, "failed": 0, "last_error": None, "script": None})
            c["ran"] += 1
            if failed:
                c["failed"] += 1
                if c["last_error"] is None:
                    c["last_error"] = (entry.get("result") or {}).get("error")
            if c["script"] is None:
                c["script"] = script_of(run.name, run.revision, entry.get("step"))
    rows = [{"name": n, "step": s, "script": c["script"], "ran": c["ran"], "failed": c["failed"],
             "rate": c["failed"] / c["ran"], "last_error": c["last_error"]}
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


__all__ = ["DEFAULT_LIMIT", "DEFAULT_WINDOW", "MISSING_FIELDS", "QUERIES", "collapsed_answers",
           "failing_scripts", "is_script_attempt", "missing_fields", "overridden_decisions", "overrides"]
