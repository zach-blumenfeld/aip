"""The procedure's `Requires` line, checked against the machine that runs its scripts.

A procedure with `Execute` steps declares `Requires <interpreter> <version>` (spec 2.1,
Header). The runtime checks it before the first `Execute` of a run and fails with one
`requires_unmet` error naming what is missing, so "this machine has Python 3.9" is told apart
from "the procedure has a bug". A passing check is remembered for the life of the `Requires`
object; a failing one is re-run, so a retry after installing the interpreter proceeds.

`script_timeout()` is how long one script may run: `AIP_SCRIPT_TIMEOUT`, else the value given
(the client passes `aip config --script-timeout`), else 300 seconds."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from aip.model.types import RequiresUnmet

PYTHON = "python"

_PROBE = 'import sys; print("%d.%d.%d" % sys.version_info[:3])'


SCRIPT_TIMEOUT_ENV = "AIP_SCRIPT_TIMEOUT"
DEFAULT_SCRIPT_TIMEOUT = 300.0
SCRIPT_TIMEOUT_HINT = "`aip config --script-timeout N` or AIP_SCRIPT_TIMEOUT"


def parse_script_timeout(raw: object, source: str = SCRIPT_TIMEOUT_ENV) -> float | None:
    """A script cap as configured: a number of seconds, or `0`, `none` or `inf` for no cap."""
    text = str(raw).strip().lower()
    if text in ("0", "none", "inf", "infinite"):
        return None
    try:
        value = float(text)
    except ValueError as err:
        raise ValueError(f"{source} must be a number of seconds, 0, or none; got {raw!r}") from err
    return value if value > 0 else None


def script_timeout(configured: object = None) -> float | None:
    """Seconds one script may run before it is killed, wherever a script runs (run, resume,
    runah): `AIP_SCRIPT_TIMEOUT`, else `configured` (the config file's), else 300. `0`, `none`
    or `inf` means no cap. It bounds scripts only; runah caps the model's turns by tool calls
    and tokens per task."""
    raw = os.environ.get(SCRIPT_TIMEOUT_ENV, "").strip()
    if raw:
        return parse_script_timeout(raw)
    if configured is not None and str(configured).strip():
        return parse_script_timeout(configured, "script_timeout in the config file")
    return DEFAULT_SCRIPT_TIMEOUT


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


def at_least(found: str | None, minimum: str | None) -> bool:
    """Whether a found version meets a dotted minimum, comparing the leading numbers."""
    if minimum is None:
        return True
    if found is None:
        return False
    match = re.match(r"\d+(\.\d+)*", found)
    if match is None:
        return False
    have, want = _version(match.group(0)), _version(minimum)
    width = max(len(have), len(want))
    return have + (0,) * (width - len(have)) >= want + (0,) * (width - len(want))


@dataclass
class Requires:
    """`Requires <interpreter> <version>`: a program name and the minimum version."""

    interpreter: str
    version: str | None = None
    _met: bool = field(default=False, init=False, repr=False)

    def ensure(self, step: str | None, python: Path | str | None = None) -> None:
        """Raise `RequiresUnmet` when the machine lacks the interpreter; a no-op once a check passed.
        `python` is the interpreter that runs `python` scripts (this process's own when None)."""
        if self._met:
            return
        missing = self.missing(python)
        if missing:
            raise RequiresUnmet(step, missing)
        self._met = True

    def missing(self, python: Path | str | None = None) -> list[str]:
        label = f"{self.interpreter}>={self.version}" if self.version else self.interpreter
        if self.interpreter == PYTHON:
            exe = str(python or sys.executable)
            found = self._probe(exe)
            if found is None:
                return [f"interpreter {label} (cannot run {exe})"]
            if not at_least(found, self.version):
                return [f"interpreter {label} (found {found})"]
            return []
        if shutil.which(self.interpreter) is None:
            return [f"interpreter {label} (not on PATH)"]
        if self.version is None:
            return []
        try:
            proc = subprocess.run([self.interpreter, "--version"], capture_output=True, text=True, timeout=30)
            match = re.search(r"\d+(\.\d+)+", proc.stdout + proc.stderr)
        except (OSError, subprocess.TimeoutExpired):
            match = None
        found = match.group(0) if match else None
        if not at_least(found, self.version):
            return [f"interpreter {label} (found {found or 'no version'})"]
        return []

    @staticmethod
    def _probe(python: str) -> str | None:
        try:
            proc = subprocess.run([python, "-c", _PROBE], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return proc.stdout.strip() if proc.returncode == 0 else None


__all__ = ["PYTHON", "Requires", "at_least", "script_timeout", "parse_script_timeout", "SCRIPT_TIMEOUT_ENV",
           "DEFAULT_SCRIPT_TIMEOUT", "SCRIPT_TIMEOUT_HINT"]
