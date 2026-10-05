"""The HTTP server (design §4.2): one API over either backend; the server executes scripts.

`create_app(backend)` returns a FastAPI application. `backend` is anything with a
`.catalog` (`CatalogBackend`) and, optionally, a `.runs` (`RunBackend`); the filesystem
and Neo4j backends both qualify. Every endpoint is one of three kinds:

- **catalog**: `/catalog`, `/catalog/search`, `/catalog/{ref}`, `/catalog/{ref}/files`,
  `/catalog/{ref}/files/{path}`, `POST /catalog`, `POST /catalog/{name}/pin|retire`, and
  `GET|POST /catalog/{name}/thresholds` for the per-question overrides a `step` merges under
  the request's own `thresholds` (design §7).
- **execution**: `/procedures/{ref}/peek|step|answer|capabilities`, one per method of
  the client's `Backend` protocol. The procedure is loaded from the backend's folder for
  that revision (`catalog.folder`), cached per revision, and `Procedure.run` does the
  work; scripts run here, with this process's interpreter and privileges.
- **runs**: `/runs`, `/runs/{id}`; `step` and `answer` append to the run named by their
  `run_id` (creating one when absent). Without a `RunBackend` these answer 501.
- **governance**: `/governance` lists the named corpus queries of `aip.server.governance`;
  `/governance/{query}?name=&window=&limit=` answers one through the backend's `.governance`
  (501 when it has none or declines the query).

- **inspector** (optional): with `inspector=<dir>`, the built `aip-inspector` bundle in that
  directory is served at `/inspector/` (`index.html` at the root, hashed assets beside it).
  `INSPECTOR_DIR` is where the package ships it; `npm run build && npm run sync` in the
  inspector repo refreshes it. A missing bundle answers 404 with instructions, not a crash.

`ref` is `name`, `name@<revision>`, or `name@latest`, resolved by the catalog.

Errors are `{"error": {"kind", "message", "location"?, ...}}`. Auth is a bearer token
with `read` and `publish` scopes (`tokens={token: {scopes}}`); with no tokens configured
the server is open, and a loopback client may call without a token either way.
"""

from __future__ import annotations

import base64
import io
import json
import mimetypes
import os
import shutil
import tarfile
import tempfile
import threading
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List

from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from aip.model import Decision, describe_next
from aip.model.types import InputValidationError, example_input
from aip.server.backend import NotFound, NotSupported, split_ref
from aip.server.governance import DEFAULT_LIMIT, DEFAULT_WINDOW, QUERIES
from aip.server.records import MANIFEST, SkillRecord, snapshot

JSON = Dict[str, Any]

READ, PUBLISH = "read", "publish"
ALL_SCOPES = frozenset({READ, PUBLISH})
LOOPBACK = {"127.0.0.1", "::1", "localhost"}

# The inspector bundle the package ships (design §10): `aip server --inspector` serves it.
INSPECTOR_DIR = Path(__file__).parent / "inspector"


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


# ----------------------------------------------------------------------------- bodies


class PeekBody(BaseModel):
    after: str | None = None
    payload: JSON = Field(default_factory=dict)


class StepBody(PeekBody):
    history: List[JSON] = Field(default_factory=list)
    thresholds: Dict[str, float] | None = None
    run_id: str | None = None


class AnswerBody(PeekBody):
    history: List[JSON] = Field(default_factory=list)
    answers: JSON
    run_id: str | None = None


class UploadFile(BaseModel):
    path: str
    bytes_b64: str
    mode: int = 0o644


class PublishBody(BaseModel):
    files: List[UploadFile]


class RevisionBody(BaseModel):
    revision: str | None = None


class RunBody(BaseModel):
    name: str
    revision: str | None = None


class ThresholdsBody(BaseModel):
    thresholds: Dict[str, float]


# ------------------------------------------------------------------------------- app


def create_app(backend: Any, tokens: Dict[str, set[str]] | None = None, client: Any = None,
               python: Path | None = None, localhost_open: bool = True,
               inspector: Path | None = None) -> FastAPI:
    """Build the server over `backend`.

    tokens:          bearer token -> scopes (`read`, `publish`); empty or None means no auth
    client:          an injected decision-model client (tests); otherwise TYPESAFE_API_KEY decides
    python:          interpreter for scripts; default this process's own
    localhost_open:  a loopback client needs no token even when tokens are configured
    inspector:       serve the inspector bundle in this directory at /inspector/ (None: do not)
    """
    catalog = backend.catalog
    runs = getattr(backend, "runs", None)
    governance = getattr(backend, "governance", None)
    tokens = {t: set(s) for t, s in (tokens or {}).items()}
    procedures: Dict[tuple[str, str], Any] = {}
    lock = threading.Lock()

    app = FastAPI(title="aip server", version="0.5a0", docs_url=None, redoc_url=None)

    # ------------------------------------------------------------------ errors

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return JSONResponse(exc.body(), status_code=exc.status)

    @app.exception_handler(NotFound)
    async def _not_found(_: Request, exc: NotFound):
        return JSONResponse(ApiError(404, "not_found", str(exc)).body(), status_code=404)

    @app.exception_handler(NotSupported)
    async def _not_supported(_: Request, exc: NotSupported):
        return JSONResponse(ApiError(501, "not_supported", str(exc)).body(), status_code=501)

    @app.exception_handler(InputValidationError)
    async def _invalid_input(_: Request, exc: InputValidationError):
        return JSONResponse(ApiError(422, "invalid_input", str(exc), location=exc.step, errors=exc.errors).body(),
                            status_code=422)

    @app.exception_handler(RequestValidationError)
    async def _invalid_request(_: Request, exc: RequestValidationError):
        detail = "; ".join(".".join(str(p) for p in e["loc"]) + ": " + e["msg"] for e in exc.errors())
        return JSONResponse(ApiError(422, "invalid_request", detail).body(), status_code=422)

    @app.exception_handler(Exception)
    async def _internal(_: Request, exc: Exception):
        return JSONResponse(ApiError(500, "internal", f"{type(exc).__name__}: {exc}").body(), status_code=500)

    # -------------------------------------------------------------------- auth

    def scopes_of(request: Request) -> set[str]:
        if not tokens:
            return set(ALL_SCOPES)
        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() == "bearer" and token.strip():
            if token.strip() in tokens:
                return tokens[token.strip()]
            raise ApiError(401, "invalid_token", "the bearer token is not recognised")
        if localhost_open and request.client is not None and request.client.host in LOOPBACK:
            return set(ALL_SCOPES)
        raise ApiError(401, "missing_token", "a bearer token is required")

    def require(scope: str):
        def check(request: Request) -> None:
            if scope not in scopes_of(request):
                raise ApiError(403, "forbidden", f"this call needs the {scope!r} scope")
        return Depends(check)

    # ---------------------------------------------------------------- helpers

    def resolve(ref: str) -> tuple[str, str]:
        try:
            return catalog.resolve(ref)
        except ValueError as exc:
            raise ApiError(422, "invalid_request", str(exc)) from exc

    def procedure(name: str, revision: str):
        key = (name, revision)
        with lock:
            if key not in procedures:
                from aip.spec.loader import load_procedure

                procedures[key] = load_procedure(catalog.folder(name, revision), client=client, python=python)
            return procedures[key]

    def has_decision_model() -> bool:
        return client is not None or bool(os.environ.get("TYPESAFE_API_KEY"))

    def require_runs():
        if runs is None:
            raise ApiError(501, "not_supported", "this server does not persist runs")
        return runs

    def record_run(run_id: str | None, name: str, revision: str, carried: int, response: JSON) -> str | None:
        """Append what this call added to the run's history; create the run when there is none yet."""
        if runs is None:
            return None
        if run_id is None:
            run_id = runs.create(name, revision)
        new_entries = response["history"][carried:]
        status, pause = run_status(response)
        for i, entry in enumerate(new_entries):
            last = i == len(new_entries) - 1
            runs.append(run_id, entry, status if last else "running", pause if last else None)
        return run_id

    def record_failure(run_id: str | None, name: str, revision: str, node: Any, payload: JSON,
                       exc: Exception) -> str | None:
        """Record a step that raised against the step itself (not the one before it), starting the
        run when the failing call was its first; returns the run id so the error can name it."""
        if runs is None:
            return None
        try:
            if run_id is None:
                run_id = runs.create(name, revision)
            runs.append(run_id, {"step": getattr(node, "name", None), "kind": "error",
                                 "step_kind": getattr(node, "kind", None), "input": payload,
                                 "result": {"error": f"{type(exc).__name__}: {exc}"}}, "error", None)
        except Exception:  # the failure itself is what the client needs to hear about
            pass
        return run_id

    def execute(ref: str, body: StepBody | AnswerBody, answers: JSON | None) -> JSON:
        name, revision = resolve(ref)
        proc = procedure(name, revision)
        if body.run_id is not None:
            require_runs().get(body.run_id)      # 404 before any script runs
        node = None
        try:
            if answers is None:
                node, _ = proc.resolve(body.after, body.payload)
                if isinstance(node, Decision) and not has_decision_model():
                    raise ApiError(422, "no_decision_model",
                                   f"step {node.name!r} is a decision and this server has no decision model; "
                                   "answer its questions through /answer", location=node.name)
                thresholds = {**catalog.thresholds(name), **(body.thresholds or {})}
                response = proc.run(body.after, body.payload, body.history, thresholds or None).to_dict()
            else:
                node, entries = proc.resolve(body.after, body.payload)
                if not isinstance(node, Decision):
                    raise ApiError(422, "not_a_decision", f"the step after {body.after!r} is not a decision",
                                   location=getattr(node, "name", None))
                response = node.accept_manual(body.payload, [*body.history, *entries], answers).to_dict()
        except (ApiError, NotFound, InputValidationError):
            raise
        except KeyError as exc:
            raise ApiError(422, "invalid_request", str(exc)) from exc
        except Exception as exc:
            failed = record_failure(body.run_id, name, revision, node, body.payload, exc)
            raise ApiError(500, "step_failed", f"{type(exc).__name__}: {exc}",
                           location=getattr(node, "name", body.after),
                           **({"run_id": failed} if failed is not None else {})) from exc
        run_id = record_run(body.run_id, name, revision, len(body.history), response)
        return {**response, "run_id": run_id, "name": name, "revision": revision}

    # ------------------------------------------------------------------ catalog

    @app.get("/catalog", dependencies=[require(READ)])
    def list_catalog() -> List[JSON]:
        return [{"name": n.name, "description": n.description, "pinned": n.pinned, "latest": n.latest,
                 "revisions": [{"revision": r["revision"], "published_at": r["published_at"],
                                "retired": bool(r["retired"])} for r in catalog.revisions(n.name)]}
                for n in catalog.list()]

    @app.get("/catalog/search", dependencies=[require(READ)])
    def search(q: str = Query(""), limit: int = Query(10, ge=1, le=100)) -> List[JSON]:
        return [{"name": h.name, "revision": h.revision, "description": h.description, "score": h.score}
                for h in catalog.search(q, limit)]

    @app.post("/catalog", dependencies=[require(PUBLISH)], status_code=201)
    def publish(body: PublishBody) -> JSON:
        from aip.spec import validate_skill
        from aip.spec.skill import parse_skill_md

        if not body.files:
            raise ApiError(422, "invalid_request", "no files in the upload")
        tmp = Path(tempfile.mkdtemp(prefix="aip-publish-"))
        try:
            stage = tmp / "stage"
            for f in body.files:
                rel = PurePosixPath(f.path)
                if not f.path or rel.is_absolute() or ".." in rel.parts or any(p in ("", ".") for p in rel.parts):
                    raise ApiError(422, "invalid_request", f"unsafe path in upload: {f.path!r}", location=f.path)
                try:
                    data = base64.b64decode(f.bytes_b64, validate=True)
                except ValueError as exc:
                    raise ApiError(422, "invalid_request", f"{f.path}: bytes_b64 is not base64", location=f.path) from exc
                target = stage / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                target.chmod(f.mode & 0o777)
            doc, issues = parse_skill_md(stage / "SKILL.md")
            name = (doc.frontmatter or {}).get("name") if doc is not None else None
            if not isinstance(name, str) or not name or "/" in name or name in (".", ".."):
                raise ApiError(422, "invalid_skill", "the upload has no SKILL.md with a usable frontmatter name",
                               issues=[_relative_issue(i.to_record(), tmp) for i in issues])
            folder = tmp / name
            stage.rename(folder)
            loaded, issues = validate_skill(folder)
            if loaded is None:
                raise ApiError(422, "invalid_skill", f"{name} failed validation",
                               issues=[_relative_issue(i.to_record(), tmp) for i in issues])
            record = snapshot(folder)
            revision = catalog.publish(record)
            with lock:
                procedures.pop((record.name, revision), None)
            return {"name": record.name, "revision": revision, "id": f"{record.name}@{revision}",
                    "warnings": [_relative_issue(i.to_record(), tmp) for i in issues if i.severity == "warning"]}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @app.get("/catalog/{ref}", dependencies=[require(READ)])
    def info(ref: str) -> JSON:
        name, revision = resolve(ref)
        record = catalog.get(name, revision)
        described = procedure(name, revision).describe()
        return {
            **described,
            "name": name, "revision": revision, "id": record.id, "description": record.description,
            "aip_version": record.aip_version, "published_at": record.published_at, "retired": record.retired,
            **{k: record.procedure.get(k) for k in ("purpose", "trigger_when", "do_not_use_when", "anti_patterns")},
            "example_input": example_input(described["start"]["inputs"]),
            "thresholds": catalog.thresholds(name),
            "step_details": record.steps, "edges": record.edges, "branches": record.branches,
            "inputs": record.inputs, "questions": record.questions, "resources": record.resources,
            "files": [f.manifest_entry() for f in record.files],
        }

    @app.get("/catalog/{ref}/files", dependencies=[require(READ)])
    def files(ref: str, archive: str | None = Query(None)):
        name, revision = resolve(ref)
        if archive is None:
            return [f.manifest_entry() for f in catalog.files(name, revision)]
        if archive != "tar":
            raise ApiError(422, "invalid_request", f"unknown archive format {archive!r}; only 'tar' is supported")
        record = catalog.get(name, revision)
        return Response(content=tar_of(record), media_type="application/x-tar",
                        headers={"Content-Disposition": f'attachment; filename="{name}@{revision}.tar"'})

    @app.get("/catalog/{ref}/files/{path:path}", dependencies=[require(READ)])
    def file(ref: str, path: str):
        name, revision = resolve(ref)
        data = catalog.file(name, revision, path)
        media, _ = mimetypes.guess_type(path)
        return Response(content=data, media_type=media or "application/octet-stream")

    @app.post("/catalog/{name}/pin", dependencies=[require(PUBLISH)])
    def pin(name: str, body: RevisionBody) -> JSON:
        catalog.pin(name, body.revision)
        return {"name": name, "pinned": body.revision}

    @app.post("/catalog/{name}/retire", dependencies=[require(PUBLISH)])
    def retire(name: str, body: RevisionBody) -> JSON:
        if body.revision is None:
            raise ApiError(422, "invalid_request", "retire needs a revision")
        catalog.retire(name, body.revision)
        return {"name": name, "retired": body.revision}

    @app.get("/catalog/{name}/thresholds", dependencies=[require(READ)])
    def get_thresholds(name: str) -> JSON:
        return {"name": name, "thresholds": catalog.thresholds(name)}

    @app.post("/catalog/{name}/thresholds", dependencies=[require(PUBLISH)])
    def set_thresholds(name: str, body: ThresholdsBody) -> JSON:
        bad = {q: v for q, v in body.thresholds.items() if not 0.0 <= v <= 1.0}
        if bad:
            raise ApiError(422, "invalid_request", f"thresholds must be between 0 and 1: {bad}")
        catalog.set_thresholds(name, body.thresholds)
        return {"name": name, "thresholds": catalog.thresholds(name)}

    # ---------------------------------------------------------------- execution

    @app.get("/procedures/{ref}/capabilities", dependencies=[require(READ)])
    def capabilities(ref: str) -> JSON:
        name, revision = resolve(ref)
        return {"name": name, "revision": revision, "decision_model": has_decision_model(),
                "executes_scripts": True, "persists_runs": runs is not None, "governance": governance is not None}

    @app.post("/procedures/{ref}/peek", dependencies=[require(READ)])
    def peek(ref: str, body: PeekBody) -> JSON | None:
        name, revision = resolve(ref)
        try:
            node, _ = procedure(name, revision).resolve(body.after, body.payload)
        except KeyError as exc:
            raise ApiError(422, "invalid_request", str(exc)) from exc
        return describe_next(node)

    @app.post("/procedures/{ref}/step", dependencies=[require(READ)])
    def step(ref: str, body: StepBody) -> JSON:
        return execute(ref, body, None)

    @app.post("/procedures/{ref}/answer", dependencies=[require(READ)])
    def answer(ref: str, body: AnswerBody) -> JSON:
        return execute(ref, body, body.answers)

    # --------------------------------------------------------------------- runs

    @app.post("/runs", dependencies=[require(READ)], status_code=201)
    def create_run(body: RunBody) -> JSON:
        name, revision = resolve(body.name if body.revision is None else f"{body.name}@{body.revision}")
        return {"run_id": require_runs().create(name, revision), "name": name, "revision": revision}

    @app.get("/runs", dependencies=[require(READ)])
    def list_runs(name: str | None = Query(None), status: str | None = Query(None),
                  limit: int = Query(50, ge=1, le=1000)) -> List[JSON]:
        return [{"run_id": r.id, "name": r.name, "revision": r.revision, "status": r.status,
                 "started_at": r.started_at, "updated_at": r.updated_at, "steps": r.steps}
                for r in require_runs().list(name, status, limit)]

    @app.get("/runs/{run_id}", dependencies=[require(READ)])
    def get_run(run_id: str) -> JSON:
        r = require_runs().get(run_id)
        return {"run_id": r.id, "name": r.name, "revision": r.revision, "status": r.status,
                "started_at": r.started_at, "updated_at": r.updated_at, "pause": r.pause, "history": r.history}

    # --------------------------------------------------------------- governance

    @app.get("/governance", dependencies=[require(READ)])
    def list_governance() -> List[JSON]:
        return [{"query": q, "description": d, "path": f"/governance/{q}"} for q, d in QUERIES.items()]

    @app.get("/governance/{query}", dependencies=[require(READ)])
    def governance_query(query: str, name: str | None = Query(None),
                         window: int = Query(DEFAULT_WINDOW, ge=1, le=100000),
                         limit: int = Query(DEFAULT_LIMIT, ge=1, le=10000)) -> List[JSON]:
        if query not in QUERIES:
            raise ApiError(404, "not_found", f"no governance query {query!r}; GET /governance lists them")
        if governance is None:
            raise ApiError(501, "not_supported", "this server does not answer governance queries")
        return governance.query(query, name=name, window=window, limit=limit)

    # --------------------------------------------------------------- inspector

    if inspector is not None:
        mount_inspector(app, inspector)

    app.state.backend = backend
    return app


def mount_inspector(app: FastAPI, bundle: Path) -> bool:
    """Serve the built inspector in `bundle` at /inspector/; a missing bundle 404s with the fix.

    The bundle is unauthenticated static HTML, JS and CSS: the API calls it makes carry the
    token the user enters on its Server page, so the read scope still gates everything it shows.
    Returns whether the bundle was found.
    """
    present = (bundle / "index.html").is_file()
    if present:
        @app.get("/inspector", include_in_schema=False)
        def inspector_root() -> RedirectResponse:
            return RedirectResponse("/inspector/", status_code=307)

        app.mount("/inspector", StaticFiles(directory=bundle, html=True), name="inspector")
    else:
        @app.get("/inspector", include_in_schema=False)
        @app.get("/inspector/{path:path}", include_in_schema=False)
        def inspector_missing(path: str = "") -> JSONResponse:
            raise ApiError(404, "not_found", f"the inspector bundle is not installed: no index.html in {bundle}. "
                                             "Build it in the aip-inspector repo with `npm run build && npm run sync` "
                                             "(or pass --inspector DIR with a built bundle).")
    return present


# --------------------------------------------------------------------------- helpers


def run_status(response: JSON) -> tuple[str, JSON | None]:
    """The run status and pause block a step response implies: done at the end, paused when the
    client must act (a client task, or answers to review), running otherwise."""
    from aip.client.runner import _expects

    if response["next"] is None:
        return "done", None
    if response["kind"] == "client_task":
        return "paused", {"kind": "client_task", "step": response["ran"], "task": response["result"].get("task"),
                          "references": response["result"].get("references", []),
                          "expects": _expects(response["next"])}
    if response["review"]:
        return "paused", {"kind": "review", "step": response["ran"], "review": response["review"],
                          "expects": _expects(response["next"])}
    return "running", None


def tar_of(record: SkillRecord) -> bytes:
    """A deterministic tar of a revision: `<name>/<path>` for every file (modes kept) plus the
    manifest beside the folder as `.aip-manifest.json`, the same layout both backends keep on disk."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        manifest = json.dumps(record.to_json(with_content=False), indent=2).encode() + b"\n"
        _add(tar, MANIFEST, manifest, 0o644)
        for d in record.directories:
            info = tarfile.TarInfo(f"{record.name}/{d}")
            info.type, info.mode, info.mtime = tarfile.DIRTYPE, 0o755, 0
            tar.addfile(info)
        for f in sorted(record.files, key=lambda x: x.path):
            _add(tar, f"{record.name}/{f.path}", f.data, f.mode)
    return buf.getvalue()


def _add(tar: tarfile.TarFile, name: str, data: bytes, mode: int) -> None:
    info = tarfile.TarInfo(name)
    info.size, info.mode, info.mtime = len(data), mode & 0o777, 0
    tar.addfile(info, io.BytesIO(data))


def _relative_issue(record: JSON, root: Path) -> JSON:
    """Validator issues name the server's temp folder; report paths relative to the upload instead."""
    out = dict(record)
    for key in ("path", "location"):
        value = out.get(key)
        if isinstance(value, str) and value.startswith(str(root)):
            out[key] = value[len(str(root)):].lstrip("/") or "."
    return out


def upload_of(folder: Path) -> JSON:
    """The `POST /catalog` body for a skill folder on disk: what `aip publish` sends."""
    from aip.server.records import walk

    files, _ = walk(Path(folder))
    return {"files": [{"path": f.path, "bytes_b64": base64.b64encode(f.data).decode("ascii"), "mode": f.mode}
                      for f in files]}


__all__ = ["ApiError", "create_app", "run_status", "tar_of", "upload_of"]
