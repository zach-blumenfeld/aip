"""Relate, the embedded graph engine a bundle is written in, imported lazily.

Relate is Neo4j's single-file Cypher database (`relate-db` on PyPI, `import relate`,
github.com/relatedb/relate). It is a dependency of this package; this module is still the one
place that imports it: everything else calls `connect()`, `open()`, `create()` or `store()` here.

Bundles are `.rl` files, Relate's single-file form, and the path is passed through as it is.

Nothing here is imported at package load: `aip compile --check` and the parser work without
Relate installed, and `aip` prints `INSTALL_HINT` as one line when a bundle is asked for and the
import fails (an environment that installed `aip` without its dependencies)."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import ModuleType

BUNDLE_SUFFIX = ".rl"

INSTALL_HINT = "Relate is not installed, and a bundle is a Relate file: pip install relate-db"


class RelateMissing(RuntimeError):
    """`relate` cannot be imported; `str()` is the install hint."""

    def __init__(self):
        super().__init__(INSTALL_HINT)


_module: ModuleType | None = None


def module() -> ModuleType:
    """The engine's Python package, `relate`; `RelateMissing` when it is not installed."""
    global _module
    if _module is None:
        try:
            import relate as mod  # type: ignore[import-not-found]
        except ImportError:
            raise RelateMissing() from None
        _module = mod
    return _module


def available() -> bool:
    try:
        module()
    except RelateMissing:
        return False
    return True


def installed_version() -> str | None:
    """The installed engine's version, or None when it is not installed."""
    try:
        mod = module()
    except RelateMissing:
        return None
    return getattr(mod, "__version__", None)


def connect(path: str | Path, *, read_only: bool):
    """A connection to the store at `path` (an `.rl` file, or `:memory:`): the raw call."""
    return module().connect(str(path), read_only=read_only)


@contextmanager
def open(path: str | Path, *, read_only: bool = True):  # noqa: A001  (the verb the engine uses)
    """A connection to an existing bundle, read-only unless asked otherwise, closed on exit."""
    target = Path(path)
    if str(path) != ":memory:" and not target.exists():
        raise FileNotFoundError(str(target))
    conn = connect(path, read_only=read_only)
    try:
        yield conn
    finally:
        conn.close()


def store(path: str | Path):
    """A read-write connection to the store at `path` (`:memory:` for one that lives with the
    process), created when missing. The caller closes it, on the thread that opened it."""
    if str(path) == ":memory:":
        return connect(path, read_only=False)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    return connect(target, read_only=False)


@contextmanager
def create(path: str | Path):
    """A connection to a new, empty bundle at `path`, replacing any file there once the block
    completes; nothing is left behind when it raises."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp" + BUNDLE_SUFFIX)
    if tmp.exists():
        tmp.unlink()
    try:
        conn = connect(tmp, read_only=False)
        try:
            yield conn
        finally:
            conn.close()
        tmp.replace(target)
    finally:
        if tmp.exists():
            tmp.unlink()
