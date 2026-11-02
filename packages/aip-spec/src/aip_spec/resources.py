"""Where the bundled authoring skill and examples live.

The wheel carries the repo's root `SKILL.md`, `references/`, and `assets/` under
`aip_spec/_skill/`, and `examples/` under `aip_spec/examples/` (hatchling `force-include`
in pyproject.toml). One file on disk in the repo, no copies to keep in sync. In an editable
checkout the wheel was never built, so both fall back to the repo root, found by walking up
from this module."""

from importlib.resources import files
from pathlib import Path

# The entries of the authoring skill, at the repo root and under `_skill/` in the wheel.
SKILL_ENTRIES = ("SKILL.md", "references", "assets")
SKILL_NAME = "aip"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def skill_dir() -> Path:
    """The folder holding the authoring skill's `SKILL.md`, `references/`, and `assets/`.

    In the wheel this is `aip_spec/_skill/`, which holds nothing else. In a checkout it is
    the repo root, so take `SKILL_ENTRIES` from it rather than the whole directory."""
    bundled = Path(str(files("aip_spec").joinpath("_skill")))
    if (bundled / "SKILL.md").is_file():
        return bundled
    root = _repo_root()
    if (root / "SKILL.md").is_file():
        return root
    raise FileNotFoundError(f"the authoring skill is neither bundled at {bundled} nor checked out at {root}")


def examples_dir() -> Path:
    bundled = Path(str(files("aip_spec").joinpath("examples")))
    if bundled.is_dir():
        return bundled
    root = _repo_root() / "examples"
    if root.is_dir():
        return root
    raise FileNotFoundError(f"examples are neither bundled at {bundled} nor checked out at {root}")


def example_names() -> list[str]:
    return sorted(p.name for p in examples_dir().iterdir() if (p / "SKILL.md").is_file())


def example_dir(name: str) -> Path:
    """The bundled example skill folder called `name`, such as `billing-support`."""
    folder = examples_dir() / name
    if not (folder / "SKILL.md").is_file():
        raise FileNotFoundError(f"no bundled example {name!r}; have {example_names()}")
    return folder
