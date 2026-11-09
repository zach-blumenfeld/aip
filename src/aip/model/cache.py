"""The file cache: a bundle's files unpacked once per bundle id, where scripts launch from.

`aip_home()` is `AIP_HOME`, else `~/.aip`. A bundle's files land under
`<home>/cache/<bundle id>/` with their modes, written into a temporary sibling first and moved
into place in one step, so a second run of the same bundle (or a second process) finds the
directory complete or absent, never half written. The bundle id is a hash of the files, so a
directory that exists is the right one."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath

from aip_spec import FileEntry


def aip_home() -> Path:
    override = os.environ.get("AIP_HOME")
    return Path(override).expanduser() if override else Path.home() / ".aip"


def cache_dir(bundle_id: str, home: Path | None = None) -> Path:
    return (home or aip_home()) / "cache" / bundle_id


def unpack(bundle_id: str, files: list[FileEntry], home: Path | None = None) -> Path:
    """The directory holding the bundle's files, written on the first call for this id."""
    target = cache_dir(bundle_id, home)
    if target.is_dir():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f".{bundle_id[:12]}-", dir=target.parent))
    try:
        for f in files:
            path = tmp / Path(*PurePosixPath(f.path).parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f.data)
            try:
                os.chmod(path, f.mode)
            except OSError:  # pragma: no cover  (a filesystem without modes)
                pass
        try:
            os.rename(tmp, target)
        except OSError:
            if not target.is_dir():  # pragma: no cover  (another process won the race, or a real failure)
                raise
    finally:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
    return target


__all__ = ["aip_home", "cache_dir", "unpack"]
