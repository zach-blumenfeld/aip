"""The client's side of the HTTP API: one session against an AIP server, the bearer token
attached and the error envelope turned into `ServerError`.

This module is the contract `aip.server.app` implements (`docs/server-design.md`, The HTTP API;
`tests/server/test_contract.py` holds the two together); every call the runtime makes is listed
here and nowhere else:

    GET  /catalog                         every published name with its revisions
    GET  /catalog/search?q=&limit=        published procedures by what they do
    GET  /catalog/{ref}                   describe `name`, `name@rev` or `name@latest` (JSON) …
    GET  /catalog/{ref}  Accept: application/octet-stream   … or hand its `.rl` back, for `pull`
    POST /catalog        (the `.rl` bytes)   publish: merge the bundle by id, assign the next revision under its name
    POST /bundles        (the `.rl` bytes)   upload a bundle with no revision, a draft, so runs of it can be recorded
    POST /runs           (the run as JSON)   record a run at every stop: the whole run each time, upserted by `run_id`
    GET  /runs?name=&status=&agent=&session=&limit=      runs, newest first (the server also filters by `user` and `draft`)
    GET  /runs/{run_id}                   one run's record
    POST /catalog/{name}/pin  {"revision"}   make a name resolve to a revision (null clears)
    POST /catalog/{name}/retire {"revision"}  stop a revision resolving
    GET  /governance, GET /governance/{query}?…   the governance queries and their rows

A reply with status 400 or above carries `{"error": {"kind", "message", "location"?, ...}}`.
Where the client points comes from `aip.client.config`.
"""

from __future__ import annotations

from typing import Any

from aip.errors import AipError

JSON = dict[str, Any]
BUNDLE_MEDIA_TYPE = "application/octet-stream"


class ServerError(AipError):
    """A failed call: the server's error envelope, or no answer at all (`status` 0, kind `unreachable`)."""

    def __init__(self, status: int, kind: str, message: str, location: str | None = None, **extra: Any):
        super().__init__(message, kind)
        self.status, self.location, self.extra = status, location, extra

    def __str__(self) -> str:
        where = f" at {self.location}" if self.location else ""
        return f"{self.kind}{where}: {self.message}"


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

    def __repr__(self) -> str:
        return f"Server({self.url!r})"

    def request(self, method: str, path: str, **kwargs: Any):
        headers = dict(kwargs.pop("headers", {}) or {})
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            response = self._session.request(method, path, headers=headers, **kwargs)
        except Exception as exc:  # httpx.HTTPError, or whatever the injected session raises on no connection
            if type(exc).__module__.split(".")[0] not in ("httpx", "httpcore", "anyio", "socket", "builtins"):
                raise
            raise ServerError(0, "unreachable", f"{self.url}: {exc}") from exc
        if response.status_code >= 400:
            raise self._error(response)
        return response

    @staticmethod
    def _error(response) -> ServerError:
        try:
            error = dict(response.json()["error"])
            return ServerError(response.status_code, error.pop("kind"), error.pop("message"), error.pop("location", None), **error)
        except (ValueError, KeyError, TypeError, AttributeError):
            return ServerError(response.status_code, "http_error", f"HTTP {response.status_code}: {response.text[:200]}")

    def get(self, path: str, **params: Any) -> Any:
        return self.request("GET", path, params={k: v for k, v in params.items() if v is not None}).json()

    def post(self, path: str, body: JSON | None = None) -> Any:
        return self.request("POST", path, json=body if body is not None else {}).json()

    def post_bytes(self, path: str, data: bytes) -> Any:
        return self.request("POST", path, content=data, headers={"Content-Type": BUNDLE_MEDIA_TYPE}).json()

    # ------------------------------------------------------------------ catalog

    def list(self) -> list[JSON]:
        return self.get("/catalog")

    def search(self, query: str, limit: int = 10) -> list[JSON]:
        return self.get("/catalog/search", q=query, limit=limit)

    def describe(self, ref: str) -> JSON:
        return self.get(f"/catalog/{ref}")

    def bundle(self, ref: str) -> bytes:
        """The `.rl` of the revision `ref` resolves to."""
        return self.request("GET", f"/catalog/{ref}", headers={"Accept": BUNDLE_MEDIA_TYPE}).content

    def publish(self, data: bytes) -> JSON:
        """`{"name", "revision", "bundle_id", "existed"}`: the revision the bundle was published as."""
        return self.post_bytes("/catalog", data)

    def draft(self, data: bytes) -> JSON:
        """`{"bundle_id", "name", "existed", "draft"}`: the bundle is in the store; `draft` is False when it
        already is a published revision."""
        return self.post_bytes("/bundles", data)

    def pin(self, name: str, revision: str | None) -> JSON:
        return self.post(f"/catalog/{name}/pin", {"revision": revision})

    def retire(self, name: str, revision: str) -> JSON:
        return self.post(f"/catalog/{name}/retire", {"revision": revision})

    # --------------------------------------------------------------------- runs

    def record(self, run: JSON) -> JSON:
        """Record a run where it stopped; the server upserts by `run_id` and answers `{"run_id", "user"?}`."""
        return self.post("/runs", run)

    def runs(self, name: str | None = None, status: str | None = None, agent: str | None = None, session: str | None = None,
             limit: int = 50) -> list[JSON]:
        return self.get("/runs", name=name, status=status, agent=agent, session=session, limit=limit)

    def run(self, run_id: str) -> JSON:
        return self.get(f"/runs/{run_id}")

    # --------------------------------------------------------------- governance

    def governance(self, query: str | None = None, **params: Any) -> Any:
        return self.get("/governance" if query is None else f"/governance/{query}", **params)


def configured(session: Any = None) -> Server | None:
    """The server the client points at (`aip.client.config.settings`), or None when none is configured."""
    from aip.client.config import settings

    s = settings()
    return Server(s.server, s.token, session=session) if s.server else None


__all__ = ["BUNDLE_MEDIA_TYPE", "Server", "ServerError", "configured"]
