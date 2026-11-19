"""The audit queries: what a server answers by name over its store, the record of runs and the
catalog read as one graph. Named Cypher, one body for both backends.

Served as `GET /audit` (the list) and `GET /audit/{query}` (the rows). Every query takes the same
parameters: `name`, `agent`, `session`, `user` and `draft` (optional filters on the runs; `draft`
true for runs of a bundle with no revision, false for runs of a published one), `window` (the last
N matching runs considered), `limit` (rows returned), `repeats` (for `repeated-cycles`) and `key`
(for `lineage`). The queries over runs are also written out, with what each answers, in
`docs/language/queries.md`, and `tests/server/test_queries.py` runs both against each backend.

They review; none of them decides who may do what, which is why the command is `aip audit` and
not `aip governance` (plan question 42).

Over the windowed runs:

- `confidence-fired`: per (procedure, route, reason), how many times the route's
  `Confidence_Below` check fired, with the runs it fired in. `reason` is `below` (the answer's
  confidence was under the bound) or `absent` (the answer carried none).
- `failing-aggregations`: per (procedure, step, aggregation), how many times it was computed and
  how many of those it did not hold, with how many answers a bar turned.
- `model-answers`: per (procedure, step, question), how many answers the decision model gave,
  their mean and lowest confidence, and how long the calls took.
- `agent-work`: per (procedure, `Task_Agent` step, who answered, model, `work`), how many tasks
  and the tool calls and tokens they took, most tokens first. `work` says whose account it is:
  `reported`, the agent's own (`aip resume --work`, unchecked; `aip agent` reports its model's
  tokens), or `observed` in a record an earlier 0.9 wrote.
- `failing-scripts`: per (procedure, `Execute` step, error), the runs that stand failed at the
  step (`script_failed`, `timeout`, `requires_unmet`), with the script and the latest message. A
  run that failed there and was resumed past it no longer counts: the record keeps where a run
  stands, not the attempts before.
- `untaken-branches`: branches of a route, its `Confidence_Below` line included, that none of the
  windowed runs took, in the bundles those runs ran.
- `repeated-cycles`: per (procedure, `Loop`, exit), the runs whose loop went round more than
  `repeats` times (default 1), with the most passes and whether it ended on its `Until` or its cap.

Over the revision each published name resolves to (`name` narrows it; the other filters do not apply):

- `agent-routes`: the routes an agent's answer steers (the source class on the route's `READ_BY`
  edge is `agent`), with how many runs went through each.
- `missing-fields`: procedures whose header lacks `Use_When`, `Do_Not_Use_When` or `Avoid` lines,
  with how many of each it has.
- `empty-results`: procedures whose `End` returns nothing a step produced: every key it reads is a
  `Start` input.
- `unused-data`: keys a step produces, and questions a `Decide` asks, that no step reads, no
  aggregation or loop looks at, and the result does not return. An unread answer is a model call
  per run that changes nothing.
- `cycles`: every `For` and `Loop`, with what bounds it (the list, the count, `Until`, the cap and
  what happens there) and the keys its body produces again on every pass.
- `lineage`: for the key named by `key`, every key it is derived from, how many steps back, and
  the steps that produce each. A key is derived from what its producer read, and a collected
  list from the key each pass gathered and the list the loop went over, so the walk goes through
  a `For` (three statements and a walk here, where the others are one statement each).

**Stored queries.** `PUT /audit/{name}` with `{"description", "cypher"}` keeps a query of your
own in the store, `DELETE /audit/{name}` removes it, and `GET /audit` lists them after the
built-ins with `builtin: false`. A stored query is run like a built-in one, with the same
parameters bound (`$name`, `$agent`, `$session`, `$user`, `$draft`, `$window`, `$limit`,
`$repeats`, `$key`, and `$bundles`, the resolved bundle ids), in a transaction that is never
committed, and its rows come back as the Cypher shapes them: a node it returns is a map
`{"labels", "properties"}`, a relationship `{"type", "properties"}`. Its name is kebab-case and
not a built-in's; Cypher with a writing clause, or that the engine cannot parse (it is planned
with `EXPLAIN`, not run), is refused when it is stored.
"""

from __future__ import annotations

import re
from typing import Any

JSON = dict[str, Any]

DEFAULT_WINDOW = 100
DEFAULT_LIMIT = 50
DEFAULT_REPEATS = 1
STORED_NAME = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")          # like `slow-steps`
SCRIPT_ERRORS = ["script_failed", "timeout", "requires_unmet"]

# The runs a query looks at: the last `$window` that match the filters.
WINDOW = """
MATCH (r:Run)
WHERE ($name IS NULL OR r.name = $name) AND ($agent IS NULL OR r.agent = $agent)
  AND ($session IS NULL OR r.session = $session) AND ($user IS NULL OR r.user = $user)
  AND ($draft IS NULL OR r.draft = $draft)
WITH r ORDER BY r.updated DESC LIMIT $window
"""

CONFIDENCE_FIRED = WINDOW + """
MATCH (r)-[:HAS_ENTRY]->(e:Entry {kind: 'Route'})
WHERE e.check_fired = true
RETURN r.name AS name, e.step AS route, e.check_reason AS reason, count(e) AS fired, collect(DISTINCT r.run_id) AS run_ids
ORDER BY fired DESC, name, route, reason
LIMIT $limit
"""

FAILING_AGGREGATIONS = WINDOW + """
MATCH (r)-[:HAS_ENTRY]->(e:Entry {kind: 'Aggregate'})-[:GAVE]->(a:Answer)
WITH r.name AS name, e.step AS step, a.name AS aggregation, count(a) AS computed,
     sum(CASE WHEN a.value = false THEN 1 ELSE 0 END) AS failed, sum(a.barred) AS barred
WHERE failed > 0
RETURN name, step, aggregation, computed, failed, barred
ORDER BY failed DESC, name, step, aggregation
LIMIT $limit
"""

MODEL_ANSWERS = WINDOW + """
MATCH (r)-[:HAS_ENTRY]->(e:Entry {kind: 'Decide'})-[:GAVE]->(a:Answer)
RETURN r.name AS name, e.step AS step, a.name AS question, e.model AS model, count(a) AS answers,
       avg(a.confidence) AS mean_confidence, min(a.confidence) AS lowest_confidence, avg(e.model_seconds) AS mean_model_seconds
ORDER BY lowest_confidence, name, step, question
LIMIT $limit
"""

AGENT_WORK = WINDOW + """
MATCH (r)-[:HAS_ENTRY]->(e:Entry {kind: 'Task_Agent'})
WHERE e.work IS NOT NULL
RETURN r.name AS name, e.step AS step, e.agent AS agent, e.model AS model, e.work AS work, count(e) AS tasks,
       sum(e.tool_calls) AS tool_calls, sum(e.tokens) AS tokens
ORDER BY tokens DESC, name, step, work
LIMIT $limit
"""

FAILING_SCRIPTS = WINDOW + """
MATCH (r)-[:OF]->(:Bundle)-[:HOLDS]->(:Procedure)-[:HAS_STEP]->(s:Execute)
WHERE r.status = 'failed' AND r.error IN $script_errors AND s.name = r.error_step
RETURN r.name AS name, s.name AS step, s.script AS script, r.error AS error, count(r) AS failed,
       head(collect(r.error_message)) AS last_message, collect(r.run_id) AS run_ids
ORDER BY failed DESC, name, step, error
LIMIT $limit
"""

UNTAKEN_BRANCHES = WINDOW + """
WITH collect(r.run_id) AS runs, collect(DISTINCT r.bundle_id) AS ran
MATCH (p:Procedure)-[:HAS_STEP]->(route:Route)-[b:BRANCH|BELOW]->(t)
WHERE p.bundle_id IN ran
OPTIONAL MATCH (e:Entry {kind: 'Route'})-[:AT]->(route)
WHERE e.run_id IN runs AND ((b.below IS NOT NULL AND e.check_fired = true) OR (b.value IS NOT NULL AND e.value = b.value))
WITH p.name AS name, route.name AS route, coalesce(b.value, 'Confidence_Below ' + toString(b.below)) AS branch, t.name AS to,
     count(e) AS taken
WHERE taken = 0
RETURN name, route, branch, to
ORDER BY name, route, branch
LIMIT $limit
"""

REPEATED_CYCLES = WINDOW + """
MATCH (r)-[:HAS_ENTRY]->(e:Entry {kind: 'Loop'})
WHERE e.iterations > $repeats
RETURN r.name AS name, e.step AS loop, e.exit AS exit, count(e) AS times, max(e.iterations) AS most_passes,
       collect(DISTINCT r.run_id) AS run_ids
ORDER BY most_passes DESC, name, loop, exit
LIMIT $limit
"""

AGENT_ROUTES = """
MATCH (p:Procedure)-[:HAS_STEP]->(route:Route)<-[read:READ_BY]-(d:Data)
WHERE p.bundle_id IN $bundles AND read.source = 'agent'
OPTIONAL MATCH (e:Entry {kind: 'Route'})-[:AT]->(route)
RETURN p.name AS name, route.name AS route, d.name + coalesce('.' + read.field, '') AS reads, d.labels AS labels,
       count(DISTINCT e.run_id) AS runs
ORDER BY name, route
LIMIT $limit
"""

MISSING_FIELDS = """
MATCH (p:Procedure)
WHERE p.bundle_id IN $bundles
WITH p.name AS name, size(coalesce(p.use_when, [])) AS use_when, size(coalesce(p.do_not_use_when, [])) AS do_not_use_when,
     size(coalesce(p.avoid, [])) AS avoid
WHERE use_when = 0 OR do_not_use_when = 0 OR avoid = 0
RETURN name, use_when, do_not_use_when, avoid
ORDER BY name
LIMIT $limit
"""

EMPTY_RESULTS = """
MATCH (p:Procedure)-[:ENDS_AT]->(end:End)
WHERE p.bundle_id IN $bundles
OPTIONAL MATCH (d:Data)-[:READ_BY]->(end)
OPTIONAL MATCH (w)-[:PRODUCES]->(d)
WITH p.name AS name, collect(DISTINCT d.name) AS returns, sum(CASE WHEN w IS NULL OR w.kind = 'Start' THEN 0 ELSE 1 END) AS produced
WHERE produced = 0
RETURN name, returns
ORDER BY name
LIMIT $limit
"""

UNUSED_KEYS = """
MATCH (p:Procedure)-[:SUPPLIES]->(d:Data)<-[:PRODUCES]-(w)
WHERE p.bundle_id IN $bundles AND w.kind <> 'Start' AND w.kind <> 'Decide' AND d.runtime IS NULL
OPTIONAL MATCH (d)-[r:READ_BY]->(reader)
OPTIONAL MATCH (other)-[o:OVER|WATCHES|COLLECTS]->(d)
WITH p.name AS name, w.name AS step, w.kind AS kind, d.name AS data, d.type AS type, count(r) + count(o) AS uses
WHERE uses = 0
RETURN name, step, kind, data, type
ORDER BY name, step, data
LIMIT $limit
"""

UNUSED_ANSWERS = """
MATCH (p:Procedure)-[:HAS_STEP]->(s:Decide)-[:ASKS]->(q:Question)
WHERE p.bundle_id IN $bundles
MATCH (s)-[:PRODUCES]->(d:Data)
OPTIONAL MATCH (d)-[r:READ_BY]->(reader)
WHERE r.field IS NULL OR r.field = q.name OR r.field STARTS WITH q.name + '.'
OPTIONAL MATCH (other)-[o:OVER|WATCHES|COLLECTS]->(d)
WHERE o.field IS NULL OR o.field = q.name OR o.field STARTS WITH q.name + '.'
WITH p.name AS name, s.name AS step, s.kind AS kind, d.name + '.' + q.name AS data, q.type AS type, count(r) + count(o) AS uses
WHERE uses = 0
RETURN name, step, kind, data, type
ORDER BY name, step, data
LIMIT $limit
"""

CYCLES = """
MATCH (p:Procedure)-[:HAS_LOOP]->(l:Loop)
WHERE p.bundle_id IN $bundles
OPTIONAL MATCH (l)-[:CONTAINS]->(s:Step)-[:PRODUCES]->(d:Data)
OPTIONAL MATCH (l)-[:OVER]->(list:Data)
RETURN p.name AS name, l.name AS loop, l.kind AS kind, l.mode AS mode, list.name AS over, l.until_answer AS until, l.times AS times,
       l.at_most AS at_most, l.at_cap AS at_cap, collect(DISTINCT d.name) AS reproduces
ORDER BY name, loop
LIMIT $limit
"""

# Lineage: a key is derived from what its producer read, and a collected list from the key each
# pass gathered and the list the loop went over. Three statements give the edges; `lineage` walks them.
DERIVED_BY_STEP = """
MATCH (p:Procedure)-[:SUPPLIES]->(d:Data)<-[:PRODUCES]-(w:Step)<-[:READ_BY]-(up:Data)
WHERE p.bundle_id IN $bundles
RETURN DISTINCT p.name AS name, d.name AS key, up.name AS derived_from
"""
DERIVED_BY_LOOP = """
MATCH (p:Procedure)-[:HAS_LOOP]->(l:Loop)-[:PRODUCES]->(d:Data)
WHERE p.bundle_id IN $bundles AND l.collect_into = d.name
MATCH (l)-[:COLLECTS|OVER]->(up:Data)
RETURN DISTINCT p.name AS name, d.name AS key, up.name AS derived_from
"""
PRODUCERS = """
MATCH (p:Procedure)-[:SUPPLIES]->(d:Data)<-[:PRODUCES]-(w)
WHERE p.bundle_id IN $bundles
RETURN p.name AS name, d.name AS key, collect(DISTINCT w.name) AS produced_by
"""
LINEAGE_DEPTH = 24


def lineage(store: Any, params: JSON) -> list[JSON]:
    """Every key `$key` is derived from, in each resolved revision that has it: `{"name", "key",
    "derived_from", "steps_back", "produced_by"}`, nearest first."""
    derived: dict[tuple[str, str], set[str]] = {}
    for cypher in (DERIVED_BY_STEP, DERIVED_BY_LOOP):
        for row in store.rows(cypher, **params):
            derived.setdefault((row["name"], row["key"]), set()).add(row["derived_from"])
    producers = {(row["name"], row["key"]): sorted(row["produced_by"]) for row in store.rows(PRODUCERS, **params)}
    rows = []
    for name in sorted({name for name, key in producers if key == params["key"]}):
        seen, frontier = {params["key"]}, [params["key"]]
        for steps_back in range(1, LINEAGE_DEPTH + 1):
            frontier = sorted({up for key in frontier for up in derived.get((name, key), ()) if up not in seen})
            if not frontier:
                break
            seen.update(frontier)
            rows += [{"name": name, "key": params["key"], "derived_from": up, "steps_back": steps_back,
                      "produced_by": producers.get((name, up), [])} for up in frontier]
    return rows

# name -> (description, the statements whose rows it returns or the function that asks them, the parameters it cannot run without)
QUERIES: dict[str, tuple[str, Any, tuple[str, ...]]] = {
    "confidence-fired": ("Routes whose confidence check fired in the last N runs, by reason, with the runs it sent elsewhere.",
                         (CONFIDENCE_FIRED,), ()),
    "failing-aggregations": ("Aggregations that did not hold in the last N runs, most failures first.", (FAILING_AGGREGATIONS,), ()),
    "model-answers": ("What the decision model answered in the last N runs, per question, least confident first.", (MODEL_ANSWERS,), ()),
    "agent-work": ("What answering Task_Agent steps took in the last N runs: tasks, tool calls and tokens per step, agent and "
                   "model, as the agent reported it.", (AGENT_WORK,), ()),
    "failing-scripts": ("Execute steps that runs among the last N stand failed at, most failures first, with the latest message.",
                        (FAILING_SCRIPTS,), ()),
    "untaken-branches": ("Route branches none of the last N runs took.", (UNTAKEN_BRANCHES,), ()),
    "repeated-cycles": ("Loops that went round more than `repeats` times in the last N runs, and how each ended.", (REPEATED_CYCLES,), ()),
    "agent-routes": ("Routes an agent's answer steers, in each name's resolved revision, with the runs through them.", (AGENT_ROUTES,), ()),
    "missing-fields": ("Procedures whose header lacks Use_When, Do_Not_Use_When or Avoid lines.", (MISSING_FIELDS,), ()),
    "empty-results": ("Procedures whose result holds nothing any step produced: the End reads only Start inputs.", (EMPTY_RESULTS,), ()),
    "unused-data": ("Keys a step produces and questions a Decide asks that nothing reads and the result does not return.",
                    (UNUSED_KEYS, UNUSED_ANSWERS), ()),
    "cycles": ("Every For and Loop: what bounds it, and the keys its body produces again on every pass.", (CYCLES,), ()),
    "lineage": ("The keys the key named by `key` is derived from, how many steps back, and the steps that produce each.",
                lineage, ("key",)),
}

WRITES = re.compile(r"\b(CREATE|MERGE|SET|DELETE|DETACH|REMOVE|DROP|FOREACH|LOAD\s+CSV)\b", re.IGNORECASE)
_QUOTED = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"|`[^`]*`|//[^\n]*")


class InvalidQuery(ValueError):
    """A stored query that cannot be kept, or a query asked without a parameter it needs (422 over HTTP)."""


def listing(store: Any = None) -> list[JSON]:
    """The rows of `GET /audit`: the built-ins, then the store's own queries."""
    rows = [{"query": name, "description": description, "builtin": True, "needs": list(needs)}
            for name, (description, _, needs) in QUERIES.items()]
    if store is not None:
        rows += [{"query": q["name"], "description": q.get("description") or "", "builtin": False, "needs": []}
                 for q in store.stored_queries()]
    return rows


def parameters(store: Any, name: str | None = None, agent: str | None = None, session: str | None = None, user: str | None = None,
               draft: bool | None = None, window: int = DEFAULT_WINDOW, limit: int = DEFAULT_LIMIT, repeats: int = DEFAULT_REPEATS,
               key: str | None = None) -> JSON:
    """Every parameter a query is run with, built-in or stored: the caller's, `$bundles` (the
    resolved bundle ids) and `$script_errors`."""
    return dict(name=name, agent=agent, session=session, user=user, draft=draft, window=window, limit=limit, repeats=repeats,
                key=key, bundles=store.resolved_bundles(name), script_errors=SCRIPT_ERRORS)


def run(store: Any, query: str, name: str | None = None, agent: str | None = None, session: str | None = None,
        user: str | None = None, draft: bool | None = None, window: int = DEFAULT_WINDOW, limit: int = DEFAULT_LIMIT,
        repeats: int = DEFAULT_REPEATS, key: str | None = None) -> list[JSON]:
    """Rows of one named query over `store` (an `aip.server.store.Store`): a built-in, else one
    the store keeps. `KeyError` for a name that is neither; `InvalidQuery` when a parameter the
    query needs is missing."""
    params = parameters(store, name=name, agent=agent, session=session, user=user, draft=draft, window=window, limit=limit,
                        repeats=repeats, key=key)
    if query in QUERIES:
        _, statements, needs = QUERIES[query]
        missing = [p for p in needs if params.get(p) is None]
        if missing:
            raise InvalidQuery(f"the audit query {query} needs {', '.join(missing)}")
        if callable(statements):
            return statements(store, params)[:limit]
        rows = [row for cypher in statements for row in store.rows(cypher, **params)]
        return rows[:limit]
    stored = next((q for q in store.stored_queries() if q["name"] == query), None)
    if stored is None:
        raise KeyError(query)
    return store.rows(stored["cypher"], **params)


def save(store: Any, name: str, cypher: str, description: str = "") -> JSON:
    """Keep a query in the store under `name`, replacing one of that name."""
    if not STORED_NAME.fullmatch(name or ""):
        raise InvalidQuery(f"a stored query's name is kebab-case (like slow-steps), not {name!r}")
    if name in QUERIES:
        raise InvalidQuery(f"{name} is a built-in audit query; store yours under another name")
    if not isinstance(cypher, str) or not cypher.strip():
        raise InvalidQuery("a stored query is its Cypher: send {\"cypher\": \"MATCH ... RETURN ...\", \"description\": \"...\"}")
    wrote = WRITES.search(_QUOTED.sub("''", cypher))
    if wrote:
        raise InvalidQuery(f"an audit query only reads; this one has {wrote.group(1).upper()}")
    try:                                    # planned, not run: Cypher that does not parse is refused now, not when it is asked
        store.parses(cypher, **parameters(store))
    except Exception as exc:
        raise InvalidQuery(f"the query does not parse: {_as_written(str(exc))}") from exc
    store.save_query(name, description or "", cypher)
    return {"query": name, "description": description or "", "builtin": False}


def _as_written(message: str) -> str:
    """The engine's parse error without the `EXPLAIN` the check put before the query: where it
    quotes the statement, the prefix goes, and the caret under it moves back with it."""
    prefix = "EXPLAIN "
    lines = message.splitlines()
    for i, line in enumerate(lines):
        at = line.find(prefix)
        if at < 0:
            continue
        lines[i] = line[:at] + line[at + len(prefix):]
        if i + 1 < len(lines) and lines[i + 1].strip() == "^" and lines[i + 1].startswith(" " * len(prefix)):
            lines[i + 1] = lines[i + 1][len(prefix):]
    return "\n".join(lines)


def delete(store: Any, name: str) -> None:
    """Remove a stored query; `KeyError` when the store keeps none of that name (a built-in cannot be removed)."""
    if name in QUERIES:
        raise InvalidQuery(f"{name} is a built-in audit query and cannot be removed")
    if not store.delete_query(name):
        raise KeyError(name)


__all__ = ["DEFAULT_LIMIT", "DEFAULT_REPEATS", "DEFAULT_WINDOW", "QUERIES", "InvalidQuery", "delete", "listing", "parameters", "run", "save"]
