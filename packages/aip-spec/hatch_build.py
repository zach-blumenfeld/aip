"""Bundle the authoring skill and the examples into the `aip_spec` wheel.

They live once, at the repository root (`skills/aip-compile/` and `examples/`, two levels above
this package), so a wheel built from the checkout takes them from there. The sdist copies them
to `skills/aip-compile/` and `examples/` under its own root (`[tool.hatch.build.targets.sdist.
force-include]` in pyproject.toml), so a wheel built from an unpacked sdist, which is what
`uv build` and `pip install <sdist>` do, takes them from there instead. A static
`force-include` can name only one of the two places; this hook picks whichever exists."""

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

SKILL = Path("skills") / "aip-compile"
EXAMPLES = Path("examples")


class BundleSkillAndExamples(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict) -> None:
        root = Path(self.root)
        base = next((b for b in (root.parent.parent, root) if (b / SKILL / "SKILL.md").is_file()), None)
        if base is None or not (base / EXAMPLES).is_dir():
            raise FileNotFoundError(f"neither {root.parent.parent} nor {root} holds {SKILL}/SKILL.md and {EXAMPLES}/")
        force = build_data.setdefault("force_include", {})
        for entry in ("SKILL.md", "references", "assets"):
            force[str(base / SKILL / entry)] = f"aip_spec/_skill/{entry}"
        force[str(base / EXAMPLES)] = "aip_spec/examples"
