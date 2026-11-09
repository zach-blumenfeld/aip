"""The filesystem backend's file lock: exclusive across open handles, and no Unix-only import
at module level, so `aip server --backend filesystem` starts on native Windows (#24)."""

import threading
import time
from pathlib import Path

import pytest

from aip.server.backends import filesystem
from aip.server.backends.filelock import lock_exclusive, unlock


def test_filesystem_backend_has_no_unconditional_fcntl_import():
    source = Path(filesystem.__file__).read_text()
    assert "fcntl" not in source


def test_lock_is_exclusive_across_handles(tmp_path):
    path = tmp_path / "catalog.lock"
    path.touch()
    released_at = []
    acquired_at = []
    holding = threading.Event()

    def holder():
        with open(path, "a+") as fh:
            lock_exclusive(fh)
            holding.set()
            time.sleep(0.3)
            released_at.append(time.monotonic())
            unlock(fh)

    def waiter():
        holding.wait()
        with open(path, "a+") as fh:
            lock_exclusive(fh)
            acquired_at.append(time.monotonic())
            unlock(fh)

    threads = [threading.Thread(target=holder), threading.Thread(target=waiter)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)
    assert acquired_at and released_at
    assert acquired_at[0] >= released_at[0]


def test_lock_can_be_taken_again_after_unlock(tmp_path):
    path = tmp_path / "run.jsonl"
    path.write_text("{}\n")
    for _ in range(3):
        with open(path, "r+") as fh:
            lock_exclusive(fh)
            assert fh.read() == "{}\n"
            unlock(fh)


@pytest.mark.parametrize("mode", ["a+", "r+"])
def test_lock_leaves_the_file_contents_alone(tmp_path, mode):
    path = tmp_path / "f"
    path.write_text("abc")
    with open(path, mode) as fh:
        lock_exclusive(fh)
        unlock(fh)
    assert path.read_text() == "abc"
