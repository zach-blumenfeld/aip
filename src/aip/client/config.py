"""Where the client points and who is running: the per-user config file and the environment.

`~/.config/aip/config.json` (`AIP_CONFIG` moves it; `aip config` writes it) holds the server
URL, its bearer token, the decision model's key and the default batch size. The environment
overrides each: `AIP_SERVER`, `AIP_TOKEN`, `TYPESAFE_API_KEY`, `AIP_BATCH`. Nothing configured
means runs work and are not recorded, and every decision is the agent's unless a step forbids
it. The identity of a run (`agent`, `session`; runtime.md, The record) comes from `--agent` /
`AIP_AGENT` and `--session` / `AIP_SESSION`; `user` is the server's to fill from the token.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aip.model.engine import DEFAULT_BATCH
from aip.model.typesafe import KEY_ENV

JSON = dict[str, Any]

CONFIG_ENV = "AIP_CONFIG"
SERVER_ENV, TOKEN_ENV, BATCH_ENV = "AIP_SERVER", "AIP_TOKEN", "AIP_BATCH"
AGENT_ENV, SESSION_ENV = "AIP_AGENT", "AIP_SESSION"
CONFIGURE_HINT = "run `aip config --server URL` to record runs on a server"


def config_path() -> Path:
    override = os.environ.get(CONFIG_ENV)
    return Path(override) if override else Path.home() / ".config" / "aip" / "config.json"


def load_config() -> JSON:
    path = config_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_config(config: JSON) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)  # it may hold the token and the key
    except OSError:
        pass
    return path


@dataclass(frozen=True)
class Settings:
    """What a `Client()` with no arguments uses. `token_set` and `decision_model_set`, not the
    secrets, so printing it leaks nothing; `decision_model_key` is for the resolver."""
    server: str | None
    source: str | None            # where the server came from: the variable or the file
    token: str | None
    decision_model_key: str | None
    decision_model_source: str | None
    batch: int
    path: Path

    @property
    def token_set(self) -> bool:
        return bool(self.token)

    @property
    def decision_model(self) -> str:
        if self.decision_model_key:
            return f"decision model: TypeSafe (key from {self.decision_model_source})"
        return (f"decision model: none (set {KEY_ENV} or run `aip config --decision-model KEY`; until then a decision "
                "is the agent's where the step allows Agent_Fallback and fails the run where not)")


def settings() -> Settings:
    config = load_config()
    server = os.environ.get(SERVER_ENV) or config.get("server") or None
    source = SERVER_ENV if os.environ.get(SERVER_ENV) else (str(config_path()) if config.get("server") else None)
    token = os.environ.get(TOKEN_ENV) or config.get("token") or None
    key = os.environ.get(KEY_ENV) or (config.get("decision_model") or {}).get("api_key") or None
    key_source = KEY_ENV if os.environ.get(KEY_ENV) else (str(config_path()) if key else None)
    batch = _int(os.environ.get(BATCH_ENV)) or _int(config.get("batch")) or DEFAULT_BATCH
    return Settings(server.rstrip("/") if server else None, source, token, key, key_source, batch, config_path())


def _int(value: Any) -> int | None:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n >= 1 else None


def configure(server: str | None = None, token: str | None = None, decision_model: str | None = None,
              batch: int | None = None, clear: bool = False) -> Settings:
    """Write the config file: arguments left None are unchanged, an empty string forgets the
    value, `clear` forgets everything."""
    if clear:
        save_config({})
        return settings()
    config = load_config()
    for key, value in (("server", server.rstrip("/") if server else server), ("token", token)):
        if value:
            config[key] = value
        elif value is not None:
            config.pop(key, None)
    if decision_model:
        config["decision_model"] = {"api_key": decision_model}
    elif decision_model is not None:
        config.pop("decision_model", None)
    if batch is not None:
        if batch < 1:
            raise ValueError(f"the batch size is at least 1, not {batch}")
        config["batch"] = batch
    save_config(config)
    return settings()


def identity(agent: str | None = None, session: str | None = None, default_agent: str | None = None) -> JSON:
    """Who runs: `agent` from the argument, `AIP_AGENT` or the caller's default; `session` from
    the argument or `AIP_SESSION`; `user` left for the server to fill from the token."""
    return {"agent": agent or os.environ.get(AGENT_ENV) or default_agent, "session": session or os.environ.get(SESSION_ENV) or None,
            "user": None}


__all__ = ["CONFIG_ENV", "SERVER_ENV", "TOKEN_ENV", "BATCH_ENV", "AGENT_ENV", "SESSION_ENV", "CONFIGURE_HINT", "Settings",
           "config_path", "load_config", "save_config", "settings", "configure", "identity"]
