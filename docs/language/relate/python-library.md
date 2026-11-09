# Python Library Reference

The `cypherlite` Python package embeds `cypherlite::Database` as a native extension
module (built with PyO3 and maturin). Queries execute in-process — there is no
subprocess, server, or network round-trip. Persistent paths are CypherLite
directories containing a WAL and one snapshot codec (Parquet by default, or
GraphData JSON).

The package offers two API styles:

| API | Entry point | Style |
|-----|-------------|-------|
| Connection/Cursor | `cypherlite.connect()` | sqlite3-style (DB-API 2.0 flavored) |
| Native | `cypherlite.Database` | Direct engine access, Arrow IPC via `execute_arrow()` |

## Installation

The package is not on PyPI yet (LABS-17), so there are two routes today.

**From a release wheel** — no Rust toolchain needed. Wheels are published for
Linux (x86-64, aarch64), macOS (arm64) and Windows (x86-64) beside the CLI
binaries on the [releases page](https://github.com/neo4j-labs/cypherlite/releases):

```bash
pip install neo4j_cypherlite-<version>-<platform>.whl
```

Because it is not on an index, downstream projects cannot yet declare it as a
dependency — vendoring the wheel or fetching it in CI is the workaround.

**From a checkout** — requires the Rust toolchain:

```bash
cd surfaces/cypherlite-python
pip install maturin
maturin develop --release
```

Or, from the repository root, use the Make target (creates a virtualenv, installs maturin, and runs `maturin develop`):

```bash
make install-python
```

Once the PyPI project is registered (trusted publishing on tagged releases) the
install becomes (`neo4j-cypherlite`; import `cypherlite`):

```bash
pip install neo4j-cypherlite
# optional Arrow IPC decoding
pip install neo4j-cypherlite[arrow]
```

:::note
Legacy single-file GraphStore JSON and Lance databases are not opened by this
package. Import old JSON explicitly into a JSON-codec directory.
:::

## Quick start

```python
import cypherlite

# Open an in-memory database
db = cypherlite.connect(":memory:")

# Create nodes
db.execute("CREATE (p:Person {name: $name, age: $age})", {"name": "Alice", "age": 30})
db.execute("CREATE (p:Person {name: $name, age: $age})", {"name": "Bob", "age": 28})

# Create a relationship
db.execute(
    "MATCH (a:Person {name: 'Alice'}), (b:Person {name: 'Bob'}) "
    "CREATE (a)-[:FRIENDS_WITH {since: 2020}]->(b)"
)

# Query the graph
cursor = db.execute("MATCH (p:Person)-[:FRIENDS_WITH]->(friend) RETURN p.name, friend.name")
for row in cursor:
    print(f"{row['p.name']} -> {row['friend.name']}")

db.close()
```

## Module-level functions

### `connect`

```python
cypherlite.connect(database: str = ":memory:") -> Connection
```

Open a connection to a CypherLite database. Pass a directory path for a
persistent database, or `":memory:"` for an in-memory database.
Raises `OperationalError` if the database cannot be opened.

```python
# In-memory
db = cypherlite.connect(":memory:")

# Persistent directory (manifest + snapshot + wal/)
db = cypherlite.connect("mydata")
```

## `Connection`

A connection to a CypherLite database backed by the in-process Database engine.
Commits are durable in the WAL before `execute()` returns; `flush()` requests a
checkpoint.

### Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `execute` | `(query, params=None) -> Cursor` | Execute a Cypher query |
| `executemany` | `(query, params_list) -> Cursor` | Execute a query for each parameter set |
| `commit` | `() -> None` | Commit the open transaction (a no-op in autocommit mode) |
| `rollback` | `() -> None` | Discard the open transaction (a no-op in autocommit mode) |
| `flush` | `() -> None` | Checkpoint and recycle eligible WAL (no-op in-memory) |
| `close` | `() -> None` | Close; persistent handles checkpoint on final drop |

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `closed` | `bool` | Whether the connection is closed |
| `autocommit` | `bool` | Whether each statement is durable on its own (default `True`) |

### Transactions

Connections default to **autocommit**: every statement is durable when
`execute()` returns. Set `connection.autocommit = False` to group statements
into a transaction — the first statement opens it, and `commit()` /
`rollback()` end it:

```python
conn = cypherlite.connect("/tmp/mydata")
conn.autocommit = False
try:
    conn.execute("CREATE (:Person {name: 'Alice'})")
    conn.execute("CREATE (:Person {name: 'Bob'})")
    conn.commit()          # both nodes durable now
except Exception:
    conn.rollback()        # neither is
    raise
```

- **Bookmarks.** `commit()` returns the transaction's bookmark — the engine's
  commit sequence, `cypherlite:<n>`, increasing per store (`None` when the
  transaction wrote nothing); an auto-commit write's bookmark is
  `cursor.consume().bookmark`.
- **Implicit rollback on close.** Closing a connection with an open transaction
  rolls it back — an unfinished transaction never becomes durable by accident.
- **Switching back to autocommit commits.** Setting `autocommit = True` while a
  transaction is open durably ends it (it commits) before the mode changes, so
  the mode change cannot silently discard work.
- **`rollback()` is not a safety net for writes.** A write inside a transaction
  that is later rolled back leaves no trace and no error — the statement
  reported success. To *refuse* writes rather than undo them, check the plan
  classification (`query_type`, below) or open the store read-only
  (`cypherlite.connect(path, read_only=True)`, which opens a separate handle and
  is therefore not available beside another writer).



### Context manager

`Connection` supports the `with` statement. The connection is closed automatically on exit.

```python
with cypherlite.connect(":memory:") as db:
    db.execute("CREATE (:Person {name: 'Alice'})")
    cursor = db.execute("MATCH (p:Person) RETURN p.name")
    print(cursor.fetchone())
# Connection is closed here
```

### `execute`

```python
Connection.execute(query: str, params: dict = None) -> Cursor
```

Execute a Cypher query and return a `Cursor` with the results.

Parameters are passed as a dictionary and referenced with `$name` in the query:

```python
cursor = db.execute(
    "MATCH (p:Person) WHERE p.age > $min_age RETURN p.name, p.age",
    {"min_age": 25}
)
```

Supported parameter value types (ADR-0219): `None`, `bool`, `int` (64-bit), `float`, `str`, `datetime.datetime`/`date`/`time`/`timedelta`, `cypherlite.Duration` (lossless months/days/seconds/nanoseconds), a returned `cypherlite.Vector`, `uuid.UUID` (crosses as its canonical string), `bytes`/`bytearray` (as a list of byte values 0–255 — the engine has no binary scalar; the PEP 249 `Binary` constructor is `bytes`), `list`, `tuple`, `dict` (nested values allowed), and `cypherlite.Point`. Dicts are always maps: a dict with `srid`/`x`/`y` keys is **not** reinterpreted as a point — pass `cypherlite.Point(srid, x, y)` or build it in Cypher with `point($coords)`. Returned maps keep the engine's key order.

Parameter-shape errors raise `ProgrammingError` with explicit wording: a non-dict `params` ("query parameters must be a dict …") or a non-string key at any nesting level ("… keys must be strings …"). An out-of-range `int` raises `DataError`.

### `executemany`

```python
Connection.executemany(query: str, params_list: list[dict]) -> Cursor
```

Execute a query once for each parameter dictionary in the list. Returns the cursor from the last execution.

```python
db.executemany(
    "CREATE (:Person {name: $name})",
    [{"name": "Alice"}, {"name": "Bob"}, {"name": "Charlie"}]
)
```

## `Cursor`

Represents the result of a query execution. Cursors are returned by `Connection.execute()` with all rows fully materialized.

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `columns` | `list[str]` | Column names from the RETURN clause |
| `stats` | `dict[str, int]` | Mutation statistics |
| `rowcount` | `int` | Number of rows, or -1 for write-only queries |
| `description` | `list[tuple]` | DB-API 2.0 compatible column description; `type_code` maps the engine-reported column type (ADR-0224) onto the PEP 249 type objects (`NUMBER`/`DATETIME` folds; graph, spatial, list/map, duration names and `ANY` report `None`) |

### Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `fetchone` | `() -> Record \| None` | Fetch the next row, or None if exhausted |
| `fetchmany` | `(size=1) -> list[Record]` | Fetch up to `size` rows |
| `fetchall` | `() -> list[Record]` | Fetch all remaining rows |
| `data` | `() -> list[Record]` | All remaining rows as `Record`s (consumes) |
| `fetch` | `(n) -> list[Record]` | Alias of `fetchmany(n)` (driver-style) |
| `peek` | `() -> Record \| None` | The next row without advancing; `None` at the end |
| `single` | `() -> Record` | The one remaining row; `ResultNotSingleError` on zero or more than one |
| `keys` | `() -> list[str]` | Alias of `.columns` |
| `to_df` | `(**kwargs) -> pandas.DataFrame` | Remaining rows as a DataFrame (consumes); needs the `[pandas]` extra |
| `to_arrow` | `(**kwargs) -> pyarrow.Table` | Remaining rows as a pyarrow Table (consumes); needs the `[arrow]` extra — `.to_pandas()` / `pl.from_arrow()` both work |
| `graph` | `() -> ResultGraph` | The result's unique graph entities, de-duplicated by id |
| `consume` | `() -> ResultSummary` | Discards remaining rows; returns counters, namespace, query type, `elapsed_ms` |
| `close` | `() -> None` | Close the cursor (no-op) |

### Iteration

Cursors support `for` loops and `len()`:

```python
cursor = db.execute("MATCH (n) RETURN n.name")
for row in cursor:
    print(row["n.name"])

print(f"{len(cursor)} rows")
```

### Row format

Each row is a `cypherlite.Record` — a `dict` subclass, so every mapping
operation keeps working — with the Neo4j driver's row conveniences on top:

```python
cursor = db.execute("MATCH (p:Person) RETURN p.name AS name, p.age AS age")
row = cursor.fetchone()
row["name"]        # "Alice" — DB-API habit
row.name           # "Alice" — driver-style attribute access (read-only)
row.keys()         # ["name", "age"] — column order, not insertion order
row.data()         # {"name": "Alice", "age": 30} — a plain dict copy
```

Unaliased columns work too — `"p.name"` is a valid dict key, and attribute
access is available when the alias is a valid Python identifier. Attribute
writes raise `AttributeError` (rows are read-only, like the driver's
`Record`); `row["name"] = x` still works because a `Record` is a `dict`.

Driver-style consumption (`single()`, `peek()`, `to_df()`) is covered in the
method table above. `to_df()` builds the frame from the already-materialized
rows — it never re-runs the query:

```python
cursor = db.execute("MATCH (p:Person) RETURN p.name AS name, p.age AS age")
df = cursor.to_df()   # pip install neo4j-cypherlite[pandas]
```

Use `AS` aliases for shorter keys:

```python
cursor = db.execute("MATCH (p:Person) RETURN p.name AS name, p.age AS age")
row = cursor.fetchone()
# row == {"name": "Alice", "age": 30}
```

What the *values* in those rows are depends on the column:

| Returned | Python value |
| --- | --- |
| `RETURN p` (a node) | `cypherlite.Node` — `id`, `element_id` (exactly `elementId(p)`, e.g. `4:cypherlite:n0`), `labels`, `properties` |
| `RETURN r` (a relationship) | `cypherlite.Relationship` — `id`, `element_id` (`5:cypherlite:r0`), `type`, `properties`, `start_node`, `end_node`, `start_node_element_id`, `end_node_element_id` |
| `RETURN p` (a path) | `cypherlite.Path` — `nodes`, `relationships` |
| `RETURN point(...)` | `cypherlite.Point` — `srid`, `x`, `y` |
| temporal values stdlib can carry losslessly (microsecond-aligned, offset only) | `datetime.datetime` / `date` / `time` |
| temporal values with sub-microsecond nanoseconds or an IANA zone name | `cypherlite.Temporal` — the engine's canonical `.text` (also `str()`), `.kind`, `.nanosecond`, `.zone_name`, `.offset_seconds`, and `.to_native()` for the lossy stdlib value |
| durations (every one) | `cypherlite.Duration` — `.months`, `.days`, `.seconds`, `.nanoseconds` exactly as Cypher keeps them (`PT36H != P1DT12H`), `str()` the ISO text, `.to_timedelta()` the lossy projection |
| `RETURN vector(...)` | `cypherlite.Vector` — `.coordinate_type`, `.dimension`, `.values` |
| scalars, lists, maps | the corresponding Python value (maps keep the engine's key order) |

```python
row = db.execute("MATCH (p:Person) RETURN p").fetchone()
row["p"].labels          # ['Person']
row["p"]["name"]         # properties are also mapping-accessible
```

The earlier `_labels` / `_type` dict convention is gone — rows carry the
objects above. `cursor.graph()` (below) is the collector for them.

### Result graph extraction

`cursor.graph()` collects every `Node`, `Relationship` and `Path` the rows
carry — directly or nested in lists/maps — de-duplicated by id, as a
`ResultGraph` with id-ordered `nodes` and `relationships`:

```python
cursor = db.execute("MATCH (a:Person)-[r:KNOWS]->(b:Person) RETURN a, r, b")
graph = cursor.graph()
graph.nodes           # the unique Person nodes
graph.relationships  # the unique KNOWS relationships
len(graph)            # entity count
```

It walks all rows of the result (rows are materialized at execute time, so
the fetch position is irrelevant) and returns an empty `ResultGraph` when
the result carries no graph entities. `Node` and `Relationship` expose
`element_id` and `items()` alongside `id`/`labels`/`type`/`properties`.
The graph converts to [networkx](https://networkx.org/) / [igraph](https://python.igraph.org/)
without a bridge dependency — every entity carries the ids, labels, type,
and properties the conversion needs:

```python
import networkx as nx
g = cursor.graph()
G = nx.MultiDiGraph()
G.add_nodes_from((n.id, {"labels": n.labels, **n.properties}) for n in g.nodes)
G.add_edges_from((r.start_node, r.end_node, {"type": r.type, **r.properties})
                 for r in g.relationships)
```

For [neo4j-viz](https://neo4j.com/docs/python-graph-visualization/current/)
rendering, `cypherlite.viz.to_visualization_graph(result)` builds a
`VisualizationGraph` directly from a cursor (needs only `neo4j-viz`).

### Stats

The `stats` property returns mutation statistics as a dictionary:

```python
cursor = db.execute("CREATE (:Person {name: 'Alice', age: 30})")
print(cursor.stats)
# {"nodes_created": 1, "properties_set": 2, "labels_added": 1, ...}
```

Available stat keys (always present, zero-padded): `nodes_created`, `nodes_deleted`, `relationships_created`, `relationships_deleted`, `properties_set`, `labels_added`, `labels_removed`.

### Result summary and `query_type`

`cursor.consume()` discards any remaining rows and returns a `ResultSummary`
with the statement's resolved `namespace`, its `counters`, `elapsed_ms`,
`notifications`, `plan`, and **`query_type`** — the plan-time classification
(ADR-0162, ADR-0332):

| `query_type` | Meaning |
| --- | --- |
| `"r"` | a pure read |
| `"w"` | a write that returns no columns |
| `"rw"` | a write that returns columns |
| `"s"` | a schema statement (index or constraint DDL) |

This is how a host keeps a **user-supplied** query read-only: classify it with
`EXPLAIN` before running it, and refuse anything that is not a pure read.

```python
def run_user_query(conn, cypher, params=None):
    planned = conn.execute(f"EXPLAIN {cypher}").consume()
    if planned.query_type != "r":
        raise PermissionError(f"only read queries are allowed (got {planned.query_type!r})")
    return conn.execute(cypher, params).fetchall()
```

`EXPLAIN` plans without executing, so the classification costs one plan and
never touches the graph. Two caveats: it is a *check-then-run* pair (the query
is planned twice, and nothing stops the second plan from differing if the
catalog changed in between), and it does not by itself bound what the query can
consume — a pathological read still runs. An engine-level read-only transaction
on a writable connection, which would replace this pattern with one guarantee,
is tracked as LABS-692; query timeouts and cancellation as LABS-195.

## Threading

`cypherlite.threadsafety` is **1**: the module may be shared between threads,
**a connection may not**. A `Connection` wraps a single-threaded native
`Database`, and it must be used, and dropped, on the thread that opened it.

This bites on the first concurrent request in any threaded server: sync
handlers in FastAPI/Flask run on worker threads, so a connection created at
startup is used from a different thread than the one that made it. That misuse
is a typed `ProgrammingError` (GH #352 / LABS-700) — the `sqlite3` behavior,
catchable by ordinary `except Exception` handling — and it is not fatal: the
owning thread keeps the connection usable. Dropping the last reference on
another thread is safe; the deferred cleanup (the native `Drop` checkpoint)
runs from that thread, with no unraisable exception.

The pattern that works: **own the connection on one worker thread** and route
every call to it.

```python
import concurrent.futures, cypherlite

# One dedicated thread owns the connection; callers submit work to it.
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

def query(cypher, params=None):
    """Runs on the owning thread, wherever it is called from."""
    def _run():
        with cypherlite.connect("/tmp/mydata") as conn:
            return conn.execute(cypher, params).fetchall()
    return _executor.submit(_run).result()
```

An in-memory store is cheap to duplicate, so one connection per thread is also
fine for `:memory:`. A **file-backed store is different**: a second *writable*
open of the same directory is refused by the writer lease (ADR-0136), so a
shared file store means one owning connection per process (or a read-only
handle beside a writer — `cypherlite.connect(path, read_only=True)`).

Two related facts:

- **The GIL is released around the engine call** (`execute` / `execute_arrow`
  run under `py.allow_threads`), so other Python threads make progress while a
  query runs — the constraint is affinity, not serialization.
- **A second handle on the same directory is refused** (the writer lease,
  ADR-0136), so "one connection per thread" only works for `:memory:` or for
  read-only handles on a store a single writer owns.

## Exceptions

All exceptions inherit from `CypherLiteError` and follow PEP 249 (DB-API 2.0) conventions:

| Exception | Description |
|-----------|-------------|
| `CypherLiteError` | Base exception for all CypherLite errors |
| `InterfaceError` | Database interface error (native module communication) |
| `OperationalError` | Query execution or connection error (syntax error, constraint violation, failure to open database) |
| `ProgrammingError` | Programming mistake (using a closed connection) |

```python
import cypherlite

db = cypherlite.connect(":memory:")
try:
    db.execute("INVALID SYNTAX")
except cypherlite.OperationalError as e:
    print(f"Query failed: {e}")

# Connection still works after an error
print(db.execute("RETURN 42 AS answer").fetchone())  # {"answer": 42}
```

---

## Native `Database` API

For lower-level access — including Arrow interop — use the native `Database` class directly. This is the class `Connection` wraps.

```python
from cypherlite import Database

db = Database()          # in-memory (same as Database(":memory:"))
db = Database("graph")   # persistent directory + WAL
```

### Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `execute` | `(query, params=None) -> QueryResult` | Execute a Cypher query (same parameter conversion as `Connection.execute`, ADR-0219) |
| `execute_arrow` | `(query, params=None) -> bytes` | Execute and return Arrow IPC stream bytes (same parameter conversion) |
| `flush` | `() -> None` | Checkpoint and recycle eligible WAL |
| `close` | `() -> None` | Close the native handle |
| `reset` | `() -> None` | Reopen the same path (in-memory: empty database; directory: reload) |
| `node_count` | `() -> int` | Number of nodes |
| `relationship_count` | `() -> int` | Number of relationships |
| `labels` | `() -> list[str]` | All node labels |
| `relationship_types` | `() -> list[str]` | All relationship types |

Errors are raised as `RuntimeError` (the `Connection` wrapper translates them into the DB-API exception hierarchy).

### `QueryResult`

| Property | Type | Description |
|----------|------|-------------|
| `columns` | `list[str]` | Column names |
| `data` | `list[dict]` | Rows as dictionaries |
| `stats` | `dict[str, int]` | Mutation statistics (only non-zero counters present) |

```python
from cypherlite import Database

db = Database()
result = db.execute("CREATE (:Person {name: 'Alice', age: 30})")
print(result.stats)  # {'nodes_created': 1, 'properties_set': 2, 'labels_added': 1}

result = db.execute("MATCH (n:Person) RETURN n.name AS name, n.age AS age")
print(result.columns)  # ['name', 'age']
print(result.data)     # [{'name': 'Alice', 'age': 30}]
```

### Arrow interop

`execute_arrow()` returns results as Arrow IPC stream bytes, enabling zero-copy transfer to PyArrow, Pandas, or Polars:

```python
from cypherlite import Database
import pyarrow as pa

db = Database()
db.execute("CREATE (:Person {name: 'Alice', age: 30})")
db.execute("CREATE (:Person {name: 'Bob', age: 28})")

buf = db.execute_arrow("MATCH (n:Person) RETURN n.name AS name, n.age AS age")
table = pa.ipc.open_stream(buf).read_all()
df = table.to_pandas()
print(df)
#     name  age
# 0  Alice   30
# 1    Bob   28
```

With Polars:

```python
import polars as pl
df = pl.from_arrow(pa.ipc.open_stream(buf).read_all())
```

---

## Examples

### Persistent database

```python
import cypherlite

# Create and populate
db = cypherlite.connect("friends")
db.execute("CREATE (:Person {name: 'Alice'})")
db.execute("CREATE (:Person {name: 'Bob'})")
db.execute(
    "MATCH (a:Person {name: 'Alice'}), (b:Person {name: 'Bob'}) "
    "CREATE (a)-[:KNOWS]->(b)"
)
db.close()  # commits were WAL-durable; close checkpoints

# Reopen later
db = cypherlite.connect("friends")
cursor = db.execute("MATCH (a)-[:KNOWS]->(b) RETURN a.name, b.name")
print(cursor.fetchall())
db.close()
```

### Vector similarity search

```python
import cypherlite

db = cypherlite.connect(":memory:")

# Create documents with embeddings
db.execute("""
    CREATE (:Document {
        title: 'Graph Databases',
        embedding: vector([0.1, 0.8, 0.3, 0.5])
    })
""")
db.execute("""
    CREATE (:Document {
        title: 'Relational DBs',
        embedding: vector([0.9, 0.1, 0.4, 0.2])
    })
""")

# Create a vector index
db.execute("""
    CREATE VECTOR INDEX doc_embedding FOR (d:Document) ON (d.embedding)
    OPTIONS {dimensions: 4, similarity: 'cosine'}
""")

# Query similar documents
cursor = db.execute("""
    CALL db.index.vector.queryNodes('doc_embedding', 2, vector([0.1, 0.9, 0.3, 0.4]))
    YIELD node, score
    RETURN node.title, score
    ORDER BY score DESC
""")
for row in cursor:
    print(f"{row['node.title']}: {row['score']:.3f}")

db.close()
```

### Arrow analytics pipeline

```python
from cypherlite import Database
import pyarrow as pa

db = Database()
for name, age, city in [("Alice", 32, "Portland"), ("Bob", 28, "Seattle"),
                        ("Carol", 35, "Portland")]:
    db.execute("CREATE (:Person {name: $n, age: $a, city: $c})",
               {"n": name, "a": age, "c": city})

buf = db.execute_arrow("MATCH (p:Person) RETURN p.city AS city, p.age AS age")
df = pa.ipc.open_stream(buf).read_all().to_pandas()
print(df.groupby("city")["age"].mean())
```

Full contract: [`docs/api/python/spec.md`](https://github.com/neo4j-labs/cypherlite/blob/main/docs/api/python/spec.md).
