"""Client: HTTP api, run/resume runner, and the `aip` CLI."""


def runtime_skill_text() -> str:
    """The `aip-runtime` meta-skill: the one page an agent reads to run published procedures
    through this client (`aip runtime --skill`). A plain Agent Skill, versioned with the format;
    the repo copy is `skills/aip-runtime/SKILL.md` and a test keeps the two identical."""
    from importlib.resources import files

    return files("aip.client").joinpath("aip-runtime", "SKILL.md").read_text(encoding="utf-8")
