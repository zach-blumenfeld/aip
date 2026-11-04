"""`aip-spec upgrade <folder>` (and `aip upgrade`): move a skill written for an earlier format
to the current one.

The mechanical part of the change to format 0.8, done as line edits so the skill's comments and
layout survive: the runtime block is replaced; a `start` step is inserted before the old first
step, carrying its `inputs` and pointing at it (the old step keeps its `inputs`, now consumed);
every `thresholds` block goes; every decision gets `fallback: true`, because a run in an earlier
format could always be answered by hand and the upgrade keeps that behaviour; and
`metadata.aip-version` becomes the current version. The edited text is parsed and compared with
the same change made on the parsed procedure, so a layout the line edits could not follow is
refused (`CannotUpgrade`) rather than written wrong. What the upgrade cannot do, it says: a
`confidence` list and a router check where the skill relied on review, `fallback: false` where a
decision model is required, and, for a 0.5a1 skill, the outputs and `requires` that format
lacked. The command validates the result afterwards; what the validator still rejects is the rest.
"""

import copy
import re
from dataclasses import dataclass, field

import yaml

from aip_spec.models import FORMAT_VERSION, LEGACY_VERSIONS, runtime_text
from aip_spec.skill import FRONTMATTER_PATTERN, VERSION_KEY

START_NAMES = ("start", "begin")
ITEM_PATTERN = re.compile(r"^(\s*)-\s+")
KEY_PATTERN = re.compile(r"([A-Za-z_][\w-]*):(?:\s|$)")
COMMENT_PATTERN = re.compile(r"^\s*(#.*)?$")
FENCE_PATTERN = re.compile(r"^```(yaml|yml)[ \t]*\n(.*?)\n```\s*$", re.DOTALL)


class CannotUpgrade(Exception):
    """The skill is not in a shape the upgrade can rewrite; nothing was changed."""


@dataclass
class Upgrade:
    version: str                  # the format the skill was in; `FORMAT_VERSION` when nothing needed doing
    text: str                     # the new SKILL.md
    changes: list[str] = field(default_factory=list)   # one line per edit made
    by_hand: list[str] = field(default_factory=list)   # what the upgrade could not do


# ---------------------------------------------------------------- the procedure


def upgraded(data: dict, start_name: str) -> dict:
    """The upgrade made on the parsed procedure: the reference the line edits must reproduce."""
    data = copy.deepcopy(data)
    steps = data["steps"]
    if not any(s.get("kind") == "start" for s in steps):
        first = steps[0]
        steps.insert(0, {"name": start_name, "kind": "start", "inputs": copy.deepcopy(first.get("inputs", [])),
                         "inputs_to": first["name"]})
    for step in steps:
        if step.get("kind") == "decision":
            step.pop("thresholds", None)
            step.setdefault("fallback", True)
    return data


def upgrade_procedure(yaml_text: str) -> tuple[str, list[str], list[str]]:
    """Rewrite the procedure block: the start step, no `thresholds`, `fallback: true` on each
    decision. Returns the new text, the changes made and what is left to do by hand."""
    data = yaml.safe_load(yaml_text)
    steps = data.get("steps") if isinstance(data, dict) else None
    if not isinstance(steps, list) or not steps:
        raise CannotUpgrade("the procedure has no `steps` list")
    if any(not isinstance(s, dict) or not isinstance(s.get("name"), str) for s in steps):
        raise CannotUpgrade("every step must be a mapping with a `name`")
    names = {s["name"] for s in steps}
    start_name = next((n for n in START_NAMES if n not in names), None)
    if start_name is None:
        raise CannotUpgrade(f"steps named {' and '.join(START_NAMES)} both exist; rename one so the start step can be called `start`")

    lines = yaml_text.split("\n")
    items, indent, column = _items(lines, len(steps))
    changes, by_hand, edits = [], [], []   # edits: (line index, lines removed, lines inserted)
    pad = " " * column

    if not any(s.get("kind") == "start" for s in steps):
        first, (begin, end) = steps[0], items[0]
        fields = _fields(lines, begin, end, column)
        block = [f"{indent}- name: {start_name}", f"{pad}kind: start"]
        if "inputs" in fields:
            block.extend(lines[fields["inputs"]:_block_end(lines, fields["inputs"], end, column)])
        else:
            block.append(f"{pad}inputs: []")
        block.extend([f"{pad}inputs_to: {first['name']}", ""])
        edits.append((begin, 0, block))
        count = len(first.get("inputs") or [])
        changes.append(f"inserted a `start` step named `{start_name}` before `{first['name']}`, carrying its "
                       f"{count} input{'s' if count != 1 else ''} and pointing at it")

    for step, (begin, end) in zip(steps, items):
        if step.get("kind") != "decision":
            continue
        fields = _fields(lines, begin, end, column)
        fallback = [f"{pad}fallback: true"] if "fallback" not in step else []
        if "thresholds" in step:
            if "thresholds" not in fields:
                raise CannotUpgrade(f"step `{step['name']}`: `thresholds` is not written as a field of its own line")
            at = fields["thresholds"]
            edits.append((at, _block_end(lines, at, end, column) - at, fallback))
            bounds = ", ".join(f"{q}: {b}" for q, b in (step["thresholds"] or {}).items())
            changes.append(f"`{step['name']}`: dropped `thresholds` ({bounds})")
            questions = ", ".join(step["thresholds"] or {})
            by_hand.append(f"`{step['name']}` reviewed its answers below those thresholds; if the skill relied on that, "
                           f"add `confidence: [{questions}]` to the decision and a `confidence: {{key: <question>_confidence, "
                           f"below: <bound>, to: <step>}}` check to the router that branches on its answer")
        elif fallback:
            at = fields.get("inputs_to", _item_end(lines, begin, end))
            edits.append((at, 0, fallback))
        if fallback:
            changes.append(f"`{step['name']}`: set `fallback: true`")

    for at, removed, inserted in sorted(edits, key=lambda e: e[0], reverse=True):
        lines[at:at + removed] = inserted
    text = "\n".join(lines)
    if yaml.safe_load(text) != upgraded(data, start_name):
        raise CannotUpgrade("the line edits did not reproduce the upgrade on this layout; make the edits by hand")
    if any(s.get("kind") == "decision" for s in steps):
        by_hand.append("every decision now says `fallback: true`, as a run in the earlier format could always be answered "
                       "by hand; set `fallback: false` where a decision model is required")
    return text, changes, by_hand


def _items(lines: list[str], count: int) -> tuple[list[tuple[int, int]], str, int]:
    """The line range of each item of the top-level `steps` list, the indent before each `- `
    and the column its fields start at. Refuses a `steps` not written as a block list."""
    at = next((i for i, line in enumerate(lines) if re.match(r"^steps:\s*(#.*)?$", line)), None)
    if at is None:
        raise CannotUpgrade("`steps:` is not a block list at the top level")
    first = next((i for i in range(at + 1, len(lines)) if not COMMENT_PATTERN.match(lines[i])), None)
    head = ITEM_PATTERN.match(lines[first]) if first is not None else None
    if head is None:
        raise CannotUpgrade("the first step is not written as a `- ` list item")
    indent, column = head.group(1), head.end()
    starts, stop = [], len(lines)
    for i in range(first, len(lines)):
        line = lines[i]
        if COMMENT_PATTERN.match(line):
            continue
        if line.startswith(f"{indent}- "):
            starts.append(i)
        elif len(line) - len(line.lstrip(" ")) <= len(indent):
            stop = i
            break
    if len(starts) != count:
        raise CannotUpgrade(f"found {len(starts)} `- ` items under `steps:` but the procedure has {count} steps")
    return [(s, e) for s, e in zip(starts, starts[1:] + [stop])], indent, column


def _fields(lines: list[str], begin: int, end: int, column: int) -> dict[str, int]:
    """The line of each field written at the item's field column (the first line's key included)."""
    fields = {}
    for i in range(begin, end):
        line = lines[i]
        if i != begin and not (line.startswith(" " * column) and not line[column:column + 1].isspace()):
            continue
        key = KEY_PATTERN.match(line[column:])
        if key:
            fields.setdefault(key.group(1), i)
    return fields


def _item_end(lines: list[str], begin: int, end: int) -> int:
    """The item's last line plus one, its trailing blank lines left outside."""
    while end > begin + 1 and not lines[end - 1].strip():
        end -= 1
    return end


def _block_end(lines: list[str], at: int, end: int, column: int) -> int:
    """Where the field at line `at` ends: the first following line, before `end`, that is not
    blank and not indented past the field column; trailing blank lines stay outside the block."""
    stop = at + 1
    while stop < end and (not lines[stop].strip() or len(lines[stop]) - len(lines[stop].lstrip(" ")) > column):
        stop += 1
    while stop > at + 1 and not lines[stop - 1].strip():
        stop -= 1
    return stop


# ------------------------------------------------------------------ the SKILL.md


def upgrade_skill_md(content: str) -> Upgrade:
    """The whole SKILL.md: the runtime block, the version in the frontmatter and the procedure."""
    match = FRONTMATTER_PATTERN.match(content)
    if not match:
        raise CannotUpgrade("SKILL.md does not begin with YAML frontmatter")
    frontmatter, body = match.group(1), match.group(2).strip()
    if body.startswith(runtime_text().strip()):
        return Upgrade(FORMAT_VERSION, content)
    version = next((v for v in LEGACY_VERSIONS if body.startswith(runtime_text(v).strip())), None)
    if version is None:
        raise CannotUpgrade("the body does not begin with a runtime block this version recognises "
                            f"({', '.join(LEGACY_VERSIONS)} or {FORMAT_VERSION})")
    fence = FENCE_PATTERN.match(body[len(runtime_text(version).strip()):].strip())
    if not fence:
        raise CannotUpgrade("after the runtime block, the body is not one fenced YAML block")

    new_frontmatter, replaced = re.subn(rf"^([ \t]*{VERSION_KEY}:[ \t]*).*$", rf'\g<1>"{FORMAT_VERSION}"', frontmatter, flags=re.M)
    if replaced != 1 or (yaml.safe_load(new_frontmatter).get("metadata") or {}).get(VERSION_KEY) != FORMAT_VERSION:
        raise CannotUpgrade(f"the frontmatter has no `metadata.{VERSION_KEY}` line to rewrite")
    procedure, changes, by_hand = upgrade_procedure(fence.group(2))
    changes = [f"replaced the {version} runtime block with the {FORMAT_VERSION} block",
               f'set `metadata.{VERSION_KEY}` to "{FORMAT_VERSION}"', *changes]
    if version == "0.5a1":
        by_hand.append("a 0.5a1 skill declares no `outputs` on its execution and client_task steps and no `requires`; "
                       "add them where the validator names them")
    text = f"---\n{new_frontmatter}\n---\n\n{runtime_text().strip()}\n\n```{fence.group(1)}\n{procedure}\n```\n"
    return Upgrade(version, text, changes, by_hand)
