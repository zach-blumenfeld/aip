"""The corpus questions a server answers over its store: named Cypher queries, one body for both backends.

Served as `GET /governance` (the list) and `GET /governance/{query}` (the rows), with `name`,
`agent`, `session` and `user` (optional filters on the runs), `window` (the last N matching runs
considered) and `limit` (rows returned). Every query here is also written out, with what it
answers, in `docs/language/queries.md`, and `tests/server/test_queries.py` runs both against
each backend.

- `confidence-fired`: per (procedure, route, reason), how many times in the windowed runs the
  route's `Confidence_Below` check fired, with the runs it fired in. `reason` is `below` (the
  answer's confidence was under the bound) or `absent` (the answer carried none).
- `failing-aggregations`: per (procedure, step, aggregation), how many times it was computed in
  the windowed runs and how many of those it did not hold, with how many answers a bar turned.
- `model-answers`: per (procedure, step, question), how many answers the decision model gave in
  the windowed runs, their mean and lowest confidence, and how long the calls took.
- `agent-routes`: the routes of each name's resolved revision that an agent's answer steers
  (the source class on the route's `READ_BY` edge is `agent`), with how many windowed runs went
  through each.

This is the part of governance that the store's schema settles (plan S1). The rest of the 0.8
set, the rename to `aip audit`, and stored queries are the next milestone's (S2).
"""

from __future__ import annotations

from typing import Any

JSON = dict[str, Any]

DEFAULT_WINDOW = 100
DEFAULT_LIMIT = 50

# The runs a query looks at: the last `$window` that match the filters.
WINDOW = """
MATCH (r:Run)
WHERE ($name IS NULL OR r.name = $name) AND ($agent IS NULL OR r.agent = $agent)
  AND ($session IS NULL OR r.session = $session) AND ($user IS NULL OR r.user = $user)
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

AGENT_ROUTES = """
MATCH (p:Procedure)-[:HAS_STEP]->(route:Route)<-[read:READ_BY]-(d:Data)
WHERE p.bundle_id IN $bundles AND read.source = 'agent'
OPTIONAL MATCH (e:Entry {kind: 'Route'})-[:AT]->(route)
RETURN p.name AS name, route.name AS route, d.name + coalesce('.' + read.field, '') AS reads, d.labels AS labels,
       count(DISTINCT e.run_id) AS runs
ORDER BY name, route
LIMIT $limit
"""

QUERIES: dict[str, tuple[str, str]] = {
    "confidence-fired": ("Routes whose confidence check fired in the last N runs, by reason, with the runs it sent elsewhere.",
                         CONFIDENCE_FIRED),
    "failing-aggregations": ("Aggregations that did not hold in the last N runs, most failures first.", FAILING_AGGREGATIONS),
    "model-answers": ("What the decision model answered in the last N runs, per question, least confident first.", MODEL_ANSWERS),
    "agent-routes": ("Routes an agent's answer steers, in each name's resolved revision, with the runs through them.", AGENT_ROUTES),
}


def listing() -> list[JSON]:
    """The rows of `GET /governance`."""
    return [{"query": name, "description": description, "builtin": True} for name, (description, _) in QUERIES.items()]


def run(store: Any, query: str, name: str | None = None, agent: str | None = None, session: str | None = None,
        user: str | None = None, window: int = DEFAULT_WINDOW, limit: int = DEFAULT_LIMIT) -> list[JSON]:
    """Rows of one named query over `store` (an `aip.server.store.Store`); `KeyError` for a name that is not one."""
    _, cypher = QUERIES[query]
    return store.rows(cypher, name=name, agent=agent, session=session, user=user, window=window, limit=limit,
                      bundles=store.resolved_bundles(name))


__all__ = ["DEFAULT_LIMIT", "DEFAULT_WINDOW", "QUERIES", "listing", "run"]
