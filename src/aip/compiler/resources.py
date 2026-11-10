"""Where the bundled example programs and the `aip` skill live.

The wheel carries the repository's `examples/` under `aip/compiler/examples/` and the entries of
`skills/aip/` under `aip/compiler/_skill/` (`[tool.hatch.build.targets.wheel.force-include]`
in `pyproject.toml`). One copy on disk in the repo, no duplicates to keep in sync. In an editable
checkout the wheel was never built, so both fall back to the repository root, found by walking up
from this module (`src/aip/compiler/`).

The example programs are the language's, under `examples/language/<name>/procedure.aip`. The
skill is the one page an agent reads to run and to write procedures, with the language on one
page beside it (`references/language.md`); `aip skill install` writes it into an agent."""

from importlib.resources import files
from pathlib import Path

SOURCE_FILE = "procedure.aip"
EXAMPLES_FOLDER = Path("examples") / "language"

# The entries of the skill, in `skills/aip/` and under `_skill/` in the wheel.
SKILL_ENTRIES = ("SKILL.md", "references")
SKILL_NAME = "aip"
# Skill names this tool used to install and has retired: the two skills of 0.7 and 0.8, which
# the one `aip` skill replaced in 0.9. `skill prune` removes their folders (with a frontmatter
# guard). `aip` itself was the authoring skill's name up to 0.6a1 and is the skill's name again:
# `skill install` overwrites that folder, so it is not pruned.
LEGACY_SKILL_NAMES = ("aip-compile", "aip-runtime")
SKILL_FOLDER = Path("skills") / "aip"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def skill_dir() -> Path:
    """The folder holding the `aip` skill's `SKILL.md` and `references/`."""
    bundled = Path(str(files("aip.compiler").joinpath("_skill")))
    if (bundled / "SKILL.md").is_file():
        return bundled
    checkout = _repo_root() / SKILL_FOLDER
    if (checkout / "SKILL.md").is_file():
        return checkout
    raise FileNotFoundError(f"the aip skill is neither bundled at {bundled} nor checked out at {checkout}")


def examples_dir() -> Path:
    """The folder of example programs, each a directory with a `procedure.aip`."""
    bundled = Path(str(files("aip.compiler").joinpath("examples"))) / "language"
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
