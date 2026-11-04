"""An exclusive, blocking lock on an open file, on every platform the server runs on.

The filesystem backend serialises catalog rewrites and run appends across processes with one
lock per file. POSIX has `fcntl.flock`; native Windows has no `fcntl` module (#24), so there the
lock is `msvcrt.locking` on the first byte of the file, which is what the catalog lock file and
a run file have in common (the catalog lock file is empty; a byte range may lie past the end).

`msvcrt.locking` with `LK_LOCK` retries once a second for ten seconds and then raises `OSError`,
where `flock` waits indefinitely; the backend holds a lock for one read-and-write, so the
difference does not show in practice.
"""

from __future__ import annotations

import os
from typing import IO

if os.name == "nt":  # pragma: no cover - exercised on Windows only
    import msvcrt

    def lock_exclusive(fh: IO) -> None:
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)

    def unlock(fh: IO) -> None:
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def lock_exclusive(fh: IO) -> None:
        fcntl.flock(fh, fcntl.LOCK_EX)

    def unlock(fh: IO) -> None:
        fcntl.flock(fh, fcntl.LOCK_UN)
