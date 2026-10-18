"""The client's side of the HTTP API (design §4.1, §8): where the server is, how to call
it, and the catalog operations `aip search|list|publish|get|pin|retire` are built on.

`Server(url, token)` is one HTTP session with the bearer token attached and the error
envelope turned into `ServerError`. Where the client points comes from `settings()`:
`AIP_SERVER` and `AIP_TOKEN` override `~/.config/aip/config.json` (`aip config` writes
it); nothing configured means local folders only.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import tarfile
import tempfile
from pathlib import Path
from typing import Any, Dict, List

JSON = Dict[str, Any]
MANIFEST = ".aip-manifest.json"


# -------------------------------------------------------------------------- config


def config_path() -> Path:
    override = os.environ.get("AIP_CONFIG")
    return Path(override) if override else Path.home() / ".config" / "aip" / "config.json"


def load_config() -> JSON:
    path = config_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_config(config: JSON) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n")
    try:
        path.chmod(0o600)                       # it may hold the token
    except OSError:
        pass
    return path


def settings() -> JSON:
    """`{"server", "token", "source"}`: the environment first, then the config file."""
    config = load_config()
    server = os.environ.get("AIP_SERVER") or config.get("server") or None
    token = os.environ.get("AIP_TOKEN") or config.get("token") or None
    source = "AIP_SERVER" if os.environ.get("AIP_SERVER") else (str(config_path()) if config.get("server") else None)
    return {"server": server, "token": token, "source": source}


def configured() -> "Server | None":
    """The server the client points at, or None when none is configured."""
    s = settings()
    return Server(s["server"], s["token"]) if s["server"] else None


# -------------------------------------------------------------------------- errors


class ServerError(Exception):
    """A failed call: the server's error envelope, or no server to speak of."""

    def __init__(self, status: int, kind: str, message: str, location: str | None = None, **extra: Any):
        super().__init__(message)
        self.status, self.kind, self.message, self.location, self.extra = status, kind, message, location, extra

    def __str__(self) -> str:
        where = f" at {self.location}" if self.location else ""
        return f"{self.kind}{where}: {self.message}"


# ------------------------------------------------------------------------- the server


class Server:
    """One HTTP session against an AIP server. `session` is any httpx-style client (FastAPI's
    test client qualifies); by default a real one on `url`."""

    def __init__(self, url: str, token: str | None = None, session: Any = None):
        self.url = url.rstrip("/")
        self.token = token
        if session is None:
            import httpx

            session = httpx.Client(base_url=self.url, timeout=httpx.Timeout(None, connect=10.0))
        self._session = session

    def request(self, method: str, path: str, **kwargs: Any):
        import httpx

        headers = dict(kwargs.pop("headers", {}) or {})
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            response = self._session.request(method, path, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise ServerError(0, "unreachable", f"{self.url}: {exc}") from exc
        if response.status_code >= 400:
            raise self._error(response)
        return response

    @staticmethod
    def _error(response) -> ServerError:
        try:
            error = response.json()["error"]
            return ServerError(response.status_code, error.pop("kind"), error.pop("message"),
                               error.pop("location", None), **error)
        except (ValueError, KeyError, TypeError, AttributeError):
            return ServerError(response.status_code, "http_error", f"HTTP {response.status_code}: {response.text[:200]}")

    def get(self, path: str, **params: Any) -> Any:
        return self.request("GET", path, params={k: v for k, v in params.items() if v is not None}).json()

    def post(self, path: str, body: JSON | None = None) -> Any:
        return self.request("POST", path, json=body or {}).json()

    def bytes(self, path: str, **params: Any) -> bytes:
        return self.request("GET", path, params={k: v for k, v in params.items() if v is not None}).content

    # ------------------------------------------------------------------ catalog

    def search(self, query: str, limit: int = 10) -> List[JSON]:
        return self.get("/catalog/search", q=query, limit=limit)

    def list(self) -> List[JSON]:
        return self.get("/catalog")

    def info(self, ref: str) -> JSON:
        return self.get(f"/catalog/{ref}")

    def file(self, ref: str, path: str) -> bytes:
        return self.bytes(f"/catalog/{ref}/files/{path}")

    def capabilities(self, ref: str) -> JSON:
        return self.get(f"/procedures/{ref}/capabilities")

    def pin(self, name: str, revision: str | None) -> JSON:
        return self.post(f"/catalog/{name}/pin", {"revision": revision})

    def retire(self, name: str, revision: str) -> JSON:
        return self.post(f"/catalog/{name}/retire", {"revision": revision})

    def runs(self, name: str | None = None, status: str | None = None, limit: int = 50) -> List[JSON]:
        return self.get("/runs", name=name, status=status, limit=limit)

    def run(self, run_id: str) -> JSON:
        return self.get(f"/runs/{run_id}")

    # --------------------------------------------------------------- transfers

    def publish(self, folder: Path) -> JSON:
        """Upload every file of a skill folder; the server validates and returns `{name, revision, ...}`.
        Validate locally first (`aip publish` does) so a rejection is never a surprise."""
        from aip.server.app import upload_of

        return self.post("/catalog", upload_of(Path(folder)))

    def download(self, ref: str, out_dir: Path) -> Path:
        """Fetch a revision losslessly to `<out_dir>/<name>/`: the tar of every file plus its
        manifest, modes restored from the manifest, every file hashed against it (the first
        mismatch aborts, naming the file), and the revision recomputed. Refuses to overwrite."""
        from aip.server.records import revision, walk

        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        data = self.bytes(f"/catalog/{ref}/files", archive="tar")
        tmp = Path(tempfile.mkdtemp(prefix=".aip-get-", dir=out_dir))
        try:
            with tarfile.open(fileobj=io.BytesIO(data)) as tar:
                tar.extractall(tmp, filter="data")
            manifest_path = tmp / MANIFEST
            if not manifest_path.is_file():
                raise ServerError(0, "bad_archive", f"{ref}: the archive carries no {MANIFEST}")
            manifest = json.loads(manifest_path.read_text())
            name, expected = manifest["name"], manifest["revision"]
            folder = tmp / name
            if not folder.is_dir():
                raise ServerError(0, "bad_archive", f"{ref}: the archive has no {name}/ folder")
            for entry in sorted(manifest["files"], key=lambda e: e["path"]):
                path = folder / entry["path"]
                if not path.is_file():
                    raise ServerError(0, "hash_mismatch", f"{name}/{entry['path']}: missing from the archive",
                                      location=entry["path"])
                path.chmod(int(entry["mode"]) & 0o777)
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                if digest != entry["sha256"]:
                    raise ServerError(0, "hash_mismatch",
                                      f"{name}/{entry['path']}: sha256 {digest[:12]}… does not match the manifest's "
                                      f"{entry['sha256'][:12]}…", location=entry["path"])
            files, _ = walk(folder)
            if revision(files) != expected:
                raise ServerError(0, "hash_mismatch", f"{name}: the files on disk hash to {revision(files)}, "
                                                      f"not the manifest's {expected}")
            target = out_dir / name
            if target.exists():
                raise ServerError(0, "exists", f"{target} already exists; choose another --out or remove it")
            shutil.move(str(folder), str(target))
            return target
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


__all__ = ["Server", "ServerError", "config_path", "configured", "load_config", "save_config", "settings"]
