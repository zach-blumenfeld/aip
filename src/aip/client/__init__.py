"""Client: HTTP api, run/resume runner, and the `aip` CLI."""

from pathlib import Path

# The `aip-runtime` meta-skill: the one page an agent reads to run published procedures
# through this client. A plain Agent Skill, versioned with the format; the repo copy is
# `skills/aip-runtime/SKILL.md` and a test keeps the two identical.
RUNTIME_SKILL = "aip-runtime"


def runtime_skill_dir() -> Path:
    """The bundled `aip-runtime/` folder (`SKILL.md` only), what `aip skill install` copies."""
    from importlib.resources import files

    return Path(str(files("aip.client").joinpath(RUNTIME_SKILL)))


def runtime_skill_text() -> str:
    """The text of the bundled `aip-runtime` skill (`aip runtime --skill` prints it)."""
    return (runtime_skill_dir() / "SKILL.md").read_text(encoding="utf-8")
