"""What the runner talks to. One method shape, two homes.

`LocalBackend` steps a Procedure in-process with `aip.model.engine`, which is what
`aip run <skill-dir>` uses; the run's cursor (state, history, pause) lives in the run file.
`HttpBackend` opens and continues the run on an AIP server (`POST /runs`,
`POST /runs/{id}/result`); the server holds the cursor, and the run file only the run's id,
server, revision, version and pending pause.

Both answer `open(payload)` and `submit(run, answer)` with a `Step`: the outcome object the
CLI prints (without `run_id` and `run_file`), the `--progress` lines, and what to write to the
run file, so the runner does not know which one it has.

Either way this process runs the scripts (`aip.client.executor`): the loop stops at each
execution step with a request, the client runs the script next to its data, from the skill
folder or the revision's cached `scripts/` and `assets/`, with the run's working directory
(`workdir`, recorded in the run file) as `AIP_WORKDIR`, and carries the report back to the loop.
"""

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Protocol

JSON = Dict[str, Any]


@dataclass
class Step:
    """Where a run stopped after one call.

    outcome:   `{"paused": kind, ...}`, `{"done": true, "state"}`, or `{"error": kind, ...}`
    lines:     the `--progress` line of every step the call completed
    run:       the run file to write; None when there is nothing to keep (the start input was
               rejected before any step ran) or when the run did not move (`kept`)
    kept:      an answer that does not fit its pause: the pause stands and the run file is unchanged
    run_id:    the run's id
    exc:       the exception behind an error, for `--debug`
    """
    outcome: JSON
    lines: List[JSON] = field(default_factory=list)
    run: Any = None
    kept: bool = False
    run_id: str | None = None
    exc: BaseException | None = None

    @property
    def resumable(self) -> bool:
        return self.kept or self.run is not None


class Backend(Protocol):
    def describe(self) -> JSON: ...

    def open(self, payload: JSON) -> Step:
        """Start a run on the start input and step it until it stops."""

    def submit(self, run: Any, answer: JSON | None) -> Step:
        """Carry the answer to the run's pause, or (None, at a failed step) retry the step."""


def _workdir(workdir: Path | str | None) -> Path:
    return Path(workdir if workdir is not None else Path.cwd()).resolve()


class LocalBackend:
    """`workdir` is the run's working directory, where its scripts read and write files (default
    the current directory)."""

    def __init__(self, skill_dir: Path, client: Any = None, python: Path | None = None,
                 workdir: Path | str | None = None):
        from aip.client.executor import Executor
        from aip.spec.loader import load_procedure

        self.skill_dir = Path(skill_dir)
        self._client = client
        self.procedure = load_procedure(self.skill_dir, client=client, python=python)
        self.workdir = _workdir(workdir)
        self.executor = Executor(self.skill_dir, self.workdir, python)

    def describe(self) -> JSON:
        return self.procedure.describe()

    def has_decision_model(self) -> bool:
        return self._client is not None or bool(os.environ.get("TYPESAFE_API_KEY"))

    def open(self, payload: JSON, run_id: str | None = None) -> Step:
        from aip.client.runner import new_run_id
        from aip.model import engine

        advance = engine.start(self.procedure, payload, self.has_decision_model(), scripts=False)
        return self._step(self._perform(advance), run_id or new_run_id())

    def submit(self, run: Any, answer: JSON | None) -> Step:
        from aip.model import engine
        from aip.model.engine import Cursor

        if getattr(run, "workdir", None):
            self.executor.workdir = Path(run.workdir)
        cursor = Cursor(run.after, run.state, run.history, run.pause)
        if run.pause.get("kind") == "execute" and answer is None:
            answer = self.executor.perform(run.pause)
        advance = engine.submit(self.procedure, cursor, answer, self.has_decision_model(), scripts=False)
        return self._step(self._perform(advance), run.run_id, created=run.created)

    def _perform(self, advance: Any) -> Any:
        """Run each script the loop stops at, here, and carry its report back, until the run stops
        for something else; the lines of every call, in order."""
        from aip.model import engine

        lines = list(advance.lines)
        while advance.error is None and advance.cursor is not None and advance.cursor.pause["kind"] == "execute":
            report = self.executor.perform(advance.cursor.pause)
            advance = engine.submit(self.procedure, advance.cursor, report, self.has_decision_model(), scripts=False)
            lines += advance.lines
        advance.lines = lines
        return advance

    def _step(self, advance: Any, run_id: str, created: float | None = None) -> Step:
        """The run file holds the whole cursor: `resume` rebuilds the run from it alone, from any
        directory (so the folder is recorded as an absolute path)."""
        from aip.client.runner import RunFile

        run = None
        if advance.cursor is not None and not advance.kept:
            c = advance.cursor
            run = RunFile(pause=c.pause, run_id=run_id, skill_dir=str(self.skill_dir.resolve()),
                          after=c.after, state=c.state, history=c.history, workdir=str(self.executor.workdir),
                          created=created or time.time())
        return Step(advance.outcome(), advance.lines, run, advance.kept, run_id if advance.resumable else None,
                    advance.exc)


class HttpBackend:
    """A run on an AIP server (design §8): `POST /runs` and `POST /runs/{id}/result`.

    `server` is a URL or a `Server`; `name` is `name`, `name@<revision>`, or `name@latest`. The
    server resolves the ref to an exact revision when it opens the run, and the run stays on it,
    so a run never straddles a re-pin. A served run's file holds only the run's id, server,
    name, revision, version, working directory and pending pause: the server holds the state
    and the history, and `resume` sends only the answer.

    When the server replies with an execution step, this client fetches the revision's
    `scripts/` and `assets/` into its cache (once), runs the script with `workdir` as the run's
    working directory, and posts the report, until the server replies with something else.
    """

    def __init__(self, server: Any, token: str | None = None, name: str = "", *, session: Any = None,
                 workdir: Path | str | None = None, python: Path | None = None):
        from aip.client.server import Server

        self.server = server if isinstance(server, Server) else Server(str(server), token, session=session)
        self.ref = name
        self.workdir = _workdir(workdir)
        self.python = python
        self._executors: Dict[str, Any] = {}

    def describe(self) -> JSON:
        return self.server.info(self.ref)

    def open(self, payload: JSON) -> Step:
        name, _, revision = self.ref.partition("@")
        body = {"name": name, "input": payload, **({"revision": revision} if revision else {})}
        return self._call("/runs", body, None)

    def submit(self, run: Any, answer: JSON | None) -> Step:
        if getattr(run, "workdir", None):
            self.workdir = Path(run.workdir)
        if run.pause.get("kind") == "execute" and answer is None:
            # the client stopped before it reported the script: run it now
            return self._perform(run, [])
        body = {"step": run.pause.get("step"), "version": run.version,
                **({"answer": answer} if answer is not None else {})}
        return self._call(f"/runs/{run.run_id}/result", body, run)

    def executor(self, name: str, revision: str) -> Any:
        """The executor for a revision, its scripts and assets fetched into the cache."""
        from aip.client.executor import Executor, fetch

        key = f"{name}@{revision}"
        if key not in self._executors:
            self._executors[key] = Executor(fetch(self.server, name, revision), self.workdir, self.python)
        executor = self._executors[key]
        executor.workdir = self.workdir
        return executor

    def _perform(self, run: Any, lines: List[JSON]) -> Step:
        """Run the script the run waits at and post the report. If the scripts cannot be fetched
        the run waits at the step (an error, resumable: `resume` tries again)."""
        from aip.client.runner import error_object

        try:
            report = self.executor(run.name, run.revision).perform(run.pause)
        except Exception as exc:
            return Step({**error_object(exc), "step": run.pause["step"]}, lines, run, run_id=run.run_id, exc=exc)
        body = {"step": run.pause["step"], "version": run.version, "answer": report}
        return self._call(f"/runs/{run.run_id}/result", body, run, lines)

    def _call(self, path: str, body: JSON, run: Any, lines: List[JSON] | None = None) -> Step:
        """Post, and turn the reply into a `Step`. A 422 is a start input or an answer that does
        not fit, a 409 a run that moved on since the run file was written: either way nothing
        changed on the server, so the run file stays as it is. An execution step is run here and
        reported, and the lines of every call are kept, in order."""
        from aip.client.runner import RunFile, error_object
        from aip.client.server import ServerError

        lines = list(lines or [])
        try:
            reply = self.server.post(path, body)
        except ServerError as exc:
            kept = run is not None and exc.status in (409, 422)
            return Step(error_object(exc), lines, kept=kept, run_id=run.run_id if run is not None else None, exc=exc)
        meta = {k: reply.pop(k) for k in ("run_id", "name", "revision", "version", "steps", "resumable") if k in reply}
        lines += meta.get("steps", [])
        outcome = reply
        if "paused" in outcome:
            pause = {"kind": outcome["paused"], **{k: v for k, v in outcome.items() if k != "paused"}}
        elif "done" in outcome:
            pause = {"kind": "done", "state": outcome["state"]}
        else:
            pause = {"kind": "error", "step": outcome["step"], "error": outcome["error"]}
        saved = RunFile(pause=pause, run_id=meta["run_id"], server=self.server.url, name=meta["name"],
                        revision=meta["revision"], version=meta["version"], workdir=str(self.workdir),
                        created=run.created if run is not None else time.time())
        if pause["kind"] == "execute":
            return self._perform(saved, lines)
        return Step(outcome, lines, saved, run_id=meta["run_id"])
