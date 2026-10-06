"""Every test runs against an empty per-user config: `AIP_CONFIG` points into a temp directory,
so neither the client's `config.json` nor the server's `server.toml` in the developer's real
`~/.config/aip/` can leak in, and no `AIP_SERVER*` variable from the shell does either."""

import pytest


@pytest.fixture(autouse=True)
def _isolated_user_config(tmp_path_factory, monkeypatch):
    home = tmp_path_factory.mktemp("aip-config")
    monkeypatch.setenv("AIP_CONFIG", str(home / "config.json"))
    for var in ("AIP_SERVER", "AIP_SERVER_CONFIG", "AIP_TOKEN"):
        monkeypatch.delenv(var, raising=False)
