"""How `aip server` is configured: a TOML file, a `.env` file, the environment, and flags.

Precedence, highest first:

1. command-line flags (`aip server --port 9000`)
2. the environment, including a `.env` file loaded into it (`load_env_file`; a variable
   already set in the real environment is never overridden by the file)
3. the config file (`aip-server.toml`; `read_config` parses it, `apply_config` turns it
   into flag defaults and fills in unset environment variables)
4. built-in defaults

The config file has three tables. `[server]` is the listener: `host`, `port`, `token`,
`read_token`, `localhost_open`, `inspector`, `log_level`. `[backend]` picks the store:
`kind` (`filesystem` or `neo4j`), `root` for the filesystem, `uri`, `user`, `password`,
`database`, `cache_dir` for Neo4j. `[decision_model]` is the TypeSafe client every decision
step uses: `api_key`, `base_url`, `model`. Without an `api_key` (here or as
`TYPESAFE_API_KEY`) the server answers no decisions; every decision step pauses for the
client to answer. The Neo4j and decision-model values are applied by setting their
`NEO4J_*` and `TYPESAFE_*` environment variables when unset, since the Neo4j connection
and the TypeSafe SDK read those; that is what makes rule 2 beat rule 3 for them too.

The file is looked up as `--config FILE`, then `$AIP_SERVER_CONFIG`, then `./aip-server.toml`,
then the per-user `~/.config/aip/server.toml` (`user_config_path`, beside the client's
`config.json`). `aip server --init` writes the complete commented `EXAMPLE` there, which is
how an installed user, with no repo, configures the server: run `--init`, edit the file it
names, run `aip server`. `--example-config` prints the same text.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any, Dict

JSON = Dict[str, Any]

CONFIG_FILE = "aip-server.toml"
CONFIG_ENV = "AIP_SERVER_CONFIG"
ENV_FILE = ".env"
USER_CONFIG_NAME = "server.toml"
DEFAULT_ROOT = Path("~/.local/share/aip/server")   # the filesystem backend's catalog and runs

# config key -> (environment variable, ) for the values the libraries read from the environment
_ENV_KEYS = {
    ("backend", "uri"): "NEO4J_URI",
    ("backend", "user"): "NEO4J_USERNAME",
    ("backend", "password"): "NEO4J_PASSWORD",
    ("backend", "database"): "NEO4J_DATABASE",
    ("decision_model", "api_key"): "TYPESAFE_API_KEY",
    ("decision_model", "base_url"): "TYPESAFE_BASE_URL",
    ("decision_model", "model"): "TYPESAFE_DEFAULT_MODEL",
}

# config key -> argparse destination, for the values only flags carry
_FLAG_KEYS = {
    ("server", "host"): "host",
    ("server", "port"): "port",
    ("server", "token"): "token",
    ("server", "read_token"): "read_token",
    ("server", "inspector"): "inspector",
    ("server", "log_level"): "log_level",
    ("backend", "kind"): "backend",
    ("backend", "root"): "root",
    ("backend", "cache_dir"): "cache_dir",
}

_KNOWN = {
    "server": {"host", "port", "token", "read_token", "localhost_open", "inspector", "log_level"},
    "backend": {"kind", "root", "uri", "user", "password", "database", "cache_dir"},
    "decision_model": {"api_key", "base_url", "model"},
}

EXAMPLE = """\
# aip server configuration. `aip server` reads this from ~/.config/aip/server.toml
# (`aip server --init` writes it there), from ./aip-server.toml, or from `--config FILE`.
# Flags override the environment, the environment overrides this file.

[server]
host = "127.0.0.1"        # keep on localhost unless `token` is set: publishing runs code here
port = 8000
# token = "..."           # bearer token for read + publish; `read_token` grants read only
# read_token = "..."
localhost_open = true     # loopback clients need no token
inspector = true          # serve the web client at /inspector/; or a path to a built dist/
log_level = "info"

[backend]
kind = "filesystem"       # or "neo4j"
root = "~/.local/share/aip/server"   # filesystem: where the catalog and runs live
# uri = "neo4j://localhost:7687"   # neo4j: or NEO4J_URI
# user = "neo4j"                   # or NEO4J_USERNAME
# password = "..."                 # or NEO4J_PASSWORD
# database = "neo4j"               # or NEO4J_DATABASE
# cache_dir = "~/.cache/aip"       # neo4j: where revisions are materialised to run

[decision_model]
# The TypeSafe client that answers decision steps. Without an api_key (here or as
# TYPESAFE_API_KEY) the server answers no decisions and every decision step pauses for
# the client to answer by hand.
# api_key = "..."                  # or TYPESAFE_API_KEY
# base_url = "https://api.typesafe.ai"   # or TYPESAFE_BASE_URL (this is the default)
# model = "jev-latest"             # or TYPESAFE_DEFAULT_MODEL (this is the default)
"""


class ConfigError(ValueError):
    """A config or env file that cannot be used, with the path and what is wrong."""


def user_config_path() -> Path:
    """`~/.config/aip/server.toml`: next to the client's `config.json` (so `AIP_CONFIG` moves both)."""
    from aip.client.server import config_path

    return config_path().parent / USER_CONFIG_NAME


def find_config(explicit: Path | None, environ: Dict[str, str] | None = None) -> Path | None:
    """The config file to use: `--config`, `$AIP_SERVER_CONFIG`, `./aip-server.toml`, the user file."""
    environ = os.environ if environ is None else environ
    if explicit is not None:
        return explicit
    if environ.get(CONFIG_ENV):
        return Path(environ[CONFIG_ENV])
    for candidate in (Path(CONFIG_FILE), user_config_path()):
        if candidate.is_file():
            return candidate
    return None


def write_example(path: Path) -> Path:
    """Write `EXAMPLE` to `path`, mode 0600 (it may come to hold keys). Refuses to overwrite."""
    if path.exists():
        raise ConfigError(f"{path} already exists; edit it, or remove it to start over")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(EXAMPLE)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


# ------------------------------------------------------------------------------ .env


def parse_env_file(text: str) -> Dict[str, str]:
    """`KEY=value` lines; blank lines and `#` comments skipped; an `export ` prefix and
    single or double quotes around the value are allowed. No interpolation."""
    values: Dict[str, str] = {}
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not key or not key.replace("_", "a").isalnum() or key[0].isdigit():
            raise ConfigError(f"line {lineno}: expected KEY=value, got {raw.strip()!r}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value[:value.index(" #")].rstrip()
        values[key] = value
    return values


def load_env_file(path: Path, environ: Dict[str, str] | None = None) -> Dict[str, str]:
    """Set each variable in the file that is not already set. Returns what was applied."""
    environ = os.environ if environ is None else environ
    try:
        values = parse_env_file(path.read_text())
    except OSError as exc:
        raise ConfigError(f"{path}: {exc.strerror}") from exc
    except ConfigError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    applied = {k: v for k, v in values.items() if k not in environ}
    environ.update(applied)
    return applied


# ----------------------------------------------------------------------------- config


def read_config(path: Path) -> JSON:
    """Parse and check the TOML: only the three known tables and their keys."""
    try:
        data = tomllib.loads(path.read_text())
    except OSError as exc:
        raise ConfigError(f"{path}: {exc.strerror}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    for table, values in data.items():
        if table not in _KNOWN:
            raise ConfigError(f"{path}: unknown table [{table}]; expected one of {sorted(_KNOWN)}")
        if not isinstance(values, dict):
            raise ConfigError(f"{path}: [{table}] must be a table")
        for key in values:
            if key not in _KNOWN[table]:
                raise ConfigError(f"{path}: unknown key {table}.{key}; expected one of {sorted(_KNOWN[table])}")
    kind = data.get("backend", {}).get("kind")
    if kind is not None and kind not in ("filesystem", "neo4j"):
        raise ConfigError(f"{path}: backend.kind must be \"filesystem\" or \"neo4j\", not {kind!r}")
    return data


def apply_config(config: JSON, environ: Dict[str, str] | None = None) -> JSON:
    """Flag defaults from the file (`{dest: value}`), and the `NEO4J_*` / `TYPESAFE_*`
    variables set where the environment does not already have them."""
    environ = os.environ if environ is None else environ
    defaults: JSON = {}
    for (table, key), var in _ENV_KEYS.items():
        value = config.get(table, {}).get(key)
        if value is not None and var not in environ:
            environ[var] = str(value)
    for (table, key), dest in _FLAG_KEYS.items():
        value = config.get(table, {}).get(key)
        if value is None:
            continue
        if dest in ("root", "cache_dir"):
            value = Path(str(value)).expanduser()
        elif dest == "inspector":
            value = value if isinstance(value, bool) else str(Path(str(value)).expanduser())
            if value is False:
                value = None
        defaults[dest] = value
    localhost_open = config.get("server", {}).get("localhost_open")
    if localhost_open is not None:
        defaults["no_localhost"] = not bool(localhost_open)
    return defaults


def decision_model_status(environ: Dict[str, str] | None = None) -> str:
    """One line for the startup log: which model answers decisions, or that none does."""
    environ = os.environ if environ is None else environ
    if not environ.get("TYPESAFE_API_KEY"):
        return "decision model: none (TYPESAFE_API_KEY unset); every decision step pauses for the client to answer"
    from typesafe_sdk.constants import DEFAULT_BASE_URL, DEFAULT_MODEL

    model = environ.get("TYPESAFE_DEFAULT_MODEL") or DEFAULT_MODEL
    base = environ.get("TYPESAFE_BASE_URL") or DEFAULT_BASE_URL
    return f"decision model: TypeSafe {model} at {base}"


__all__ = ["CONFIG_ENV", "CONFIG_FILE", "ENV_FILE", "EXAMPLE", "ConfigError", "apply_config", "decision_model_status",
           "DEFAULT_ROOT", "find_config", "load_env_file", "parse_env_file", "read_config", "user_config_path", "write_example"]
