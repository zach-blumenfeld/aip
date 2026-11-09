# Cypher Syntax Reference

CypherLite implements the [openCypher](https://opencypher.org/) query language (3892 of 3892 pinned openCypher TCK scenarios pass under a strict harness, 0 skips — one CIP-271-superseded `toString()` outline is removed from the pin itself, ADR-0188, and four Cypher-25-superseded ORDER BY scenarios are re-pinned to the current behaviour, ADR-0472) plus a large slice of Neo4j's post-standard Cypher (GQL alignment), verified against an evaluation suite derived from ~200 Neo4j CIP documents. This page documents the openCypher base first, then the Neo4j / GQL extensions.

For the full language semantics behind the extensions, consult the
[Neo4j Cypher Manual](https://neo4j.com/docs/cypher-manual/current/introduction/)
and the [Cypher refcard](https://neo4j.com/docs/cypher-manual/current/cheat-sheet/) --
CypherLite tracks that surface via the CIP evaluation suite rather than
re-documenting every detail here.

## Identifiers

Unquoted identifiers -- variables, labels, relationship types, property keys,
map keys, aliases and parameter names -- may contain Unicode letters. Under
CYPHER 25 the rule is a BMP-only Unicode 13.0.0 predicate with no exceptions
([ADR-0182](../adr/0182-unicode-identifiers.md)):

- an **identifier start** has `General_Category` in {`Lu`, `Ll`, `Lt`, `Lm`,
  `Lo`, `Nl`, `Pc`} and is not `Pattern_Syntax`;
- an **identifier part** has `General_Category` in the start set plus
  {`Mn`, `Mc`, `Nd`, `Sc`} and is not `Pattern_Syntax`.

ASCII `[A-Za-z_]` / `[A-Za-z0-9_]` is always valid; supplementary-plane
characters (beyond U+FFFF) are never identifier characters; and the tables
are Unicode 13.0.0, not a newer runtime's. Identifiers are compared
code-point-exact: there is no normalization, no case folding and no keyword
lookalike -- `ſKIP` (U+017F) is an ordinary identifier, not the `SKIP`
keyword.

```cypher
CREATE (a:Ärzte {Größe: 'Dr. Müller'})-[:BESCHÄFTIGT]->(b:Praxis {Größe: 'Praxis Ünver'});
MATCH (a:Ärzte)-[:BESCHÄFTIGT]->(b:Praxis)
WHERE a.Größe = $größe
RETURN labels(a) AS labels, b.Größe AS größe;
```

Anything else -- a supplementary-plane character or a name with punctuation --
still goes in backticks: `` `café` ``. A reserved word needs no backticks
where it is read as a symbolic name: aliases after `AS`/`YIELD`, variable
references, binding variables (node, relationship and path patterns,
`FOREACH`, comprehensions, quantifiers, `reduce`, `CALL` import) and map
keys accept any keyword spelling unquoted, kept as written
([ADR-0191](../adr/0191-keywords-as-symbolic-names.md)). It does need them
where an existing meaning wins: the literals `TRUE`, `FALSE`, `NULL`, `INF`,
`INFINITY` and `NAN`; a prefix `NOT`; `DISTINCT`/`ALL` directly after
`RETURN`/`WITH` or inside `fn(`; the `CASE`/`COUNT`/`EXISTS`/`COLLECT`
forms; the inline element predicate (`(WHERE 1 = 1)`); and `IS NOT`
negation (`n IS Not`, ADR-0169). Non-ASCII names are always re-emitted
backtick-quoted by the formatter.

## Reading clauses

### MATCH

Find patterns in the graph:

```cypher
MATCH (n:Label {prop: 'value'})
RETURN n;
```

#### Node patterns

```cypher
(n)                      -- any node
(n:Person)               -- node with label
(n:Person:Employee)      -- multiple labels
(n {name: 'Alice'})      -- with properties
(n:Person {name: 'Alice'}) -- label + properties
```

#### Relationship patterns

```cypher
(a)-[r]->(b)             -- directed right
(a)<-[r]-(b)             -- directed left
(a)-[r]-(b)              -- undirected
(a)-[:KNOWS]->(b)        -- with type
(a)-[:KNOWS|LIKES]->(b)  -- multiple types
(a)-[r:KNOWS {since: 2020}]->(b)  -- with properties
```

#### Variable-length paths

```cypher
(a)-[*1..3]->(b)         -- 1 to 3 hops
(a)-[:KNOWS*2]->(b)      -- exactly 2 hops
(a)-[*..5]->(b)          -- up to 5 hops
```

An explicit upper bound above the traversal-depth admission limit
(500 hops by default) is rejected at admission with
`TraversalDepthExceeded`, a safety limit protecting against a stack
overflow rather than a database limit. Raise it with
`--max-traversal-depth N` (1 through 2000) or
`CYPHERLITE_MAX_TRAVERSAL_DEPTH`; an unbounded upper bound (`*`, `*1..`)
is exempt because a classic walk already stops at 32 hops. See
[ADR-0466](https://github.com/neo4j-labs/cypherlite/blob/main/docs/adr/0466-traversal-depth-admission-limit.md)
and [Limitations](../limitations.md#traversal-depth).

#### Named paths

Bind a matched path to a variable:

```cypher
MATCH p = (a:Person)-[:KNOWS]->(b:Person)
RETURN p, nodes(p), relationships(p), length(p);
```

Named paths work with variable-length patterns and path functions like `nodes()`, `relationships()`, and `length()`.

### OPTIONAL MATCH

Like `MATCH`, but returns `null` for unmatched patterns instead of filtering the row:

```cypher
MATCH (p:Person)
OPTIONAL MATCH (p)-[:LIVES_IN]->(c:City)
RETURN p.name, c.name;
```

### WHERE

Filter results:

```cypher
MATCH (p:Person)
WHERE p.age > 25 AND p.city = 'NYC'
RETURN p.name;
```

#### Comparison operators

| Operator | Description |
|----------|-------------|
| `=` | Equal |
| `<>` | Not equal |
| `<` | Less than |
| `>` | Greater than |
| `<=` | Less than or equal |
| `>=` | Greater than or equal |

#### Chronological comparisons (preview)

Cypher 25's four temporal comparison operators sit behind the
`CYPHERLITE_PREVIEW=chronological-comparisons` preview gate (ADR-0371 /
ADR-0467; Neo4j's `internal.cypher.chronological_comparisons_enabled`):

| Operator | Meaning |
|----------|---------|
| `IS [NOT] BEFORE` | left instant strictly precedes the right |
| `IS [NOT] AFTER` | left instant strictly follows the right |
| `IS [NOT] SAME INSTANT` | both denote the same UTC instant |
| `IS [NOT] SAME REPRESENTATION` | equal under `=` (local clock plus zone identity) |

```cypher
RETURN datetime('2020-01-01T12:00+01:00') IS SAME INSTANT datetime('2020-01-01T11:00Z');
```

The four words stay ordinary identifiers everywhere else. Without the
opt-in a statement using one fails closed with
`preview feature 'chronological-comparisons' is not enabled: set
CYPHERLITE_PREVIEW=chronological-comparisons`.

#### Boolean operators

`AND`, `OR`, `NOT`, `XOR`

#### String predicates

```cypher
WHERE p.name STARTS WITH 'A'
WHERE p.name ENDS WITH 'son'
WHERE p.name CONTAINS 'lic'
```

#### Null checks

```cypher
WHERE p.age IS NULL
WHERE p.age IS NOT NULL
```

#### List membership

```cypher
WHERE p.age IN [25, 30, 35]
```

### SEARCH

Restrict a `MATCH` to the entities of a vector or full-text index (Neo4j's
`SEARCH` clause, CIP-224 / CIP-225). The query is `FOR <expr>`, the `LIMIT`
is mandatory, and an optional `SCORE AS <var>` exposes the relevance score:

```cypher
-- Vector (ANN) search: nearest neighbours of a query vector
MATCH (n:Doc)
SEARCH n IN (VECTOR INDEX doc_embed FOR $queryVector LIMIT 10)
RETURN n.title, score AS relevance;

-- Full-text search: term match over the indexed string properties
MATCH (n:Doc)
SEARCH n IN (FULLTEXT INDEX doc_text FOR 'graph database' LIMIT 10)
SCORE AS relevance
RETURN n.title, relevance;
```

Rules, matching Neo4j:

- the binding variable (the `n` after `SEARCH`) must be declared by the same
  `MATCH` pattern the SEARCH annotates, and the search query cannot reference it
- the index must exist and be of the matching kind (a full-text search over a
  vector index raises `WrongIndexType`)
- `WHERE` inside the search is **vector-search only**; it may reference only the
  index's `WITH [...]`-declared properties, with simple comparisons joined by
  `AND`. A full-text search with `WHERE` is rejected
- `SKIP`/`OFFSET` is **full-text only**; on a vector search it is rejected
- `WITH ANALYZER <expr>` is accepted on full-text searches (analyzers are not
  differentiated: CypherLite tokenizes lowercase alphanumeric terms)
- the searched `MATCH` pattern is CIP-225 Rule 0's single node or single-hop
  relationship, binding one variable, with predicates only on it. The
  `CYPHERLITE_PREVIEW=complex-search-patterns` preview gate (ADR-0371 /
  ADR-0467; Neo4j's
  `enable_extra_semantic_features=VectorSearchWithComplexPattern`) lifts that
  shape restriction, admitting multi-component, multi-hop, variable-length,
  quantified, selected and multi-variable patterns; without the opt-in the
  Rule 0 rejections stay (`SearchClauseTooComplexPattern`,
  `SearchClauseMultipleBoundVariables`, `SearchClauseInvalidPredicates`)

#### Hybrid search (COMBINE, preview)

Two or more index searches can be fused into a single ranking with weighted
reciprocal rank fusion (Neo4j's CIP-278 `COMBINE`, behind the
`CYPHERLITE_PREVIEW=hybrid-search` preview gate, ADR-0371 / ADR-0379):

```cypher
MATCH (n:Movie)
SEARCH n IN (
  COMBINE (
    VECTOR INDEX plot_embed FOR $queryVector LIMIT 10 WEIGHT 0.7,
    FULLTEXT INDEX plot_text FOR $queryText LIMIT 10 WEIGHT 0.3
  ) USING WRRF WITH CONSTANT 60
  LIMIT 5
) SCORE AS score
RETURN n.title, score;
```

Rules:

- the combined body needs **two or more** weighted sources (fewer is a syntax
  error); a source may itself be a nested `COMBINE`, with its own `WEIGHT`
- each source is a full index specification: `FOR`, optional `WITH ANALYZER` /
  `WHERE` / `SKIP`-`OFFSET`, and a mandatory `LIMIT`, exactly as at the top
  level; every source must index the same entity kind (node/relationship) as
  the `SEARCH` binding variable
- `WEIGHT <expr>` (default 1) and `WITH CONSTANT <expr>` (default 60) must
  evaluate to INTEGER NOT NULL or FLOAT NOT NULL, at least 0 and at most Java's
  `Integer.MAX_VALUE` (2147483647); neither may reference the search binding
  variable
- the fused score is the sum over the sources of `weight / (constant + rank + 1)`
  (0-based rank within each source's own ranked, limited result list); an
  entity missing from a source gets nothing from that source. Results are
  ordered by fused score descending, ties on entity id ascending
  (implementation-dependent tie-break, CLG-102), then the combined `LIMIT`
  keeps the n highest

## Writing clauses

### CREATE

Create nodes and relationships:

```cypher
CREATE (n:Person {name: 'Alice'});
CREATE (a)-[:KNOWS {since: 2020}]->(b);
CREATE (a:Person {name: 'Alice'})-[:KNOWS]->(b:Person {name: 'Bob'});
```

### MERGE

Match or create. Ensures a pattern exists:

```cypher
MERGE (p:Person {name: 'Alice'})
ON CREATE SET p.created = timestamp()
ON MATCH SET p.lastSeen = timestamp();
```

### SET

Update properties and labels:

```cypher
SET n.name = 'Alice'          -- set a property
SET n.age = 31, n.city = 'LA' -- set multiple
SET n:Employee                 -- add a label
SET n = {name: 'Alice'}        -- replace all properties
SET n += {age: 31}             -- merge properties
```

### REMOVE

Remove properties and labels:

```cypher
REMOVE n.age          -- remove property
REMOVE n:Employee     -- remove label
```

### DELETE

Delete nodes and relationships:

```cypher
DELETE n               -- delete a node (must have no relationships)
DETACH DELETE n        -- delete node and all its relationships
```

## Composing clauses

### RETURN

Project results:

```cypher
RETURN n.name, n.age
RETURN n.name AS name
RETURN DISTINCT n.city
RETURN *                 -- all variables
```

#### ORDER BY

```cypher
RETURN n.name ORDER BY n.age DESC
```

#### SKIP and LIMIT

```cypher
RETURN n.name SKIP 5 LIMIT 10
```

`SKIP` and `LIMIT` take a non-negative integer
([ADR-0175](../adr/0175-list-and-string-form-conversions.md)). A float
literal fails at parse time (`SKIP 1.0` → error
`InvalidArgumentType: SKIP requires an integer value`), and any float
value at runtime — `1.0`, NaN and ±Infinity included — fails with
`InvalidArgumentType: SKIP/LIMIT must be an integer`; there is no
truncation:

```cypher
UNWIND [1,2,3] AS x RETURN x SKIP head([1.0, 'x'])
-- error: type error: InvalidArgumentType: SKIP/LIMIT must be an integer
```

#### GROUP BY

Explicit grouping keys (CIP-236): the keys replace the inference from the
non-aggregating items; `GROUP BY ()` aggregates globally and `GROUP BY ALL`
takes every non-aggregating item:

```cypher
RETURN n.city AS city, count(*) AS cnt GROUP BY city
RETURN count(*) AS cnt GROUP BY ()
```

### WITH

Pipe results between query parts:

```cypher
MATCH (p:Person)
WITH p.city AS city, count(*) AS cnt
WHERE cnt > 5
RETURN city, cnt;
```

Supports `DISTINCT`, `GROUP BY` (CIP-236, between the items and the
order/page clauses), `ORDER BY`, `SKIP`, `LIMIT`, `WHERE`.

### UNWIND

Expand a list into rows:

```cypher
UNWIND [1, 2, 3] AS x
RETURN x;
```

#### FOR (preview)

The GQL-compliant successor spelling of UNWIND, with the binding variable
*before* the expression (CIP-250, GQ10, behind the
`CYPHERLITE_PREVIEW=gql-for` preview gate, ADR-0371):

```cypher
FOR x IN [1, 2, 3]
RETURN x;
```

Rules:

- valid wherever `UNWIND` is valid (after `MATCH`/`WITH`, inside `CALL`
  subqueries and `FOREACH` bodies, before `RETURN`); `UNWIND` is not
  deprecated — the two spellings coexist and produce identical results
- per input row: a list source produces one row per element, `null`
  produces no rows, and a non-list value is coerced to a singleton list
  (one row), exactly as `UNWIND` behaves
- the clause is normalized onto the existing `UNWIND` machinery: the
  query plan shows the same `Unwind` operator, and no new plan operator
  exists
- while the gate is off, a `FOR x IN ...` clause fails with
  `preview feature 'gql-for' is not enabled: set CYPHERLITE_PREVIEW=gql-for`
- the binding variable follows the same scoping rules as the `UNWIND`
  alias (any keyword spelling works unquoted, ADR-0191)
- malformed shapes are parse errors: a missing `IN`, a missing binding
  variable, and the UNWIND-shaped `FOR <expr> AS <var>` (the variable must
  precede the expression)
- GQ11 (`WITH ORDINALITY`), GQ24 (`WITH OFFSET`) and GQ23 (binding table
  references) are out of scope, reserved for future CIPs

### UNION / UNION ALL

Combine results from multiple queries:

```cypher
MATCH (p:Person) RETURN p.name
UNION
MATCH (c:Company) RETURN c.name;
```

`UNION` removes duplicates. `UNION ALL` keeps all rows.

### FOREACH

Iterate over a list and apply update clauses:

```cypher
FOREACH (name IN ['Alice', 'Bob', 'Charlie'] |
  CREATE (:Person {name: name})
);
```

### LOAD CSV

Import CSV data:

```cypher
LOAD CSV WITH HEADERS FROM 'file.csv' AS row
CREATE (:Person {name: row.name});

LOAD CSV FROM 'file.csv' AS row
RETURN row;
```

## Schema clauses

### CREATE INDEX

```cypher
CREATE INDEX idx_name FOR (n:Label) ON (n.property);
CREATE INDEX idx_name IF NOT EXISTS FOR (n:Label) ON (n.property);
CREATE VECTOR INDEX idx FOR (n:Label) ON (n.embedding)
  OPTIONS {indexConfig: {'vector.dimensions': 384, 'vector.similarity_function': 'cosine'}};
CREATE VECTOR INDEX idx FOR (n:Label) ON (n.embedding) WITH [n.category];
CREATE FULLTEXT INDEX idx FOR (n:Label) ON EACH [n.title, n.body];
CREATE POINT INDEX idx FOR (n:Label) ON (n.location);
```

The `indexConfig` keys are dotted (`vector.dimensions`,
`vector.similarity_function`) and must be single-quoted — a map literal
rejects an unquoted dotted key (`{vector.dimensions: 384}` is a parse
error). A relationship vector index targets the relationship pattern
form: `CREATE VECTOR INDEX idx FOR ()-[r:TYPE]-() ON (r.embedding)`.

`WITH [...]` declares the additional properties a vector search may filter
on (see SEARCH). `CREATE FULLTEXT INDEX` indexes one or more string
properties for full-text search.

### DROP INDEX

```cypher
DROP INDEX idx_name;
DROP INDEX idx_name IF EXISTS;
```

### CREATE CONSTRAINT

```cypher
CREATE CONSTRAINT name FOR (n:Label) REQUIRE n.prop IS UNIQUE;
CREATE CONSTRAINT name FOR (n:Label) REQUIRE n.prop IS NOT NULL;
CREATE CONSTRAINT name FOR (n:Label) REQUIRE (n.a, n.b) IS NODE KEY;
```

### DROP CONSTRAINT

```cypher
DROP CONSTRAINT name;
DROP CONSTRAINT name IF EXISTS;
```

## Query prefixes

### EXPLAIN

Show the query execution plan without running the query. Nothing is
executed — writes, procedures, and `LOAD CSV` are only planned. The result
is a single `plan` column with one row per plan line (the clause pipeline;
`UNION` parts and `NEXT` stages are labelled):

```cypher
EXPLAIN MATCH (p:Person)-[:KNOWS]->(f) RETURN p.name, f.name;
```

```text
+---------------------------------------------------------------+
| plan                                                          |
+---------------------------------------------------------------+
| "Query: MATCH (p:Person)-[:KNOWS]->(f) RETURN p.name, f.name" |
| "Plan:"                                                       |
| "1. MATCH (1 patterns)"                                       |
| "2. RETURN (2 items)"                                         |
+---------------------------------------------------------------+
```

### PROFILE

Execute the query and show profiling statistics (execution time, rows returned, etc.).
The result is the query's own rows plus four profiling columns:
`_profile_plan` (the plan rendered on one line), `_profile_time`
(wall-clock execution time), `_profile_rows` (rows returned), and
`_profile_mutations` (a summary of graph changes, `none` for a read):

```cypher
PROFILE MATCH (p:Person) RETURN p.name;
```

With two `Person` nodes present (`Alice`, `Bob`):

```text
+---------+-----------------------------------------------------------------------------------------------+---------------+---------------+--------------------+
| p.name  | _profile_plan                                                                                 | _profile_time | _profile_rows | _profile_mutations |
+---------+-----------------------------------------------------------------------------------------------+---------------+---------------+--------------------+
| "Alice" | "Query: MATCH (p:Person) RETURN p.name | Plan: | 1. MATCH (1 patterns) | 2. RETURN (1 items)" | "0.146ms"     | 2             | "none"             |
| "Bob"   | "Query: MATCH (p:Person) RETURN p.name | Plan: | 1. MATCH (1 patterns) | 2. RETURN (1 items)" | "0.146ms"     | 2             | "none"             |
+---------+-----------------------------------------------------------------------------------------------+---------------+---------------+--------------------+
```

When the query returns no rows (for example a write-only statement such as
`PROFILE CREATE (:Person {name: 'Alice'})`), the result still carries one
row with the four profiling columns — `_profile_mutations` then reports
what the statement changed (e.g. `created 1 node(s), set 1 properties,
added 1 labels`).

## Expressions

### Literals

| Type | Examples |
|------|----------|
| Integer | `42`, `-7`, `0` |
| Float | `3.14`, `-0.5` |
| String | `'hello'`, `"world"` |
| Boolean | `true`, `false` |
| Null | `null` |
| List | `[1, 2, 3]` |
| Map | `{name: 'Alice', age: 30}` |

Interpolated string literals (CIP-261) embed `{expressions}` inline;
`\{`/`\}` escape literal braces, and a null embed makes the whole string
null:

```cypher
RETURN s'Hello {name}!';          -- with name = 'World': 'Hello World!'
```

### Arithmetic

`+`, `-`, `*`, `/`, `%`

The `+` operator also concatenates strings and lists.

Integer `+`, `-`, `*` and unary minus raise `integer out of range` on
overflow, as do `/ 0` and `% 0`. Two cases at the INTEGER limits follow
Neo4j's plain Java operators instead and do **not** raise
([ADR-0175](../adr/0175-list-and-string-form-conversions.md)):
`(-9223372036854775807 - 1) / -1` wraps to `-9223372036854775808` and
`(-9223372036854775807 - 1) % -1` is `0` — a deliberate replication of a
Neo4j quirk (a silent, mathematically wrong wrap) for cross-engine
portability. Float division and modulo keep IEEE semantics (`1.0 / 0` →
Infinity, `1.0 % 0.0` → NaN).

### CASE expressions

```cypher
-- Simple form
CASE n.type
  WHEN 'A' THEN 'Alpha'
  WHEN 'B' THEN 'Beta'
  ELSE 'Unknown'
END

-- Generic form
CASE
  WHEN n.age < 18 THEN 'minor'
  WHEN n.age >= 65 THEN 'senior'
  ELSE 'adult'
END
```

### CALL subqueries

Execute a subquery for each input row:

```cypher
MATCH (p:Person)
CALL {
  WITH p
  MATCH (p)-[:KNOWS]->(friend)
  RETURN count(friend) AS friendCount
}
RETURN p.name, friendCount;
```

### CALL procedures

Call built-in procedures:

```cypher
CALL db.index.vector.queryNodes('embedding_idx', 10, $queryVector)
YIELD node, score
RETURN node.title, score;
```

`db.index.fulltext.queryNodes(indexName, query)` and
`db.index.fulltext.queryRelationships(indexName, query)` query a FULLTEXT
index, yielding `(node, score)` or `(relationship, score)` respectively.
`queryNodes` matches the labels of a node index, `queryRelationships` the
types of a relationship index; both take the index name and the query
string, a single token optionally written `property:token`. The `SEARCH`
clause (see SEARCH) is the current-search replacement.

```cypher
CREATE FULLTEXT INDEX relNotes FOR ()-[r:RELATED_TO]-() ON EACH [r.note];
CALL db.index.fulltext.queryRelationships('relNotes', 'lamp')
YIELD relationship, score
RETURN relationship.note, score;
```

The `db.ontology.*` procedures (ADR-0121, ADR-0226, ADR-0227, ADR-0364 —
Neo4j's CIP-287 surface) manage the store's single ontology document. They
require `CYPHERLITE_PREVIEW=ontology` (ADR-0378; ADR-0371's opt-in): with it
off, every call fails with `SemanticError: preview feature 'ontology' is not
enabled: set CYPHERLITE_PREVIEW=ontology` and `SHOW PROCEDURES` omits them;
the stored document and the store's open/replay path are unaffected. They
act on the session or `USE`-target database, which must be `neo4j`:

```cypher
CALL db.ontology.set($ontology);        -- validate + store a JSON or YAML document (implicit transactions only)
CALL db.ontology.get() YIELD ontology;  -- the stored document, 'yaml' by default, 'json' on request, null when unset
CALL db.ontology.apply();               -- set the current graph type from the stored ontology (fails on violating data)
CALL db.ontology.drop();                -- remove the stored ontology (succeeds when unset)
```

`set` accepts the published Ontology Graph Spec 1.1.0 document shape
(ADR-0364, raised by ADR-0487)
under the exact `schema` URI
`https://neo4j.com/docs/ontology-graph-spec/1.1.0/schema.json`: `version` is
a string, property existence is `must_exist`, and `constraints` is an
id-keyed map with `type: EXISTS | KEY | UNIQUE | PROPERTY_TYPE`. A pre-bump
document (including the 1.0.0 main dialect) fails at `set`; there is no
dual gate or migration.

`set` and `drop` run only in implicit (auto-commit) transactions, and a
statement calling them may not write anything else. `get` reads the calling
transaction's captured document; `apply` may run in explicit transactions.
The `system_ontologies` namespace is listed by `SHOW DATABASES` but not
queryable (ADR-0229): every statement routed to it — `USE
system_ontologies MATCH (n) RETURN n` included, `EXPLAIN`-wrapped included —
fails with 42N17 `This database is not queryable. Use the db.ontology.*
procedures on the user database 'neo4j' instead.`; only the ADR-0116 §2
database-administration commands still run from there, and the stored
document is reachable only through the procedures. See the
[ontology procedures reference](ontology-procedures.md) for the full
signatures, modes, transaction and namespace rules, storage behavior and
runnable examples.

`db.schema.nodeTypeProperties()` infers the property schema of the stored node
categories by scanning the data (ADR-0112). `nodeType` is the full sorted label
set (`:A:B`), `propertyTypes` are `valueType()` names, and `mandatory` is true
when the key is present on every node of the category. A category with no
properties yields one row with `propertyName: null` and `propertyTypes: []`.
Syntax: `CALL db.schema.nodeTypeProperties() YIELD ... RETURN ...`.

| Name | Type |
|------|------|
| `nodeType` | `STRING` |
| `nodeLabels` | `LIST<STRING>` |
| `propertyName` | `STRING` |
| `propertyTypes` | `LIST<STRING>` |
| `mandatory` | `BOOLEAN` |

```cypher
CREATE (:Person {name: 'Alice', age: 30});
CALL db.schema.nodeTypeProperties()
YIELD nodeType, nodeLabels, propertyName, propertyTypes, mandatory
RETURN nodeType, propertyName, propertyTypes, mandatory;
```

`db.schema.relTypeProperties()` is the same inference for stored relationship
categories. `relType` is the single type rendered as `[:TYPE]`, and the
property-less row rule is the same.

| Name | Type |
|------|------|
| `relType` | `STRING` |
| `propertyName` | `STRING` |
| `propertyTypes` | `LIST<STRING>` |
| `mandatory` | `BOOLEAN` |

```cypher
CREATE (:Person {name: 'Alice'})-[:KNOWS {since: 2020}]->(:Person {name: 'Bob'});
CALL db.schema.relTypeProperties()
YIELD relType, propertyName, propertyTypes, mandatory
RETURN relType, propertyName, propertyTypes, mandatory;
```

`db.schema.visualization()` renders the inferred schema as a graph (LABS-150):
one row whose `nodes` list holds one virtual node per stored label (Neo4j's
`{name, indexes, constraints}` property shape) and whose `relationships` list
holds one virtual relationship per distinct `(startLabel, relType, endLabel)`
triple, with multi-label endpoints expanded over every label combination.
Each virtual node's `indexes` is a sorted list of property names, one per
non-constraint-backing catalog index on that label (a uniqueness or key
constraint's backing index is excluded: Neo4j lists it only as `ownedIndex`
on the constraint string, a field cypherlite omits), and its `constraints`
is a name-sorted list of
`Constraint( name='<name>', type='<TYPE>', schema=(:<Label> {<props>}) )`
strings, one per node constraint on that label, with `<TYPE>` in Neo4j's
space style (`'NODE PROPERTY UNIQUENESS'`, `'NODE KEY'`,
`'NODE PROPERTY EXISTENCE'`, `'NODE PROPERTY TYPE'`,
`'NODE LABEL EXISTENCE'`). CypherLite has no schema-rule ids, so the strings
carry no `id`/`ownedIndex` fields, and relationship constraints appear on no
virtual node. Virtual entities carry negative ids and resolve through
`startNode()`/`endNode()`; each virtual relationship carries one property,
`name`, a `STRING` equal to its relationship type (Neo4j's shape; ADR-0187),
and the empty graph yields zero rows.

| Name | Type |
|------|------|
| `nodes` | `LIST<NODE>` |
| `relationships` | `LIST<RELATIONSHIP>` |

The optional `options` argument is a `BOOLEAN` (Cypher 25): the omitted
argument and `true` (and the legacy options `MAP`, whose contents are
ignored) report the synthesized ("ghost") relationship combinations of a
type; `false` reports only the label combinations that exist in the data;
`null` selects nothing (zero rows); any other type is an
`InvalidArgumentType` error.

```cypher
CREATE (:Person {name: 'Alice'})-[:KNOWS {since: 2020}]->(:Person {name: 'Bob'});
CALL db.schema.visualization()
YIELD nodes, relationships
RETURN nodes, relationships;
```

```cypher
-- only relationships that exist in the data
CALL db.schema.visualization(false)
YIELD relationships
RETURN size(relationships) AS relationshipCount;
```

These procedures report no counts; use plain Cypher
(`MATCH (n:Label) RETURN count(n)`) for aggregates.

### EXISTS subquery

Test if a pattern exists as a boolean expression:

```cypher
MATCH (p:Person)
WHERE EXISTS {
  MATCH (p)-[:KNOWS]->(:Person {name: 'Alice'})
}
RETURN p.name;
```

### List comprehensions

Filter and transform lists:

```cypher
RETURN [x IN range(1, 10) WHERE x % 2 = 0 | x * x] AS squares;
-- Returns [4, 16, 36, 64, 100]
```

### Map comprehensions and map addition

Map comprehensions (CIP-272) project a list or map into a map --
`{item IN list | keyExpr : valueExpr}` and `{k : v IN map | keyExpr : valueExpr}`:

```cypher
RETURN {i IN [1, 2] | 'k' + toString(i): i};   -- {k1: 1, k2: 2}
RETURN {k : v IN {a: 1, b: 2} | k: v * 10};    -- {a: 10, b: 20}
```

The `+` operator on maps (CIP-273) merges them with last-write-wins on
duplicate keys: `RETURN {a: 1} + {a: 2, b: 3}` → `{a: 2, b: 3}`.

### reduce

Reduce a list to a single value:

```cypher
RETURN reduce(total = 0, x IN [1, 2, 3, 4] | total + x) AS sum;
-- Returns 10
```

### shortestPath / allShortestPaths

Find shortest paths between nodes:

```cypher
MATCH (a:Person {name: 'Alice'}), (b:Person {name: 'Dave'})
RETURN shortestPath((a)-[*..10]->(b)) AS path;

MATCH (a:Person {name: 'Alice'}), (b:Person {name: 'Dave'})
RETURN allShortestPaths((a)-[*..10]->(b)) AS paths;
```

As a `MATCH` pattern, `shortestPath` returns one row for each connected
(start, end) pair and `allShortestPaths` one row per shortest path; a
pair with no path gives no row. In the expression form above, each
input row gets one value (`null` when unreachable). A classic (non-shortest)
`MATCH` walk caps an unbounded `[*]` at 32 hops; the
`MATCH p = shortestPath(...)` route explores without a hop cap (bounded by
the relationship count). The expression form stops at 32 hops.

```cypher
MATCH (a:Person {name: 'Alice'}), (b:Person {name: 'Dave'})
MATCH p = shortestPath((a)-[:KNOWS*]-(b))
RETURN p, length(p) AS hops;
```

### Parameters

Use `$name` to reference query parameters:

```cypher
MATCH (p:Person {name: $name}) RETURN p.age;
```

## Neo4j / GQL extensions

The following are implemented beyond standard openCypher, matching Neo4j's Cypher 25 / GQL-aligned behavior. Where CypherLite is an embedded single-process engine, some server-oriented commands are adapted (see notes).

### Label expressions

Labels and relationship types accept GQL boolean expressions — `&` (and), `|` (or), `!` (not), `%` (wildcard), and parentheses. The `IS` keyword is an alternative to the leading colon.

```cypher
MATCH (n:Person&Employee)         RETURN n;   -- has both labels
MATCH (n:Admin|Moderator)         RETURN n;   -- either label
MATCH (n:Person&!Bot)             RETURN n;   -- Person but not Bot
MATCH (n IS Person)               RETURN n;   -- IS form
RETURN labelExpression;
MATCH ()-[r:FOLLOWS|BLOCKS]->()   RETURN r;   -- relationship type expression
```

The `LABELED` predicate tests labels in expression position:

```cypher
MATCH (n) WHERE n IS LABELED Person&Employee RETURN n;
```

Keywords also work unquoted as label and relationship-type names, as in Neo4j (ADR-0169): in patterns, label expressions, `IS`, `n:Label` predicates, and `SET`/`REMOVE`. `:Order` and `` :`Order` `` name the same label. A keyword directly after `:`, `IS`, `|`, `&` or `!` is always read as a label or type name, even when it starts the next line (`WHERE n:` followed by `OPTIONAL MATCH …` makes `OPTIONAL` the label), so when label text is spliced into a query, pass it through [dynamic labels](#dynamic-labels-types-and-properties) `$(...)` instead.

```cypher
CREATE (:Order {id: 1})-[:ORDER]->(:Product {name: 'Chai'});
MATCH (o:Order)-[:ORDER]->(x) RETURN o.id, x.name;
MATCH (n) WHERE n IS Order SET n:Where RETURN labels(n);
MATCH (n:Product|Order) RETURN count(n);
```

Beyond labels and types, keywords are accepted unquoted as symbolic names
in four position groups, as in Neo4j
([ADR-0191](../adr/0191-keywords-as-symbolic-names.md)): aliases after
`AS`/`YIELD`, variable references, binding variables (node, relationship and
path patterns, `FOREACH`, comprehensions, quantifiers, `reduce`, and the
`CALL` import list) and map keys (map literals, map projections and pattern
property maps), each kept exactly as written. Where an existing meaning wins
the keyword still needs backticks: the literals `TRUE`, `FALSE`, `NULL`,
`INF`, `INFINITY` and `NAN`; a prefix `NOT`; `DISTINCT`/`ALL` directly after
`RETURN`/`WITH` or inside `fn(`; the `CASE`/`COUNT`/`EXISTS`/`COLLECT`
forms; and the inline element predicate (`(WHERE 1 = 1)`). A label named
`Not` in a `WHERE n IS` predicate also needs backticks, because `IS NOT` is
a negation (ADR-0169):

```cypher
MATCH (order:Order) RETURN order.id;
RETURN {order: 1} AS m;
WITH 1 AS a RETURN a AS as;
MATCH (n) WHERE n IS `Not` RETURN n;
```

### Inline pattern predicates

A `WHERE` may appear inside a node or relationship pattern:

```cypher
MATCH (n:Person WHERE n.age > 30)-[r:KNOWS WHERE r.since < 2020]->(m)
RETURN n, m;
```

### Quantified path patterns (QPP)

Repeat a parenthesized path pattern with a quantifier (`{n,m}`, `{n,}`, `*`, `+`), binding group variables:

```cypher
MATCH (start:Stop)((a)-[:NEXT]->(b)){1,5}(end:Stop)
RETURN end.name;
```

### Path modes and selectors

```cypher
MATCH p = TRAIL (a)-[:R]->*(b) RETURN p;          -- path mode: TRAIL / ACYCLIC / WALK
MATCH p = ANY SHORTEST (a)-[:R]->+(b) RETURN p;   -- selector: ANY / ALL / SHORTEST k
MATCH p = SHORTEST 3 (a)-[:R]->+(b) RETURN p;
```

### Dynamic labels, types, and properties

Use `$(expr)` (or `$all(expr)`) where a static label/type goes, and `n[keyExpr]` for a dynamic property key. The expression must evaluate to a string or list of strings.

```cypher
CREATE (n:$(['Person','Admin']))            -- dynamic labels from a list
MATCH (n:$($labelParam))          RETURN n; -- from a parameter
CREATE ()-[r:$('KNOWS')]->()                -- dynamic relationship type
SET n:$(labelVar), n[$keyVar] = 42          -- dynamic label + property key
MATCH (n) RETURN n[$key] AS value;
```

### Type predicates and value types

```cypher
RETURN 5 IS :: INTEGER AS a;             -- true
RETURN 'x' IS NOT :: INTEGER AS b;       -- true
RETURN valueType([1, 2.0]) AS t;         -- "LIST<INTEGER NOT NULL | FLOAT NOT NULL> NOT NULL"
```

Property **type** constraints:

```cypher
CREATE CONSTRAINT FOR (n:Person) REQUIRE n.age IS :: INTEGER;
```

### New clauses

```cypher
-- LET: bind variables without a full WITH
MATCH (n:Person) LET adult = n.age >= 18 RETURN n.name, adult;

-- FILTER: filter rows (WHERE as a standalone clause)
UNWIND [1,2,3,4] AS x FILTER x % 2 = 0 RETURN x;

-- NEXT: chain statements linearly
MATCH (n:Person) RETURN n.name AS name NEXT RETURN upper(name) AS shout;

-- Conditional clause
MATCH (n:Person) WHEN n.age >= 18 THEN RETURN 'adult' ELSE RETURN 'minor';

-- FINISH: run for side effects, return nothing
MATCH (n:Temp) DELETE n FINISH;

-- INSERT (GQL alias for CREATE)
INSERT (:Person {name: 'Alice'});

-- UNION DISTINCT (explicit), RETURN ALL, NODETACH DELETE
MATCH (n) RETURN n.name UNION DISTINCT MATCH (m) RETURN m.name;
MATCH (n) NODETACH DELETE n;
```

### Subquery expressions

```cypher
RETURN COUNT { (n:Person)-[:KNOWS]->() } AS knownCount;
RETURN COLLECT { MATCH (n:Person) RETURN n.name } AS names;
MATCH (n) WHERE EXISTS { (n)-[:OWNS]->(:Car) } RETURN n;
```

### CALL scope clause & CALL IN TRANSACTIONS

```cypher
-- Variable-scope CALL: import outer variables explicitly
MATCH (n:Person) CALL (n) { RETURN n.age * 2 AS doubled } RETURN doubled;

-- Batched transactions with status and error handling
UNWIND range(1, 1000) AS i
CALL (i) { CREATE (:Row {v: i}) } IN TRANSACTIONS OF 100 ROWS
  REPORT STATUS AS s
  ON ERROR CONTINUE
RETURN s.committed;

-- The legacy importing-WITH form (no scope-clause parens) batches too —
-- the standard bulk-delete idiom:
MATCH (n) CALL { WITH n DETACH DELETE n } IN TRANSACTIONS OF 100 ROWS;

-- A concluding CALL { } IN TRANSACTIONS whose body ends in RETURN
-- returns the body's rows:
CALL { MATCH (n:Row) RETURN n } IN TRANSACTIONS;
```

`ON ERROR RETRY`, `IN n CONCURRENT TRANSACTIONS` (adapted to sequential batching in the embedded engine), and per-batch rollback are supported. Each batch commits independently (ADR-0210): a committed batch stays committed and durable even when a later batch fails under `ON ERROR FAIL`, and live memory during the statement is bounded by the batch size rather than the total write volume. This independent-commit behavior applies to auto-commit statements; inside an explicit transaction the batches accumulate in the statement's overlay and commit with the enclosing transaction (ADR-0210 Consequences).

### Local callables (DEFINE, preview)

`DEFINE PROCEDURE` / `DEFINE FUNCTION` name a query-local callable and
call it from the same query (Neo4j's CIP-231, behind the
`CYPHERLITE_PREVIEW=local-callables` preview gate, ADR-0371 / ADR-0382).
A definition block heads any statement block — the top level, or a braced
body (`CALL { … }`, a conditional arm, a `COLLECT { … }` subquery, a NEXT
stage):

```cypher
DEFINE FUNCTION isEven(num, radix = 2) =
  CASE WHEN num % radix = 0 THEN true ELSE false END
DEFINE PROCEDURE createPersonNode(name :: STRING) :: (person :: NODE) {
  CREATE (p:Person {name: name})
  RETURN p AS person
}
UNWIND ['Alice', 'Barb'] AS memberName
CALL createPersonNode(memberName) YIELD person AS node
RETURN isEven(2), node.name;
```

Rules (CIP-231; every deviation is recorded in the CIP-231 NOTES.md):

- definitions are visible from their own position onward, only inside the
  statement block that contains them (and blocks nested within it); a
  definition never escapes its braces. Procedure and function names are
  independent namespaces; each must be unique across the whole query
- no calls before the definition, no recursive calls, and no calls of a
  callable whose body contains the call site (a parent definition)
- arguments are call-by-value: each is evaluated exactly once per outer
  row, before the body runs; default values are evaluated once per
  invocation. A function with a query body is an implicit scalar subquery:
  the body must have a single return item and either `LIMIT 1` or a total
  aggregation; zero rows yield `null`
- parameter/output/return types are parsed and validated (no `NOT NULL`
  anywhere in a signature type; a literal default must match its parameter
  type) but not enforced at runtime (this engine has no static expression
  type checker)
- no `USE` inside a callable body; no `CALL { … } IN TRANSACTIONS`
  anywhere in a query that also has a `DEFINE`; no local function in
  `SKIP`/`LIMIT` (already constants-only); no `DISTINCT` with a local
  function; a local callable shadows a built-in of the same name for the
  whole query
- every return item of a procedure body's emitting `RETURN` must be aliased;
  `YIELD` maps the body's columns (a `FINISH` body needs none). `YIELD …
  WHERE` on a local procedure call is not supported yet (an authored error)

### Vector type

```cypher
RETURN vector([1.0, 2.0, 3.0], 3, FLOAT32) AS v;
RETURN valueType(vector([1.0, 2.0], 2, FLOAT32));   -- "VECTOR<FLOAT32 NOT NULL>(2) NOT NULL"
RETURN vector.similarity.cosine([1.0,0.0], [0.9,0.1]) AS sim;
CREATE VECTOR INDEX embIdx FOR (n:Doc) ON n.embedding OPTIONS { indexConfig: {} };
CALL db.index.vector.queryNodes('embIdx', 5, $query) YIELD node, score RETURN node, score;
```

### UUID type

A first-class 128-bit UUID value (CIP-246) with `uuid()` (random,
v7-shaped), `uuid('...')` (strict RFC-4122 parse), and
`uuid(mostSigBits, leastSigBits)` constructors plus the
`uuid.mostSignificantBits`/`uuid.leastSignificantBits` accessors; usable in
`IS :: UUID` predicates, `valueType()` (`UUID NOT NULL`), `toString`, and
string interpolation. See [UUID functions](./functions.md#uuid-functions).

### Graph types

Declare and inspect a schema (graph type):

```cypher
CREATE GRAPH TYPE socialGT {
  (p:Person => {name :: STRING NOT NULL, age :: INTEGER}),
  (p)-[:KNOWS => {since :: INTEGER}]->(p)
};

ALTER CURRENT GRAPH TYPE SET { (:City => {name :: STRING NOT NULL}) };
SHOW CURRENT GRAPH TYPE YIELD specification RETURN specification;
```

Property declarations also accept the GQL `IS [::]` spelling instead of
`::` (ADR-0211). The `=>` (or `IMPLIES`) marker after the label stays
mandatory before a property block — without it the label is not an
explicitly denoted identifying label and the statement is a compile-time
syntax error (Neo4j behaves the same way):

```cypher
CREATE GRAPH TYPE SOGraph AS {
  (t:Tag => {name IS STRING}),
  (q:Question => {title IS STRING}),
  (q)-[:TAGGED]->(t)
};
```

`CREATE GRAPH TYPE` only registers a named type; the database's *current*
graph type is separate and stays empty until set (Neo4j behaves the same
way, but offers no promotion statement). Promote a declared type with
`ALTER CURRENT GRAPH TYPE SET GRAPH TYPE <name>` (ADR-0211 — an unknown
name fails with `GraphTypeNotFound`), and render the current type as
synthetic graph elements with `SHOW CURRENT GRAPH TYPE AS GRAPH [SINGLE |
SEPARATE]` (CIP-257; one row with `nodes`/`relationships` columns, like
`db.schema.visualization`):

```cypher
ALTER CURRENT GRAPH TYPE SET GRAPH TYPE SOGraph;
SHOW CURRENT GRAPH TYPE AS GRAPH;
```

Three element-type constructs sit behind `CYPHERLITE_PREVIEW` preview gates
(ADR-0371, each independently enableable; ungated, each fails closed with the
authored `preview feature '<name>' is not enabled` error):

- `graph-type-opt-props` (CIP-283) — the optional property: a bare `ANY`
  value type in an element type's property declarations
  (`(:Label => {prop :: ANY})`). It restricts nothing (any storable value
  fits, an absent property violates nothing) and works with the
  key/uniqueness shorthands. Independent property type constraints keep
  rejecting `ANY`.
- `graph-type-default-values` (CIP-262) — `DEFAULT ON COMMIT <value
  expression>` on an element-type property, restricted to literals and the
  allowed type constructors (`uuid()` without arguments, the date/time
  constructors, `duration()`, `point()`, `vector()`). The default applies at
  the transaction boundary — the statement is this engine's transaction —
  when an entity is created or gains the identifying label without the
  property (an explicit non-null value always wins; a same-statement removal
  is ignored; two unrelated element types both defaulting one property on a
  node fail instead of picking one).
- `graph-type-implied-labels` (CIP-266) — an implied label may name another
  node element type's identifying label, making the child inherit the
  parent's implied labels and property definitions (a re-specification must
  repeat exactly or further restrict; a diamond intersects the parents'
  effective definitions, a parent not defining the property contributing
  `ANY`; inheritance must be acyclic; an inherited node element type cannot
  be dropped while a child implies it). Derived constraints enforce it: a
  child's nodes must carry the parent's labels and satisfy its rules.

### Cypher version selection

Prefix a statement with `CYPHER 5` or `CYPHER 25` to select the language version:

```cypher
CYPHER 25 RETURN vector([1.0, 2.0], 2, FLOAT32);   -- 25-only features
CYPHER 5  MATCH (n) RETURN n;
```

### Extended functions

Beyond the openCypher function set, CypherLite adds GQL string functions (`trim(BOTH/LEADING/TRAILING x FROM s)`, `normalize(s, NFC)`, `char_length`), IEEE-conformant and hyperbolic math, the `||` string/list concatenation operator, `NULLIF`, `allReduce()`, `elementId()`, `valueType()`, aggregate set-quantifiers (`count(DISTINCT x)`), and many GQL function aliases. See the [Functions reference](./functions.md).

Three function names accepted into a CIP that no reference release ships sit behind `CYPHERLITE_PREVIEW` *name* gates (ADR-0497): `coll.zip` (`coll-zip`), the `coll.hasAnyOf`/`coll.hasAllOf`/`coll.hasNoneOf` family (`coll-has`) and the GQL `stddev_samp`/`stddev_pop` aliases (`gql-stddev-aliases`). They hide a name rather than a syntax, so a gated call while off is the ordinary unknown-function error, and the default dialect lists none of them in `SHOW FUNCTIONS`.

### Scope note

Server- and multi-user-oriented Cypher (RBAC & privileges, user auth, remote/composite/sharded databases, clustering) is intentionally **not** implemented — CypherLite is a single-process embedded engine. Multi-database surface follows Neo4j Community Edition over three fixed namespaces (`neo4j`, `system`, `system_ontologies`; ADR-0116): `USE` routes a statement to one of them (unknown names fail with 42N00), composite forms (`USE graph.byName`, composite databases) fail with 42N72/51N27, and `SHOW DATABASES` lists the three fixed rows. `SHOW` commands are supported over local metadata with a stable column subset. The full per-feature scope decision lives in `testdata/cip-eval/MANIFEST.md`.
