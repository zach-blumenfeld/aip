"""Every test runs against an empty per-user config: `AIP_CONFIG` points into a temp directory,
so neither the client's `config.json` nor the server's `server.toml` in the developer's real
`~/.config/aip/` can leak in, and no `AIP_SERVER*` variable from the shell does either.
`AIP_HOME` points there too, so no run file or cache lands in the real `~/.aip/`.

The 0.9 engine's tests (`test_engine.py`) run. The 0.8 CLI, SDK, runner and server tests listed
below are not collected until the milestones that rewrite those layers (R3 and S1 on
aip-dev#1): they drive the 0.8 commands over the 0.8 model, which R1 replaced.
`runtime_pending_test.py` is the one visible skip that says so."""

import pytest

collect_ignore = ["test_cli_json.py", "test_client_execution.py", "test_runner.py", "test_runtime_skill.py", "test_sdk.py", "server"]


@pytest.fixture(autouse=True)
def _isolated_user_config(tmp_path_factory, monkeypatch):
    home = tmp_path_factory.mktemp("aip-config")
    monkeypatch.setenv("AIP_CONFIG", str(home / "config.json"))
    monkeypatch.setenv("AIP_HOME", str(home / "aip-home"))
    for var in ("AIP_SERVER", "AIP_SERVER_CONFIG", "AIP_TOKEN"):
        monkeypatch.delenv(var, raising=False)
