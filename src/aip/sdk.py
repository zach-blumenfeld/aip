"""The Python SDK: `aip.Client`, what the `aip` command and agent frameworks are built on.

    import aip

    client = aip.Client()                          # the configured server (`aip config`, AIP_SERVER)
    client = aip.Client("https://aip.example.com", token="...")
    client = aip.Client("./skills")                # a folder: local runs only, no catalog

    result = client.run("billing-support", {"message": "I was charged twice"})
    while isinstance(result, aip.Paused):
        result = client.resume(result, answer_for(result))
    print(result.state)

Every method returns a typed result and raises an `AipError` subclass: `RunError` when a run
stops on an error (the CLI's error object, with `resumable` saying whether `resume` can
retry), `ServerError` for a failed call to the server, `NoServer` for a catalog operation with
no server, `NotFound` for a skill that is neither a folder nor a published name, `InvalidSkill`
for a folder that does not validate, `InvalidInput` for an input or run reference that is not
usable. A run stops paused (`Paused`, the CLI's paused object) or done (`Done`); either way the
run file is written as the CLI writes it (`~/.aip/runs/<run-id>.json`), so a run started here
can be resumed by `aip resume` and the other way round.

`Driver` is one run's moves through a backend (`aip.client.backend`): it turns each stop into
a typed result and writes the run file. The CLI's `Runner` prints what it returns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Union

from aip.client.server import Server, ServerError
from aip.errors import AipError

JSON = Dict[str, Any]


# --------------------------------------------------------------------------- errors


class NoServer(AipError):
    """A catalog operation, or a published name, with no server to ask."""
    kind = "no_server"


class NotFound(AipError):
    """A skill that is neither a folder on disk nor a name the client can look up."""
    kind = "not_found"


class InvalidInput(AipError):
    """A start input, answer, or run reference that cannot be used as given."""
    kind = "invalid_input"


class InvalidSkill(AipError):
    """A skill folder that does not validate; `validation` lists every issue."""
    kind = "invalid_skill"

    def __init__(self, message: str, validation: "Validation | None" = None):
        super().__init__(message)
        self.validation = validation


class RunError(AipError):
    """A run stopped on an error. `error` is the CLI's error object (`docs/cli-json.md`): `error`
    (the kind), `step`, `message`, the kind's own keys, `run_id`, `resumable`, and `run_file`
    when it is resumable. `cause` is the exception behind it, if any."""

    def __init__(self, error: JSON, cause: BaseException | None = None):
        super().__init__(error.get("message") or error["error"], error["error"])
        self.error = error
        self.cause = cause

    step = property(lambda self: self.error.get("step"))
    run_id = property(lambda self: self.error.get("run_id"))
    resumable = property(lambda self: bool(self.error.get("resumable")))
    run_file = property(lambda self: Path(self.error["run_file"]) if self.error.get("run_file") else None)

    def to_json(self) -> JSON:
        return dict(self.error)


# --------------------------------------------------------------------------- results


@dataclass(frozen=True)
class Paused:
    """The run waits for an answer: `kind` is `decision`, `client_task` or `review`, and `state`
    is the paused step's declared inputs. `to_json()` is the CLI's paused object."""
    kind: str
    step: str
    state: JSON
    run_id: str | None
    run_file: Path | None
    body: JSON = field(default_factory=dict, repr=False, compare=False)   # the object, in printed order

    task = property(lambda self: self.body.get("task"))
    references = property(lambda self: self.body.get("references"))
    answer_with = property(lambda self: self.body.get("answer_with"))
    questions = property(lambda self: self.body.get("questions"))
    proposed_answers = property(lambda self: self.body.get("proposed_answers"))
    review = property(lambda self: self.body.get("review"))

    def to_json(self) -> JSON:
        return {**self.body, "run_id": self.run_id, "run_file": str(self.run_file)}


@dataclass(frozen=True)
class Done:
    """The run reached its end step; `state` is the procedure's result."""
    run_id: str | None
    state: JSON
    run_file: Path | None

    def to_json(self) -> JSON:
        return {"done": True, "run_id": self.run_id, "state": self.state, "run_file": str(self.run_file)}


Result = Union[Paused, Done]


def _record(cls, data: JSON):
    """A typed record of a server object; `data` keeps the object as the server sent it."""
    names = [f for f in cls.__dataclass_fields__ if f != "data"]
    return cls(**{f: data.get(f) for f in names}, data=data)


@dataclass(frozen=True)
class Hit:
    """A search result."""
    name: str
    revision: str
    score: float
    description: str | None
    data: JSON = field(repr=False, compare=False)


@dataclass(frozen=True)
class Entry:
    """A published name: its revisions, newest first, and what it resolves to."""
    name: str
    description: str | None
    pinned: str | None
    latest: str | None
    revisions: List[JSON]
    data: JSON = field(repr=False, compare=False)

    @property
    def resolves(self) -> str | None:
        live = [r for r in self.revisions if not r.get("retired")]
        return self.pinned or self.latest or (live[0]["revision"] if live else None)


@dataclass(frozen=True)
class Validation:
    """The validator's verdict on a folder. `issues` are `aip_spec.Issue`s, errors and warnings."""
    path: Path
    name: str | None
    issues: List[Any]

    @property
    def errors(self) -> List[Any]:
        return [i for i in self.issues if i.severity != "warning"]

    @property
    def warnings(self) -> List[Any]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def valid(self) -> bool:
        return self.name is not None and not self.errors


@dataclass(frozen=True)
class SkillInfo:
    """What a skill does and what to give it. `data` is the `aip info --json` object: the
    procedure's description for a folder, the catalog entry for a published name; `revision` is
    None for a folder. `summary()` is the `aip info` text."""
    name: str
    revision: str | None
    description: str | None
    start_step: str
    inputs: JSON                       # the start step's inputs: name -> type
    result: JSON                       # the end step's inputs, what `done` hands back
    example_input: JSON
    data: JSON = field(repr=False, compare=False)
    _loaded: Callable[[], Any] = field(repr=False, compare=False, default=lambda: None)

    def summary(self) -> str:
        return describe_skill(self._loaded())


@dataclass(frozen=True)
class Published:
    name: str
    revision: str
    id: str
    warnings: List[JSON]
    validation: Validation | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class Fetched:
    """A revision downloaded to `path`, and whether it validates on this machine."""
    path: Path
    validation: Validation


@dataclass(frozen=True)
class Pinned:
    name: str
    revision: str | None               # None: the pin was cleared


@dataclass(frozen=True)
class Retired:
    name: str
    revision: str


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    name: str
    revision: str
    status: str
    started_at: Any
    updated_at: Any
    steps: int
    data: JSON = field(repr=False, compare=False)


@dataclass(frozen=True)
class RunRecord:
    """One run as its home holds it: the server's record, or a local run's file."""
    run_id: str
    name: str | None
    revision: str | None
    status: str
    pause: JSON | None
    state: JSON | None
    history: List[JSON]
    data: JSON = field(repr=False, compare=False)


@dataclass(frozen=True)
class GovernanceQuery:
    query: str
    description: str
    data: JSON = field(repr=False, compare=False)


@dataclass(frozen=True)
class Settings:
    """Where the client points. `token_set`, not the token, so printing it leaks nothing."""
    server: str | None
    source: str | None
    token_set: bool
    decision_model: str
    path: Path


# --------------------------------------------------------------------------- driver


OnStep = Callable[[JSON], None]
OnPause = Callable[[Paused], "JSON | None"]


class Driver:
    """One run's moves through a backend. `run_file` is an explicit path; without one the run
    file is `run_path(<run id>)`, and it follows the id. `on_step` gets each `--progress` line;
    `on_pause`, if given, answers each pause in-process (returning None stops at the pause)."""

    def __init__(self, backend: Any, run_file: Path | None = None, on_step: OnStep | None = None,
                 on_pause: OnPause | None = None, run_id: str | None = None):
        from aip.client.runner import run_path

        self.backend = backend
        self.run_file = run_file
        self.keyed = run_file is None or Path(run_file).resolve().parent == run_path("x").parent.resolve()
        self.on_step = on_step
        self.on_pause = on_pause
        self.run_id = run_id

    def start_step(self) -> JSON:
        """The start step's description (`step`, `inputs`)."""
        try:
            return self.backend.describe()["start"]
        except Exception as exc:
            raise self._error(_crashed(exc)) from exc

    def start(self, payload: JSON | None) -> Result:
        from aip.client.backend import Step

        if payload is None:
            start = self.start_step()
            raise self._error(Step({"error": "invalid_input", "step": start["step"],
                                    "message": f"no input given; start step {start['step']!r} expects {start['inputs']}",
                                    "missing": list(start["inputs"]), "invalid": []}))
        if not isinstance(payload, dict):
            raise InvalidInput(f"the start input must be a JSON object, got {type(payload).__name__}")
        return self._loop(self._call(lambda: self.backend.open(payload)), None)

    def resume(self, run: Any, payload: JSON | None) -> Result:
        from aip.client.backend import Step

        self.run_id = run.run_id
        if run.pause["kind"] == "done":
            return self._settle(Step({"done": True, "state": run.pause.get("state", run.state)}, run=run,
                                     run_id=run.run_id))
        return self._loop(self._call(lambda: self.backend.submit(run, payload)), run)

    def _call(self, call: Callable[[], Any]) -> Any:
        try:
            return call()
        except Exception as exc:
            return _crashed(exc)

    def _loop(self, step: Any, run: Any) -> Result:
        while True:
            result = self._settle(step, run)
            if not (isinstance(result, Paused) and self.on_pause is not None):
                return result
            answer = self.on_pause(result)
            if answer is None:
                return result
            run = step.run
            step = self._call(lambda: self.backend.submit(run, answer))

    def _settle(self, step: Any, run: Any = None) -> Result:
        """Report the step's lines, write the run file when there is one to keep, and return
        the stop as a result, or raise it as a `RunError`."""
        from aip.model.engine import PRIVATE

        for line in step.lines:
            if self.on_step is not None:
                self.on_step(line)
        if step.run is not None:
            path = self._save(step.run)
        elif step.kept and run is not None:
            path = Path(self.run_file) if self.run_file is not None else None
        else:
            path = None
        run_id = step.run_id or (run.run_id if run is not None and step.kept else None)
        outcome = step.outcome
        if "error" in outcome:
            raise self._error(step, run_id, path)
        if "done" in outcome:
            return Done(run_id, outcome["state"], path)
        body = {k: v for k, v in outcome.items() if k not in PRIVATE}
        return Paused(body["paused"], body["step"], body.get("state") or {}, run_id, path, body)

    def _error(self, step: Any, run_id: str | None = None, path: Path | None = None) -> RunError:
        block = {**step.outcome, "run_id": run_id, "resumable": step.resumable}
        if path is not None:
            block["run_file"] = str(path)
        return RunError(block, step.exc)

    def _save(self, run: Any) -> Path:
        from aip.client.runner import run_path

        old = self.run_file
        if self.keyed:
            self.run_file = run_path(run.run_id)
        run.save(self.run_file)
        if old is not None and Path(old) != self.run_file:
            Path(old).unlink(missing_ok=True)
        return self.run_file


def _crashed(exc: BaseException) -> Any:
    """A call that raised before the run could move: an unknown skill, an unreachable server."""
    from aip.client.backend import Step
    from aip.client.runner import error_object

    return Step(error_object(exc), exc=exc)


# --------------------------------------------------------------------------- client


class Client:
    """The AIP client.

    `server` is a URL, a folder, or None for the configured server (`aip config`; `AIP_SERVER`
    and `AIP_TOKEN` override it), which may be none. A folder is a skill folder or a folder of
    skill folders: runs are local and there is no catalog. A skill folder's path works in any
    mode and always runs locally. `token` is the bearer token (default the configured one, for
    the configured server). `decision_client` is a TypeSafe client to resolve decisions with
    (default: the configured key, else every decision pauses). `session` is an httpx-style
    client to send requests through (tests pass FastAPI's).
    """

    def __init__(self, server: str | Path | None = None, token: str | None = None, *,
                 decision_client: Any = None, session: Any = None):
        from aip.client.server import settings

        self.folder: Path | None = None
        self.server: Server | None = None
        self.decision_client = decision_client
        if isinstance(server, Server):
            self.server = server
        elif server is None:
            s = settings()
            if s["server"]:
                self.server = Server(s["server"], token if token is not None else s["token"], session=session)
        elif isinstance(server, Path) or not str(server).startswith(("http://", "https://")):
            self.folder = Path(server)
            if not self.folder.is_dir():
                raise NotFound(f"no such folder {str(server)!r}")
        else:
            self.server = Server(str(server), token, session=session)

    @classmethod
    def over(cls, server: Server | None, decision_client: Any = None) -> "Client":
        """A client on an open `Server`, or (None) with no server: folders only."""
        client = cls.__new__(cls)
        client.folder, client.server, client.decision_client = None, server, decision_client
        return client

    def __repr__(self) -> str:
        where = self.server.url if self.server else self.folder if self.folder else "no server"
        return f"aip.Client({str(where)!r})"

    # ------------------------------------------------------------------ resolving a skill

    def _where(self, skill: str | Path) -> tuple[str, Any]:
        """`("folder", Path)` or `("name", Server)`."""
        path = Path(skill)
        if path.exists():
            return "folder", path
        if self.folder is not None:
            if (self.folder / "SKILL.md").is_file() and str(skill) == self.folder.resolve().name:
                return "folder", self.folder
            if (self.folder / str(skill)).is_dir():
                return "folder", self.folder / str(skill)
            raise NotFound(f"no skill {str(skill)!r} in {self.folder}")
        if self.server is None:
            raise NoServer(f"{str(skill)!r} is not a skill folder, and no server is configured to look it up by name "
                           "(set AIP_SERVER or run `aip config --server URL`)")
        if "/" in str(skill) or "\\" in str(skill):
            raise NotFound(f"no such folder {str(skill)!r}")
        return "name", self.server

    def _server(self) -> Server:
        if self.server is None:
            raise NoServer("no server configured (set AIP_SERVER or run `aip config --server URL`)")
        return self.server

    # ------------------------------------------------------------------------- runs

    def run(self, skill: str | Path, input: JSON | None = None, *, workdir: Path | str | None = None,
            run_file: Path | str | None = None, on_step: OnStep | None = None,
            on_pause: OnPause | None = None) -> Result:
        """Start a run of `skill` (a folder, or a published `name[@revision]`) on `input`, the start
        step's object, and step it until it pauses or is done. `workdir` is where its scripts
        read and write files (default the current directory). Raises `RunError` when it stops on
        an error."""
        from aip.client.backend import HttpBackend, LocalBackend

        kind, where = self._where(skill)
        backend = (HttpBackend(where, name=str(skill), workdir=workdir, client=self.decision_client) if kind == "name"
                   else LocalBackend(where, workdir=workdir, client=self.decision_client))
        return Driver(backend, Path(run_file) if run_file else None, on_step, on_pause).start(input)

    def resume(self, run: str | Path | Paused | RunError, answer: JSON | None = None, *,
               on_step: OnStep | None = None, on_pause: OnPause | None = None) -> Result:
        """Answer a run's pause, or with no answer retry the step it failed at. `run` is a run id,
        a run file's path, or the `Paused`/`RunError` a call returned."""
        from aip.client.runner import RunFile, backend_for

        if answer is not None and not isinstance(answer, dict):
            raise InvalidInput(f"an answer must be a JSON object, got {type(answer).__name__}")
        path = self.run_file(run)
        handle = RunFile.load(path)
        same = self.server is not None and handle.server is not None and self.server.url == handle.server.rstrip("/")
        backend = backend_for(handle, token=self.server.token if same else None,
                              session=self.server._session if same else None, client=self.decision_client)
        return Driver(backend, path, on_step, on_pause, run_id=handle.run_id).resume(handle, answer)

    @staticmethod
    def run_file(run: str | Path | Paused | RunError) -> Path:
        """The run file of a run id, a path, or a result."""
        from aip.client.runner import RUN_ID, run_path

        if isinstance(run, (Paused, RunError)):
            if run.run_file is None:
                raise InvalidInput(f"run {run.run_id!r} has no run file: there is nothing to resume")
            return Path(run.run_file)
        ref = str(run)
        if isinstance(run, Path) or Path(ref).is_file() or not RUN_ID.fullmatch(ref):
            if not Path(ref).is_file():
                raise InvalidInput(f"no run file {ref}")
            return Path(ref)
        path = run_path(ref)
        if not path.is_file():
            raise InvalidInput(f"no run {ref!r} (looked for {path})")
        return path

    def runs(self, name: str | None = None, status: str | None = None, limit: int = 50) -> List[RunSummary]:
        """The server's runs, newest first."""
        return [_record(RunSummary, r) for r in self._server().runs(name, status, limit)]

    def run_record(self, run_id: str) -> RunRecord:
        """One run's state and history: from the server, or from a local run's file."""
        from aip.client.runner import RUN_ID, RunFile, run_path

        if RUN_ID.fullmatch(run_id) and run_path(run_id).is_file():
            handle = RunFile.load(run_path(run_id))
            if handle.server is None:
                status = {"done": "done", "error": "failed"}.get(handle.pause.get("kind"), "paused")
                data = {"run_id": handle.run_id, "name": Path(handle.skill_dir).name, "revision": None,
                        "status": status, "pause": handle.pause, "state": handle.state, "history": handle.history or []}
                return _record(RunRecord, data)
        return _record(RunRecord, self._server().run(run_id))

    # --------------------------------------------------------------------- catalog

    def search(self, query: str, limit: int = 10) -> List[Hit]:
        """Published procedures by what they do, best first; the ranking is the server's."""
        return [_record(Hit, h) for h in self._server().search(query, limit)]

    def list(self) -> List[Entry]:
        """Every published name."""
        return [_record(Entry, r) for r in self._server().list()]

    def info(self, skill: str | Path) -> SkillInfo:
        """Describe a skill folder or a published `name[@revision]`."""
        from aip.model.types import example_input
        from aip.spec import load_skill
        from aip.spec.loader import build_procedure

        kind, where = self._where(skill)
        if kind == "name":
            data = where.info(str(skill))
            return SkillInfo(data["name"], data["revision"], data.get("description"), data["start"]["step"],
                             data["start"]["inputs"], (data.get("end") or {}).get("inputs", {}), data["example_input"],
                             data, lambda: _remote_skill(where, str(skill)))
        try:
            loaded = load_skill(where)
        except ValueError as exc:
            raise InvalidSkill(str(exc)) from exc
        data = build_procedure(loaded).describe()
        return SkillInfo(data["meta"]["name"], None, data["meta"].get("description"), data["start"]["step"],
                         data["start"]["inputs"], (data.get("end") or {}).get("inputs", {}),
                         example_input(data["start"]["inputs"]), data, lambda: loaded)

    @staticmethod
    def validate(folder: str | Path) -> Validation:
        """Every check the format defines, on a skill folder."""
        from aip.spec import validate_skill

        loaded, issues = validate_skill(Path(folder))
        name = loaded.frontmatter.get("name") if loaded is not None else None
        return Validation(Path(folder), name, list(issues))

    def publish(self, folder: str | Path) -> Published:
        """Validate a skill folder here, then upload it. Raises `InvalidSkill` (nothing uploaded)
        when it does not validate."""
        server = self._server()
        validation = self.validate(folder)
        if not validation.valid:
            raise InvalidSkill(f"{folder}: {len(validation.errors)} error(s); not published", validation)
        result = server.publish(Path(folder))
        return Published(result["name"], result["revision"], result.get("id", f"{result['name']}@{result['revision']}"),
                         result.get("warnings", []), validation)

    def get(self, ref: str, out: str | Path = ".") -> Fetched:
        """Download a revision losslessly to `<out>/<name>/`, every file verified against the
        manifest, and validate it here."""
        target = self._server().download(ref, Path(out))
        return Fetched(target, self.validate(target))

    def pin(self, name: str, revision: str | None) -> Pinned:
        """Make `name` resolve to `revision`; None clears the pin."""
        self._server().pin(name, revision)
        return Pinned(name, revision)

    def retire(self, ref: str) -> Retired:
        """Stop `name@revision` resolving (it is kept for the runs that reference it)."""
        name, sep, revision = ref.partition("@")
        if not sep or not revision or revision == "latest":
            raise InvalidInput(f"retire takes `name@revision`, not {ref!r}")
        self._server().retire(name, revision)
        return Retired(name, revision)

    # ------------------------------------------------------------------- governance

    def governance(self, query: str | None = None, *, name: str | None = None, window: int | None = None,
                   limit: int | None = None, repeats: int | None = None) -> List[Any]:
        """With no query, the queries the server answers (`GovernanceQuery`); with one, its rows
        (`repeats` is the threshold of `repeated-cycles`)."""
        server = self._server()
        if query is None:
            return [_record(GovernanceQuery, q) for q in server.get("/governance")]
        return server.get(f"/governance/{query}", name=name, window=window, limit=limit, repeats=repeats)


# --------------------------------------------------------------------------- config


def settings() -> Settings:
    """Where a `Client()` with no arguments points, and which decision model it resolves with."""
    from aip.client.resolver import status
    from aip.client.server import config_path, settings as current

    s = current()
    return Settings(s["server"], s["source"], bool(s["token"]), status(), config_path())


def configure(server: str | None = None, token: str | None = None, decision_model: str | None = None,
              clear: bool = False) -> Settings:
    """Write the client config file: the server, its token, and the decision-model key (an empty
    string forgets it). `clear` forgets all three. Arguments left None are unchanged."""
    from aip.client.server import load_config, save_config

    if clear:
        save_config({})
    elif server is not None or token is not None or decision_model is not None:
        config = load_config()
        if server is not None:
            config["server"] = server.rstrip("/")
        if token is not None:
            config["token"] = token
        if decision_model:
            config["decision_model"] = {"api_key": decision_model}
        elif decision_model is not None:
            config.pop("decision_model", None)
        save_config(config)
    return settings()


# ------------------------------------------------------------------------ describing


def _inputs_table(items) -> str:
    if not items:
        return "  (none)\n"
    width = max(len(i.name) for i in items)
    return "".join(f"  {i.name.ljust(width)}  {i.type.value:8}  {i.description or ''}".rstrip() + "\n" for i in items)


def describe_skill(loaded) -> str:
    """Human-readable summary of a skill: what it does, what to give it, how it flows."""
    import json

    from aip.model.types import example_input

    fm, spec = loaded.frontmatter, loaded.spec
    start = spec.start
    example = example_input({item.name: item.type.value for item in start.inputs})
    lines = [f"{fm['name']}  (AIP {fm.get('metadata', {}).get('aip-version', '?')})", "", fm.get("description", ""), ""]
    lines += ["PURPOSE", "  " + " ".join(spec.purpose.split()), ""]
    lines += ["TRIGGER WHEN"] + [f"  - {t}" for t in spec.trigger_when]
    if spec.do_not_use_when:
        lines += ["DO NOT USE WHEN"] + [f"  - {t}" for t in spec.do_not_use_when]
    lines += ["", f"START INPUT  (step `{start.name}`, {start.kind})", _inputs_table(start.inputs).rstrip(), "",
              "  example start.json:", "  " + json.dumps(example), "",
              f"  run:  aip run {loaded.skill_dir} --input start.json", ""]
    lines += ["STEPS"]
    for step in spec.steps:
        if step.kind == "router":
            branches = ", ".join(f"{v} -> {t}" for v, t in step.branches.items())
            lines.append(f"  {step.name}  [router on `{step.branch_on}`]  {branches}")
        elif step.kind == "end":
            lines.append(f"  {step.name}  [end]")
        else:
            lines.append(f"  {step.name}  [{step.kind}]  -> {step.inputs_to}")
        if getattr(step, "description", None):
            lines.append(f"      {step.description}")
        if step.kind == "decision":
            for name, q in step.questions.items():
                threshold = step.thresholds.get(name)
                suffix = f"  (threshold {threshold})" if threshold is not None else ""
                lines.append(f"      ? {name} [{q.type}]{suffix}: {q.instructions}")
        if step.kind == "execution":
            lines.append(f"      script: {step.script}" + (f"  assets: {', '.join(step.assets)}" if step.assets else ""))
        if step.kind == "client_task":
            lines.append(f"      template: {step.template}" + (f"  assets: {', '.join(step.assets)}" if step.assets else ""))
            for ref in step.references:
                lines.append(f"      reference: {ref.path}  ({ref.description})")
    end = next((s for s in spec.steps if s.kind == "end"), None)
    if end is not None:
        lines += ["", "RESULT  (end state)", _inputs_table(end.inputs).rstrip()]
    if spec.anti_patterns:
        lines += ["", "ANTI-PATTERNS"] + [f"  - {a}" for a in spec.anti_patterns]
    return "\n".join(lines) + "\n"


def _remote_skill(server: Server, ref: str):
    """A `LoadedSkill` built from the published SKILL.md, so `describe_skill` renders it as for a folder."""
    import tempfile

    from aip_spec.skill import LoadedSkill, parse_skill_md, parse_spec

    text = server.file(ref, "SKILL.md").decode("utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        md = Path(tmp) / "SKILL.md"
        md.write_text(text)
        doc, issues = parse_skill_md(md)
    if doc is None:
        raise InvalidSkill(f"the server's SKILL.md for {ref} did not parse: " + "; ".join(i.message for i in issues))
    spec, issues = parse_spec(doc.yaml_text, "SKILL.md")
    if spec is None:
        raise InvalidSkill(f"the server's SKILL.md for {ref} did not parse: " + "; ".join(i.message for i in issues))
    return LoadedSkill(skill_dir=Path(ref), frontmatter=doc.frontmatter, spec=spec)


__all__ = [
    "AipError", "Client", "Done", "Driver", "Entry", "Fetched", "GovernanceQuery", "Hit", "InvalidInput", "InvalidSkill",
    "NoServer", "NotFound", "Paused", "Pinned", "Published", "Result", "Retired", "RunError", "RunRecord", "RunSummary",
    "ServerError", "Settings", "SkillInfo", "Validation", "configure", "describe_skill", "settings",
]
