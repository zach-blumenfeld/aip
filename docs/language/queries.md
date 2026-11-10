# Queries over a bundle

A compiled procedure is a graph (spec section 3, schema in `bundle.md`), and anything that opens
the `.rl` can ask it questions in Cypher: the Relate CLI on the file, a Neo4j Browser pointed at
`relate serve --bolt`, or the aip server's store, where every published revision sits beside its
runs. These are the queries worth knowing, each verified against the five examples. Swap the
procedure name; every node carries `bundle_id`, so one store holds many bundles without a clash.
The queries over runs and revisions, which only a server's store can answer, are the second half
(The server's store).

## The whole procedure

Every node the bundle holds and every edge between them.

```cypher
MATCH (p:Procedure {name: 'billing_support'})-[:HAS_STEP|HAS_LOOP|SUPPLIES|HAS_FILE]->(n)
OPTIONAL MATCH (n)-[r]->(m) WHERE m.bundle_id = p.bundle_id
RETURN p, n, r, m
```

## Control flow

From the start step along every edge a run can take. `NEXT` is `Next_Step`; `BRANCH {value}`
and `BELOW {below}` are a route's lines; `ENTERS` is a loop to the first node of its body, where
a pass starts; `CONTINUES` is `Continue`, a step back to its enclosing loop, which then tests
`Until` or takes the next item. Every cycle in a bundle is a loop node, `ENTERS` in and
`CONTINUES` back: no other edge leads to a node that has already run. A nested loop is entered
only by `ENTERS`, so a walk on `NEXT` alone skips every loop body; this pattern does not.

```cypher
MATCH (p:Procedure {name: 'dynamic_policy'})
MATCH flow = (p)-[:STARTS_AT]->()-[:NEXT|BRANCH|BELOW|ENTERS|CONTINUES*]->()
RETURN flow
```

`CONTAINS` (loop to each body node, with `order`) is membership, not flow, and is left out so it
does not draw a second edge beside every `ENTERS`.

## Data flow

One `Data` node per key of the state. `PRODUCES` comes from the step or loop that writes it (a
`Produce` line, a `Start` input, a `For`'s collected list, a loop's `index` and `iterations` and
the key under its own name, as in `revise.iterations`);
`READ_BY` goes to every step that reads it, with `field` when the step reads one answer of a
decision (`tone` in `triage_decision.tone`) and `interpolated: true` for a `{key}` in a question
or prompt. Read left to right: `(Step)-[:PRODUCES]->(Data)-[:READ_BY]->(Step)`.

```cypher
MATCH (p:Procedure {name: 'fixed_policy'})-[:SUPPLIES]->(d:Data)
OPTIONAL MATCH produced = ()-[:PRODUCES]->(d)
OPTIONAL MATCH read = (d)-[:READ_BY]->()
RETURN d, produced, read
```

As a table, producer to key to reader:

```cypher
MATCH (p:Procedure {name: 'billing_support'})-[:SUPPLIES]->(d:Data)
MATCH (w)-[:PRODUCES]->(d)-[e:READ_BY]->(r)
RETURN w.name AS producer, d.name + coalesce('.' + e.field, '') AS data, r.name AS reader
ORDER BY w.line, r.line
```

## Routes, and what steers them

Every route with the answer it reads, the answer's source class (`measured`: a decision model;
`agent`: a `Task_Agent`; `scripted`: an `Execute`; `input`: a `Start`; `aggregated`), and its
branches. This is the governance question "which routes does an agent steer, and which a model".

```cypher
MATCH (p:Procedure)-[:HAS_STEP]->(r:Route)<-[e:READ_BY]-(d:Data)
OPTIONAL MATCH (r)-[b:BRANCH|BELOW]->(t)
RETURN p.name AS procedure, r.name AS route, d.name + coalesce('.' + e.field, '') AS reads,
       e.source AS source, d.labels AS labels,
       collect(type(b) + ' ' + coalesce(b.value, toString(b.below)) + ' -> ' + t.name) AS branches
ORDER BY procedure, route
```

## Loops

Each loop with the keys it touches: `OVER` the list it iterates, `BINDS` the item key, `COLLECTS`
the per-pass key gathered into the list it produces, `WATCHES` the answer its `Until` tests.

```cypher
MATCH (p:Procedure)-[:HAS_LOOP]->(l:Loop)-[x:OVER|BINDS|COLLECTS|WATCHES|PRODUCES]->(d:Data)
RETURN p.name AS procedure, l.name AS loop, l.kind AS kind, l.mode AS mode, type(x) AS edge, d.name AS data
ORDER BY procedure, l.line, edge
```

## Decisions and their questions

```cypher
MATCH (p:Procedure)-[:HAS_STEP]->(s:Decide)-[a:ASKS]->(q:Question)
RETURN p.name AS procedure, s.name AS step, q.name AS question, q.type AS type, q.labels AS labels, q.instruction AS instruction
ORDER BY procedure, s.line, a.order
```

## Files

What each step runs, is prompted by, or hands over as an asset or reference, with the file's
size and hash. The bytes are on the `File` node too (`text` or `base64`), which is how `aip
export` writes the program directory back.

```cypher
MATCH (p:Procedure)-[:HAS_STEP]->(s:Step)-[u:RUNS|PROMPTED_BY|USES]->(f:File)
RETURN p.name AS procedure, s.name AS step, type(u) AS how, f.path AS file, f.size AS bytes, u.description AS description
ORDER BY procedure, s.line, file
```

## The server's store

A bundle holds no runs; the server's store does. It keeps every bundle's graph exactly as above
and adds its own nodes beside them (`src/aip/server/store.py` writes them, on a Relate file or
in Neo4j alike; `docs/server-design.md` has the properties):

```
(:Name {name, pinned})-[:HAS_REVISION]->(:Revision {name, revision, number, published_at, retired})
(:Revision)-[:OF]->(:Bundle {bundle_id, name, stored_at, draft})-[:HOLDS]->(:Procedure)
(:Run {run_id, name, revision, draft, status, agent, session, user, started, finished})-[:OF]->(:Bundle)
(:Run)-[:HAS_ENTRY]->(:Entry {seq, step, kind, at, seconds, ...})-[:THEN]->(:Entry)
(:Entry)-[:AT]->(:Step or :Loop)
(:Entry)-[:GAVE]->(:Answer {name, value, confidence, source})-[:ANSWERS]->(:Question or :Aggregation)
```

A run's `draft` and `revision` are the server's word: a run is a draft's when the bundle it ran
had no revision when the run was recorded, whatever the client ran it from.

An `Entry` is one entry of a run's history, in order (`seq`, and `THEN` to the next one), tied by
`AT` to the step or loop of the procedure it ran, so a question about runs can walk into the
procedure and back. The queries below are run against both backends by
`tests/server/test_queries.py`, over a store holding the examples and a run of each kind. `$run_id`
is a run's id (`aip runs` lists them) and `$key` a key of the state.

### Revisions

Every published name with its revisions, newest first: which is pinned, which are retired, and
the bundle each one is.

```cypher
MATCH (n:Name)-[:HAS_REVISION]->(r:Revision)-[:OF]->(b:Bundle)-[:HOLDS]->(p:Procedure)
RETURN n.name AS name, r.revision AS revision, r.retired AS retired, n.pinned AS pinned,
       r.published_at AS published, b.bundle_id AS bundle, p.description AS description
ORDER BY name, r.number DESC
```

### Drafts

Bundles the store holds with no revision (a folder or a file that was run with a server
configured), and how many runs each has.

```cypher
MATCH (b:Bundle {draft: true})
OPTIONAL MATCH (run:Run)-[:OF]->(b)
RETURN b.name AS name, b.bundle_id AS bundle, b.stored_at AS stored, count(run) AS runs
ORDER BY stored DESC
```

### A run's path

One run, step by step: the step each entry ran, the loop passes it stood in, when, how long it
took, and where a route sent the run.

```cypher
MATCH (r:Run {run_id: $run_id})-[:HAS_ENTRY]->(e:Entry)-[:AT]->(s)
RETURN e.seq AS seq, s.name AS step, e.kind AS kind, e.loops AS passes, e.at AS at, e.seconds AS seconds, e.to AS went_to
ORDER BY seq
```

The same as a picture, the entries in order over the steps they ran:

```cypher
MATCH (r:Run {run_id: $run_id})-[:HAS_ENTRY]->(e:Entry)-[at:AT]->(s)
OPTIONAL MATCH (e)-[then:THEN]->(next:Entry)
RETURN e, at, s, then, next
```

### Where a run's time went

Per step of one run: how often it ran, its own time, the model's share of it, and how long the
run waited for an agent (which `seconds` does not count).

```cypher
MATCH (r:Run {run_id: $run_id})-[:HAS_ENTRY]->(e:Entry)
RETURN e.step AS step, e.kind AS kind, count(e) AS ran, sum(e.seconds) AS seconds,
       sum(e.model_seconds) AS model_seconds, sum(e.waited_seconds) AS waited_seconds
ORDER BY seconds DESC, step
```

### Routes whose check fired, and why

Every time a route's `Confidence_Below` sent a run elsewhere: the answer it read, the answer's
confidence against the bound (`below`), or `absent` when the answer carried none.

```cypher
MATCH (r:Run)-[:HAS_ENTRY]->(e:Entry {kind: 'Route'})-[:AT]->(route:Route)
WHERE e.check_fired = true
RETURN r.name AS procedure, route.name AS route, e.check_reason AS reason, e.read AS answer,
       e.check_confidence AS confidence, e.check_below AS bound, e.to AS went_to, r.run_id AS run
ORDER BY procedure, route, run
```

### What the model answered, and how sure it was

Every answer a decision model gave, least confident first, with the question it answered and
whether the call carried other passes with it.

```cypher
MATCH (r:Run)-[:HAS_ENTRY]->(e:Entry {kind: 'Decide'})-[:GAVE]->(a:Answer)-[:ANSWERS]->(q:Question)
RETURN r.name AS procedure, e.step AS step, q.name AS question, q.type AS type, a.value AS value,
       a.confidence AS confidence, e.model AS model, coalesce(e.batch_size, 1) AS passes_in_call, r.run_id AS run
ORDER BY confidence, procedure, step, question, run
```

### Aggregations that fail most often

Per aggregation: how often it was computed, how often it did not hold, and how many of the
answers it judged were turned by its bar (`With Confidence_Above`).

```cypher
MATCH (p:Procedure)-[:HAS_STEP]->(s:Aggregate)-[:AGGREGATES]->(g:Aggregation)<-[:ANSWERS]-(a:Answer)
RETURN p.name AS procedure, s.name AS step, g.name AS aggregation, g.mode AS mode, g.source AS over,
       count(a) AS computed, sum(CASE WHEN a.value = false THEN 1 ELSE 0 END) AS failed, sum(a.barred) AS barred
ORDER BY failed DESC, procedure, step, aggregation
```

### The lineage of a key

Where a key comes from, back through the steps that produced what its producer read: a path
over `PRODUCES` and `READ_BY`, in the procedure a run ran.

```cypher
MATCH (:Run {run_id: $run_id})-[:OF]->(:Bundle)-[:HOLDS]->(p:Procedure)-[:SUPPLIES]->(d:Data {name: $key})
MATCH lineage = (origin)-[:PRODUCES|READ_BY*1..6]->(d)
RETURN lineage
```

And what the run itself did there: each time a step that produces the key ran, and the keys it read.

```cypher
MATCH (r:Run {run_id: $run_id})-[:OF]->(:Bundle)-[:HOLDS]->(p:Procedure)-[:SUPPLIES]->(d:Data {name: $key})
MATCH (w)-[:PRODUCES]->(d), (e:Entry {run_id: $run_id})-[:AT]->(w)
OPTIONAL MATCH (up:Data)-[:READ_BY]->(w)
RETURN e.seq AS seq, w.name AS produced_by, e.loops AS passes, e.at AS at, collect(DISTINCT up.name) AS read
ORDER BY seq
```

### Who answered the tasks

Per agent task: which agent answered, in which session, and how long the run waited.

```cypher
MATCH (r:Run)-[:HAS_ENTRY]->(e:Entry {kind: 'Task_Agent'})
RETURN r.name AS procedure, e.step AS task, e.agent AS agent, e.session AS session, count(e) AS answered,
       avg(e.waited_seconds) AS mean_wait_seconds
ORDER BY procedure, task, agent, session
```

### Why loops ended

Per loop: how it exited (`until`, `items`, `times` or `cap`), where, and after how many passes.

```cypher
MATCH (r:Run)-[:HAS_ENTRY]->(e:Entry)-[:AT]->(l:Loop)
RETURN r.name AS procedure, l.name AS loop, e.exit AS reason, e.exit_where AS exit_at, count(e) AS times,
       avg(e.iterations) AS mean_passes
ORDER BY procedure, loop, reason
```

### Passes that ran because `Until` did not hold yet

The head of a `Loop` tests its `Until` before every pass; the first entry of a pass that ran says
what the test found.

```cypher
MATCH (r:Run {run_id: $run_id})-[:HAS_ENTRY]->(e:Entry)
WHERE e.until_holds = false
RETURN e.seq AS seq, e.step AS first_step, e.loops AS passes, e.until_where AS tested_at
ORDER BY seq
```

The server answers twelve questions of this kind by name, over the last N runs and filtered by
procedure, agent, session, user, and draft or published: `aip audit` lists them
(`confidence-fired`, `failing-aggregations`, `model-answers`, `failing-scripts`,
`untaken-branches`, `repeated-cycles`, `agent-routes`, `missing-fields`, `empty-results`,
`unused-data`, `cycles`, `lineage`; `src/aip/server/audit.py`, and `docs/server-design.md`, Audit,
for each one's rows). `aip audit lineage --key K` follows a key through a `For`'s collected list,
which the path above does not: `COLLECTS` points from the loop to the key each pass gathers. A
query of your own is stored with `aip audit --save NAME --cypher '...'` and run by name.

`aip export runs [name] --since DATE -o audit.rl` writes the runs that match and the procedures
they ran as one Relate file with exactly these nodes and edges, so every query on this page runs
on the file with no server: `relate query --database audit.rl "MATCH (r:Run) RETURN count(r)"`.
