"""Where the bundled example programs and the authoring skill live.

The wheel carries the repository's `examples/` under `aip_spec/examples/` and the entries of
`skills/aip-compile/` under `aip_spec/_skill/` (`hatch_build.py`). One copy on disk in the repo,
no duplicates to keep in sync. In an editable checkout the wheel was never built, so both fall
back to the repository root, found by walking up from this module (`packages/aip-spec/src/aip_spec/`).

The example programs are the language's, under `examples/language/<name>/procedure.aip`. The
skill entries stay here for the runtime's `aip skill install` until the 0.9 skill replaces them."""

from importlib.resources import files
from pathlib import Path

SOURCE_FILE = "procedure.aip"
EXAMPLES_FOLDER = Path("examples") / "language"

# The entries of the authoring skill, in `skills/aip-compile/` and under `_skill/` in the wheel.
SKILL_ENTRIES = ("SKILL.md", "references", "assets")
SKILL_NAME = "aip-compile"
# Skill names this tool used to install and has retired: `aip`, the authoring skill up to 0.6a1.
# `skill prune` removes their folders (with a frontmatter guard); the table only grows.
LEGACY_SKILL_NAMES = ("aip",)
SKILL_FOLDER = Path("skills") / "aip-compile"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def skill_dir() -> Path:
    """The folder holding the authoring skill's `SKILL.md`, `references/`, and `assets/`."""
    bundled = Path(str(files("aip_spec").joinpath("_skill")))
    if (bundled / "SKILL.md").is_file():
        return bundled
    checkout = _repo_root() / SKILL_FOLDER
    if (checkout / "SKILL.md").is_file():
        return checkout
    raise FileNotFoundError(f"the authoring skill is neither bundled at {bundled} nor checked out at {checkout}")


def examples_dir() -> Path:
    """The folder of example programs, each a directory with a `procedure.aip`."""
    bundled = Path(str(files("aip_spec").joinpath("examples"))) / "language"
    if bundled.is_dir():
        return bundled
    root = _repo_root() / EXAMPLES_FOLDER
    if root.is_dir():
        return root
    raise FileNotFoundError(f"examples are neither bundled at {bundled} nor checked out at {root}")


def example_names() -> list[str]:
    return sorted(p.name for p in examples_dir().iterdir() if (p / SOURCE_FILE).is_file())


def example_dir(name: str) -> Path:
    """The bundled example program called `name`, such as `billing-support`."""
    folder = examples_dir() / name
    if not (folder / SOURCE_FILE).is_file():
        raise FileNotFoundError(f"no bundled example {name!r}; have {example_names()}")
    return folder
