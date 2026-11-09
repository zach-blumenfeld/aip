# Queries over a bundle

A compiled procedure is a graph (spec section 3, schema in `bundle.md`), and anything that opens
the `.rl` can ask it questions in Cypher: the Relate CLI on the file, a Neo4j Browser pointed at
`relate serve --bolt`, or the aip server's store, where every published revision sits beside its
runs. These are the queries worth knowing, each verified against the five examples. Swap the
procedure name; every node carries `bundle_id`, so one store holds many bundles without a clash.

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
`Until` or takes the next item; `AGAIN` is `Again <step>`, the one edge allowed to form a cycle
inside a body. A nested loop is entered only by `ENTERS`, so a walk on `NEXT` alone skips every
loop body; this pattern does not.

```cypher
MATCH (p:Procedure {name: 'dynamic_policy'})
MATCH flow = (p)-[:STARTS_AT]->()-[:NEXT|BRANCH|BELOW|ENTERS|CONTINUES|AGAIN*]->()
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

## Runs

A bundle holds no runs; the server's store does, beside the revisions (plan milestone S1 defines
that schema and adds its queries here: a run's path over the steps, where a route's check fired
and why, which answers a model gave and with what confidence, aggregations that fail most often,
the lineage of a key back through the steps that produced what it read).
