"""Every test runs against an empty per-user config: `AIP_CONFIG` points into a temp directory,
so neither the client's `config.json` nor the server's `server.toml` in the developer's real
`~/.config/aip/` can leak in, and no `AIP_SERVER*` variable from the shell does either.
`AIP_HOME` points there too, so no run file, bundle or cache lands in the real `~/.aip/`, and
`AIP_LOCAL_DATA` and `AIP_LOCAL_PORT` keep a test that asks for the local server (`aip config
server local`) away from the developer's own store and from a local server that may be running.

`served.py` is the real server in process, which the client's tests run against."""

import pytest

collect_ignore = ["served.py"]


@pytest.fixture(autouse=True)
def _isolated_user_config(tmp_path_factory, monkeypatch):
    home = tmp_path_factory.mktemp("aip-config")
    monkeypatch.setenv("AIP_CONFIG", str(home / "config.json"))
    monkeypatch.setenv("AIP_HOME", str(home / "aip-home"))
    monkeypatch.setenv("AIP_LOCAL_DATA", str(home / "local-server"))
    monkeypatch.setenv("AIP_LOCAL_PORT", "1")           # nothing listens there; a test that starts one picks its own
    for var in ("AIP_SERVER", "AIP_SERVER_CONFIG", "AIP_TOKEN", "AIP_BATCH", "AIP_AGENT", "AIP_SESSION", "AIP_LOCAL_IDLE",
                "AIP_RUNAH_MODEL_URI", "AIP_RUNAH_MODEL_KEY", "AIP_RUNAH_MODEL_NAME", "AIP_SCRIPT_TIMEOUT"):
        monkeypatch.delenv(var, raising=False)
