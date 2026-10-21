"""The skill's `requires` block, checked against the machine that runs its scripts.

A procedure with execution steps declares the interpreter (and minimum version), the Python
packages, and the tools its scripts need. Whoever runs the scripts checks the block before the
first one and stops with one `requires_unmet` error naming every missing item, so "this machine
lacks numpy" is told apart from "the procedure has a bug". A passing check is remembered for the
life of the procedure; a failing one is re-run, so a retry after installing the package proceeds.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from aip.model.types import StepError, JSON

PYTHON = "python"

# Run in the scripts' interpreter: its version, and the installed version of each distribution.
_PROBE = """
import json, sys
from importlib import metadata
found = {}
for name in sys.argv[1:]:
    try:
        found[name] = metadata.version(name)
    except metadata.PackageNotFoundError:
        found[name] = None
print(json.dumps({"version": "%d.%d.%d" % sys.version_info[:3], "packages": found}))
"""


class RequiresUnmet(StepError, RuntimeError):
    """The machine lacks what the skill's `requires` block names. `missing` lists every item."""
    kind = "requires_unmet"

    def __init__(self, step: str | None, missing: List[str]):
        self.missing = list(missing)
        super().__init__(step, "this machine lacks what the skill requires: " + "; ".join(missing))

    def fields(self) -> JSON:
        return {"missing": self.missing}


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


def _at_least(found: str | None, minimum: str | None) -> bool:
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
    """The `requires` block. `interpreter` is a program name; `packages` are pip names,
    optionally `name>=version`; `tools` are executables on PATH."""
    interpreter: str
    version: str | None = None
    packages: List[str] = field(default_factory=list)
    tools: List[str] = field(default_factory=list)
    _met: bool = field(default=False, init=False, repr=False)

    def ensure(self, step: str | None, python: Path | None = None) -> None:
        """Raise `RequiresUnmet` naming every missing item; a no-op once a check has passed."""
        if self._met:
            return
        missing = self.missing(python)
        if missing:
            raise RequiresUnmet(step, missing)
        self._met = True

    def missing(self, python: Path | None = None) -> List[str]:
        """Every item this machine lacks, in declaration order. `python` is the interpreter that
        runs `python` scripts (the client's own when None)."""
        python_exe = str(python or sys.executable)
        wanted = [self._split(p) for p in self.packages]
        missing: List[str] = []

        probe: JSON | None = None
        if self.interpreter == PYTHON or wanted:
            probe = self._probe(python_exe, [name for name, _ in wanted])
        if self.interpreter == PYTHON:
            label = f"python>={self.version}" if self.version else "python"
            if probe is None:
                missing.append(f"interpreter {label} (cannot run {python_exe})")
            elif not _at_least(probe["version"], self.version):
                missing.append(f"interpreter {label} (found {probe['version']})")
        else:
            missing += self._program("interpreter", self.interpreter, self.version)

        for name, minimum in wanted:
            spec = f"{name}>={minimum}" if minimum else name
            found = (probe or {}).get("packages", {}).get(name)
            if found is None:
                missing.append(f"package {spec}")
            elif not _at_least(found, minimum):
                missing.append(f"package {spec} (found {found})")
        for tool in self.tools:
            missing += self._program("tool", tool, None)
        return missing

    @staticmethod
    def _split(package: str) -> tuple[str, str | None]:
        name, _, minimum = package.partition(">=")
        return name.strip(), minimum.strip() or None

    @staticmethod
    def _probe(python: str, packages: List[str]) -> JSON | None:
        try:
            proc = subprocess.run([python, "-c", _PROBE, *packages], capture_output=True, text=True, timeout=30)
            return json.loads(proc.stdout) if proc.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
            return None

    @staticmethod
    def _program(what: str, name: str, minimum: str | None) -> List[str]:
        """A program on PATH, at its minimum version when one is given (from `<name> --version`)."""
        label = f"{name}>={minimum}" if minimum else name
        if shutil.which(name) is None:
            return [f"{what} {label} (not on PATH)"]
        if minimum is None:
            return []
        try:
            proc = subprocess.run([name, "--version"], capture_output=True, text=True, timeout=30)
            match = re.search(r"\d+(\.\d+)+", proc.stdout + proc.stderr)
        except (OSError, subprocess.TimeoutExpired):
            match = None
        found = match.group(0) if match else None
        if not _at_least(found, minimum):
            return [f"{what} {label} (found {found or 'no version'})"]
        return []


__all__ = ["PYTHON", "Requires", "RequiresUnmet"]
