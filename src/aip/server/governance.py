"""Governance (design §7 and §10.5): the corpus questions a server answers over its catalog and runs.

Ten named queries, served as `GET /governance/{query}` with `name` (optional filter), `window`
(the last N runs considered), `limit` (rows returned), and `repeats` (for `repeated-cycles`); each
returns a list of flat rows. Five are about runs, how the procedures behave in use; one joins the
procedures' structure to the runs that went through it; four are about the procedures' structure
alone, what the control flow and the data flow say when read as one graph, and those four are
answered by the graph backend only.

Decisions are resolved by clients, and each decision entry in a run's history carries its
`attribution`: `{"resolver": "typesafe"|"manual", "model", "confidence"}`, where `confidence` maps
each question to the probability the model put on its answer (`None` for a manual answer).
Routers are walked by the server, and a router with a confidence check records what the check
made of the state in its entry: `result.confidence: {fired, reason}`, `reason` one of `low`,
`absent` or `null` when it fired, `manual` when it was skipped for an answer given by hand.

- `confidence-fired`: per (name, router, reason), how many times in the windowed runs the
  router's confidence check fired, with the ids of the runs it fired in. A fired check is a run
  the decision model was not sure about (or one answered with no confidence at all), sent where
  the author pointed it.
- `unmeasured-routes`: routers the validator flagged at publish with `unmeasured_route` or
  `confidence_on_unmeasured_source` on each name's resolved revision, with the router's source
  class, how many windowed runs of that revision passed through the router, and their ids: the
  runs a probabilistic choice steered with nothing recorded about how sure it was.
- `manual-decisions`: per (name, decision step), how many decisions were answered with no
  model (`resolver: manual`) out of all its recorded decisions.
- `failing-scripts`: per execution step, how many of the windowed runs it ran in and how many of
  those attempts ended in an error, with the latest error message and, when the client reported
  the script's exit, its `exit_code` and `stderr` (null for a timeout or unmet requirements).
- `missing-fields`: names whose resolved revision has an empty `do_not_use_when` or `anti_patterns`.
- `untaken-branches`: router branches no windowed run followed, for revisions that ran at all.
  The filesystem backend declines this one (`NotSupported`, 501 over HTTP); the Neo4j backend
  answers it from the graph.
- `empty-results`: resolved revisions whose end step reads only start inputs, so the result the
  caller gets back holds nothing any step produced; every step's work is a side effect or a
  history entry. Graph only.
- `unused-data`: keys a step produces (an output, or a decision's answer) that no step reads and
  the end step does not return. An output may be a receipt kept for the ledger; an unread answer
  is a model call per run that changes nothing. Graph only.
- `cycles`: the control-flow cycles of each resolved revision, with the router value (or the
  confidence bound) that keeps each going and the keys its steps re-produce every time round.
  Graph only.
- `repeated-cycles`: runs in the window that went round a cycle more than `repeats` times
  (default 1), by the router at the cycle, since the format has no iteration bound. Graph only.

The filesystem backend answers by scanning run files with the helpers here; the Neo4j backend
projects the same facts at append time (`Answer` nodes, the check's outcome on a router's
`StepRun`) and runs Cypher (`aip.server.backends.neo4j.queries`). Both give the same rows for
the same history.

Stored queries. The Neo4j backend also keeps queries of its own: `PUT /governance/{name}` with a
description and Cypher adds one, `DELETE /governance/{name}` removes it, and `GET /governance`
lists them after the built-ins with `builtin: false`. A stored query runs like a built-in one,
with the same parameters available to it (`$name`, `$window`, `$limit`, `$repeats`, and `$ids`,
the resolved revision ids), in a read-only transaction the database enforces, with a timeout
(`STORED_QUERY_TIMEOUT`), and its rows are returned as the Cypher shapes them. The name must be
kebab-case (`STORED_NAME_PATTERN`) and not one of the built-ins. The filesystem backend has no
query language to keep one in and declines with 501.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Tuple

from aip.server.records import RunRecord

JSON = Dict[str, Any]

QUERIES: Dict[str, str] = {
    "confidence-fired": "Routers whose confidence check fired in the last N runs, by reason, with the runs it sent elsewhere.",
    "unmeasured-routes": "Routers an unmeasured source steers (flagged at publish), with the runs that passed through them.",
    "manual-decisions": "Decision steps answered with no decision model, most manual answers first.",
    "failing-scripts": "Execution steps that failed in the last N runs, most failures first, with the latest error.",
    "missing-fields": "Names whose resolved revision has an empty do_not_use_when or anti_patterns.",
    "untaken-branches": "Router branches no run in the last N took (graph backends only).",
    "empty-results": "Procedures whose result holds nothing any step produced: the end step reads only start inputs (graph backends only).",
    "unused-data": "Keys a step produces or a decision answers that no step reads and the result does not return (graph backends only).",
    "cycles": "Control-flow cycles, with the branch value that continues each and the keys it re-produces every time round (graph backends only).",
    "repeated-cycles": "Runs in the last N that went round a cycle more than `repeats` times (graph backends only).",
}
STRUCTURAL = ("empty-results", "unused-data", "cycles")     # over the catalog's resolved revisions, no runs involved
RESOLVED = STRUCTURAL + ("missing-fields", "unmeasured-routes")   # given the resolved revision ids

MISSING_FIELDS = ("do_not_use_when", "anti_patterns")
UNMEASURED_CODES = ("unmeasured_route", "confidence_on_unmeasured_source")   # the validator's, on a router

DEFAULT_WINDOW = 100
DEFAULT_LIMIT = 50
DEFAULT_REPEATS = 1
STORED_QUERY_TIMEOUT = 30.0                       # seconds a stored query may run
STORED_NAME_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"  # like a step name: `slow-steps`
NOT_FOUND = "no governance query {name!r}; GET /governance lists them"


def listing(stored: Iterable[JSON] = ()) -> List[JSON]:
    """The rows of `GET /governance`: the built-ins, then the stored queries as given."""
    rows = [{"query": q, "description": d, "builtin": True} for q, d in QUERIES.items()]
    rows += [{"query": r["query"], "description": r.get("description") or "", "builtin": False} for r in stored]
    return rows


# ------------------------------------------------------------------- one run's history


def attribution(entry: JSON) -> JSON | None:
    """A decision entry's attribution (a manual one for an entry recorded without it); None otherwise."""
    if entry.get("kind") != "decision":
        return None
    return entry.get("attribution") or {"resolver": "manual", "model": None, "confidence": None}


def model_answers(entry: JSON) -> List[JSON]:
    """A decision entry's model answers, one row per question: `{question, resolver, model, value,
    confidence}`, `value` the answer the run recorded and `confidence` the probability the model
    put on it (None when the model gave none); `[]` for a manual answer or any other entry."""
    who = attribution(entry)
    if who is None or who.get("resolver") == "manual":
        return []
    answers = (entry.get("result") or {}).get("answers") or {}
    scores = who.get("confidence") or {}
    return [{"question": q, "resolver": who.get("resolver"), "model": who.get("model"), "value": v,
             "confidence": scores.get(q)} for q, v in answers.items()]


def routing(entry: JSON) -> JSON | None:
    """A router entry's confidence check as recorded, `{fired, reason}`, or None for a router with
    no check or any other entry."""
    if entry.get("kind") != "router":
        return None
    return (entry.get("result") or {}).get("confidence")


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


def confidence_fired(runs: Iterable[RunRecord], limit: int = DEFAULT_LIMIT) -> List[JSON]:
    """`runs` newest first; `run_ids` keep that order."""
    counts: Dict[tuple, JSON] = {}
    for run in runs:
        for entry in run.history:
            check = routing(entry)
            if not check or not check.get("fired"):
                continue
            c = counts.setdefault((run.name, entry.get("step"), check.get("reason")), {"fired": 0, "run_ids": []})
            c["fired"] += 1
            if run.id not in c["run_ids"]:
                c["run_ids"].append(run.id)
    rows = [{"name": n, "router": r, "reason": why, "fired": c["fired"], "run_ids": c["run_ids"]}
            for (n, r, why), c in counts.items()]
    rows.sort(key=lambda r: (-r["fired"], r["name"], r["router"], r["reason"]))
    return rows[:limit]


def unmeasured_routes(procedures: Iterable[Tuple[str, str, JSON]], runs: Iterable[RunRecord],
                      limit: int = DEFAULT_LIMIT) -> List[JSON]:
    """`procedures` yields (name, revision, manifest) for each name's resolved revision, the manifest
    holding its `steps` and `issues` rows; `runs` is the window, newest first."""
    runs = list(runs)
    rows = []
    for name, revision, manifest in procedures:
        classes = {s["name"]: s.get("source_class") for s in manifest.get("steps", []) if s.get("kind") == "router"}
        for issue in manifest.get("issues", []):
            if issue.get("code") not in UNMEASURED_CODES or issue.get("step") not in classes:
                continue
            router = issue["step"]
            ids = [run.id for run in runs if run.name == name and run.revision == revision
                   and any(e.get("step") == router and e.get("kind") == "router" for e in run.history)]
            rows.append({"name": name, "revision": revision, "router": router, "code": issue["code"],
                         "source_class": classes[router], "runs": len(ids), "run_ids": ids})
    rows.sort(key=lambda r: (-r["runs"], r["name"], r["router"]))
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


__all__ = ["DEFAULT_LIMIT", "DEFAULT_REPEATS", "DEFAULT_WINDOW", "MISSING_FIELDS", "NOT_FOUND", "QUERIES", "RESOLVED",
           "STORED_NAME_PATTERN", "STORED_QUERY_TIMEOUT", "STRUCTURAL", "UNMEASURED_CODES", "listing", "attribution",
           "confidence_fired", "failing_scripts", "is_script_attempt", "manual_decisions", "missing_fields",
           "model_answers", "routing", "unmeasured_routes"]
