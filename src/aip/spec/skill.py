"""Reading and validating an AIP skill folder.

A skill folder is an Agent Skill: `SKILL.md` with frontmatter, plus `scripts/`,
`assets/`, `references/`, and the AIP-required `source/` holding the human-readable
material the skill was compiled from. The SKILL.md body is exactly one fenced YAML
block, the procedure, with nothing but whitespace around it.

Validation issues follow one contract everywhere (CLI, wrapper script, server):
records with `path`, `kind`, `message`, optional `location`, and `severity`.
"""

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml
from pydantic import ValidationError

from aip.spec.models import FORMAT_VERSION, RUNNABLE_KINDS, ProcedureSpec

FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)
FENCE_PATTERN = re.compile(r"^```(?:yaml|yml)[ \t]*\n(.*?)\n```\s*$", re.DOTALL)
# Agent Skills `name` rule: lowercase a-z/0-9, hyphen-separated groups.
NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
VERSION_KEY = "aip-version"


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

    content = skill_md.read_text()
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
        return None, [Issue(path, "empty_body", "SKILL.md body is empty; expected one fenced YAML code block")]
    fence = FENCE_PATTERN.match(body)
    if not fence:
        return None, [Issue(path, "invalid_body_format",
                            "SKILL.md body must be exactly one fenced YAML code block (language tag `yaml` or `yml`) with no surrounding prose")]
    return SkillDoc(frontmatter=frontmatter, yaml_text=fence.group(1)), []


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
    elif isinstance(version, str) and version != FORMAT_VERSION:
        yield Issue(path, "aip_version_mismatch",
                    f"`metadata.{VERSION_KEY}` is `{version}` but this validator implements `{FORMAT_VERSION}`; "
                    f"update the skill or install a matching aip version", f"$.metadata.{VERSION_KEY}")


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


def _targets(step: Any) -> list[str]:
    if step.kind == "router":
        return list(step.branches.values())
    return [step.inputs_to] if getattr(step, "inputs_to", None) else []


def _resource_paths(step: Any) -> list[str]:
    paths: list[str] = []
    for attr in ("script", "template"):
        if getattr(step, attr, None):
            paths.append(getattr(step, attr))
    paths.extend(getattr(step, "assets", []) or [])
    paths.extend(r.path for r in getattr(step, "references", []) or [])
    return paths


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

    start = steps[0]
    if start.kind not in RUNNABLE_KINDS:
        issues.append(Issue(path, "invalid_start_step",
                            f"the first step is the start and must be a decision, execution, or client_task; got kind `{start.kind}`",
                            "body:$.steps[0].kind"))

    end_names = [s.name for s in steps if s.kind == "end"]
    if not end_names:
        issues.append(Issue(path, "missing_end_step", "procedure has no step of kind `end`", "body:$.steps"))
    elif len(end_names) > 1:
        issues.append(Issue(path, "multiple_end_steps", f"procedure must have exactly one `end` step; found {end_names}", "body:$.steps"))

    for i, step in enumerate(steps):
        for target in _targets(step):
            if target not in by_name:
                where = "branches" if step.kind == "router" else "inputs_to"
                issues.append(Issue(path, "unknown_step_reference",
                                    f"step `{step.name}` hands off to `{target}`, which is not a declared step", f"body:$.steps[{i}].{where}"))

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

    from_start = reachable(start.name)
    for i, step in enumerate(steps):
        if step.name not in from_start:
            issues.append(Issue(path, "unreachable_step", f"step `{step.name}` cannot be reached from the start step `{start.name}`", f"body:$.steps[{i}]"))
    if len(end_names) == 1:
        for i, step in enumerate(steps):
            if step.kind != "end" and end_names[0] not in reachable(step.name):
                issues.append(Issue(path, "no_path_to_end", f"step `{step.name}` has no path to the end step `{end_names[0]}`", f"body:$.steps[{i}]"))

    for i, step in enumerate(steps):
        seen_inputs: set[str] = set()
        for j, item in enumerate(getattr(step, "inputs", []) or []):
            if item.name in seen_inputs:
                issues.append(Issue(path, "duplicate_input_name", f"step `{step.name}` declares input `{item.name}` more than once",
                                    f"body:$.steps[{i}].inputs[{j}].name"))
            seen_inputs.add(item.name)
        if step.kind == "decision":
            for key in step.thresholds:
                if key not in step.questions:
                    issues.append(Issue(path, "unknown_threshold_question",
                                        f"step `{step.name}` sets a threshold for `{key}`, which is not one of its questions",
                                        f"body:$.steps[{i}].thresholds.{key}"))
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

    if any(i.severity == "error" for i in issues) or spec is None:
        return None, issues
    return LoadedSkill(skill_dir=skill_dir, frontmatter=doc.frontmatter, spec=spec), issues


def load_skill(skill_dir: Path) -> LoadedSkill:
    """Validate and return the skill, raising with every issue listed if it is invalid."""
    loaded, issues = validate_skill(skill_dir)
    if loaded is None:
        detail = "\n".join(f"  [{i.kind}] {i.message}" + (f" ({i.location})" if i.location else "") for i in issues)
        raise ValueError(f"Invalid AIP skill at {skill_dir}:\n{detail}")
    return loaded
