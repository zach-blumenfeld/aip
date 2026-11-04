"""Reading and validating an AIP skill folder.

A skill folder is an Agent Skill: `SKILL.md` with frontmatter, plus `scripts/`,
`assets/`, `references/`, and the AIP-required `source/` holding the human-readable
material the skill was compiled from. The SKILL.md body is the AIP runtime block,
verbatim (see `runtime_text()`), followed by exactly one fenced YAML block, the
procedure, with nothing else. The block carries the execution semantics so any agent
that activates the skill can run it with no aip tooling present.

Validation issues follow one contract everywhere (CLI, wrapper script, server):
records with `path`, `kind`, `message`, optional `location`, and `severity` (`error`,
`warning` or `info`; an error fails validation, the other two never do).
"""

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml
from pydantic import ValidationError

from aip_spec.models import (
    DEFAULT_LAUNCHER, FORMAT_VERSION, LEGACY_VERSIONS, ProcedureSpec, runtime_text,
)

FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)
FENCE_PATTERN = re.compile(r"^```(?:yaml|yml)[ \t]*\n(.*?)\n```\s*$", re.DOTALL)
# Agent Skills `name` rule: lowercase a-z/0-9, hyphen-separated groups.
NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
VERSION_KEY = "aip-version"
SEVERITIES = ("error", "warning", "info")


@dataclass
class Issue:
    path: str
    kind: str
    message: str
    location: str | None = None
    severity: str = "error"

    def to_record(self) -> dict:
        record = {k: v for k, v in asdict(self).items() if v is not None}
        if record.get("severity") == "error":
            record.pop("severity")
        return record


@dataclass
class SkillDoc:
    """A parsed SKILL.md."""
    frontmatter: dict
    yaml_text: str


# ------------------------------------------------------------------------- parsing


def parse_skill_md(skill_md: Path) -> tuple[SkillDoc | None, list[Issue]]:
    path = str(skill_md)
    if not skill_md.is_file():
        return None, [Issue(path, "missing_skill_md", "Skill folder is missing required SKILL.md")]

    content = skill_md.read_text(encoding="utf-8")
    match = FRONTMATTER_PATTERN.match(content)
    if not match:
        return None, [Issue(path, "missing_frontmatter", "SKILL.md must begin with YAML frontmatter delimited by `---`")]
    try:
        frontmatter = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        return None, [Issue(path, "invalid_frontmatter", f"failed to parse frontmatter YAML: {exc}")]
    if not isinstance(frontmatter, dict):
        return None, [Issue(path, "invalid_frontmatter", f"frontmatter must be a mapping, got {type(frontmatter).__name__}")]

    body = match.group(2).strip()
    if not body:
        return None, [Issue(path, "empty_body", "SKILL.md body is empty; expected the AIP runtime block and one fenced YAML code block")]
    block, issues = runtime_text().strip(), []
    if not body.startswith(block):
        outdated = next((v for v in LEGACY_VERSIONS if body.startswith(runtime_text(v).strip())), None)
        if outdated is None:
            return None, [Issue(path, "missing_runtime_block",
                                f"SKILL.md body must begin with the {FORMAT_VERSION} AIP runtime block, verbatim "
                                f"(copy it from the aip skill, or `aip-spec runtime`)")]
        block = runtime_text(outdated).strip()
        issues.append(_outdated(path, outdated))
    rest = body[len(block):].strip()
    fence = FENCE_PATTERN.match(rest)
    if not fence:
        return None, [Issue(path, "invalid_body_format",
                            "after the runtime block, SKILL.md body must be exactly one fenced YAML code block "
                            "(language tag `yaml` or `yml`) with no other prose")]
    return SkillDoc(frontmatter=frontmatter, yaml_text=fence.group(1)), issues


# What a skill in each recognised earlier format must change, said as an upgrade, not a fault.
UPGRADES = {
    "0.5a1": "run `aip upgrade <folder>` (or `aip-spec upgrade <folder>`) for the mechanical part (the `start` step, "
             "no `thresholds`, `fallback: true` on each decision, the runtime block), then add outputs to each execution "
             "and client_task step and a requires block by hand",
    "0.6a0": "run `aip upgrade <folder>` (or `aip-spec upgrade <folder>`): it adds the `start` step, drops `thresholds`, "
             "sets `fallback: true` on each decision, and replaces the runtime block",
    "0.6a1": "run `aip upgrade <folder>` (or `aip-spec upgrade <folder>`): it adds the `start` step, drops `thresholds`, "
             "sets `fallback: true` on each decision, and replaces the runtime block",
}
# Earlier formats the current one still accepts: their skills load, with the upgrade said as a warning.
# A version in `LEGACY_VERSIONS` but not here is rejected (an error). 0.8 is breaking, so nothing older loads.
ACCEPTED_VERSIONS: tuple[str, ...] = ()


def _outdated(path: str, version: str) -> Issue:
    """The one issue a recognised earlier format gets; see `LEGACY_VERSIONS`."""
    edits = (f"{version} skill: {UPGRADES[version]} (`aip-spec runtime` prints the {FORMAT_VERSION} block; set "
             f"`metadata.{VERSION_KEY}` to \"{FORMAT_VERSION}\").")
    if version in ACCEPTED_VERSIONS:
        return Issue(path, "runtime_block_outdated",
                     f"{edits} Format {FORMAT_VERSION} still accepts {version} skills", severity="warning")
    return Issue(path, "runtime_block_outdated",
                 f"{edits} Format {FORMAT_VERSION} does not accept {version} skills; the errors below name what to edit")


# ---------------------------------------------------------------- frontmatter rules


def check_frontmatter(frontmatter: dict, skill_dir: Path) -> Iterable[Issue]:
    """Agent Skills frontmatter rules plus the single AIP key, `metadata.aip-version`."""
    path = str(skill_dir / "SKILL.md")

    name = frontmatter.get("name")
    if not name:
        yield Issue(path, "missing_required_frontmatter", "`name` is required in frontmatter (Agent Skills spec)", "$.name")
    elif not isinstance(name, str):
        yield Issue(path, "invalid_name", f"`name` must be a string; got {type(name).__name__}", "$.name")
    elif len(name) > 64:
        yield Issue(path, "invalid_name", f"`name` must be 1–64 characters; got {len(name)}", "$.name")
    elif not NAME_PATTERN.match(name):
        yield Issue(path, "invalid_name",
                    "`name` must contain only lowercase a–z, 0–9, and hyphens, with no leading/trailing and no consecutive hyphens", "$.name")
    elif name != skill_dir.resolve().name:
        yield Issue(path, "name_mismatch", f"`name` (`{name}`) must match the Skill's folder name (`{skill_dir.resolve().name}`)", "$.name")

    description = frontmatter.get("description")
    if description is None:
        yield Issue(path, "missing_required_frontmatter", "`description` is required in frontmatter (Agent Skills spec)", "$.description")
    elif not isinstance(description, str):
        yield Issue(path, "invalid_description", f"`description` must be a string; got {type(description).__name__}", "$.description")
    elif not description.strip():
        yield Issue(path, "invalid_description", "`description` must be a non-empty string", "$.description")
    elif len(description) > 1024:
        yield Issue(path, "invalid_description", f"`description` must be 1–1024 characters; got {len(description)}", "$.description")

    compatibility = frontmatter.get("compatibility")
    if compatibility is not None:
        if not isinstance(compatibility, str):
            yield Issue(path, "invalid_compatibility", f"`compatibility` must be a string when present; got {type(compatibility).__name__}", "$.compatibility")
        elif not 1 <= len(compatibility) <= 500:
            yield Issue(path, "invalid_compatibility", f"`compatibility` must be 1–500 characters; got {len(compatibility)}", "$.compatibility")

    for key, kind in (("allowed-tools", "invalid_allowed_tools"), ("license", "invalid_license")):
        value = frontmatter.get(key)
        if value is not None and not isinstance(value, str):
            yield Issue(path, kind, f"`{key}` must be a string when present; got {type(value).__name__}", f"$.{key}")

    metadata = frontmatter.get("metadata", {})
    if not isinstance(metadata, dict):
        yield Issue(path, "invalid_metadata", "`metadata` must be an object", "$.metadata")
        return
    for key, value in metadata.items():
        if not isinstance(value, str):
            yield Issue(path, "invalid_metadata",
                        f"`metadata.{key}` must be a string (Agent Skills spec: string→string mapping); got {type(value).__name__}",
                        f"$.metadata.{key}")

    version = metadata.get(VERSION_KEY)
    if version is None:
        yield Issue(path, "missing_aip_version",
                    f"missing required `metadata.{VERSION_KEY}` (the AIP format version this skill is written in)", f"$.metadata.{VERSION_KEY}")
    elif isinstance(version, str) and version in LEGACY_VERSIONS:
        yield _outdated(path, version)
    elif isinstance(version, str) and version != FORMAT_VERSION:
        yield Issue(path, "aip_version_mismatch",
                    f"`metadata.{VERSION_KEY}` is `{version}` but this validator implements `{FORMAT_VERSION}`; "
                    f"update the skill or install a matching aip-spec version", f"$.metadata.{VERSION_KEY}")


# ----------------------------------------------------------------------- the body


def parse_spec(yaml_text: str, path: str) -> tuple[ProcedureSpec | None, list[Issue]]:
    """Parse the YAML block into a ProcedureSpec, converting pydantic errors to Issues."""
    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        return None, [Issue(path, "invalid_body_yaml", f"failed to parse body YAML: {exc}")]
    if not isinstance(data, dict):
        return None, [Issue(path, "invalid_body", f"body must be a mapping, got {type(data).__name__}")]
    try:
        return ProcedureSpec.model_validate(data), []
    except ValidationError as exc:
        issues = []
        for err in exc.errors(include_url=False):
            loc = "body:$" + "".join(f"[{p}]" if isinstance(p, int) else f".{p}" for p in err["loc"])
            issues.append(Issue(path, "schema_violation", err["msg"], loc))
        return None, issues


def _edges(step: Any) -> list[tuple[str, str]]:
    """Every step a step hands off to, with the field that names it: a router's branches and
    its confidence check's `to`, everything else's `inputs_to`; the end step has none."""
    if step.kind == "router":
        edges = [(target, f"branches.{value}") for value, target in step.branches.items()]
        if step.confidence is not None:
            edges.append((step.confidence.to, "confidence.to"))
        return edges
    if step.kind == "end":
        return []
    return [(step.inputs_to, "inputs_to")]


def _targets(step: Any) -> list[str]:
    return [target for target, _ in _edges(step)]


def _resource_paths(step: Any) -> list[str]:
    paths: list[str] = []
    for attr in ("script", "template"):
        if getattr(step, attr, None):
            paths.append(getattr(step, attr))
    paths.extend(getattr(step, "assets", []) or [])
    paths.extend(r.path for r in getattr(step, "references", []) or [])
    return paths


def _consumed(step: Any) -> list[str]:
    """Keys a step reads from the state, in declaration order. The start step reads none: its
    inputs are what the client supplies. A router's confidence key is checked apart (it need
    only be declared on some path, not every path)."""
    if step.kind == "router":
        return [step.branch_on]
    if step.kind == "start":
        return []
    return [item.name for item in step.inputs]


def confidence_key(question: str) -> str:
    """The state key a decision's `confidence` list emits for a question. Fixed, not configurable."""
    return f"{question}_confidence"


def _produced(step: Any) -> list[str]:
    """Keys a step adds to the state. The start step adds its inputs, a decision its question
    names and the confidence keys it names; routers and the end step add none."""
    if step.kind == "start":
        return [item.name for item in step.inputs]
    if step.kind == "decision":
        return [*step.questions, *(confidence_key(q) for q in step.confidence)]
    return [item.name for item in getattr(step, "outputs", []) or []]


# The state type a collapsed answer lands as, per question type.
QUESTION_TYPES = {"noul": "boolean", "choice": "string", "score": "integer"}
# The type a confidence key carries (the vocabulary's number type), and what a router may branch on.
CONFIDENCE_TYPE = "float"
BRANCHABLE_TYPES = ("boolean", "string", "integer")


def _declarations(step: Any, i: int) -> list[tuple[str, str, str, str, str]]:
    """Every (key, type, what this step says, what it is when another step cites it, location)
    a step declares, in order: a start's inputs, a runnable step's inputs then outputs or
    questions and confidence keys, an end's inputs, a router's confidence key."""
    where = f"body:$.steps[{i}]"
    out: list[tuple[str, str, str, str, str]] = []
    if step.kind == "router":
        if step.confidence is not None:
            out.append((step.confidence.key, CONFIDENCE_TYPE, f"router `{step.name}` checks `{step.confidence.key}` as a `float`",
                        f"the confidence check of `{step.name}`", f"{where}.confidence.key"))
        return out
    for j, item in enumerate(step.inputs):
        noun = "start input" if step.kind == "start" else "input"
        out.append((item.name, item.type.value, f"step `{step.name}` declares {noun} `{item.name}` as `{item.type.value}`",
                    f"{noun} on `{step.name}`" if step.kind == "start" else f"input of `{step.name}`", f"{where}.inputs[{j}].type"))
    if step.kind == "decision":
        for qname, q in step.questions.items():
            out.append((qname, QUESTION_TYPES[q.type], f"step `{step.name}` answers `{qname}` with a {q.type} question, a `{QUESTION_TYPES[q.type]}`",
                        f"a {q.type} question in `{step.name}`", f"{where}.questions.{qname}"))
        for k, qname in enumerate(step.confidence):
            key = confidence_key(qname)
            out.append((key, CONFIDENCE_TYPE, f"step `{step.name}` emits `{key}`, the confidence of `{qname}`, a `float`",
                        f"the confidence of `{qname}` in `{step.name}`", f"{where}.confidence[{k}]"))
    for j, item in enumerate(getattr(step, "outputs", []) or []):
        out.append((item.name, item.type.value, f"step `{step.name}` declares output `{item.name}` as `{item.type.value}`",
                    f"output of `{step.name}`", f"{where}.outputs[{j}].type"))
    return out


def _availability(steps: list[Any], start: Any, preds: dict[str, list[Any]], by_name: dict[str, Any],
                  combine) -> dict[str, set[str] | None]:
    """The keys known to be in the state when each step is reached: a fixpoint over the graph,
    cycles included. `combine` is set intersection for must-availability (on every path) or
    union for may-availability (on some path). None marks a step nothing reaches."""
    available: dict[str, set[str] | None] = {s.name: None for s in steps}
    if start is not None:
        available[start.name] = set()
    changed = True
    while changed:
        changed = False
        for step in steps:
            if step is start or by_name.get(step.name) is not step:
                continue
            known = [available[p.name] | set(_produced(p)) for p in preds.get(step.name, []) if available[p.name] is not None]
            if not known:
                continue
            new = combine(*known)
            if new != available[step.name]:
                available[step.name], changed = new, True
    return available


def check_state(spec: ProcedureSpec, path: str, by_name: dict[str, Any], start: Any) -> list[Issue]:
    """The state contract: every consumed key has a producer on every path to its consumer
    (the start step produces its inputs), client tasks declare outputs, every declaration of a
    key agrees on its type, a router branches on a value it can match and checks a `float`. A
    key with several producers is reported as information, not a fault: a later producer
    overwrites the value where a run passes through both."""
    issues: list[Issue] = []
    steps = spec.steps
    index = {id(step): i for i, step in enumerate(steps)}

    # Rule 3: a client task's outputs are what the client is asked to answer with.
    for i, step in enumerate(steps):
        if step.kind == "client_task" and not step.outputs:
            issues.append(Issue(path, "missing_outputs",
                                f"client_task `{step.name}` declares no `outputs`; they are what the client is asked to "
                                f"answer with, so declare each key the answer adds to the state", f"body:$.steps[{i}]"))
        seen: set[str] = set()
        for j, item in enumerate(getattr(step, "outputs", []) or []):
            if item.name in seen:
                issues.append(Issue(path, "duplicate_output_name", f"step `{step.name}` declares output `{item.name}` more than once",
                                    f"body:$.steps[{i}].outputs[{j}].name"))
            seen.add(item.name)

    # Several producers of one key: allowed, and said, so authors and compilers see the overwrite.
    producers: dict[str, list[Any]] = {}
    for step in steps:
        for key in dict.fromkeys(_produced(step)):
            producers.setdefault(key, []).append(step)
    for key, makers in producers.items():
        if len(makers) > 1:
            names = ", ".join(f"`{s.name}`" + (" (a start input)" if s.kind == "start" else "") for s in makers)
            issues.append(Issue(path, "duplicate_producer",
                                f"key `{key}` has more than one producer: {names}; where a run passes through both, the "
                                f"later one overwrites the value", f"body:$.steps[{index[id(makers[1])]}]", severity="info"))

    # Rule 4: every declaration of a key agrees on its type. The first in step order is the reference.
    reference: dict[str, tuple[str, str]] = {}      # key -> (type, who declares it)
    for i, step in enumerate(steps):
        for key, type_, says, cited_as, location in _declarations(step, i):
            expected = reference.setdefault(key, (type_, cited_as))
            if expected[0] != type_:
                issues.append(Issue(path, "type_mismatch",
                                    f"{says}, but it is `{expected[0]}` ({expected[1]}); a key has one type everywhere it is declared",
                                    location))
    for i, step in enumerate(steps):
        if step.kind != "router":
            continue
        expected = reference.get(step.branch_on)
        if expected is not None and expected[0] not in BRANCHABLE_TYPES:
            issues.append(Issue(path, "unbranchable_type",
                                f"router `{step.name}` branches on `{step.branch_on}`, which is `{expected[0]}` ({expected[1]}); a "
                                f"router branches on a `boolean`, `string` or `integer`", f"body:$.steps[{i}].branch_on"))

    # Rule 1: keys available on every path (must-availability over the graph, cycles included).
    preds: dict[str, list[Any]] = {}
    for step in steps:
        for target in _targets(step):
            preds.setdefault(target, []).append(step)
    must = _availability(steps, start, preds, by_name, set.intersection)
    may = _availability(steps, start, preds, by_name, set.union)
    for i, step in enumerate(steps):
        have = must[step.name]
        if have is None:
            continue  # unreachable; reported elsewhere
        missing = [key for key in dict.fromkeys(_consumed(step)) if key not in have]
        if missing:
            keys = ", ".join(f"`{k}`" for k in missing)
            on_start = f" on the start step `{start.name}`" if start is not None else " on the start step"
            issues.append(Issue(path, "unproduced_input",
                                f"step `{step.name}` consumes {keys}, which no step produces on every path to it; declare "
                                f"them{on_start} if the client supplies them, or as `outputs` of an upstream step",
                                f"body:$.steps[{i}]"))
        if step.kind == "router" and step.confidence is not None and step.confidence.key not in (may[step.name] or set()):
            issues.append(Issue(path, "unproduced_input",
                                f"router `{step.name}` checks `{step.confidence.key}`, which no step produces on any path to it; "
                                f"name the question in a decision's `confidence` list (which emits `<question>_confidence`), or "
                                f"declare the key as an output of an upstream step", f"body:$.steps[{i}].confidence.key"))
    return issues


# ------------------------------------------------------------- the sources of a route

DETERMINISTIC, MEASURED, UNMEASURED = "deterministic", "measured", "unmeasured"
# Worst class wins when a branch key has several producers.
CLASS_RANK = {DETERMINISTIC: 0, MEASURED: 1, UNMEASURED: 2}


def _classify(router: Any, producer: Any) -> tuple[str, str]:
    """What kind of source one producer of a router's branch key is, and why in a phrase.

    Deterministic: a start input, or a script's output the router does not read a confidence
    from. Measured: a decision model (no fallback) whose confidence for the branch question the
    router checks, or a script or client task whose own declared number the router checks.
    Unmeasured: a decision the client may answer by hand, or a client task's output the router
    does not check. Probabilistic, with no calibrated number behind it."""
    check = router.confidence
    checked = check.key if check is not None else None
    key = router.branch_on
    if producer.kind == "start":
        return DETERMINISTIC, f"`{key}` is a start input"
    if producer.kind in ("execution", "client_task"):
        own = [o.name for o in producer.outputs]
        label = "script" if producer.kind == "execution" else "client task"
        if checked in own:
            return MEASURED, f"{label} `{producer.name}` declares `{checked}`, the number the router checks, beside `{key}`"
        if producer.kind == "execution":
            return DETERMINISTIC, f"`{key}` is an output of script `{producer.name}`"
        return UNMEASURED, (f"`{key}` is an output of client task `{producer.name}`, chosen by the client's own judgment, and "
                            f"the router checks no number the task declares")
    # a decision
    if producer.fallback:
        return UNMEASURED, f"decision `{producer.name}` answers `{key}` with `fallback: true`, so the client may have chosen it by hand"
    if key not in producer.confidence:
        return UNMEASURED, f"decision `{producer.name}` does not name `{key}` in its `confidence` list, so the model's confidence is not recorded"
    if checked != confidence_key(key):
        return UNMEASURED, f"decision `{producer.name}` emits `{confidence_key(key)}` but the router does not check it"
    return MEASURED, f"decision `{producer.name}` answers `{key}` with a decision model and the router checks `{checked}`"


def _sources(spec: ProcedureSpec) -> dict[str, list[tuple[Any, str, str]]]:
    """For each router, by name: every producer of its branch key from which the router can be
    reached, with the producer's class and the reason. The first step of each name counts."""
    by_name: dict[str, Any] = {}
    for step in spec.steps:
        by_name.setdefault(step.name, step)

    def reaches(from_name: str, target: str) -> bool:
        seen: set[str] = set()
        stack = [from_name]
        while stack:
            current = stack.pop()
            if current in seen or current not in by_name:
                continue
            seen.add(current)
            for nxt in _targets(by_name[current]):
                if nxt == target:
                    return True
                stack.append(nxt)
        return False

    sources: dict[str, list[tuple[Any, str, str]]] = {}
    for router in spec.steps:
        if router.kind != "router" or by_name[router.name] is not router:
            continue
        found = []
        for producer in spec.steps:
            if router.branch_on in _produced(producer) and reaches(producer.name, router.name):
                found.append((producer, *_classify(router, producer)))
        sources[router.name] = found
    return sources


def classify_sources(spec: ProcedureSpec) -> dict[str, str]:
    """The class of every router's source, by router name: `deterministic`, `measured` or
    `unmeasured`, the worst of its branch key's producers. The server stores it with the
    procedure so governance can report the runs that passed through an unmeasured route."""
    return {name: max((cls for _, cls, _ in found), key=CLASS_RANK.get, default=DETERMINISTIC)
            for name, found in _sources(spec).items()}


def check_sources(spec: ProcedureSpec, path: str) -> list[Issue]:
    """What the class of a route says to its author. A router whose check reads a number
    nothing calibrated (`confidence_on_unmeasured_source`), a router an LLM steers with
    nothing recorded (`unmeasured_route`), both warnings; a router checking a confidence a
    script or client task declared itself (`declared_confidence`), information. A
    deterministic route says nothing."""
    issues: list[Issue] = []
    index: dict[str, int] = {}
    for i, s in enumerate(spec.steps):
        index.setdefault(s.name, i)
    fix = ("decide the key with a decision model (`fallback: false`) that names the question in its `confidence` "
           "list, and check `<question>_confidence` on the router")
    for name, found in _sources(spec).items():
        router = spec.step(name)
        where = f"body:$.steps[{index[name]}]"
        worst = max((cls for _, cls, _ in found), key=CLASS_RANK.get, default=DETERMINISTIC)
        reasons = "; ".join(why for _, cls, why in found if cls == UNMEASURED)
        if worst == UNMEASURED and router.confidence is not None:
            issues.append(Issue(path, "confidence_on_unmeasured_source",
                                f"router `{name}` checks `{router.confidence.key}`, but its branch key `{router.branch_on}` is "
                                f"unmeasured: {reasons}; the check reads a number nothing calibrated. To measure the route, {fix}",
                                f"{where}.confidence", severity="warning"))
        elif worst == UNMEASURED:
            issues.append(Issue(path, "unmeasured_route",
                                f"router `{name}` branches on `{router.branch_on}`, which is unmeasured: {reasons}; a probabilistic "
                                f"choice routes the run and nothing records how sure it was. To measure the route, {fix}",
                                where, severity="warning"))
        for producer, cls, _ in found:
            if cls != MEASURED or producer.kind == "decision":
                continue
            if producer.kind == "execution":
                verdict = f"script `{producer.name}` declares itself; legitimate when the code behind it is calibrated"
            else:
                verdict = (f"client task `{producer.name}` declares itself; discouraged, because an agent cannot calibrate "
                           f"its own confidence. Prefer a decision step for the judgment")
            issues.append(Issue(path, "declared_confidence",
                                f"router `{name}` checks `{router.confidence.key}`, a confidence {verdict}",
                                f"{where}.confidence.key", severity="info"))
    return issues


# ----------------------------------------------------------------------- the graph


def check_requires(spec: ProcedureSpec, path: str) -> list[Issue]:
    """A procedure with execution steps declares the environment its scripts need, and each
    script is launched with the declared interpreter or one of the declared tools."""
    executions = [(i, s) for i, s in enumerate(spec.steps) if s.kind == "execution"]
    if not executions:
        return []
    if spec.requires is None:
        names = ", ".join(f"`{s.name}`" for _, s in executions)
        return [Issue(path, "missing_requires",
                      f"the procedure runs scripts ({names}) but declares no `requires`; add a `requires` block "
                      f"naming the interpreter and its minimum version, the packages, and the tools the scripts need",
                      "body:$.requires")]
    declared = {spec.requires.interpreter.name, *spec.requires.tools}
    issues = []
    for i, step in executions:
        launcher = step.command[0] if step.command else DEFAULT_LAUNCHER
        if launcher not in declared:
            how = "is launched with" if step.command else "has no `command`, so it is launched with"
            issues.append(Issue(path, "undeclared_launcher",
                                f"execution step `{step.name}` {how} `{launcher}`, which `requires` does not name; make it "
                                f"the interpreter or add it to `tools`", f"body:$.steps[{i}]"
                                + (".command[0]" if step.command else "")))
    return issues


def check_graph(spec: ProcedureSpec, path: str, skill_dir: Path | None = None) -> list[Issue]:
    """Graph checks the models cannot express. `skill_dir` enables resource existence checks."""
    issues: list[Issue] = []
    steps = spec.steps

    by_name: dict[str, Any] = {}
    for i, step in enumerate(steps):
        if step.name in by_name:
            issues.append(Issue(path, "duplicate_step_name", f"step name `{step.name}` is declared more than once", f"body:$.steps[{i}].name"))
        else:
            by_name[step.name] = step

    starts = [s for s in steps if s.kind == "start"]
    if not starts:
        issues.append(Issue(path, "missing_start_step",
                            "procedure has no step of kind `start`; add one holding the procedure's inputs, with `inputs_to` "
                            "naming the first runnable step", "body:$.steps"))
    elif len(starts) > 1:
        issues.append(Issue(path, "multiple_start_steps",
                            f"procedure must have exactly one `start` step; found {[s.name for s in starts]}", "body:$.steps"))
    start = starts[0] if starts else None

    end_names = [s.name for s in steps if s.kind == "end"]
    if not end_names:
        issues.append(Issue(path, "missing_end_step", "procedure has no step of kind `end`", "body:$.steps"))
    elif len(end_names) > 1:
        issues.append(Issue(path, "multiple_end_steps", f"procedure must have exactly one `end` step; found {end_names}", "body:$.steps"))

    for i, step in enumerate(steps):
        for target, where in _edges(step):
            if target not in by_name:
                issues.append(Issue(path, "unknown_step_reference",
                                    f"step `{step.name}` hands off to `{target}`, which is not a declared step", f"body:$.steps[{i}].{where}"))
            elif start is not None and target == start.name:
                issues.append(Issue(path, "edge_into_start",
                                    f"step `{step.name}` hands off to `{target}`, the start step; a run begins there and nothing "
                                    f"returns to it", f"body:$.steps[{i}].{where}"))

    for i, step in enumerate(steps):
        if step.kind != "decision":
            continue
        for k, qname in enumerate(step.confidence):
            if qname not in step.questions:
                issues.append(Issue(path, "unknown_confidence_question",
                                    f"decision `{step.name}` names `{qname}` in `confidence`, which is not one of its questions "
                                    f"{sorted(step.questions)}", f"body:$.steps[{i}].confidence[{k}]"))

    def reachable(from_name: str) -> set[str]:
        seen: set[str] = set()
        stack = [from_name]
        while stack:
            current = stack.pop()
            if current in seen or current not in by_name:
                continue
            seen.add(current)
            stack.extend(_targets(by_name[current]))
        return seen

    if start is not None:
        from_start = reachable(start.name)
        for i, step in enumerate(steps):
            if step.name not in from_start:
                issues.append(Issue(path, "unreachable_step", f"step `{step.name}` cannot be reached from the start step `{start.name}`", f"body:$.steps[{i}]"))
    if len(end_names) == 1:
        for i, step in enumerate(steps):
            if step.kind != "end" and end_names[0] not in reachable(step.name):
                issues.append(Issue(path, "no_path_to_end", f"step `{step.name}` has no path to the end step `{end_names[0]}`", f"body:$.steps[{i}]"))

    # Routers fed directly by a decision: branch keys must be answers that question can give.
    for i, step in enumerate(steps):
        if step.kind != "router":
            continue
        feeders = [s for s in steps if getattr(s, "inputs_to", None) == step.name and s.kind == "decision"]
        for feeder in feeders:
            question = feeder.questions.get(step.branch_on)
            if question is None:
                continue
            if question.type == "noul":
                allowed = {"true", "false"}
            elif question.type == "choice":
                allowed = set(question.criteria)
            else:
                allowed = {str(n) for n in range(len(question.criteria))}
            for key in step.branches:
                if key not in allowed:
                    issues.append(Issue(path, "unknown_branch_value",
                                        f"router `{step.name}` branches on `{step.branch_on}`, a {question.type} question in "
                                        f"`{feeder.name}`, but `{key}` is not one of its possible answers {sorted(allowed)}",
                                        f"body:$.steps[{i}].branches.{key}"))

    issues.extend(check_state(spec, path, by_name, start))
    issues.extend(check_sources(spec, path))
    issues.extend(check_requires(spec, path))

    for i, step in enumerate(steps):
        seen_inputs: set[str] = set()
        for j, item in enumerate(getattr(step, "inputs", []) or []):
            if item.name in seen_inputs:
                issues.append(Issue(path, "duplicate_input_name", f"step `{step.name}` declares input `{item.name}` more than once",
                                    f"body:$.steps[{i}].inputs[{j}].name"))
            seen_inputs.add(item.name)
        if skill_dir is not None:
            for rel in _resource_paths(step):
                if not (skill_dir / rel).is_file():
                    issues.append(Issue(path, "missing_resource",
                                        f"step `{step.name}` references `{rel}`, which does not exist under {skill_dir}", f"body:$.steps[{i}]"))
    return issues


# ------------------------------------------------------------------- entry points


@dataclass
class LoadedSkill:
    skill_dir: Path
    frontmatter: dict
    spec: ProcedureSpec
    # The class of each router's source (see `classify_sources`), by router name.
    routers: dict[str, str] = field(default_factory=dict)


def validate_skill(skill_dir: Path) -> tuple[LoadedSkill | None, list[Issue]]:
    """Run every check on a skill folder. Returns the loaded skill when there are no errors."""
    skill_dir = Path(skill_dir)
    path = str(skill_dir)
    if not skill_dir.exists():
        return None, [Issue(path, "file_not_found", "Skill path does not exist")]
    if not skill_dir.is_dir():
        return None, [Issue(path, "not_a_directory", "Skill path must be a directory (the Skill folder)")]

    doc, issues = parse_skill_md(skill_dir / "SKILL.md")
    if doc is None:
        return None, issues
    issues.extend(check_frontmatter(doc.frontmatter, skill_dir))

    source = skill_dir / "source"
    if not source.is_dir():
        issues.append(Issue(str(source), "missing_source_dir",
                            "Skill is missing required `source/` directory (the canonical human-readable material the skill was compiled from)"))

    spec, spec_issues = parse_spec(doc.yaml_text, str(skill_dir / "SKILL.md"))
    issues.extend(spec_issues)
    if spec is not None:
        issues.extend(check_graph(spec, str(skill_dir / "SKILL.md"), skill_dir))

    # an outdated block and an outdated version string are the same fact; say it once
    outdated = [i for i in issues if i.kind == "runtime_block_outdated"]
    if len(outdated) > 1:
        issues = [i for i in issues if i.kind != "runtime_block_outdated" or i is outdated[0]]
    if any(i.severity == "error" for i in issues) or spec is None:
        return None, issues
    return LoadedSkill(skill_dir=skill_dir, frontmatter=doc.frontmatter, spec=spec, routers=classify_sources(spec)), issues


def load_skill(skill_dir: Path) -> LoadedSkill:
    """Validate and return the skill, raising with every issue listed if it is invalid."""
    loaded, issues = validate_skill(skill_dir)
    if loaded is None:
        detail = "\n".join(f"  [{i.kind}] {i.message}" + (f" ({i.location})" if i.location else "") for i in issues)
        raise ValueError(f"Invalid AIP skill at {skill_dir}:\n{detail}")
    return loaded
