"""The HTTP server: the catalog of bundles and the record of runs, over either backend.

`create_app(backend)` returns a FastAPI application over a backend's `.store`
(`aip.server.store.Store`; the Relate and Neo4j backends both supply one). The server never runs
a procedure: every run is local to its client (`docs/language/runtime.md`), which posts where it
stopped. So the API is the contract `aip.client.server` lists, and nothing else:

- **catalog**: `GET /catalog` (every published name with its revisions), `GET /catalog/search`,
  `GET /catalog/{ref}` (the description as JSON, or with `Accept: application/octet-stream` the
  `.rl` itself, for `aip pull`), `POST /catalog` (the `.rl` bytes: verify the bundle, merge it by
  id, assign the next revision under its procedure's name), `POST /catalog/{name}/pin|retire`.
- **bundles**: `POST /bundles` (the `.rl` bytes: hold the bundle with no revision, a *draft*, so
  a run of a folder or a file can be recorded), `GET /bundles?drafts=` (what the store holds),
  `GET /bundles/{bundle_id}` (describe one, or hand its `.rl` back, by id).
- **graph**: `GET /catalog/{ref}/graph` and `GET /bundles/{bundle_id}/graph`: the bundle's own
  nodes and edges as JSON, the shape `aip compile --json` prints under `graph`, here with the
  source and the files' contents, so a page can draw a procedure and show its text without
  opening an `.rl`.
- **runs**: `POST /runs` (the whole run as JSON, upserted by `run_id`; the bundle it names must
  be held, else 404 `unknown_bundle`; the reply names the `user` the token stands for, which the
  server writes into the run's identity whatever the client claimed), `GET /runs` (newest first;
  `name`, `status`, `agent`, `session`, `user`, `draft`, `limit`), `GET /runs/{run_id}`.
  The reply also says what the store made of it: `draft` (the bundle has no revision) and the
  `revision` the bundle is published as.
- **audit**: `GET /audit` lists the named queries of `aip.server.audit` and the ones stored
  here, `GET /audit/{query}?name=&agent=&session=&user=&draft=&window=&limit=&repeats=&key=`
  answers one, `PUT /audit/{name}` (`{"description", "cypher"}`) stores a query and
  `DELETE /audit/{name}` removes it.
- **export**: `GET /export/runs?name=&since=&agent=&session=&user=&draft=` hands back one
  Relate file holding the runs that match and the procedures they ran (`aip export runs`).
- **health**: `GET /health`, with no token: `{"aip", "language", "backend", "local"}`, which is
  how a client tells an aip server from whatever else answers on a port (a local server adds its `pid`).

An upload is a bundle file and is treated as one: it is read and verified exactly as `aip run
file.rl` would (`aip.compiler.read_bundle`), and a file that is not a bundle, was edited, or is
of another language version is refused with the bundle error's own kind (422).

The server serves no UI: the console is its own package and calls this API like any other
client, from its own origin. So the server answers CORS for pages served from a loopback origin
(`http://localhost:<port>`, `127.0.0.1`, `[::1]`), where the console runs, and for any origin in
`allow_origins`; a page from anywhere else on the web cannot read it.

`ref` is `name`, `name@<revision>`, or `name@latest`, resolved by the store.

Errors are `{"error": {"kind", "message", "location"?, ...}}`. Auth is a bearer token. A token
has scopes (`read`: every GET; `run`: upload a draft and record runs; `publish`: publish, pin,
retire, store or remove an audit query) and may have a name, which is the `user` of the runs recorded with it. With no tokens
configured the server is open, and a loopback client may call without a token either way.
"""

from __future__ import annotations

import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from aip.compiler.bundle import BUNDLE_SUFFIX, Bundle, BundleError
from aip.server import audit
from aip.server.store import InvalidRun, NotFound, UnknownBundle

JSON = dict[str, Any]

READ, RUN, PUBLISH = "read", "run", "publish"
ALL_SCOPES = frozenset({READ, RUN, PUBLISH})
LOOPBACK = {"127.0.0.1", "::1", "localhost"}
BUNDLE_MEDIA_TYPE = "application/octet-stream"

# Pages the server answers CORS for without being told: the console runs on the user's machine.
LOOPBACK_ORIGINS = r"https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?"


@dataclass(frozen=True)
class Token:
    """What a bearer token grants, and the name its runs are recorded under."""
    scopes: frozenset[str] = ALL_SCOPES
    name: str | None = None


class ApiError(Exception):
    """An error the API reports in its envelope."""

    def __init__(self, status: int, kind: str, message: str, location: str | None = None, **extra: Any):
        super().__init__(message)
        self.status, self.kind, self.message, self.location, self.extra = status, kind, message, location, extra

    def body(self) -> JSON:
        error: JSON = {"kind": self.kind, "message": self.message}
        if self.location is not None:
            error["location"] = self.location
        error.update(self.extra)
        return {"error": error}


class RevisionBody(BaseModel):
    revision: str | int | None = None


class QueryBody(BaseModel):
    cypher: str
    description: str = ""


def since_of(value: str | None) -> str | None:
    """`since` as the store compares it: an ISO 8601 date or timestamp, checked."""
    if value is None or not value.strip():
        return None
    from datetime import datetime

    try:
        datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        raise ApiError(422, "invalid_request", f"since is a date or a timestamp (2026-11-01, 2026-11-01T09:00:00), not {value!r}") from None
    return value.strip()


def describe_bundle(bundle: Bundle) -> JSON:
    """The description stored with a bundle, the one `aip info` prints for a folder: computed
    once, when the bundle arrives, by loading it as a run would."""
    from aip.model import Procedure
    from aip.sdk import describe_procedure

    with Procedure.load(bundle) as procedure:
        return describe_procedure(procedure)


def read_upload(data: bytes) -> Bundle:
    """The bundle in an upload, verified; `ApiError` 422 with the bundle error's kind otherwise."""
    from aip.compiler import read_bundle
    from aip.compiler.relate import RelateMissing

    if not data:
        raise ApiError(422, "not_a_bundle", f"the upload is empty; send the bytes of an {BUNDLE_SUFFIX} bundle")
    with tempfile.TemporaryDirectory(prefix="aip-upload-") as tmp:
        path = Path(tmp) / f"upload{BUNDLE_SUFFIX}"
        path.write_bytes(data)
        try:
            return read_bundle(path)
        except BundleError as exc:
            raise ApiError(422, exc.code, exc.message.replace(str(path), "the upload")) from exc
        except RelateMissing as exc:
            raise ApiError(500, "internal", str(exc)) from exc


def create_app(backend: Any, tokens: dict[str, Token | set[str] | frozenset[str]] | None = None, localhost_open: bool = True,
               allow_origins: list[str] | None = None, builtins: bool = True, local: bool = False) -> FastAPI:
    """Build the server over `backend`.

    tokens:          bearer token -> `Token` (or just its scopes); empty or None means no auth
    localhost_open:  a loopback client needs no token even when tokens are configured
    allow_origins:   origins besides loopback ones whose pages may call this server (CORS)
    builtins:        publish the package's built-in bundles this store has not been offered yet
    local:           this is the server a client started for itself (`aip server --local`); `GET /health` says so

    `app.state.last_request` is the monotonic time of the last request, which is how a local
    server knows it has been idle.
    """
    store = backend.store
    known = {t: v if isinstance(v, Token) else Token(frozenset(v)) for t, v in (tokens or {}).items()}
    if builtins:
        from aip.server.builtins import publish_builtins

        publish_builtins(store)

    app = FastAPI(title="aip server", version="0.9", docs_url=None, redoc_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=list(allow_origins or []), allow_origin_regex=LOOPBACK_ORIGINS,
                       allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Authorization", "Content-Type", "Accept"])

    app.state.last_request = time.monotonic()

    @app.middleware("http")
    async def _stamp(request: Request, call_next):
        app.state.last_request = time.monotonic()
        return await call_next(request)

    # ------------------------------------------------------------------ errors

    def answer(error: ApiError) -> JSONResponse:
        return JSONResponse(error.body(), status_code=error.status)

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return answer(exc)

    @app.exception_handler(UnknownBundle)
    async def _unknown_bundle(_: Request, exc: UnknownBundle):
        return answer(ApiError(404, "unknown_bundle", str(exc)))

    @app.exception_handler(NotFound)
    async def _not_found(_: Request, exc: NotFound):
        return answer(ApiError(404, "not_found", str(exc)))

    @app.exception_handler(InvalidRun)
    async def _invalid_run(_: Request, exc: InvalidRun):
        return answer(ApiError(422, "invalid_request", str(exc)))

    @app.exception_handler(audit.InvalidQuery)
    async def _invalid_query(_: Request, exc: audit.InvalidQuery):
        return answer(ApiError(422, "invalid_request", str(exc)))

    @app.exception_handler(RequestValidationError)
    async def _invalid_request(_: Request, exc: RequestValidationError):
        detail = "; ".join(".".join(str(p) for p in e["loc"]) + ": " + e["msg"] for e in exc.errors())
        return answer(ApiError(422, "invalid_request", detail))

    @app.exception_handler(Exception)
    async def _internal(_: Request, exc: Exception):
        return answer(ApiError(500, "internal", f"{type(exc).__name__}: {exc}"))

    # -------------------------------------------------------------------- auth

    def token_of(request: Request) -> Token:
        if not known:
            return Token()
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() == "bearer" and token.strip():
            if token.strip() in known:
                return known[token.strip()]
            raise ApiError(401, "invalid_token", "the bearer token is not recognised")
        if localhost_open and request.client is not None and request.client.host in LOOPBACK:
            return Token()
        raise ApiError(401, "missing_token", "a bearer token is required")

    def require(scope: str):
        def check(request: Request) -> None:
            if scope not in token_of(request).scopes:
                raise ApiError(403, "forbidden", f"this call needs the {scope!r} scope")
        return Depends(check)

    def resolve(ref: str) -> tuple[str, str, str]:
        try:
            return store.resolve(ref)
        except ValueError as exc:
            raise ApiError(422, "invalid_request", str(exc)) from exc

    def bundle_reply(request: Request, bundle_id: str, filename: str, described: JSON):
        if BUNDLE_MEDIA_TYPE in request.headers.get("accept", ""):
            return Response(content=store.bundle_file(bundle_id), media_type=BUNDLE_MEDIA_TYPE,
                            headers={"Content-Disposition": f'attachment; filename="{filename}{BUNDLE_SUFFIX}"'})
        return described

    # ------------------------------------------------------------------- health

    @app.get("/health")
    def health() -> JSON:
        from importlib.metadata import version

        from aip.compiler import LANGUAGE_VERSION

        about = {"aip": version("agent-instruction-protocol"), "language": LANGUAGE_VERSION,
                 "backend": getattr(backend, "kind", None), "local": local}
        if local:                                    # loopback only: the client that started it may stop it
            about["pid"] = os.getpid()
        return about

    # ------------------------------------------------------------------ catalog

    @app.get("/catalog", dependencies=[require(READ)])
    def list_catalog() -> list[JSON]:
        return store.catalog()

    @app.get("/catalog/search", dependencies=[require(READ)])
    def search(q: str = Query(""), limit: int = Query(10, ge=1, le=100)) -> list[JSON]:
        return store.search(q, limit)

    @app.post("/catalog", dependencies=[require(PUBLISH)])
    async def publish(request: Request) -> JSON:
        data = await request.body()

        def work() -> JSON:
            bundle = read_upload(data)
            return store.publish(bundle, describe_bundle(bundle))
        return await run_in_threadpool(work)

    @app.get("/catalog/{ref}", dependencies=[require(READ)])
    def info(ref: str, request: Request):
        name, revision, bundle_id = resolve(ref)
        return bundle_reply(request, bundle_id, f"{name}@{revision}", store.describe(f"{name}@{revision}"))

    def graph_reply(bundle_id: str, about: JSON) -> JSON:
        return {**about, "bundle_id": bundle_id, "graph": store.bundle_graph(bundle_id).to_dict()}

    @app.get("/catalog/{ref}/graph", dependencies=[require(READ)])
    def revision_graph(ref: str) -> JSON:
        name, revision, bundle_id = resolve(ref)
        return graph_reply(bundle_id, {"name": name, "revision": revision, "draft": False})

    @app.post("/catalog/{name}/pin", dependencies=[require(PUBLISH)])
    def pin(name: str, body: RevisionBody) -> JSON:
        revision = None if body.revision is None else str(body.revision)
        store.pin(name, revision)
        return {"name": name, "pinned": revision}

    @app.post("/catalog/{name}/retire", dependencies=[require(PUBLISH)])
    def retire(name: str, body: RevisionBody) -> JSON:
        if body.revision is None:
            raise ApiError(422, "invalid_request", "retire needs a revision")
        store.retire(name, str(body.revision))
        return {"name": name, "revision": str(body.revision), "retired": True}

    # ------------------------------------------------------------------ bundles

    @app.post("/bundles", dependencies=[require(RUN)])
    async def upload(request: Request) -> JSON:
        data = await request.body()

        def work() -> JSON:
            bundle = read_upload(data)
            return store.draft(bundle, describe_bundle(bundle))
        return await run_in_threadpool(work)

    @app.get("/bundles", dependencies=[require(READ)])
    def list_bundles(drafts: bool | None = Query(None)) -> list[JSON]:
        return store.bundles(drafts)

    @app.get("/bundles/{bundle_id}", dependencies=[require(READ)])
    def bundle(bundle_id: str, request: Request):
        return bundle_reply(request, bundle_id, bundle_id[:12], store.describe_bundle(bundle_id))

    @app.get("/bundles/{bundle_id}/graph", dependencies=[require(READ)])
    def bundle_graph(bundle_id: str) -> JSON:
        about = store.describe_bundle(bundle_id)
        return graph_reply(bundle_id, {"name": about["name"], "revision": about["revision"], "draft": about["draft"]})

    # --------------------------------------------------------------------- runs

    @app.post("/runs", dependencies=[require(RUN)])
    def record(body: JSON, request: Request) -> JSON:
        return store.record(dict(body), user=token_of(request).name)

    @app.get("/runs", dependencies=[require(READ)])
    def list_runs(name: str | None = Query(None), status: str | None = Query(None), agent: str | None = Query(None),
                  session: str | None = Query(None), user: str | None = Query(None), draft: bool | None = Query(None),
                  limit: int = Query(50, ge=1, le=1000)) -> list[JSON]:
        return store.runs(name=name, status=status, agent=agent, session=session, user=user, draft=draft, limit=limit)

    @app.get("/runs/{run_id}", dependencies=[require(READ)])
    def get_run(run_id: str) -> JSON:
        return store.run(run_id)

    # -------------------------------------------------------------------- audit

    @app.get("/audit", dependencies=[require(READ)])
    def list_audit() -> list[JSON]:
        return [{**row, "path": f"/audit/{row['query']}"} for row in audit.listing(store)]

    @app.get("/audit/{query}", dependencies=[require(READ)])
    def audit_query(query: str, name: str | None = Query(None), agent: str | None = Query(None),
                    session: str | None = Query(None), user: str | None = Query(None), draft: bool | None = Query(None),
                    window: int = Query(audit.DEFAULT_WINDOW, ge=1, le=100000), limit: int = Query(audit.DEFAULT_LIMIT, ge=1, le=10000),
                    repeats: int = Query(audit.DEFAULT_REPEATS, ge=0, le=100000), key: str | None = Query(None)) -> list[JSON]:
        try:
            return audit.run(store, query, name=name, agent=agent, session=session, user=user, draft=draft, window=window,
                             limit=limit, repeats=repeats, key=key)
        except KeyError:
            raise ApiError(404, "not_found", f"no audit query {query!r}; GET /audit lists them") from None
        except audit.InvalidQuery:
            raise
        except Exception as exc:
            if query in audit.QUERIES:
                raise
            raise ApiError(422, "invalid_request", f"the stored query {query} failed: {type(exc).__name__}: {exc}") from exc

    @app.put("/audit/{name}", dependencies=[require(PUBLISH)])
    def store_query(name: str, body: QueryBody) -> JSON:
        return {**audit.save(store, name, body.cypher, body.description), "path": f"/audit/{name}"}

    @app.delete("/audit/{name}", dependencies=[require(PUBLISH)])
    def remove_query(name: str) -> JSON:
        try:
            audit.delete(store, name)
        except KeyError:
            raise ApiError(404, "not_found", f"no stored audit query {name!r}") from None
        return {"query": name, "deleted": True}

    # ------------------------------------------------------------------- export

    @app.get("/export/runs", dependencies=[require(READ)])
    def export_runs(name: str | None = Query(None), since: str | None = Query(None), agent: str | None = Query(None),
                    session: str | None = Query(None), user: str | None = Query(None), draft: bool | None = Query(None)):
        with tempfile.TemporaryDirectory(prefix="aip-export-") as tmp:
            path = Path(tmp) / f"runs{BUNDLE_SUFFIX}"
            counted = store.export_runs(path, name=name, since=since_of(since), agent=agent, session=session, user=user, draft=draft)
            return Response(content=path.read_bytes(), media_type=BUNDLE_MEDIA_TYPE,
                            headers={"Content-Disposition": f'attachment; filename="runs{BUNDLE_SUFFIX}"',
                                     "X-AIP-Runs": str(counted["runs"]), "X-AIP-Bundles": str(counted["bundles"])})

    app.state.backend = backend
    return app


__all__ = ["ALL_SCOPES", "ApiError", "PUBLISH", "READ", "RUN", "Token", "create_app", "describe_bundle", "read_upload"]
