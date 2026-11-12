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
says so for one command whatever the file holds. `aip runah` has its own block (`runah: {model_uri,
model_name, model_key, max_tool_calls_per_task, max_tokens_per_task}`; `AIP_RUNAH_MODEL_URI`,
`AIP_RUNAH_MODEL_NAME`, `AIP_RUNAH_MODEL_KEY`): the chat model that answers `Task_Agent` pauses
in a run started or carried on with `aip runah` (`aip.model.answerer`, `docs/runah.md`), an
endpoint with the OpenAI Chat Completions shape, Anthropic's by default. Nothing else calls it.
A file written before runah had a name keeps the block as `agent_model: {url, api_key, name}`,
which is read as the same block and moved on the next `aip config runah`. The same block holds
the orchestrator's two bounds (`docs/runah.md`, The orchestrator): `max_depth`, how deep runah
runs may nest when a script or the SDK starts one inside another (2 by default; a run started
from a script is one deeper than the run whose script started it, `AIP_RUNAH_DEPTH`), and
`budget_tokens`, the model tokens a runah run may spend, its children's included (unlimited by
default; `AIP_RUNAH_BUDGET_TOKENS`, which a run's scripts are given as what is left). `script_timeout`
(`AIP_SCRIPT_TIMEOUT`) is the seconds one script may run, wherever a script runs; 300 by
default. The identity
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
RUNAH_MODEL_URI_ENV, RUNAH_MODEL_NAME_ENV, RUNAH_MODEL_KEY_ENV = "AIP_RUNAH_MODEL_URI", "AIP_RUNAH_MODEL_NAME", "AIP_RUNAH_MODEL_KEY"
RUNAH_BUDGET_ENV = "AIP_RUNAH_BUDGET_TOKENS"
DEFAULT_MAX_DEPTH = 2
DEFAULT_RUNAH_MODEL_URI = "https://api.anthropic.com/v1"
DEFAULT_RUNAH_MODEL_NAME = "claude-opus-5-5"        # pinned, not an alias: two runs never record one name for two models
DEFAULT_MAX_TOOL_CALLS_PER_TASK = 40
DEFAULT_MAX_TOKENS_PER_TASK = 500_000
RUNAH_HINT = ("`aip config runah --model-key KEY` (and `--model-uri URL --model-name NAME` for an endpoint other than "
              "Anthropic's), or AIP_RUNAH_MODEL_KEY")
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
    runah_model_uri: str | None = None   # runah's chat endpoint as configured; None means Anthropic's
    runah_model_key: str | None = None
    runah_model_name: str | None = None  # None means DEFAULT_RUNAH_MODEL_NAME
    runah_source: str | None = None
    max_tool_calls_per_task: int = DEFAULT_MAX_TOOL_CALLS_PER_TASK   # per task runah's model answers
    max_tokens_per_task: int = DEFAULT_MAX_TOKENS_PER_TASK           # per task: prompt and completion tokens over every call of its chat
    script_timeout: float | None = 300.0  # seconds one script may run, wherever a script runs; None: no cap
    max_depth: int = DEFAULT_MAX_DEPTH    # how deep runah runs may nest, started from a script or the SDK inside another run
    budget_tokens: int | None = None      # model tokens a runah run may spend, its children's included; None: no budget
    budget_source: str | None = None

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

    @property
    def runah_configured(self) -> bool:
        """runah can run when its model key is set: the endpoint and the name have defaults."""
        return bool(self.runah_model_key)

    @property
    def runah_model_endpoint(self) -> str:
        return self.runah_model_uri or DEFAULT_RUNAH_MODEL_URI

    @property
    def runah_model(self) -> str:
        return self.runah_model_name or DEFAULT_RUNAH_MODEL_NAME

    @property
    def runah(self) -> str:
        """The `aip config` block for runah: endpoint, model, whether a key is set, the caps."""
        key = "set" if self.runah_model_key else f"none (`aip runah` refuses to start; {RUNAH_HINT})"
        source = f"  (from {self.runah_source})" if self.runah_source else ""
        budget = "none" if self.budget_tokens is None else f"{self.budget_tokens} tokens per run, its children's included"
        if self.budget_tokens is not None and self.budget_source:
            budget += f"  (from {self.budget_source})"
        return (f"runah:{source}\n  model uri:   {self.runah_model_endpoint}\n  model name:  {self.runah_model}\n"
                f"  model key:   {key}\n  per task:    at most {self.max_tool_calls_per_task} tool calls, "
                f"{self.max_tokens_per_task} tokens\n  max depth:   {self.max_depth} (runah runs started inside another run)\n"
                f"  budget:      {budget}")

    @property
    def script_cap(self) -> str:
        """The `aip config` line for the script cap."""
        seconds = "none" if self.script_timeout is None else f"{self.script_timeout:g} seconds"
        return f"script timeout: {seconds} per script"


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
    runah = _runah_block(config)
    values = {}
    for field, env in (("model_uri", RUNAH_MODEL_URI_ENV), ("model_key", RUNAH_MODEL_KEY_ENV), ("model_name", RUNAH_MODEL_NAME_ENV)):
        values[field] = (os.environ[env] if env in os.environ else runah.get(field)) or None
    runah_env = [v for v in (RUNAH_MODEL_URI_ENV, RUNAH_MODEL_NAME_ENV, RUNAH_MODEL_KEY_ENV) if os.environ.get(v)]
    runah_source = ", ".join(runah_env) if runah_env else (str(config_path()) if any(values.values()) else None)
    uri = values["model_uri"]
    from aip.model.environment import script_timeout

    env_budget = os.environ.get(RUNAH_BUDGET_ENV, "").strip()
    budget = _int(env_budget) if env_budget else _int(runah.get("budget_tokens"))
    budget_source = RUNAH_BUDGET_ENV if env_budget else (str(config_path()) if budget else None)
    depth = runah.get("max_depth")
    max_depth = depth if isinstance(depth, int) and not isinstance(depth, bool) and depth >= 0 else DEFAULT_MAX_DEPTH

    return Settings(server.rstrip("/") if server else None, source, token, url.rstrip("/") if url else None, key, model_source,
                    batch, config_path(), local, uri.rstrip("/") if uri else None, values["model_key"], values["model_name"],
                    runah_source, _int(runah.get("max_tool_calls_per_task")) or DEFAULT_MAX_TOOL_CALLS_PER_TASK,
                    _int(runah.get("max_tokens_per_task")) or DEFAULT_MAX_TOKENS_PER_TASK, script_timeout(config.get("script_timeout")),
                    max_depth, budget, budget_source)


LEGACY_RUNAH = {"url": "model_uri", "api_key": "model_key", "name": "model_name", "max_tool_calls": "max_tool_calls_per_task",
                "max_tokens": "max_tokens_per_task"}


def _runah_block(config: JSON) -> JSON:
    """The file's `runah` block; a file written before runah had a name holds it as `agent_model`
    under the old field names."""
    if isinstance(config.get("runah"), dict):
        return dict(config["runah"])
    old = config.get("agent_model") if isinstance(config.get("agent_model"), dict) else {}
    return {LEGACY_RUNAH[k]: v for k, v in old.items() if k in LEGACY_RUNAH}


def _int(value: Any) -> int | None:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n >= 1 else None


def configure(server: str | None = None, token: str | None = None, decision_model: str | None = None,
              decision_model_key: str | None = None, batch: int | None = None, clear: bool = False, *,
              script_timeout: float | str | None = None) -> Settings:
    """Write the config file: arguments left None are unchanged, an empty string forgets the
    value, `clear` forgets everything. `server` is a URL, `local` for this machine's server
    started on demand, or `none` (the same as an empty string). `decision_model` is the
    endpoint's URL, `decision_model_key` its key. `script_timeout` is the seconds one script
    may run (`0` or `none`: no cap; an empty string forgets it, back to 300). runah's block is
    written by `configure_runah`."""
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
    if script_timeout is not None:
        if str(script_timeout).strip() == "":
            config.pop("script_timeout", None)
        else:
            from aip.model.environment import parse_script_timeout

            seconds = parse_script_timeout(script_timeout, "--script-timeout")
            config["script_timeout"] = 0 if seconds is None else seconds
    if batch is not None:
        if batch < 1:
            raise ValueError(f"the batch size is at least 1, not {batch}")
        config["batch"] = batch
    save_config(config)
    return settings()


def configure_runah(model_uri: str | None = None, model_name: str | None = None, model_key: str | None = None,
                    max_tool_calls_per_task: int | None = None, max_tokens_per_task: int | None = None,
                    max_depth: int | None = None, budget_tokens: int | None = None) -> Settings:
    """Write runah's block (`aip config runah`): arguments left None are unchanged, an empty
    string forgets the value (back to its default; for the key, no key). `max_depth` is how
    deep runah runs may nest (0: none may start inside another run); `budget_tokens` the model
    tokens one runah run may spend, its children's included (0 forgets it: no budget)."""
    config = load_config()
    block = _runah_block(config)
    for key, value in (("model_uri", model_uri.rstrip("/") if model_uri else model_uri), ("model_name", model_name),
                       ("model_key", model_key)):
        if value:
            block[key] = value
        elif value is not None:
            block.pop(key, None)
    for key, value in (("max_tool_calls_per_task", max_tool_calls_per_task), ("max_tokens_per_task", max_tokens_per_task)):
        if value is not None:
            if value < 1:
                raise ValueError(f"--{key.replace('_', '-')} is at least 1, not {value}")
            block[key] = value
    if max_depth is not None:
        if max_depth < 0:
            raise ValueError(f"--max-depth is at least 0, not {max_depth}")
        block["max_depth"] = max_depth
    if budget_tokens is not None:
        if budget_tokens < 0:
            raise ValueError(f"--budget-tokens is at least 0 (0: no budget), not {budget_tokens}")
        if budget_tokens:
            block["budget_tokens"] = budget_tokens
        else:
            block.pop("budget_tokens", None)
    config.pop("agent_model", None)
    if block:
        config["runah"] = block
    else:
        config.pop("runah", None)
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
           "DECISION_MODEL_KEY_ENV", "CONFIGURE_HINT", "RUNAH_MODEL_URI_ENV", "RUNAH_MODEL_NAME_ENV", "RUNAH_MODEL_KEY_ENV",
           "RUNAH_HINT", "RUNAH_BUDGET_ENV", "DEFAULT_MAX_DEPTH", "DEFAULT_RUNAH_MODEL_URI", "DEFAULT_RUNAH_MODEL_NAME", "DECISION_MODEL_HINT", "Settings", "config_path",
           "load_config", "save_config", "settings", "configure", "configure_runah", "identity"]
