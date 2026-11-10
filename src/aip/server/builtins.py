"""The built-in bundles: procedures that ship inside the package and are in every catalog.

`publish_builtins(store)` runs when a server starts. Each `.rl` under `aip/server/bundles/` in
the installed package that this store has not been offered before is published under its
procedure's name, and the store remembers the bundle ids it has been offered. So a built-in
appears on a store's first start, a new version of one appears on the first start after the
upgrade that carries it, and one that was retired or superseded by hand stays that way: the
hook never offers the same bundle twice.

`make_procedure` is the one that ships: `bundles/make_procedure.rl`, compiled from
`examples/language/make_procedure/`. Whenever that folder changes, or the graph the compiler
derives does, compile it again and commit the file (`tests/test_make_procedure.py` fails when
the two disagree, and its message has the command):

    uv run aip compile examples/language/make_procedure -o src/aip/server/bundles/make_procedure.rl

Two compilations of one folder share a bundle id and differ byte for byte (spec section 3), so a
rebuild with nothing changed still shows as a modified file; do not commit that. `aip upgrade`
publishes the same files from a client, for a server that runs an older package than the client.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aip.compiler.bundle import BUNDLE_SUFFIX

JSON = dict[str, Any]

BUNDLES_DIR = Path(__file__).parent / "bundles"


def builtin_files(directory: Path | None = None) -> list[Path]:
    """The `.rl` files that ship with the package, by name."""
    root = BUNDLES_DIR if directory is None else Path(directory)
    return sorted(root.glob(f"*{BUNDLE_SUFFIX}")) if root.is_dir() else []


def publish_builtins(store: Any, directory: Path | None = None) -> list[JSON]:
    """Publish every built-in bundle this store has not been offered; returns what `publish`
    answered for each. A file that is not a usable bundle is a packaging error and raises."""
    files = builtin_files(directory)
    if not files:
        return []
    from aip.compiler import read_bundle
    from aip.server.app import describe_bundle

    offered = set(store.offered())
    published = []
    for path in files:
        bundle = read_bundle(path)
        if bundle.id in offered:
            continue
        published.append(store.publish(bundle, describe_bundle(bundle)))
        offered.add(bundle.id)
    if published:
        store.set_offered(sorted(offered))
    return published


__all__ = ["BUNDLES_DIR", "builtin_files", "publish_builtins"]
