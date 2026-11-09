"""Relate, the embedded graph engine a bundle is written in, imported lazily.

Relate (formerly CypherLite) is Neo4j Labs' single-file Cypher database. It is pinned at one
version (`RELATE_VERSION`) and is not on PyPI yet: the wheels sit on the project's GitHub
release, and `scripts/install-relate.sh` fetches the one for this platform and installs it (the
plan's open item 2). The release of the pinned version still carries the old name, so the module
is `cypherlite`; the rename to `import relate` is on their main branch. This module is the one
place that knows both names: everything else calls `connect()` here and never imports either.

Bundles are `.rl` files, the name Relate's next release gives its single-file form. The pinned
release recognises the single-file form by the `.cl` suffix alone, so until the rename ships,
`create()` writes beside the target as `<name>.rl.tmp.cl` and renames into place, and `open()`
links (or copies) an `.rl` to a temporary `.cl` for the duration of the open. With the renamed
package the dance disappears and the path is passed through.

Nothing here is imported at package load: `aip compile --check` and the parser work without
Relate installed, and `aip` prints `INSTALL_HINT` as one line when a bundle is asked for and
neither import works."""

from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType

RELATE_VERSION = "0.16.1"
BUNDLE_SUFFIX = ".rl"
# What the pinned release still calls its single-file form.
_LEGACY_SUFFIX = ".cl"

INSTALL_HINT = (
    f"Relate is not installed, and a bundle is a Relate file: run scripts/install-relate.sh from a checkout, or pip install "
    f"the neo4j_cypherlite {RELATE_VERSION} wheel for your platform from github.com/neo4j-labs/cypherlite/releases/tag/v{RELATE_VERSION}"
)


class RelateMissing(RuntimeError):
    """Neither `relate` nor `cypherlite` can be imported; `str()` is the install hint."""

    def __init__(self):
        super().__init__(INSTALL_HINT)


_module: ModuleType | None = None
_renamed = False  # True when the import is the renamed `relate` package, which opens `.rl` natively


def module() -> ModuleType:
    """The engine's Python package: `relate` when installed, else `cypherlite`; `RelateMissing` otherwise."""
    global _module, _renamed
    if _module is None:
        try:
            import relate as mod  # type: ignore[import-not-found]
            _renamed = True
        except ImportError:
            try:
                import cypherlite as mod  # type: ignore[import-not-found]
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


def _needs_legacy_suffix(path: Path) -> bool:
    module()
    return not _renamed and path.suffix != _LEGACY_SUFFIX


def connect(path: str | Path, *, read_only: bool):
    """A connection to the store at `path` (an `.rl` file, or `:memory:`). Prefer `open()` and
    `create()`, which handle the suffix of the pinned release; this is the raw call."""
    return module().connect(str(path), read_only=read_only)


@contextmanager
def open(path: str | Path, *, read_only: bool = True):  # noqa: A001  (the verb the engine uses)
    """A connection to an existing bundle, read-only unless asked otherwise, closed on exit."""
    target = Path(path)
    if str(path) == ":memory:" or not _needs_legacy_suffix(target) or target.is_dir():
        conn = connect(path, read_only=read_only)
        try:
            yield conn
        finally:
            conn.close()
        return
    if not target.is_file():
        raise FileNotFoundError(str(target))
    tmp = Path(tempfile.mkdtemp(prefix="aip-bundle-"))
    alias = tmp / ("bundle" + _LEGACY_SUFFIX)
    try:
        try:
            os.link(target, alias)
            linked = True
        except OSError:
            shutil.copyfile(target, alias)
            linked = False
        conn = connect(alias, read_only=read_only)
        try:
            yield conn
        finally:
            conn.close()
        if not read_only and not linked:  # a write through a copied alias has to travel back
            shutil.copyfile(alias, target)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def store_file(path: str | Path) -> Path:
    """Where a long-lived store asked for at `path` really sits. A server's store is one file it
    keeps open and writes for as long as it runs, so the link `open()` makes for a bundle will
    not do; until the rename ships, the file carries the pinned release's suffix instead
    (`store.rl` is kept as `store.cl`), and moving to the renamed engine is renaming the file."""
    target = Path(path)
    if str(path) == ":memory:" or not _needs_legacy_suffix(target):
        return target
    return target.with_suffix(_LEGACY_SUFFIX)


def store(path: str | Path):
    """A read-write connection to the store at `path` (`:memory:` for one that lives with the
    process), created when missing. The caller closes it, on the thread that opened it."""
    if str(path) == ":memory:":
        return connect(path, read_only=False)
    target = store_file(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    return connect(target, read_only=False)


@contextmanager
def create(path: str | Path):
    """A connection to a new, empty bundle at `path`, replacing any file there once the block
    completes; nothing is left behind when it raises."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not _needs_legacy_suffix(target):
        if target.exists():
            target.unlink()
        conn = connect(target, read_only=False)
        try:
            yield conn
        finally:
            conn.close()
        return
    tmp = target.with_name(target.name + ".tmp" + _LEGACY_SUFFIX)
    if tmp.exists():
        tmp.unlink()
    try:
        conn = connect(tmp, read_only=False)
        try:
            yield conn
        finally:
            conn.close()
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()
