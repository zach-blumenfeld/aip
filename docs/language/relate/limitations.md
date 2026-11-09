# Limitations

CypherLite is `0.16.1`. It is a lightweight, embeddable, **single-process**
graph database — closer to SQLite than to a clustered graph server or a
columnar warehouse. Several of these are scope choices, not bugs.

## Fixed namespaces; one graph per statement (no cross-graph queries)

A CypherLite store holds exactly the three fixed namespaces of ADR-0116 —
`neo4j` (the user data graph), `system` (no graph data) and
`system_ontologies` (listed but not queryable, ADR-0229: every statement
routed to it, reads included, fails with 42N17; only the database
administration commands still run from there) — and a single query always
runs against a single graph:

- Multi-database switching is withdrawn: you cannot open several databases in
  a session and switch between them (the shell's `.open` / `.attach` / `.use`
  commands are withdrawn, ADR-0058). A statement's `USE` clause routes it to
  one of the fixed namespaces; any other name fails with `Graph not found:
  <name>` (42N00), resolved before execution (`USE g RETURN 1` fails too).
- `graph.byName`, `graph.names` and `graph.propertiesByName` are
  composite-only and fail with 42N72; several distinct `USE` targets in one
  statement (across `UNION` arms, `CALL` subqueries or `NEXT`) fail with
  42NA5.
- `SHOW DATABASES` returns exactly the three fixed-namespace rows: `neo4j`
  (standard, read-write, `default` and `home`), `system` (system,
  read-write) and `system_ontologies` (standard, read-only), all `online`
  with empty `aliases`/`constituents`. `SHOW DEFAULT DATABASE` and
  `SHOW HOME DATABASE` return `neo4j`; an unknown name returns no rows.
  Database administration follows Neo4j Community Edition: only
  `SHOW DATABASE[S]`, `SHOW DEFAULT/HOME DATABASE` and
  `ALTER DATABASE … SET DEFAULT LANGUAGE CYPHER 5|25` are supported; every
  other database administration command (`CREATE`/`DROP`/`ALTER DATABASE`
  otherwise, `START`/`STOP DATABASE`, aliases, composite forms) fails with
  51N27 `Unsupported administration command: <statement>` (ADR-0116). A
  `WITH` composing one of these commands (`… YIELD … WITH … RETURN …`) is
  rejected when routed to `system` — `The following clauses are not allowed
  on a system database: WITH.` — and an explicit `USE` clause targeting a
  non-system namespace on a statement headed by one of them fails with
  42N79 ``The `USE` clause is not required for administration commands.
  Retry your query without the `USE` clause, and it will be routed
  automatically.``; `USE system` + administration command stays accepted.
  Composed administration commands with **no** `USE` clause deliberately
  still run from the user namespace, where Neo4j 2026.09 raises 51N28
  instead: that boundary is DBMS session-routing and privilege semantics,
  with no meaning in a single-user embedded engine whose catalog is
  store-level (ADR-0116 §2's Later references, ADR-0276).
- No composite, federated, or sharded databases.

## Transactions are single-level

Single-level explicit transactions (`.begin` / `.commit` / `.rollback` and the
binding APIs) over an autocommit default. Nested transactions are not
supported. `CALL { … } IN TRANSACTIONS` batches its own durable units; it is
not a savepoint mechanism.

Durability (when writes hit the WAL, snapshot codecs, poisoned transactions)
is in [Storage Engine](guides/storage-engine.md#persistence-model) and
[Autocommit vs. explicit transactions](guides/storage-engine.md#autocommit-vs-explicit-transactions).

The HTTP Query API's managed transactions (ADR-0237) have an enforced
lifecycle (ADR-0435): a transaction idle longer than
`--tx-idle-timeout-secs` (default 60 s; `0` disables) is reclaimed by the
next registry operation with 404/`42N90`, and a per-registry cap
(`--max-open-transactions`, default 128; `0` unlimited) refuses a begin
over it with 429/`42N91`. Engine-level explicit transactions (embedded API,
bindings, Bolt) are not idle-expired; a silent Bolt connection is instead
closed by the Bolt surface's idle timeout (300 s default; the
`--idle-timeout-secs` knob is library-level — no product binary parses
it), which rolls back its open transaction.

## Durability: WAL plus one snapshot codec

`cypherlite::Database` appends redo to a WAL, then checkpoints to **one** codec
per directory (parquet shards or a full `graph.json` rewrite). The default
`full` mode barriers before acknowledgement; `everysecond` and `snapshot`
explicitly accept bounded or checkpoint-sized data loss (ADR-0077).
Open loads the snapshot and replays WAL. Codecs do not mix in one directory
([ADR-0050](https://github.com/neo4j-labs/cypherlite/blob/main/docs/adr/0050-snapshot-codecs.md)). GraphStore `--legacy` JSON
files are withdrawn ([ADR-0052](https://github.com/neo4j-labs/cypherlite/blob/main/docs/adr/0052-graphstore-withdrawn.md)).

`:memory:` is process-ephemeral.

## Single-process engine

A directory-backed database is used from **one process**. CypherLite is not a
multi-process or multi-writer client/server. Bolt (`cypherlite-bolt`) is still
one engine. Concurrent **threads** in that process may read together; overlapping
writers get `write-write conflict` at WAL append (no silent retry).

## Constraints are checked per statement, plus at commit for constrained values

Each write statement (and each `CALL { … } IN TRANSACTIONS` batch) checks
the constraints against its own snapshot plus its own writes, and re-checks
only the nodes and relationships it touched
([ADR-0172](https://github.com/neo4j-labs/cypherlite/blob/main/docs/adr/0172-incremental-constraint-validation.md)).
A constraint another session commits or changes while a transaction is open
is still enforced on that transaction at its **next statement** — including
a read-only one — which re-checks the constraint against the transaction's
earlier writes
([ADR-0174](https://github.com/neo4j-labs/cypherlite/blob/main/docs/adr/0174-committed-catalog-constraint-rechecks.md)).
Commit admission additionally enforces `unique` and `key` at the commit-time
serialization point
([ADR-0439](https://github.com/neo4j-labs/cypherlite/blob/main/docs/adr/0439-commit-time-uniqueness.md)):
a maintained per-constraint committed-state tuple map rejects the later of
two concurrent transactions that introduce the same constrained value with
the retryable `Error::Conflict`, before the WAL append. The loser's ops are
discarded; on retry its statement-time validator sees the winner and reports
the precise `ConstraintValidationFailed` violation (a retried `MERGE` may
instead match the winner). Commit conflicts beyond constrained values still
look at element ids only (no general write-skew detection,
[ADR-0015](https://github.com/neo4j-labs/cypherlite/blob/main/docs/adr/0015-optimistic-wal-commits.md)):
read/write dependencies that do not touch a constrained tuple still commit.

## Whole graph held in memory

The live graph is **in RAM**. Traversal is typed CSR; persistence is WAL + a
snapshot. **The working set must fit in memory.** There is no paging, buffer
pool, or spill-to-disk. An optional logical cap
([ADR-0042](https://github.com/neo4j-labs/cypherlite/blob/main/docs/adr/0042-graph-memory-limit.md)) fails growing writes with
`Error::Capacity`.

Size is “whatever fits,” not a fixed node count. This is not an out-of-core
analytics engine.

## Query and value nesting limits

Query text is capped at 4 MiB and static nesting at 500 levels
([ADR-0257](https://github.com/neo4j-labs/cypherlite/blob/main/docs/adr/0257-query-input-limits.md));
violations are typed errors before lexing/parsing. Runtime values built by
an expression are independently capped at **500 container levels**
([ADR-0462](https://github.com/neo4j-labs/cypherlite/blob/main/docs/adr/0462-value-nesting-depth.md)):
a dynamically built list or map nested past that — e.g. a `reduce`
accumulator that wraps itself in a new list each iteration — fails with the
typed `ValueDepthExceeded` error instead of building a value that overflows
a later recursive walk. Exactly 500 levels are accepted. A statement that
nests evaluations (nested `CALL`/`EXISTS`/`FOREACH`) is additionally bounded
by the fixed 100 000-pass per-statement budget (ADR-0395). All three limits
are fixed: no option or environment override.

## Traversal depth

An explicit variable-length hop bound (`*1..N`, `*..N`, or the CIP-28
group form `{1,N}`) is walked recursively, so a large enough `N` would
abort the process on the native stack. Statement admission rejects a bound
above the limit with `TraversalDepthExceeded` — a syntax error, before the
statement is planned or run ([ADR-0466](https://github.com/neo4j-labs/cypherlite/blob/main/docs/adr/0466-traversal-depth-admission-limit.md)).
An unbounded upper bound (`*`, `*1..`, `{1,}`) is exempt: the classic
walk already stops at 32 hops.

| | |
|---|---|
| What it protects | The process from a stack-overflow abort (no error, no recovery). |
| Knob | `--max-traversal-depth N`, `CYPHERLITE_MAX_TRAVERSAL_DEPTH`, or `OpenOptions::max_traversal_depth`. |
| Default | 500 hops. Valid values are 1 through 2000. |
| Action | Lower the path bound, or raise the knob. Above 2000 the recursive walker risks a stack overflow on small-stack platforms (WebAssembly's 16 MiB stack is the tightest supported surface); measured abort bounds are ≈2,700 hops (debug WASM) to ≈11,000 (debug native). |

The `MATCH p = shortestPath(...)` route explores without a hop cap
(ADR-0186) and is not covered by this limit; it is bounded by the
relationship count. Neo4j has no equivalent traversal ceiling, so a query
ported from Neo4j with an explicit bound above 500 needs the knob raised.

## Memory limits

Every memory limit in CypherLite is a **protective guard rail with a generous
default**, never a native database capability limit. Each refusal names the
mechanism, what it protected, and the knob or workaround that clears it — so
a human or an agent reading the error does not need to look anything up.
None of these limits is a statement about what the engine can do; they exist
so one statement cannot exhaust the process.

| Mechanism | What it protects | Knob | Default | What to do when you hit it |
|---|---|---|---|---|
| **Graph capacity** ([ADR-0042](https://github.com/neo4j-labs/cypherlite/blob/main/docs/adr/0042-graph-memory-limit.md)) | The live graph + index bytes held in RAM (a growing write is refused at WAL append) | `--logical-graph-size-limit SIZE` / `CYPHERLITE_LOGICAL_GRAPH_SIZE_LIMIT` | unset = unlimited | Delete data, or raise the knob; `0` is unlimited |
| **Retained workspace** ([ADR-0452](https://github.com/neo4j-labs/cypherlite/blob/main/docs/adr/0452-workspace-limit-enables-admission.md)) | The shared pool of logical workspace held by concurrently executing queries (opt-in admission) | `--concurrent-logical-workspace-limit SIZE` / `CYPHERLITE_CONCURRENT_LOGICAL_WORKSPACE_LIMIT` | unset = admission off | Retry when fewer queries run, reduce concurrency, or raise the pool. The refusal reads: *this query needs more shared workspace than the concurrent-workspace limit allows — this is a safety limit protecting the server from memory exhaustion (not a database limit); retry when fewer queries run, or raise it with `--concurrent-logical-workspace-limit`* |
| **Expression build** ([ADR-0463](https://github.com/neo4j-labs/cypherlite/blob/main/docs/adr/0463-expression-allocation-budget.md)) | One value an expression builds (`range`, concatenation, `join`, `split`, a comprehension output, an accumulator, a materialized `UNWIND`, a `collect` buffer) | `--expression-memory-limit SIZE` / `CYPHERLITE_EXPRESSION_MEMORY_LIMIT` (also `OpenOptions::expression_memory_limit`) | **256 MiB** | Build the value in smaller pieces (batch the `UNWIND`, `range`, or join), or raise the knob; `none`/`0` disables the cap for known bulk pipelines. A refused statement reads: *This statement tried to build a single value of 24 GB. This is a safety limit protecting against memory exhaustion (not a database limit) — build the value in smaller pieces, or raise it with `--expression-memory-limit`.* |

The expression cap is **per allocation**, not a per-statement total: a long
streaming load that builds many small values never accumulates against it
(and `PROFILE`'s `Expression Built (Bytes)` column is construction-work
telemetry — total bytes built, not live memory; values are dropped as the
statement runs). Its 256 MiB default leaves headroom above the measured bulk
watermarks (a 1M-row `UNWIND` materializes 48 MB in its row buffer).


## Safe mode

Safe mode ([ADR-0477](https://github.com/neo4j-labs/cypherlite/blob/main/docs/adr/0477-safe-mode.md))
is an opt-in policy for agent-driven use. It refuses two statement shapes
an agent commonly gets wrong, at admission and before anything runs, as the
syntax error `SafeModeViolation` (CLI exit 6, HTTP 400/`42N06`, Bolt
`Neo.ClientError.Statement.SyntaxError`):

| Refused shape | Exemptions | Remedy |
|---|---|---|
| `CREATE`/`MERGE` of a new named node without a label | anonymous `()` endpoints (the relationship-only `CREATE ()-[r:X]->()` form) and endpoints bound earlier in the body | give the node a label, e.g. `CREATE (n:Person)` |
| a `MATCH` body whose final `RETURN`/`WITH` has no `LIMIT` and no reducing aggregate | constant-only `RETURN`/`WITH`, `SHOW`/`CALL`-only statements, and write tails (`MATCH … SET`/`DELETE`); `collect()` does **not** count as a reducing aggregate because it buffers every row | add `LIMIT <n>`, or return `count(*)`/another reducing aggregate |

| | |
|---|---|
| What it protects | An agent from unbounded scans and unlabeled writes. |
| Knob | `--safe` / `--no-safe`, `CYPHERLITE_SAFE_MODE=1/0`, or `OpenOptions::safe_mode`. |
| Default | Off, everywhere. Never auto-detected. |
| Action | Add the label or the `LIMIT`/aggregate; or reopen without `--safe`. This is a policy, not a database limit. |

Narrow-form caveats: a `LIMIT`-less read of a genuinely small database is
refused (the rule cannot see the store's size), and a `CALL { … }` subquery
body is validated on its own, so a correlated `MATCH … RETURN` inside one
needs its own `LIMIT`.


## Lance / GraphStore are withdrawn

JSON GraphStore files, Lance directories, and `--legacy` CLI flags are not
product surfaces ([ADR-0052](https://github.com/neo4j-labs/cypherlite/blob/main/docs/adr/0052-graphstore-withdrawn.md)). Import
an old `.db` by copying it to `<dir>/graph.json` and opening with
`--snapshot-format json`.

The JSONL `--server` protocol is withdrawn with GraphStore. Language bindings
call the engine in-process.

## openCypher TCK: superseded scenarios

CypherLite runs the openCypher TCK under a **strict** harness (it checks error
class, error phase, and side effects, and fails on unknown steps). Of the 3892
pinned, cucumber-expanded scenarios, **3892 pass and 0 are skipped**. The pin
is the 2024.3 snapshot minus one superseded outline, with four ORDER BY
scenarios re-pinned to Neo4j's current Cypher 25 behaviour (ADR-0188,
ADR-0458, ADR-0472):

| Scenario | Why it is out of the pin |
|----------|--------------------------|
| `TypeConversion4 [10]` — *"Fail `toString()` on invalid types"* | Superseded by CIP-271 (ADR-0002): Neo4j 2026.09 (verified live under `CYPHER 25`) renders LIST/MAP/NODE/RELATIONSHIP/PATH in `toString()` instead of erroring, an intentional Cypher 25 semantic change over the 2024.3 TCK floor. The scenario can never pass without regressing, so it is removed from the pinned corpus (kept as a `#`-commented reference in the feature file) rather than skipped forever. The current contract is carried by cip-eval's CIP-271 suite. |

Four further scenarios are **in the pin asserting Cypher 25 behaviour** instead
of the 2024.3 expectation (ADR-0002, ADR-0472):

| Scenario | What it asserts now |
|----------|--------------------|
| `WithOrderBy4 [13]` — *"Fail on sorting by a non-projected aggregation on a variable"* | The 2024.3 expectation is `UndefinedVariable`; Neo4j's current Cypher 25 behaviour recomputes the aggregation subexpression over the group, and CypherLite follows it: rows `(mod 2, min 7)` and `(mod 1, min 5)`. The acceptance suite's `[13]` (success) and `[13-c5]` (42I24) variants pin both current forms. |
| `WithOrderBy4 [14]` — *"Fail on sorting by a non-projected aggregation on an expression"* | Same as `[13]`, for a non-projected expression: rows `(mod 2, min 7)` and `(mod 1, min 5)`. Its `[14]`/`[14-c5]` acceptance variants pin both current forms. |
| `WithOrderBy4 [20]` — *"Fail if more complex expressions, even if projected, are used inside an order by item which contains an aggregation expression"* | The current behaviour raises the unaliased-`WITH`-item error (42N21), which the acceptance suite's `[20]` pins, not `AmbiguousAggregationExpression`. |
| `ReturnOrderBy6 [5]` — *"Fail if more complex expressions, even if returned, are used inside an order by item which contains an aggregation expression"* | Cypher 25 accepts an ORDER BY key that decomposes a projected expression beside an aggregation; the acceptance suite's `[5]` ("This works in LTS") pins the current behaviour. Over an empty graph the result set is empty, with columns `me.age + you.age` and `cnt`. |

The CIP evaluation suite (Neo4j Cypher beyond the TCK) is tracked separately
at 5876/5917 (99.3%); its residual is documented in
`testdata/cip-eval/SWEEP-FOLLOWUP.md`.

## Not in scope for the embedded engine

Role-based access control, user authentication, remote/composite/sharded
databases, cluster topology, and server-settings administration. Those are
multi-tenant server concerns, not a single-process library.
