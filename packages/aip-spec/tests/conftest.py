"""Every test gets its own `AIP_HOME`, so the install record `skill install` writes
(`skills.json`) never lands in the developer's real `~/.aip/`."""

import pytest


@pytest.fixture(autouse=True)
def _isolated_aip_home(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("AIP_HOME", str(tmp_path_factory.mktemp("aip-home")))
