"""assist's `search` step: the catalog's procedures that may fit the task, as text for the planner.

stdin `{"state": {"task": ...}}`; stdout `{"catalog": "..."}`. Each procedure the configured
server's search finds for the task (`aip search`), best first, with what it does, when to use it
and not, and its inputs with their types; then `build_procedure`, which is how the planner makes
one when none fits. With no server configured the catalog is the procedures that ship with aip,
which `act` runs from their bundles. It reads the catalog and changes nothing.
"""

from __future__ import annotations

import json
import sys

HITS = 8
SELF = "assist"
BUILDER = "build_procedure"


def entry(name: str, revision: str | None, data: dict) -> str:
    """One procedure as the planner reads it."""
    head = f"- {name}" + (f"@{revision}" if revision else "") + f": {' '.join((data.get('description') or '').split())}"
    lines = [head]
    for label, key in (("use when", "use_when"), ("do not use when", "do_not_use_when")):
        for text in data.get(key) or []:
            lines.append(f"    {label}: {' '.join(text.split())}")
    described = data.get("input_descriptions") or {}
    inputs = data.get("inputs") or {}
    if inputs:
        lines.append("    inputs:")
        for key, type_ in inputs.items():
            lines.append(f"      {key} ({type_ or 'any'}): {' '.join((described.get(key) or '').split())}".rstrip(": "))
    else:
        lines.append("    inputs: none")
    return "\n".join(lines)


def main() -> None:
    task = json.load(sys.stdin)["state"]["task"]
    from aip import Client
    from aip.server.builtins import builtin_files

    client = Client()
    found: list[str] = []
    seen: set[str] = set()
    if client.server is not None:
        for hit in client.search(task, limit=HITS):
            if hit.name in seen or hit.name == SELF:
                continue
            seen.add(hit.name)
            try:
                found.append(entry(hit.name, hit.revision, client.describe(hit.name).data))
            except Exception as exc:  # a name that cannot be described is listed bare
                found.append(f"- {hit.name}: {hit.description or ''} (could not describe it: {exc})")
        if BUILDER not in seen:
            found.append(entry(BUILDER, None, client.describe(BUILDER).data))
        header = f"{len(seen)} procedure(s) found for the task, best first; build_procedure last, to build one when none fits."
    else:
        for path in builtin_files():
            name = path.stem
            if name != SELF:
                found.append(entry(name, None, client.describe(path).data))
        header = "No server is configured, so the catalog is the procedures that ship with aip."
    print(json.dumps({"catalog": header + "\n\n" + "\n".join(found)}))


if __name__ == "__main__":
    main()
