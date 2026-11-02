"""Installing Agent Skills into the agents on this machine.

An agent is detected by a marker directory under the home directory and has a skills
directory beside it; a skill is installed by copying its folder to
`<skills_dir>/<skill name>/`. The catalog mirrors neo4j-cli's and knowledge-index's so users
have one mental model across tools. `aip-spec skill install` installs the authoring skill
through this module, and `aip skill install` installs it and `aip-runtime` through the
same functions, so adding an agent is one line in `AGENTS`.

Paths are templates: `~` is `$HOME`, `$XDG_CONFIG_HOME` falls back to `~/.config`. They
resolve at call time, so tests can point `HOME` at a temporary directory."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

# What a skill folder may carry (Agent Skills layout plus AIP's `source/`); anything else
# beside them, such as a checkout's `src/`, is not part of the skill. A caller can narrow
# this per folder: the authoring skill is `SKILL.md`, `references/`, and `assets/` only.
SKILL_ENTRIES = ("SKILL.md", "scripts", "references", "assets", "source")
# A skill to install: its folder, or the folder with the entries to take from it.
Source = Path | tuple[Path, Sequence[str]]
IGNORE = shutil.ignore_patterns("__pycache__", ".DS_Store")


@dataclass(frozen=True)
class Agent:
    name: str
    display_name: str
    detect_dir: str
    skills_dir: str

    def detect_path(self) -> Path | None:
        return _expand(self.detect_dir)

    def skills_path(self) -> Path | None:
        return _expand(self.skills_dir)

    def detected(self) -> bool:
        path = self.detect_path()
        return path is not None and path.is_dir()

    def installed(self, skill_name: str) -> bool:
        skills = self.skills_path()
        return skills is not None and (skills / skill_name / "SKILL.md").is_file()


def _expand(template: str) -> Path | None:
    home = os.environ.get("HOME")
    if template == "~" or template.startswith("~/"):
        return Path(home) / template[2:] if home else None
    if "$XDG_CONFIG_HOME" in template:
        xdg = os.environ.get("XDG_CONFIG_HOME") or (str(Path(home) / ".config") if home else None)
        return Path(template.replace("$XDG_CONFIG_HOME", xdg)) if xdg else None
    return Path(template)


AGENTS: dict[str, Agent] = {a.name: a for a in (
    Agent("claude-code", "Claude Code", "~/.claude", "~/.claude/skills"),
    Agent("cursor", "Cursor", "~/.cursor", "~/.cursor/skills"),
    Agent("windsurf", "Windsurf", "~/.codeium/windsurf", "~/.codeium/windsurf/skills"),
    Agent("copilot", "Copilot", "~/.copilot", "~/.copilot/skills"),
    Agent("gemini-cli", "Gemini CLI", "~/.gemini", "~/.gemini/skills"),
    Agent("cline", "Cline", "~/.cline", "~/.agents/skills"),  # Cline reads ~/.agents/skills
    Agent("codex", "Codex", "~/.codex", "~/.codex/skills"),
    Agent("pi", "Pi", "~/.pi/agent", "~/.pi/agent/skills"),
    Agent("opencode", "OpenCode", "$XDG_CONFIG_HOME/opencode", "$XDG_CONFIG_HOME/opencode/skills"),
    Agent("junie", "Junie", "~/.junie", "~/.junie/skills"),
)}


class NoAgentDetected(Exception):
    pass


def lookup(name: str) -> Agent:
    try:
        return AGENTS[name.lower()]
    except KeyError:
        raise KeyError(f"unknown agent {name!r}; supported: {', '.join(AGENTS)}") from None


def detected_agents() -> list[Agent]:
    return [a for a in AGENTS.values() if a.detected()]


def skill_name(folder: Path) -> str:
    """The folder's frontmatter `name`; falls back to the folder name."""
    from aip_spec.skill import FRONTMATTER_PATTERN

    import yaml

    match = FRONTMATTER_PATTERN.match((folder / "SKILL.md").read_text())
    front = yaml.safe_load(match.group(1)) if match else None
    return front["name"] if isinstance(front, dict) and isinstance(front.get("name"), str) else folder.name


def write_skill(folder: Path, skills_dir: Path, entries: Sequence[str] = SKILL_ENTRIES) -> Path:
    """Copy `entries` of the skill at `folder` to `skills_dir/<name>/`, replacing what is there."""
    target = skills_dir / skill_name(folder)
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for entry in entries:
        src = folder / entry
        if src.is_file():
            shutil.copy2(src, target / entry)
        elif src.is_dir():
            shutil.copytree(src, target / entry, ignore=IGNORE)
    return target


def target_dirs(agent: str | None = None, path: Path | None = None) -> list[tuple[str, Path]]:
    """Where to install: `path` alone, one named agent, or every detected agent."""
    if path is not None:
        return [(str(path), Path(path).expanduser())]
    if agent is not None:
        a = lookup(agent)
        skills = a.skills_path()
        if skills is None:
            raise NoAgentDetected(f"cannot resolve {a.display_name}'s skills directory (HOME unset)")
        return [(a.display_name, skills)]
    found = [(a.display_name, a.skills_path()) for a in detected_agents() if a.skills_path() is not None]
    if not found:
        raise NoAgentDetected(f"no supported agent detected; pass one of {', '.join(AGENTS)}, or --path DIR")
    return found


def install(sources: Sequence[Source], agent: str | None = None, path: Path | None = None) -> list[tuple[str, Path]]:
    """Install every skill into each target. Returns (target label, written folder) pairs."""
    written = []
    for label, skills_dir in target_dirs(agent, path):
        for source in sources:
            folder, entries = source if isinstance(source, tuple) else (source, SKILL_ENTRIES)
            written.append((label, write_skill(Path(folder), skills_dir, entries)))
    return written


def remove(names: list[str], agent: str | None = None, path: Path | None = None) -> list[Path]:
    """Remove the named skills from one agent, `path`, or every agent that has one. Idempotent."""
    if path is not None:
        dirs = [Path(path).expanduser()]
    elif agent is not None:
        skills = lookup(agent).skills_path()
        dirs = [skills] if skills is not None else []
    else:
        dirs = [a.skills_path() for a in AGENTS.values() if any(a.installed(n) for n in names)]
    removed = []
    for skills_dir in dirs:
        for name in names:
            target = skills_dir / name
            if target.is_dir():
                shutil.rmtree(target)
                removed.append(target)
    return removed


def table(names: list[str]) -> str:
    """One row per supported agent: detected, which of `names` are installed, and the path."""
    rows = [("agent", "detected", "installed", "skills directory")]
    for a in AGENTS.values():
        have = [n for n in names if a.installed(n)]
        rows.append((a.name, "yes" if a.detected() else "no", ", ".join(have) or "-", str(a.skills_path() or "(HOME unset)")))
    widths = [max(len(r[i]) for r in rows) for i in range(3)]
    return "\n".join("  ".join(cell.ljust(widths[i]) if i < 3 else cell for i, cell in enumerate(row)) for row in rows)
