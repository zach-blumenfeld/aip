"""Where the client points and who is running: the per-user config file and the environment.

`~/.config/aip/config.json` (`AIP_CONFIG` moves it; `aip config` writes it) holds the server
(a URL, or `local` for the server on this machine that is started when needed,
`aip.client.local`), its bearer token, the decision model (`decision_model: {url, api_key}`) and the default
batch size. The environment overrides each: `AIP_SERVER`, `AIP_TOKEN`, `AIP_DECISION_MODEL`,
`AIP_DECISION_MODEL_KEY`, `AIP_BATCH`. The two decision-model variables override the file even
when set to nothing: `AIP_DECISION_MODEL_KEY=` is "no key for this command" (and with
`AIP_DECISION_MODEL=` beside it when the file names an endpoint, no model at all), which is how
to run without the configured model. The decision model is an endpoint with the TypeSafe API
shape (plan question 7): the URL defaults to TypeSafe's and the key is the endpoint's; a model
is configured when either is set, and with none every `Decide` fails the run
(`no_decision_model`) until one is. With no server, runs work but are not recorded; `AIP_SERVER=none`
says so for one command whatever the file holds. The identity
of a run (`agent`, `session`; runtime.md, The record) comes from `--agent` / `AIP_AGENT` and
`--session` / `AIP_SESSION`; `user` is the server's to fill from the token.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aip.model.engine import DEFAULT_BATCH
from aip.model.typesafe import DEFAULT_URL, KEY_ENV, URL_ENV
from aip.model.types import DECISION_MODEL_HINT

JSON = dict[str, Any]

CONFIG_ENV = "AIP_CONFIG"
SERVER_ENV, TOKEN_ENV, BATCH_ENV = "AIP_SERVER", "AIP_TOKEN", "AIP_BATCH"
AGENT_ENV, SESSION_ENV = "AIP_AGENT", "AIP_SESSION"
DECISION_MODEL_ENV, DECISION_MODEL_KEY_ENV = URL_ENV, KEY_ENV
CONFIGURE_HINT = "run `aip config server local` to record runs on this machine, or `aip config server URL` for a server elsewhere"
LOCAL, NONE = "local", "none"


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
    """What a `Client()` with no arguments uses. `token_set` and `decision_model_key_set`, not
    the secrets, so printing it leaks nothing; `decision_model_key` is for the resolver."""
    server: str | None                 # the URL; the local server's own when `local`
    source: str | None                 # where the server came from: the variable or the file
    token: str | None
    decision_model_url: str | None     # the endpoint as configured; None means TypeSafe's (`DEFAULT_URL`)
    decision_model_key: str | None
    decision_model_source: str | None  # where the model came from: the variable(s) or the file
    batch: int
    path: Path
    local: bool = False                # the server is this machine's, started on demand (`aip config server local`)

    @property
    def token_set(self) -> bool:
        return bool(self.token)

    @property
    def decision_model_key_set(self) -> bool:
        return bool(self.decision_model_key)

    @property
    def decision_model_configured(self) -> bool:
        """A model is configured when an endpoint or a key is set (plan R4)."""
        return bool(self.decision_model_url or self.decision_model_key)

    @property
    def decision_model_endpoint(self) -> str:
        """The URL the resolver speaks to: the configured one, else TypeSafe's."""
        return self.decision_model_url or DEFAULT_URL

    @property
    def decision_model(self) -> str:
        """The `aip config` line: the endpoint and whether a key is set, never the key."""
        if not self.decision_model_configured:
            return f"decision model: none (a Decide fails the run with no_decision_model; {DECISION_MODEL_HINT})"
        where = f"{self.decision_model_endpoint}" + ("  (TypeSafe's, the default)" if not self.decision_model_url else "")
        key = "set" if self.decision_model_key_set else "none"
        return f"decision model: {where}  key: {key}  (from {self.decision_model_source})"


def settings() -> Settings:
    config = load_config()
    server = os.environ.get(SERVER_ENV) or config.get("server") or None
    source = SERVER_ENV if os.environ.get(SERVER_ENV) else (str(config_path()) if config.get("server") else None)
    local = isinstance(server, str) and server.strip().lower() == LOCAL
    if local:
        from aip.client.local import url as local_url

        server = local_url()
    elif isinstance(server, str) and server.strip().lower() == NONE:
        server = None
    token = os.environ.get(TOKEN_ENV) or config.get("token") or None
    model = config.get("decision_model") if isinstance(config.get("decision_model"), dict) else {}
    # A variable that is set wins over the file even when it is empty: `AIP_DECISION_MODEL_KEY=` is "no key".
    url = (os.environ[DECISION_MODEL_ENV] if DECISION_MODEL_ENV in os.environ else model.get("url")) or None
    key = (os.environ[DECISION_MODEL_KEY_ENV] if DECISION_MODEL_KEY_ENV in os.environ else model.get("api_key")) or None
    from_env = [v for v in (DECISION_MODEL_ENV, DECISION_MODEL_KEY_ENV) if os.environ.get(v)]
    model_source = ", ".join(from_env) if from_env else (str(config_path()) if url or key else None)
    batch = _int(os.environ.get(BATCH_ENV)) or _int(config.get("batch")) or DEFAULT_BATCH
    return Settings(server.rstrip("/") if server else None, source, token, url.rstrip("/") if url else None, key, model_source,
                    batch, config_path(), local)


def _int(value: Any) -> int | None:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n >= 1 else None


def configure(server: str | None = None, token: str | None = None, decision_model: str | None = None,
              decision_model_key: str | None = None, batch: int | None = None, clear: bool = False) -> Settings:
    """Write the config file: arguments left None are unchanged, an empty string forgets the
    value, `clear` forgets everything. `server` is a URL, `local` for this machine's server
    started on demand, or `none` (the same as an empty string). `decision_model` is the
    endpoint's URL, `decision_model_key` its key."""
    if clear:
        save_config({})
        return settings()
    config = load_config()
    if server is not None and server.strip().lower() in (LOCAL, NONE):
        server = LOCAL if server.strip().lower() == LOCAL else ""
    for key, value in (("server", server.rstrip("/") if server else server), ("token", token)):
        if value:
            config[key] = value
        elif value is not None:
            config.pop(key, None)
    model = dict(config.get("decision_model") or {}) if isinstance(config.get("decision_model"), dict) else {}
    for key, value in (("url", decision_model.rstrip("/") if decision_model else decision_model), ("api_key", decision_model_key)):
        if value:
            model[key] = value
        elif value is not None:
            model.pop(key, None)
    if model:
        config["decision_model"] = model
    else:
        config.pop("decision_model", None)
    if batch is not None:
        if batch < 1:
            raise ValueError(f"the batch size is at least 1, not {batch}")
        config["batch"] = batch
    save_config(config)
    return settings()


def identity(agent: str | None = None, session: str | None = None, default_agent: str | None = None,
             agent_version: str | None = None) -> JSON:
    """Who runs: `agent` from the argument, `AIP_AGENT` or the caller's default; `session` from
    the argument or `AIP_SESSION`; `user` left for the server to fill from the token;
    `agent_version` only when the caller gives one."""
    who = {"agent": agent or os.environ.get(AGENT_ENV) or default_agent, "session": session or os.environ.get(SESSION_ENV) or None,
           "user": None}
    if agent_version:
        who["agent_version"] = agent_version
    return who


__all__ = ["CONFIG_ENV", "SERVER_ENV", "TOKEN_ENV", "BATCH_ENV", "AGENT_ENV", "SESSION_ENV", "DECISION_MODEL_ENV", "LOCAL", "NONE",
           "DECISION_MODEL_KEY_ENV", "CONFIGURE_HINT", "DECISION_MODEL_HINT", "Settings", "config_path", "load_config", "save_config",
           "settings", "configure", "identity"]
