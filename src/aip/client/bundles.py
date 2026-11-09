"""The cache of bundles every run runs from (plan aip-dev#1, R3): `~/.aip/bundles/` (`AIP_HOME`).

Whatever `aip run` is given lands here first as a verified `.rl` under its bundle id:

    bundles/<bundle id>.rl        the bundle, written once per id (the id is its content hash)
    bundles/refs/<name>[@rev]     the id a catalog reference resolved to when it was pulled

A folder is compiled and written here; an `.rl` given by path is copied in after verification; a
catalog name is fetched from the server (`aip pull` does it ahead of time). `aip resume` reopens
the run's bundle from here by id, so a folder edited between run and resume does not change what
the run is of. The refs let `aip run <name>` work with no server reachable, on the revision last
pulled. Files are written to a temporary sibling and renamed into place, so the cache holds a
bundle whole or not at all.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from aip.compiler import Bundle, BundleError, read_bundle, write_bundle
from aip.compiler.bundle import BUNDLE_SUFFIX

from aip.model.cache import aip_home

REF = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*(@[A-Za-z0-9_.-]+)?$")


def bundles_dir(home: Path | None = None) -> Path:
    return (home or aip_home()) / "bundles"


def bundle_path(bundle_id: str, home: Path | None = None) -> Path:
    return bundles_dir(home) / f"{bundle_id}{BUNDLE_SUFFIX}"


def is_cached(bundle_id: str, home: Path | None = None) -> bool:
    return bundle_path(bundle_id, home).is_file()


def store(bundle: Bundle, home: Path | None = None) -> Path:
    """The cached `.rl` of a compiled bundle, written now if this id is new here."""
    target = bundle_path(bundle.id, home)
    if target.is_file():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{bundle.id[:12]}-{os.getpid()}{BUNDLE_SUFFIX}")
    try:
        write_bundle(bundle, tmp)
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()
    return target


def store_file(path: Path, home: Path | None = None) -> Bundle:
    """Verify an `.rl` given by path and copy it into the cache under its id."""
    bundle = read_bundle(path)
    target = bundle_path(bundle.id, home)
    if not target.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{bundle.id[:12]}-{os.getpid()}{BUNDLE_SUFFIX}")
        try:
            tmp.write_bytes(Path(path).read_bytes())
            os.replace(tmp, target)
        finally:
            if tmp.exists():
                tmp.unlink()
    return bundle


def store_bytes(data: bytes, home: Path | None = None, expected_id: str | None = None) -> Bundle:
    """Verify the bytes of a fetched `.rl` and cache them under the id they hold; `expected_id`
    is what the catalog said they were, refused when it differs."""
    folder = bundles_dir(home)
    folder.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".fetched-", suffix=BUNDLE_SUFFIX, dir=folder)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        bundle = read_bundle(tmp)
        if expected_id is not None and bundle.id != expected_id:
            raise BundleError("bundle_tampered", f"the catalog said bundle {expected_id[:12]}…, the file holds {bundle.id[:12]}…")
        target = bundle_path(bundle.id, home)
        if target.is_file():
            tmp.unlink()
        else:
            os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()
    return bundle


def load(bundle_id: str, home: Path | None = None) -> Bundle:
    """The verified bundle cached under `bundle_id`; `KeyError` when it is not here."""
    path = bundle_path(bundle_id, home)
    if not path.is_file():
        raise KeyError(bundle_id)
    return read_bundle(path)


def read_bytes(bundle_id: str, home: Path | None = None) -> bytes:
    return bundle_path(bundle_id, home).read_bytes()


# ------------------------------------------------------------------ catalog references

def is_ref(text: str) -> bool:
    """Whether `text` is shaped like a catalog reference, `name` or `name@rev`."""
    return bool(REF.match(text))


def split_ref(ref: str) -> tuple[str, str | None]:
    name, _, revision = ref.partition("@")
    return name, (revision or None)


def _ref_path(ref: str, home: Path | None) -> Path:
    return bundles_dir(home) / "refs" / ref


def remember(ref: str, bundle_id: str, revision: str | None, home: Path | None = None) -> None:
    """Record that `ref` resolved to `bundle_id` at `revision`: under the bare name (what it
    resolves to today) and under `name@rev`."""
    name, _ = split_ref(ref)
    refs = {name}
    if revision is not None:
        refs.add(f"{name}@{revision}")
    folder = bundles_dir(home) / "refs"
    folder.mkdir(parents=True, exist_ok=True)
    record = json.dumps({"bundle_id": bundle_id, "revision": revision}) + "\n"
    for r in refs:
        tmp = folder / f".{r}.{os.getpid()}"
        tmp.write_text(record, encoding="utf-8")
        os.replace(tmp, _ref_path(r, home))


def resolve_ref(ref: str, home: Path | None = None) -> tuple[str, str | None] | None:
    """`(bundle id, revision)` that `ref` last resolved to when it was pulled, if the bundle is
    still cached; None otherwise."""
    name, revision = split_ref(ref)
    path = _ref_path(name if revision in (None, "latest") else ref, home)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    return (data["bundle_id"], data.get("revision")) if is_cached(data["bundle_id"], home) else None


def cached_refs(home: Path | None = None) -> dict[str, dict]:
    """Every reference the cache knows, with its bundle id and revision."""
    folder = bundles_dir(home) / "refs"
    if not folder.is_dir():
        return {}
    out = {}
    for p in sorted(folder.iterdir()):
        if p.name.startswith("."):
            continue
        try:
            out[p.name] = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
    return out


__all__ = ["bundles_dir", "bundle_path", "is_cached", "store", "store_file", "store_bytes", "load", "read_bytes", "is_ref",
           "split_ref", "remember", "resolve_ref", "cached_refs"]
