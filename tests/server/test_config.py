"""`aip server` configuration: the .env file, the TOML file, and their precedence under the
environment and the flags (`aip.server.config`)."""

from pathlib import Path

import pytest

from aip.server.config import (EXAMPLE, ConfigError, apply_config, decision_model_status, load_env_file,
                               parse_env_file, read_config)


def test_env_file_parses_comments_quotes_and_export():
    values = parse_env_file(
        "# comment\n\nTYPESAFE_API_KEY=abc\nexport NEO4J_PASSWORD='p w'\nX=\"a=b\"\nY=plain # trailing\n"
    )
    assert values == {"TYPESAFE_API_KEY": "abc", "NEO4J_PASSWORD": "p w", "X": "a=b", "Y": "plain"}


def test_env_file_rejects_garbage():
    with pytest.raises(ConfigError, match="line 1"):
        parse_env_file("not a pair\n")


def test_env_file_never_overrides_the_environment(tmp_path: Path):
    f = tmp_path / ".env"
    f.write_text("TYPESAFE_API_KEY=from-file\nNEO4J_URI=bolt://file\n")
    env = {"TYPESAFE_API_KEY": "from-env"}
    applied = load_env_file(f, env)
    assert applied == {"NEO4J_URI": "bolt://file"}
    assert env == {"TYPESAFE_API_KEY": "from-env", "NEO4J_URI": "bolt://file"}


def test_example_config_is_valid_and_complete(tmp_path: Path):
    f = tmp_path / "aip-server.toml"
    f.write_text(EXAMPLE)
    config = read_config(f)
    assert set(config) == {"server", "backend", "decision_model"}
    env: dict = {}
    defaults = apply_config(config, env)
    assert defaults["backend"] == "filesystem" and defaults["root"] == Path("~/.local/share/aip/server").expanduser()
    assert defaults["inspector"] is True and defaults["no_localhost"] is False
    assert env == {}                      # every secret in the example is commented out


def test_config_rejects_unknown_keys(tmp_path: Path):
    f = tmp_path / "c.toml"
    f.write_text("[server]\nprot = 1\n")
    with pytest.raises(ConfigError, match="unknown key server.prot"):
        read_config(f)
    f.write_text("[nope]\n")
    with pytest.raises(ConfigError, match=r"unknown table \[nope\]"):
        read_config(f)
    f.write_text('[backend]\nkind = "sqlite"\n')
    with pytest.raises(ConfigError, match="backend.kind"):
        read_config(f)


def test_config_fills_env_only_where_unset(tmp_path: Path):
    f = tmp_path / "c.toml"
    f.write_text(
        '[backend]\nkind = "neo4j"\nuri = "neo4j://file"\npassword = "file-pw"\ncache_dir = "~/c"\n'
        '[decision_model]\napi_key = "file-key"\nmodel = "jev-2"\n'
        '[server]\nport = 9000\nlocalhost_open = false\ninspector = "dist"\n'
    )
    env = {"NEO4J_URI": "neo4j://env"}
    defaults = apply_config(read_config(f), env)
    assert env == {"NEO4J_URI": "neo4j://env", "NEO4J_PASSWORD": "file-pw",
                   "TYPESAFE_API_KEY": "file-key", "TYPESAFE_DEFAULT_MODEL": "jev-2"}
    assert defaults == {"backend": "neo4j", "cache_dir": Path("~/c").expanduser(), "port": 9000,
                        "no_localhost": True, "inspector": str(Path("dist"))}


def test_decision_model_status():
    assert "none" in decision_model_status({})
    assert decision_model_status({"TYPESAFE_API_KEY": "k"}) == "decision model: TypeSafe jev-latest at https://api.typesafe.ai"
    assert "jev-2 at http://x" in decision_model_status({"TYPESAFE_API_KEY": "k", "TYPESAFE_DEFAULT_MODEL": "jev-2",
                                                          "TYPESAFE_BASE_URL": "http://x"})


def test_server_flags_override_config_which_overrides_defaults(tmp_path: Path, monkeypatch, capsys):
    """Through the real `aip server` parser: --example-config prints the file, and a bad config
    is a clean exit 1 naming the key."""
    from aip.client.cli import server_command

    monkeypatch.chdir(tmp_path)
    assert server_command(["--example-config"]) == 0
    assert capsys.readouterr().out == EXAMPLE
    (tmp_path / "aip-server.toml").write_text("[server]\nbogus = 1\n")
    assert server_command([]) == 1
    assert "unknown key server.bogus" in capsys.readouterr().err


def test_init_writes_the_user_file_and_the_server_finds_it(tmp_path: Path, monkeypatch, capsys):
    from aip.client.cli import server_command
    from aip.server.config import find_config, user_config_path

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AIP_CONFIG", str(tmp_path / "cfg" / "config.json"))   # moves the client dir, and ours with it
    monkeypatch.delenv("AIP_SERVER_CONFIG", raising=False)
    assert find_config(None) is None
    assert server_command(["--init"]) == 0
    target = tmp_path / "cfg" / "server.toml"
    assert user_config_path() == target and target.read_text() == EXAMPLE
    assert (target.stat().st_mode & 0o777) == 0o600
    assert str(target) in capsys.readouterr().out
    assert find_config(None) == target
    (tmp_path / "aip-server.toml").write_text("")
    assert find_config(None) == Path("aip-server.toml")              # the working directory wins
    assert find_config(Path("x.toml")) == Path("x.toml")             # the flag wins
    assert server_command(["--init"]) == 1                            # never overwrites
    assert "already exists" in capsys.readouterr().err
