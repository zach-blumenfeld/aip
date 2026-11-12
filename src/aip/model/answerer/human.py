"""Which `Task_Agent` steps a person answers when nobody says (plan aip#29, R8).

`aip runah` stops for a person at the steps `--human` lists. With no `--human` it stops at the
steps written for a person: a step whose prompt (the `Prompt` file, else the description) opens
with the drafter's marker, which `build_procedure` and `edit_procedure` write, or whose
description says a person does it ("a person answers ...", "the person ..."). This module is the
one place that rule lives: the SDK applies it, the server puts its answer on a bundle's graph
(`human_steps`) and the console's run picker ticks what that says.
"""

from __future__ import annotations

import re
from typing import Any

PERSON_MARKER = "This is a task for a person, not for you"
"""How a task for a person opens (`build_procedure`'s `assets/draft.md`, `edit_procedure`'s `assets/rewrite.md`)."""

_NAMES_A_PERSON = re.compile(r"\b(a|the) (person|human)\b", re.IGNORECASE)


def for_a_person(description: str, prompt: str = "") -> bool:
    """Whether a task is a person's: its prompt or description opens with the marker, or its
    description says a person (or the person) does it."""
    def opens(text: str) -> bool:
        return (text or "").strip().lower().startswith(PERSON_MARKER.lower())

    return opens(prompt) or opens(description) or bool(_NAMES_A_PERSON.search(description or ""))


def human_steps(bundle: Any) -> list[str]:
    """The `Task_Agent` steps of a bundle that are a person's, in source order. `bundle` is a
    compiled `Bundle`, or a bundle's graph as JSON data whose `File` nodes carry their `text`
    (the server's); without the text, a step's description stands in for its prompt file."""
    if isinstance(bundle, dict):
        graph = bundle
        files = {str(n["properties"].get("path")): n["properties"].get("text") or ""
                 for n in graph.get("nodes", []) if "File" in n.get("labels", [])}
    else:
        graph = bundle.graph.to_dict(content=False)
        files = {f.path: f.data.decode("utf-8", errors="replace") for f in bundle.files}
    steps = [n["properties"] for n in graph.get("nodes", [])
             if "Step" in n.get("labels", []) and n["properties"].get("kind") == "Task_Agent"]
    steps.sort(key=lambda p: int(p.get("line") or 0))
    out = []
    for step in steps:
        description = step.get("description") or ""
        prompt = files.get(step.get("prompt") or "", "") if step.get("prompt") else ""
        if for_a_person(description, prompt or description):
            out.append(step["name"])
    return out


__all__ = ["PERSON_MARKER", "for_a_person", "human_steps"]
