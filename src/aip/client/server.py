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
    GET  /runs?name=&status=&agent=&session=&user=&draft=&limit=      runs, newest first
    GET  /runs/{run_id}                   one run's record
    POST /catalog/{name}/pin  {"revision"}   make a name resolve to a revision (null clears)
    POST /catalog/{name}/retire {"revision"}  stop a revision resolving
    GET  /audit, GET /audit/{query}?…     the audit queries and their rows
    PUT  /audit/{name} {"description", "cypher"}, DELETE /audit/{name}   store a query of one's own, remove it
    GET  /export/runs?name=&since=&…      the runs that match and the procedures they ran, as one Relate file
    GET  /health                          what the server is; how the local server is told from anything else on its port

When the client points at `local` (`aip config server local`), nothing has to be running: a
request that finds no server starts one and is sent again (`aip.client.local`, the `starter`).

A reply with status 400 or above carries `{"error": {"kind", "message", "location"?, ...}}`.
Where the client points comes from `aip.client.config`.
"""

from __future__ import annotations

from typing import Any, Callable

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
    test client qualifies); by default a real one on `url`. `starter`, when given, is called
    once when the server does not answer, and the request is sent again: the local server,
    started on demand."""

    def __init__(self, url: str, token: str | None = None, session: Any = None, starter: Callable[[], Any] | None = None):
        self.url = url.rstrip("/")
        self.token = token
        self.starter = starter
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
            response = self._send(method, path, headers, kwargs)
        except ServerError:
            if self.starter is None:
                raise
            starter, self.starter = self.starter, None
            starter()                            # raises when the server cannot be started, and is not asked again
            self.starter = starter
            response = self._send(method, path, headers, kwargs)
        if response.status_code >= 400:
            raise self._error(response)
        return response

    def _send(self, method: str, path: str, headers: JSON, kwargs: JSON):
        try:
            return self._session.request(method, path, headers=headers, **kwargs)
        except Exception as exc:  # httpx.HTTPError, or whatever the injected session raises on no connection
            if type(exc).__module__.split(".")[0] not in ("httpx", "httpcore", "anyio", "socket", "builtins"):
                raise
            raise ServerError(0, "unreachable", f"{self.url}: {exc}") from exc

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
        """Record a run where it stopped; the server upserts by `run_id` and answers `{"run_id", "user",
        "draft", "revision"}`: who the token stands for, and what the store holds the run's bundle as."""
        return self.post("/runs", run)

    def runs(self, name: str | None = None, status: str | None = None, agent: str | None = None, session: str | None = None,
             limit: int = 50, user: str | None = None, draft: bool | None = None) -> list[JSON]:
        return self.get("/runs", name=name, status=status, agent=agent, session=session, user=user, draft=draft, limit=limit)

    def run(self, run_id: str) -> JSON:
        return self.get(f"/runs/{run_id}")

    # -------------------------------------------------------------------- audit

    def audit(self, query: str | None = None, **params: Any) -> Any:
        """With no query, the queries the server answers; with one, its rows."""
        return self.get("/audit" if query is None else f"/audit/{query}", **params)

    def save_audit(self, name: str, cypher: str, description: str = "") -> JSON:
        return self.request("PUT", f"/audit/{name}", json={"cypher": cypher, "description": description}).json()

    def delete_audit(self, name: str) -> JSON:
        return self.request("DELETE", f"/audit/{name}").json()

    def export_runs(self, **filters: Any) -> tuple[bytes, int, int]:
        """The runs that match (`name`, `since`, `agent`, `session`, `user`, `draft`) and the
        procedures they ran, as one Relate file: its bytes, how many runs, how many bundles."""
        response = self.request("GET", "/export/runs", params={k: v for k, v in filters.items() if v is not None})
        return response.content, int(response.headers.get("X-AIP-Runs", 0)), int(response.headers.get("X-AIP-Bundles", 0))

    def health(self) -> JSON:
        return self.get("/health")


def connect(url: str, token: str | None = None, session: Any = None, local: bool = False) -> Server:
    """A `Server` on `url`; with `local`, one that starts the local server when it does not
    answer (never through an injected session, which stands for a server that is there)."""
    starter = None
    if local and session is None:
        from aip.client.local import ensure as starter
    return Server(url, token, session=session, starter=starter)


def configured(session: Any = None) -> Server | None:
    """The server the client points at (`aip.client.config.settings`), or None when none is configured."""
    from aip.client.config import settings

    s = settings()
    return connect(s.server, s.token, session, s.local) if s.server else None


__all__ = ["BUNDLE_MEDIA_TYPE", "Server", "ServerError", "configured", "connect"]
