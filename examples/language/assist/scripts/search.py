"""assist's `search` step: the catalog's procedures that may fit the task, and this session's runs,
as text for `plan`.

stdin `{"state": {"task": ...}}`; stdout `{"catalog": "..."}`. Each procedure the configured
server's search finds for the task (`aip search`), best first, with what it does, when to use it
and not, and its inputs with their types; then `build_procedure`, which is how `plan` makes one
when none fits; then the runs of this session so far (`AIP_SESSION`), newest first, so a later
turn of `aip agent` sees what the earlier ones did. With no server configured the catalog is the
procedures that ship with aip. It reads and changes nothing. `act.py` imports `entry`.
"""

from __future__ import annotations

import json
import os
import sys

HITS = 8
SELF = "assist"
BUILDER = "build_procedure"
RUNS = 12


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


def session_runs(client) -> str:
    session = os.environ.get("AIP_SESSION")
    if not session:
        return ""
    try:
        rows = [r for r in client.runs(session=session, limit=RUNS + 1) if r.name != SELF][:RUNS]
    except Exception as exc:  # the record is a help here, not a need
        return f"\n\nThis session's runs could not be listed: {exc}"
    if not rows:
        return f"\n\nThis session ({session}) has run nothing yet."
    lines = [f"- {r.run_id} {r.name}{'@' + r.revision if r.revision else ''}: {r.status}" for r in rows]
    return f"\n\nThis session's runs ({session}), newest first:\n" + "\n".join(lines)


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
            if path.stem != SELF:
                found.append(entry(path.stem, None, client.describe(path).data))
        header = "No server is configured, so the catalog is the procedures that ship with aip."
    print(json.dumps({"catalog": header + "\n\n" + "\n".join(found) + session_runs(client)}))


if __name__ == "__main__":
    main()
