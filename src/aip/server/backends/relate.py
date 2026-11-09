"""The Relate backend, the default: the store as one Relate file under the server's data directory.

Relate is the embedded engine a bundle is written in (`aip.compiler.relate`), so the server
needs no database beside itself: `aip server` opens `store.rl` (or `:memory:`, for tests) and is
its only writer. Every statement is `aip.server.store`'s; this module supplies the adapter they
run through.

One process at a time holds the file. Within the process a connection belongs to the thread
that opened it, and the server answers requests on a thread pool, so one worker thread opens the
connection and runs every statement and transaction in turn: a transaction's reads and writes
are atomic because nothing else runs between them. Anyone else reads the file through the
engine's own tools (`relate query`, `relate serve --read-only`), which open a frozen view
beside the writer.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, TypeVar

from aip.server.store import JSON, Store

T = TypeVar("T")

STORE_FILE = "store.rl"
DEFAULT_DATA_DIR = Path("~/.local/share/aip/server")


def default_path() -> Path:
    return DEFAULT_DATA_DIR.expanduser() / STORE_FILE


class _Tx:
    def __init__(self, conn):
        self.conn = conn

    def run(self, cypher: str, /, **params: Any) -> list[JSON]:
        return [dict(r) for r in self.conn.execute(cypher, params)]

    def execute(self, cypher: str, params: JSON | None = None) -> list[JSON]:
        return [dict(r) for r in self.conn.execute(cypher, params or {})]


class RelateGraph:
    """`aip.server.store.Graph` over one Relate connection, owned by one worker thread."""

    def __init__(self, path: str | Path):
        from aip.compiler import relate

        relate.module()                      # RelateMissing here, with the install hint, not on the worker
        self.path = ":memory:" if str(path) == ":memory:" else str(relate.store_file(Path(path).expanduser()))
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="aip-store")
        self.conn = self._on_worker(lambda: relate.store(self.path))

    def _on_worker(self, fn: Callable[[], T]) -> T:
        return self.worker.submit(fn).result()

    def read(self, cypher: str, /, **params: Any) -> list[JSON]:
        return self._on_worker(lambda: _Tx(self.conn).run(cypher, **params))

    def _transaction(self, fn: Callable[[_Tx], T], keep: bool) -> T:
        def tx() -> T:
            self.conn.autocommit = False
            try:
                out = fn(_Tx(self.conn))
                if keep:
                    self.conn.commit()
                else:
                    self.conn.rollback()
                return out
            except BaseException:
                self.conn.rollback()
                raise
            finally:
                self.conn.autocommit = True
        return self._on_worker(tx)

    def reading(self, fn: Callable[[_Tx], T]) -> T:
        return self._transaction(fn, keep=False)

    def write(self, fn: Callable[[_Tx], T]) -> T:
        return self._transaction(fn, keep=True)

    def schema(self, statements: list[str]) -> None:
        def run() -> None:
            for statement in statements:
                self.conn.execute(statement)
        self._on_worker(run)

    def close(self) -> None:
        def drop() -> None:   # close, and let go of the handle here too: it may not be freed on another thread
            conn, self.conn = self.conn, None
            if conn is not None:
                conn.close()
        try:
            self._on_worker(drop)
        finally:
            self.worker.shutdown()


class RelateBackend:
    """The store in a Relate file. `path` is the store file (created when missing; default
    `~/.local/share/aip/server/store.rl`) or `:memory:`. `close()` (or the context manager)
    checkpoints and releases the file."""

    kind = "relate"

    def __init__(self, path: str | Path | None = None):
        self.graph = RelateGraph(default_path() if path is None else path)
        self.path = self.graph.path
        self.store = Store(self.graph)

    def close(self) -> None:
        self.store.close()

    def __enter__(self) -> "RelateBackend":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


__all__ = ["DEFAULT_DATA_DIR", "STORE_FILE", "RelateBackend", "RelateGraph", "default_path"]
