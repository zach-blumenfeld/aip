"""Every test runs against an empty per-user config: `AIP_CONFIG` points into a temp directory,
so neither the client's `config.json` nor the server's `server.toml` in the developer's real
`~/.config/aip/` can leak in, and no `AIP_SERVER*` variable from the shell does either.
`AIP_HOME` points there too, so no run file, bundle or cache lands in the real `~/.aip/`.

The 0.9 engine's, CLI's and SDK's tests run. The 0.8 server tests under `tests/server/` and the
runtime-skill test are not collected until the milestones that rewrite those layers (S1 and K1
on aip-dev#1). `runtime_pending_test.py` is the one visible skip that says so."""

import pytest

collect_ignore = ["test_runtime_skill.py", "server", "fake_server.py"]


@pytest.fixture(autouse=True)
def _isolated_user_config(tmp_path_factory, monkeypatch):
    home = tmp_path_factory.mktemp("aip-config")
    monkeypatch.setenv("AIP_CONFIG", str(home / "config.json"))
    monkeypatch.setenv("AIP_HOME", str(home / "aip-home"))
    for var in ("AIP_SERVER", "AIP_SERVER_CONFIG", "AIP_TOKEN", "AIP_BATCH", "AIP_AGENT", "AIP_SESSION"):
        monkeypatch.delenv(var, raising=False)
