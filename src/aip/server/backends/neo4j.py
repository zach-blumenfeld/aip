"""The Neo4j backend: the store in a Neo4j database, for a deployment several servers or people share.

The graph and every statement are `aip.server.store`'s, the same as the Relate backend runs;
this module supplies the adapter over the Neo4j driver and the connection settings. A bundle
published here is the same nodes and edges as in its `.rl`, so a Browser pointed at the database
shows the procedures beside their runs and the queries of `docs/language/queries.md` work as
written.

Transactions are the driver's managed ones (`execute_read`, `execute_write`), which retry on a
transient error; the store's transaction functions only read and write the graph, so a retry
repeats nothing outside it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

from aip.server.store import JSON, Store

T = TypeVar("T")


@dataclass
class Connection:
    """Where the database is; every field defaults to the matching `NEO4J_*` variable."""
    uri: str = field(default_factory=lambda: os.environ.get("NEO4J_URI", "neo4j://localhost:7687"))
    user: str = field(default_factory=lambda: os.environ.get("NEO4J_USERNAME", "neo4j"))
    password: str = field(default_factory=lambda: os.environ.get("NEO4J_PASSWORD", ""))
    database: str = field(default_factory=lambda: os.environ.get("NEO4J_DATABASE", "neo4j"))

    def driver(self):
        try:
            from neo4j import GraphDatabase
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("the Neo4j driver is not installed; install `agent-instruction-protocol[server]` "
                               "(or `uv sync --extra neo4j` in the repo)") from exc
        # notifications off: an empty database otherwise logs a warning per unknown label on every read
        return GraphDatabase.driver(self.uri, auth=(self.user, self.password), notifications_min_severity="OFF")


def _plain(value: Any) -> Any:
    """A driver value as plain Python: maps as dicts, lists as lists."""
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


class _Tx:
    def __init__(self, tx):
        self.tx = tx

    def run(self, cypher: str, /, **params: Any) -> list[JSON]:
        return [{k: _plain(v) for k, v in record.items()} for record in self.tx.run(cypher, parameters=params)]

    def execute(self, cypher: str, params: JSON | None = None) -> list[JSON]:
        return self.run(cypher, **(params or {}))


class Neo4jGraph:
    """`aip.server.store.Graph` over a Neo4j driver."""

    def __init__(self, driver, database: str):
        self.driver, self.database = driver, database

    def read(self, cypher: str, /, **params: Any) -> list[JSON]:
        return self.reading(lambda tx: tx.run(cypher, **params))

    def reading(self, fn: Callable[[_Tx], T]) -> T:
        with self.driver.session(database=self.database) as session:
            return session.execute_read(lambda tx: fn(_Tx(tx)))

    def write(self, fn: Callable[[_Tx], T]) -> T:
        with self.driver.session(database=self.database) as session:
            return session.execute_write(lambda tx: fn(_Tx(tx)))

    def schema(self, statements: list[str]) -> None:
        with self.driver.session(database=self.database) as session:
            for statement in statements:
                session.run(statement).consume()

    def close(self) -> None:
        self.driver.close()


class Neo4jBackend:
    """The store in Neo4j. Verifies the connection and creates the constraints and indexes on
    construction; `close()` (or the context manager) closes the driver."""

    kind = "neo4j"

    def __init__(self, conn: Connection | None = None):
        self.conn = conn or Connection()
        driver = self.conn.driver()
        try:
            driver.verify_connectivity()
            self.graph = Neo4jGraph(driver, self.conn.database)
            self.store = Store(self.graph)
        except BaseException:
            driver.close()
            raise

    def close(self) -> None:
        self.store.close()

    def __enter__(self) -> "Neo4jBackend":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


__all__ = ["Connection", "Neo4jBackend", "Neo4jGraph"]
