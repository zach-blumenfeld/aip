"""The HTTP server (design §4.2): one API over either backend; the server holds every run.

`create_app(backend)` returns a FastAPI application. `backend` is anything with a
`.catalog` (`CatalogBackend`) and, optionally, a `.runs` (`RunBackend`); the filesystem
and Neo4j backends both qualify. Every endpoint is one of three kinds:

- **catalog**: `/catalog`, `/catalog/search`, `/catalog/{ref}`, `/catalog/{ref}/files`,
  `/catalog/{ref}/files/{path}`, `POST /catalog`, `POST /catalog/{name}/pin|retire`.
  Decision thresholds are the author's, from SKILL.md, and nothing else.
- **runs**: `POST /runs` opens a run on a start input and replies with where it stopped;
  `POST /runs/{id}/result` carries one thing to it (the answer to its pause, or nothing to
  retry a failed step); `GET /runs`, `GET /runs/{id}`. Each call loads the run from the
  `RunBackend`, steps it with `aip.model.engine`, and stores what changed with a version
  check, so nothing per run stays in this process and any replica can answer any call; a
  write that lost a race answers 409. Without a `RunBackend` these answer 501.
  The server never runs a script and never calls a decision model. At a decision the run stops
  and the reply is the decision pause with the author's `thresholds`; the client resolves it
  and posts the answers with their `attribution` (`{"resolver": "typesafe"|"manual", "model",
  "confidence", "reviewed"}`, plus `proposed` when reviewed; omitted means manual), which is
  checked against the questions and recorded in the history. At an execution step the run
  stops and the reply is the step to perform (`{"paused": "execute", "step", "script", "command", "stdin", "timeout",
  "requires"}`); the client runs it next to its data and posts the report as the `answer`
  (`{"output": {...}, "seconds"}`, or a failure with exit code and stderr, a timeout, or the
  unmet requirements), which is validated against the step's outputs and recorded.
- **execution** (deprecated, one version): `/procedures/{ref}/peek|step|answer|capabilities`,
  where the client carries the state and history on every call. `step` and `answer` reply
  with a `Deprecation` header and append to the run named by their `run_id`; an execution
  step answers 409 `runs_on_client` (open the run with `POST /runs`), a decision 422
  `no_decision_model` (answer it through `answer`).
- **governance**: `/governance` lists the named corpus queries of `aip.server.governance`;
  `/governance/{query}?name=&window=&limit=` answers one through the backend's `.governance`
  (501 when it has none or declines the query).

The server serves no UI: the console (formerly inspector) is its own npm package and calls
this API like any other client, from its own origin. So the server answers CORS for pages served
from a loopback origin (`http://localhost:<port>`, `127.0.0.1`, `[::1]`), where the console runs,
and for any origin in `allow_origins`; a page from anywhere else on the web cannot read it.

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
import shutil
import tarfile
import tempfile
import threading
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List

from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from aip.model import Decision, Execution, describe_next, engine
from aip.model.engine import Advance, Cursor
from aip.model.types import InputValidationError, OutputValidationError, StepError, example_input
from aip.server.backend import NotFound, NotSupported, StaleRun, split_ref
from aip.server.governance import DEFAULT_LIMIT, DEFAULT_WINDOW, QUERIES
from aip.server.records import MANIFEST, SkillRecord, snapshot

JSON = Dict[str, Any]

READ, PUBLISH = "read", "publish"
ALL_SCOPES = frozenset({READ, PUBLISH})
LOOPBACK = {"127.0.0.1", "::1", "localhost"}

# Pages the server answers CORS for without being told: the console runs on the user's machine.
LOOPBACK_ORIGINS = r"https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?"

# On the replies of `/procedures/{ref}/step|answer`, which go once `POST /runs` has had a version.
DEPRECATED = {"Deprecation": "true", "Link": '</runs>; rel="successor-version"'}


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
    run_id: str | None = None


class AnswerBody(PeekBody):
    history: List[JSON] = Field(default_factory=list)
    answers: JSON
    attribution: JSON | None = None
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
    input: JSON


class ResultBody(BaseModel):
    """One thing for a run. `answer` answers its pause or reports its script (omit it to retry a failed step), with
    `attribution` at a decision (omit it for a manual answer); `step` and `version` are what the client last saw,
    and a run that has moved on answers 409."""
    answer: JSON | None = None
    attribution: JSON | None = None
    step: str | None = None
    version: int | None = None


# ------------------------------------------------------------------------------- app


def create_app(backend: Any, tokens: Dict[str, set[str]] | None = None,
               localhost_open: bool = True, allow_origins: List[str] | None = None) -> FastAPI:
    """Build the server over `backend`.

    tokens:          bearer token -> scopes (`read`, `publish`); empty or None means no auth
    localhost_open:  a loopback client needs no token even when tokens are configured
    allow_origins:   origins besides loopback ones whose pages may call this server (CORS)
    """
    catalog = backend.catalog
    runs = getattr(backend, "runs", None)
    governance = getattr(backend, "governance", None)
    tokens = {t: set(s) for t, s in (tokens or {}).items()}
    procedures: Dict[tuple[str, str], Any] = {}
    lock = threading.Lock()

    app = FastAPI(title="aip server", version="0.5a0", docs_url=None, redoc_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=list(allow_origins or []), allow_origin_regex=LOOPBACK_ORIGINS,
                       allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"])

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

    @app.exception_handler(StaleRun)
    async def _stale(_: Request, exc: StaleRun):
        return JSONResponse(ApiError(409, "stale_run", str(exc)).body(), status_code=409)

    @app.exception_handler(InputValidationError)
    @app.exception_handler(OutputValidationError)
    async def _invalid_keys(_: Request, exc: InputValidationError | OutputValidationError):
        return JSONResponse(ApiError(422, exc.kind, str(exc), location=exc.step, errors=exc.errors,
                                     **exc.fields()).body(), status_code=422)

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

                procedures[key] = load_procedure(catalog.folder(name, revision))
            return procedures[key]

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
        state = response["result"] if response["next"] is None else response["suggested"]
        for i, entry in enumerate(new_entries):
            last = i == len(new_entries) - 1
            runs.append(run_id, entry, status if last else "running", pause if last else None,
                        **({"state": state, "after": response["ran"]} if last else {}))
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
            detail = exc.fields() if isinstance(exc, StepError) else {}
            runs.append(run_id, {"step": getattr(node, "name", None), "kind": "error",
                                 "step_kind": getattr(node, "kind", None), "input": payload,
                                 "result": {"error": f"{type(exc).__name__}: {exc}", **detail}}, "failed", None)
        except Exception:  # the failure itself is what the client needs to hear about
            pass
        return run_id

    def failed_step(body: StepBody | AnswerBody, name: str, revision: str, node: Any, exc: Exception) -> None:
        """Record a step that failed while running and raise its error: the failure's own kind and
        detail (`script_failed` with exit code and stderr, `timeout`, `invalid_output`), else `step_failed`."""
        failed = record_failure(body.run_id, name, revision, node, body.payload, exc)
        kind, detail = (exc.kind, exc.fields()) if isinstance(exc, StepError) else ("step_failed", {})
        raise ApiError(500, kind, f"{type(exc).__name__}: {exc}", location=getattr(node, "name", body.after),
                       **detail, **({"run_id": failed} if failed is not None else {})) from exc

    def execute(ref: str, body: StepBody | AnswerBody, answers: JSON | None) -> JSON:
        name, revision = resolve(ref)
        proc = procedure(name, revision)
        if body.run_id is not None:
            require_runs().get(body.run_id)      # 404 before any script runs
        node = None
        try:
            if answers is None:
                node, _ = proc.resolve(body.after, body.payload)
                if isinstance(node, Execution):
                    raise ApiError(409, "runs_on_client",
                                   f"step {node.name!r} is an execution step and scripts run on the client; "
                                   "open the run with POST /runs", location=node.name)
                if isinstance(node, Decision):
                    raise ApiError(422, "no_decision_model",
                                   f"step {node.name!r} is a decision and decisions are resolved by the client; "
                                   "answer its questions through /answer", location=node.name)
                response = proc.run(body.after, body.payload, body.history).to_dict()
            else:
                node, entries = proc.resolve(body.after, body.payload)
                if not isinstance(node, Decision):
                    raise ApiError(422, "not_a_decision", f"the step after {body.after!r} is not a decision",
                                   location=getattr(node, "name", None))
                response = node.accept_answers(body.payload, [*body.history, *entries], answers,
                                               body.attribution).to_dict()
        except (ApiError, NotFound, InputValidationError):
            raise
        except OutputValidationError as exc:
            if exc.script is None:                # an answer that does not fit: nothing ran
                raise
            failed_step(body, name, revision, node, exc)
        except KeyError as exc:
            raise ApiError(422, "invalid_request", str(exc)) from exc
        except Exception as exc:
            failed_step(body, name, revision, node, exc)
        run_id = record_run(body.run_id, name, revision, len(body.history), response)
        return {**response, "run_id": run_id, "name": name, "revision": revision}

    def store(run_id: str, version: int, advance: Advance) -> int:
        """Append what one call did, every write checked against the version before it: the new
        history entries, a failure's entry, then the run's status, pause, state and `after`."""
        cursor = advance.cursor
        entries = [*advance.entries, *([advance.failure] if advance.failure is not None else [])]
        for entry in entries[:-1]:
            version = runs.append(run_id, entry, "running", None, expected=version)
        return runs.append(run_id, entries[-1] if entries else None, cursor.status, cursor.pause,
                           expected=version, state=cursor.state, after=cursor.after)

    def reply(run_id: str, name: str, revision: str, version: int, advance: Advance) -> JSON:
        """Where the run stopped: the paused, done, or error object the CLI prints (a decision pause
        also carries its `thresholds`), the run's id and version, and the `--progress` lines of
        the steps this call completed."""
        out = {**advance.outcome(), "run_id": run_id, "name": name, "revision": revision, "version": version,
               "steps": advance.lines}
        if advance.error is not None:
            out["resumable"] = True
        return out

    def rejected(advance: Advance, status: int) -> ApiError:
        """A call that changed nothing: a start input or an answer that does not fit."""
        error = dict(advance.error)
        kind, message, step = error.pop("error"), error.pop("message"), error.pop("step")
        return ApiError(status, kind, message, location=step, **error)

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
        from aip_spec.skill import parse_skill_md

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

    # ---------------------------------------------------------------- execution

    @app.get("/procedures/{ref}/capabilities", dependencies=[require(READ)])
    def capabilities(ref: str) -> JSON:
        name, revision = resolve(ref)
        return {"name": name, "revision": revision, "executes_scripts": False, "persists_runs": runs is not None, "governance": governance is not None}

    @app.post("/procedures/{ref}/peek", dependencies=[require(READ)])
    def peek(ref: str, body: PeekBody) -> JSON | None:
        name, revision = resolve(ref)
        try:
            node, _ = procedure(name, revision).resolve(body.after, body.payload)
        except KeyError as exc:
            raise ApiError(422, "invalid_request", str(exc)) from exc
        return describe_next(node)

    @app.post("/procedures/{ref}/step", dependencies=[require(READ)])
    def step(ref: str, body: StepBody, response: Response) -> JSON:
        response.headers.update(DEPRECATED)
        return execute(ref, body, None)

    @app.post("/procedures/{ref}/answer", dependencies=[require(READ)])
    def answer(ref: str, body: AnswerBody, response: Response) -> JSON:
        response.headers.update(DEPRECATED)
        return execute(ref, body, body.answers)

    # --------------------------------------------------------------------- runs

    @app.post("/runs", dependencies=[require(READ)], status_code=201)
    def open_run(body: RunBody) -> JSON:
        """Open a run on the start input and step it until it stops. A start input the first step
        rejects is a 422 and opens nothing."""
        require_runs()
        name, revision = resolve(body.name if body.revision is None else f"{body.name}@{body.revision}")
        advance = engine.start(procedure(name, revision), body.input, scripts=False)
        if advance.cursor is None:
            raise rejected(advance, 422)
        run_id = runs.create(name, revision)
        return reply(run_id, name, revision, store(run_id, 0, advance), advance)

    @app.post("/runs/{run_id}/result", dependencies=[require(READ)])
    def post_result(run_id: str, body: ResultBody | None = None) -> JSON:
        """Carry one thing to a run: the answer to its pause, the report of the script it waits at,
        or nothing (retry a failed step). 409 when the run has moved past what the client saw
        (`step`, `version`) or another call wrote first; 422 when the answer does not fit (the
        run stays)."""
        body = body or ResultBody()
        run = require_runs().get(run_id)
        if body.version is not None and body.version != run.version:
            raise ApiError(409, "stale_run", f"run {run_id!r} is at version {run.version}, not {body.version}")
        pending = (run.pause or {}).get("step")
        if body.step is not None and body.step != pending:
            raise ApiError(409, "stale_run", f"run {run_id!r} is not waiting on step {body.step!r} "
                                             f"(status {run.status}, step {pending!r})")
        cursor = Cursor(run.after, run.state, [e for e in run.history if e.get("kind") != "error"], run.pause)
        advance = engine.submit(procedure(run.name, run.revision), cursor, body.answer, scripts=False,
                                attribution=body.attribution)
        if advance.kept:
            raise rejected(advance, 422 if advance.error["error"] in ("invalid_input", "invalid_output") else 409)
        return reply(run_id, run.name, run.revision, store(run_id, run.version, advance), advance)

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
                "started_at": r.started_at, "updated_at": r.updated_at, "version": r.version,
                "after": r.after, "pause": r.pause, "state": r.state, "history": r.history}

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

    app.state.backend = backend
    return app


# --------------------------------------------------------------------------- helpers


def run_status(response: JSON) -> tuple[str, JSON | None]:
    """The run status and pause block a step response implies: done at the end, paused when the
    client must act (a client task, or answers to review), running otherwise. The pause block
    is the client's (`aip.model.engine.pause_of`)."""
    from aip.model.engine import pause_of

    if response["next"] is None:
        return "done", None
    pause = pause_of(response)
    return ("running", None) if pause is None else ("paused", pause)


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
