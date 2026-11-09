"""Every test runs against an empty per-user config: `AIP_CONFIG` points into a temp directory,
so neither the client's `config.json` nor the server's `server.toml` in the developer's real
`~/.config/aip/` can leak in, and no `AIP_SERVER*` variable from the shell does either.
`AIP_HOME` points there too, so no run file lands in the real `~/.aip/runs/`.

Until the 0.9 runtime lands (plan milestones R1 to R3 on aip-dev#1), the 0.8 runtime's tests
here are not collected: they load skills through the 0.8 format, which L1 removed from
`aip_spec`, so every module would fail at import. `runtime_pending_test.py` is the one visible
skip that says so. R1 replaces `src/aip/model` and `src/aip/spec` and rewrites these tests."""

import pytest

collect_ignore_glob = ["test_*.py", "server"]


@pytest.fixture(autouse=True)
def _isolated_user_config(tmp_path_factory, monkeypatch):
    home = tmp_path_factory.mktemp("aip-config")
    monkeypatch.setenv("AIP_CONFIG", str(home / "config.json"))
    monkeypatch.setenv("AIP_HOME", str(home / "aip-home"))
    for var in ("AIP_SERVER", "AIP_SERVER_CONFIG", "AIP_TOKEN"):
        monkeypatch.delenv(var, raising=False)
