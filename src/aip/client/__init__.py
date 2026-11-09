"""The client: the `aip` command (`cli.py`), its config (`config.py`), the bundle cache every
run runs from (`bundles.py`), run files and outcomes (`runs.py`), and the HTTP client
(`server.py`). The SDK the command wraps is `aip.sdk`."""

from pathlib import Path

# The `aip-runtime` skill of 0.8, bundled here until the 0.9 `aip` skill replaces it (plan
# aip-dev#1, K1); the repo copy is `skills/aip-runtime/SKILL.md`.
RUNTIME_SKILL = "aip-runtime"


def runtime_skill_dir() -> Path:
    """The bundled `aip-runtime/` folder (`SKILL.md` only)."""
    from importlib.resources import files

    return Path(str(files("aip.client").joinpath(RUNTIME_SKILL)))


def runtime_skill_text() -> str:
    return (runtime_skill_dir() / "SKILL.md").read_text(encoding="utf-8")
