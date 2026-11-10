"""The Python SDK: `aip.Client`, the runtime as a library (`docs/sdk.md`). The `aip` command is a
thin wrapper over it, and so is `aip mcp` (`aip.mcp`).

    import aip

    client = aip.Client()                                   # the configured server, if any (`aip config`)
    result = client.run("examples/language/billing-support", {"message": "I was charged twice"})
    while isinstance(result, aip.Paused):
        result = client.resume(result, answer_for(result))  # one answer per task, keyed by index
    print(result.result)

Every run is local (`aip.model`): the target, a program directory, an `.rl` bundle or a catalog
reference, is put in the bundle cache (`aip.client.bundles`) and loaded into an in-memory
store; scripts run from the file cache; the decision model is the configured endpoint (`aip
config --decision-model URL --decision-model-key KEY`; TypeSafe's URL by default).
Every stop writes the run file (`aip.client.runs`), so a run started here can be resumed by
`aip resume <run id>` and the other way round. When a server is configured the run is recorded
there at every stop, a folder or file run as a run of a *draft* bundle; when none is, the run
works and the result says `recorded=None`. Every method returns a typed value and raises an
`AipError` subclass.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from aip.compiler import (Bundle, BundleError, Diagnostic, compile_folder, export_bundle, has_errors, read_bundle,
                          result_on_some_paths, write_bundle)
from aip.compiler.bundle import BUNDLE_SUFFIX, SOURCE_FILE

from aip.client import bundles, config
from aip.client.config import CONFIGURE_HINT, Settings, configure, settings
from aip.client.runs import RunFile, error_outcome, local_runs, new_run_id, outcome, progress_line, run_path, RUN_ID
from aip.client.server import Server, ServerError, connect
from aip.errors import AipError
from aip.model import DONE, FAILED, PAUSED, Engine, InvalidOutput, NotPaused, Procedure, Run, StepError, TypeSafeResolver
from aip.model.engine import _where, utc_now
from aip.model.steps import start as check_inputs
from aip.model.types import resumable

JSON = dict[str, Any]
EXAMPLE_VALUES = {"string": "<string>", "integer": 0, "float": 0.0, "boolean": False, "list": [], "object": {}}


# --------------------------------------------------------------------------- errors


class NoServer(AipError):
    """A catalog operation, or a catalog reference, with no server to ask."""
    kind = "no_server"


class NotFound(AipError):
    """A target that is neither a program directory, a bundle file, nor a reference the client
    can resolve. For a catalog reference the message is the server's, the same whichever call
    asked: `no procedure 'x'` (with `did you mean` when the name with `_` for `-` is published),
    `no revision 7 of x`, `x has no live revision`."""
    kind = "not_found"


class RetiredRevision(AipError):
    """`name@revision` names a retired revision: it is kept for the runs that reference it, and
    runs again only when the caller says so (`force`)."""
    kind = "retired"


class InvalidInput(AipError):
    """Inputs, answers or a run reference that cannot be used as given, before any run is involved."""
    kind = "invalid_input"


class CompileError(AipError):
    """A program directory that does not compile; `diagnostics` are the compiler's."""
    kind = "compile_error"

    def __init__(self, target: str, diagnostics: list[Diagnostic]):
        self.diagnostics = list(diagnostics)
        errors = [d for d in diagnostics if d.severity == "error"]
        first = f": {errors[0]}" if errors else ""
        self.summary = f"{target} does not compile ({len(errors)} error(s))"   # the message without the first diagnostic
        super().__init__(self.summary + first)


class InvalidBundle(AipError):
    """An `.rl` that is not a usable bundle; `kind` is the bundle error's code (`not_a_bundle`,
    `bundle_tampered`, `bundle_language_version`, `bundle_format`)."""

    def __init__(self, error: BundleError):
        super().__init__(error.message, error.code)


class RunError(AipError):
    """A run stopped on an error. `error` is the CLI's error object (`docs/cli-json.md`): `error`
    (the kind), `step`, `message`, the kind's own keys, `pass`, `passes`, `run_id`, `resumable`,
    `run_file` when resumable, `recorded`. `cause` is the exception behind it, if any; `stopped`
    is False when the call changed nothing (an answer refused, a run with nothing to resume), so
    there is no new stop to record."""

    def __init__(self, error: JSON, cause: BaseException | None = None, stopped: bool = True):
        super().__init__(error.get("message") or error["error"], error["error"])
        self.error = error
        self.cause = cause
        self.stopped = stopped

    step = property(lambda self: self.error.get("step"))
    run_id = property(lambda self: self.error.get("run_id"))
    resumable = property(lambda self: bool(self.error.get("resumable")))
    run_file = property(lambda self: Path(self.error["run_file"]) if self.error.get("run_file") else None)
    recorded = property(lambda self: self.error.get("recorded"))

    def to_json(self) -> JSON:
        return dict(self.error)


# --------------------------------------------------------------------------- results


@dataclass(frozen=True)
class Task:
    """One task of a pause (runtime.md, Pauses): `index` is what the answer is keyed by; `pass_`
    and `passes` say which loop pass is waiting. It carries `prompt`, `state` (the `Read` keys),
    `references`, `answer_with` (the `Produce` keys and types) and `labels` (the values each
    `choice` or `score` among them may take). Inside a `Loop` with a cap, `last_pass` says
    whether this pass is the last the cap allows and `pass_of` is the cap; both are None
    anywhere else."""
    index: int
    pass_: int | None
    passes: list[JSON]
    state: JSON
    answer_with: dict[str, str | None]
    prompt: str
    references: list[JSON]
    labels: dict[str, list[str]] = field(default_factory=dict)
    last_pass: bool | None = None
    pass_of: int | None = None
    data: JSON = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_dict(cls, data: JSON) -> "Task":
        return cls(data["index"], data.get("pass"), list(data.get("passes") or []), data.get("state") or {},
                   data.get("answer_with") or {}, data.get("prompt") or "", list(data.get("references") or []),
                   dict(data.get("labels") or {}), data.get("last_pass"), data.get("pass_of"), data)


@dataclass(frozen=True)
class Paused:
    """The run waits for the agent at a `Task_Agent` step: `kind` is `task`, the one kind of
    pause (a `Decide` never pauses; without a model it fails the run); `tasks` has one task per
    pass waiting at `step`, all answered in one `resume`. `hint` is one line on the shape of an
    answer. `recorded` is True when the server has this stop, False when the post failed, None
    when no server is configured. `warning` is what `run` had to say before the first step (a
    `Decide` ahead and no decision model configured), else None. `to_json()` is the CLI's
    paused object."""
    kind: str
    step: str
    tasks: list[Task]
    run_id: str
    run_file: Path
    recorded: bool | None
    body: JSON = field(default_factory=dict, repr=False, compare=False)

    @property
    def hint(self) -> str:
        return self.body.get("hint") or ""

    @property
    def warning(self) -> str | None:
        return self.body.get("warning")

    @property
    def task(self) -> Task:
        """The one task of a pause outside a loop."""
        if len(self.tasks) != 1:
            raise ValueError(f"the pause carries {len(self.tasks)} tasks; answer them by index")
        return self.tasks[0]

    def to_json(self) -> JSON:
        return dict(self.body)


@dataclass(frozen=True)
class Done:
    """The run reached its `End`; `result` is the End step's keys, those the path taken produced."""
    run_id: str
    result: JSON
    run_file: Path
    recorded: bool | None
    body: JSON = field(default_factory=dict, repr=False, compare=False)

    @property
    def warning(self) -> str | None:
        return self.body.get("warning")

    def to_json(self) -> JSON:
        return dict(self.body)


Result = Paused | Done


@dataclass(frozen=True)
class Compiled:
    """`aip compile`'s result: the bundle when `ok`, every diagnostic either way, and the `.rl`
    written when an output path was given."""
    ok: bool
    name: str | None
    bundle_id: str | None
    diagnostics: list[Diagnostic]
    output: Path | None = None
    bundle: Bundle | None = field(default=None, repr=False, compare=False)

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "error"]


@dataclass(frozen=True)
class Description:
    """What a procedure is and what to give it (`aip info`). `inputs` and `result` map keys to
    types; `steps` lists name, kind and description in source order; `data` is the whole
    object, the server's for a catalog reference. In `data`, `result_on_some_paths` lists the
    result keys only some paths produce (a result has them when its path did), `retired` is
    true for a retired revision, and `warning` is there when the procedure has a `Decide` and
    this client has no decision model configured."""
    name: str
    bundle_id: str
    description: str
    inputs: dict[str, str | None]
    result: dict[str, str | None]
    steps: list[JSON]
    target: str
    revision: str | None = None
    data: JSON = field(default_factory=dict, repr=False, compare=False)

    @property
    def example_inputs(self) -> JSON:
        return {k: EXAMPLE_VALUES.get(t or "", None) for k, t in self.inputs.items()}

    def summary(self) -> str:
        """The `aip info` text."""
        d = self.data
        where = f"{self.name}@{self.revision}" if self.revision else self.target
        if d.get("retired"):
            where += ", retired"
        lines = [f"{self.name}  ({where})", f"  bundle {self.bundle_id}", "  " + " ".join(self.description.split()), ""]
        if d.get("warning"):
            lines += [f"WARNING  {d['warning']}", ""]
        for heading, key in (("USE WHEN", "use_when"), ("DO NOT USE WHEN", "do_not_use_when"), ("AVOID", "avoid")):
            if d.get(key):
                lines += [heading] + [f"  - {t}" for t in d[key]] + [""]
        if d.get("requires"):
            lines += [f"REQUIRES  {d['requires'].get('interpreter')} {d['requires'].get('version') or ''}".rstrip(), ""]
        descriptions = d.get("input_descriptions") or {}
        lines += ["INPUTS"] + (_table([(k, t or "", descriptions.get(k) or "") for k, t in self.inputs.items()]) or ["  (none)"])
        lines += ["", f"  run:  aip run {self.target} --inputs '{json.dumps(self.example_inputs)}'", ""]
        lines += ["STEPS"] + _table(_outline(self.steps, d.get("loops") or []))
        partial = set(d.get("result_on_some_paths") or [])
        lines += ["", "RESULT"] + (_table([(k, t or "", "on some paths" if k in partial else "") for k, t in self.result.items()])
                                   or ["  (none)"])
        return "\n".join(lines) + "\n"


def _table(rows: list[tuple[str, str, str]]) -> list[str]:
    if not rows:
        return []
    w1, w2 = max(len(r[0]) for r in rows), max(len(r[1]) for r in rows)
    return [f"  {a.ljust(w1)}  {b.ljust(w2)}  {' '.join(c.split())}".rstrip() for a, b, c in rows]


def _brief(text: str) -> str:
    """A description as one line of a table: the text before the first blank line (a
    `Task_Agent` whose description is its whole prompt shows its opening)."""
    return (text or "").strip().split("\n\n", 1)[0]


def _outline(steps: list[JSON], loops: list[JSON]) -> list[tuple[str, str, str]]:
    """The steps in source order with each loop's header where the loop stands and its body
    indented under it. A description without the nesting (a server's) is listed flat."""
    by_name = {l["name"]: l for l in loops}
    if not all("body" in l for l in loops) or not all("loop" in s for s in steps):
        return [(s["name"], s["kind"], _brief(s.get("description") or "")) for s in steps] + \
               [(l["name"], l["kind"], l.get("header") or l.get("mode") or "") for l in loops]
    step_rows = {s["name"]: s for s in steps}
    rows: list[tuple[str, str, str]] = []

    def place(name: str, depth: int) -> None:
        pad = "  " * depth
        if name in by_name:
            loop = by_name[name]
            rows.append((pad + name, loop["kind"], loop.get("header") or ""))
            for inner in loop["body"]:
                place(inner, depth + 1)
        else:
            s = step_rows[name]
            rows.append((pad + name, s["kind"], _brief(s.get("description") or "")))

    top = sorted([s for s in steps if s["loop"] is None] + [l for l in loops if l.get("loop") is None], key=lambda n: n.get("line") or 0)
    for node in top:
        place(node["name"], 0)
    return rows


def _record(cls, data: JSON):
    """A typed record of a server object; `data` keeps the object as the server sent it."""
    names = [f for f in cls.__dataclass_fields__ if f != "data"]
    return cls(**{f: data.get(f) for f in names}, data=data)


@dataclass(frozen=True)
class Hit:
    name: str
    revision: str
    bundle_id: str | None
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
    resolves: str | None
    revisions: list[JSON]
    data: JSON = field(repr=False, compare=False)


@dataclass(frozen=True)
class Published:
    name: str
    revision: str | None          # None for a bundle uploaded as a draft that has no revision
    bundle_id: str
    existed: bool                 # the bundle id was already in the store (a draft, or a published revision)
    draft: bool = False           # the store holds the bundle with no revision (`publish(..., draft=True)`)


@dataclass(frozen=True)
class Pulled:
    """A catalog reference in the bundle cache: `fetched` says whether the bytes travelled now."""
    ref: str
    name: str
    revision: str | None
    bundle_id: str
    path: Path
    fetched: bool


@dataclass(frozen=True)
class Fetched:
    """A program directory written from a bundle (`aip get`)."""
    path: Path
    name: str
    bundle_id: str
    revision: str | None


@dataclass(frozen=True)
class SkillExported:
    """A procedure written as a plain Agent Skill (`aip export --skill`): the folder, its
    `SKILL.md`, the procedure's name and the skill's (`billing_support`, `billing-support`)."""
    path: Path
    skill_file: Path
    name: str
    skill: str
    bundle_id: str
    revision: str | None


@dataclass(frozen=True)
class Pinned:
    name: str
    revision: str | None


@dataclass(frozen=True)
class Retired:
    name: str
    revision: str


@dataclass(frozen=True)
class RunSummary:
    """One row of `aip runs`: a run on the server, or one of this machine's run files."""
    run_id: str
    name: str | None
    revision: str | None
    status: str
    draft: bool | None
    identity: JSON | None
    started: str | None
    created: str | None
    updated: str | None
    data: JSON = field(repr=False, compare=False)


@dataclass(frozen=True)
class RunRecord:
    """One run as its home holds it: the local run file, or the server's record. `history` is
    its entries, one per step run; `table()` is the text `aip runs <run id>` prints."""
    run_id: str
    bundle_id: str | None
    name: str | None
    status: str
    identity: JSON | None
    started: str | None
    finished: str | None
    pause: JSON | None
    error: JSON | None
    result: JSON | None
    history: list[JSON]
    data: JSON = field(repr=False, compare=False)

    def table(self) -> str:
        from aip.client.runs import run_table

        return run_table(self.data)


@dataclass(frozen=True)
class AuditQuery:
    """One query `aip audit` lists: a built-in, or one stored on the server (`builtin` False)."""
    query: str
    description: str
    builtin: bool | None
    data: JSON = field(repr=False, compare=False)


@dataclass(frozen=True)
class Exported:
    """Runs and the procedures they ran, written as one Relate file (`aip export runs`):
    how many runs, of how many procedures (names), in how many bundles (a procedure's
    revisions and drafts are a bundle each)."""
    path: Path
    runs: int
    bundles: int
    procedures: int = 0


OnStep = Callable[[JSON], None]
OnPause = Callable[[Paused], Any]


# --------------------------------------------------------------------------- client


class Client:
    """The AIP client.

    `server` is a URL, `"local"`, a `Server`, or None for the configured one (`aip config`;
    `AIP_SERVER` and `AIP_TOKEN` override), which may be none: then runs work and are not
    recorded, and catalog calls raise `NoServer`. `local` is the server on this machine, started
    by the first call that needs it and stopped when idle (`aip.client.local`). `token` is the bearer token. `decision_client` injects a
    client with the TypeSafe SDK's shape (tests); otherwise the configured endpoint and key
    decide (`aip config --decision-model URL --decision-model-key KEY`; `AIP_DECISION_MODEL`
    and `AIP_DECISION_MODEL_KEY` override), and with neither a `Decide` fails the run
    (`no_decision_model`). `session` is an httpx-style client to send requests through. `home`
    moves `~/.aip` (default `AIP_HOME`). `agent` is the identity's `agent` when neither a call
    nor `AIP_AGENT` names one.
    """

    def __init__(self, server: str | Server | None = None, token: str | None = None, *, decision_client: Any = None,
                 session: Any = None, home: Path | str | None = None, agent: str | None = None):
        self.settings: Settings = settings()
        self.decision_client = decision_client
        self.home = Path(home) if home is not None else None
        self.agent = agent
        self.recording_error: str | None = None   # why the last stop was not recorded, when a server is configured
        self._uploaded: set[str] = set()
        self._retired: dict[str, bool] = {}        # catalog reference -> whether the server said its revision is retired
        if isinstance(server, Server):
            self.server: Server | None = server
        elif server is None:
            s = self.settings
            self.server = connect(s.server, token if token is not None else s.token, session, s.local) if s.server else None
        elif str(server).strip().lower() == config.LOCAL:
            from aip.client import local

            self.server = connect(local.url(), token, session, True)
        else:
            self.server = Server(str(server), token, session=session)

    def __repr__(self) -> str:
        return f"aip.Client({self.server.url if self.server else 'no server'!r})"

    def _server(self) -> Server:
        if self.server is None:
            raise NoServer(f"no server is configured; {CONFIGURE_HINT}")
        return self.server

    # ------------------------------------------------------------------ compile

    def compile(self, folder: str | Path, output: str | Path | None = None) -> Compiled:
        """Compile a program directory (or its `procedure.aip`); with `output`, a path ending
        in `.rl`, write the bundle there."""
        if output is not None and Path(output).suffix != BUNDLE_SUFFIX:
            raise InvalidInput(f"a bundle is written as an {BUNDLE_SUFFIX} file, which is how `run` and `describe` know one; "
                               f"give an output path ending in {BUNDLE_SUFFIX}, not {str(output)!r}")
        if not Path(folder).exists():
            raise NotFound(f"no such folder or file {str(folder)!r}")
        bundle, diagnostics = compile_folder(folder)
        if bundle is None or has_errors(diagnostics):
            return Compiled(False, bundle.name if bundle else None, None, list(diagnostics))
        written = None
        if output is not None:
            written = Path(output)
            write_bundle(bundle, written)
        return Compiled(True, bundle.name, bundle.id, list(diagnostics), written, bundle)

    # ------------------------------------------------------------------ targets

    def _open(self, target: str | Path, cache: bool = True) -> tuple[Bundle, JSON]:
        """The bundle a target names and where it came from: `{"kind": folder | file | name,
        "target", "revision"}`. A folder is compiled, an `.rl` verified, a reference fetched;
        with `cache` each is put in the bundle cache."""
        text = str(target)
        path = Path(target)
        if path.is_dir() or (path.is_file() and path.name == SOURCE_FILE):
            folder = path if path.is_dir() else path.parent
            if not (folder / SOURCE_FILE).is_file():
                raise NotFound(f"{folder} has no {SOURCE_FILE}; a program directory holds one")
            bundle, diagnostics = compile_folder(folder)
            if bundle is None or has_errors(diagnostics):
                raise CompileError(str(folder), diagnostics)
            if cache:
                bundles.store(bundle, self.home)
            return bundle, {"kind": "folder", "target": str(folder.resolve()), "revision": None}
        if path.is_file() and path.suffix == BUNDLE_SUFFIX:
            try:
                bundle = bundles.store_file(path, self.home) if cache else read_bundle(path)
            except BundleError as exc:
                raise InvalidBundle(exc) from exc
            return bundle, {"kind": "file", "target": str(path.resolve()), "revision": None}
        if path.exists():
            raise NotFound(f"{text} is neither a program directory, a {SOURCE_FILE}, nor an {BUNDLE_SUFFIX} bundle")
        if not bundles.is_ref(text):
            raise NotFound(f"no such folder or file {text!r}")
        bundle, revision, _ = self._fetch(text)
        return bundle, {"kind": "name", "target": text, "revision": revision, "retired": self._retired.get(text, False)}

    def _described(self, ref: str) -> JSON:
        """The server's description of a catalog reference. A reference it does not have is
        `NotFound` in the server's own words, so every call that names one says the same thing."""
        try:
            return self._server().describe(ref)
        except ServerError as exc:
            if exc.status == 404 and exc.kind == "not_found":
                raise NotFound(exc.message) from exc
            raise

    def _fetch(self, ref: str) -> tuple[Bundle, str | None, bool]:
        """A catalog reference's bundle, from the cache or the server: the bundle, its revision,
        and whether the bytes were fetched now. Whether the revision is retired is kept in
        `_retired` for `run` to ask."""
        cached = bundles.resolve_ref(ref, self.home)
        if self.server is None:
            if cached is None:
                raise NoServer(f"{ref!r} is not a folder or a bundle file, it is not in the bundle cache, and no server is "
                               f"configured to look it up; {CONFIGURE_HINT}, then `aip pull {ref}`")
            bundle_id, revision = cached
            return bundles.load(bundle_id, self.home), revision, False
        try:
            info = self._described(ref)
        except ServerError as exc:
            if exc.status == 0 and cached is not None:  # the server is down; the cache is what we have
                bundle_id, revision = cached
                return bundles.load(bundle_id, self.home), revision, False
            raise
        self._retired[ref] = bool(info.get("retired"))
        bundle_id, revision = info["bundle_id"], info.get("revision")
        fetched = False
        try:
            if bundles.is_cached(bundle_id, self.home):
                bundle = bundles.load(bundle_id, self.home)
            else:
                bundle = bundles.store_bytes(self.server.bundle(ref), self.home, expected_id=bundle_id)
                fetched = True
        except BundleError as exc:
            raise InvalidBundle(exc) from exc
        bundles.remember(ref, bundle_id, revision, self.home)
        return bundle, revision, fetched

    def describe(self, target: str | Path) -> Description:
        """Describe a program directory, an `.rl`, or a catalog reference."""
        text = str(target)
        if not Path(target).exists() and bundles.is_ref(text) and self.server is not None:
            data = self._model_warned(self._described(text))
            return Description(data["name"], data["bundle_id"], data.get("description") or "", data.get("inputs") or {},
                               data.get("result") or {}, data.get("steps") or [], text, data.get("revision"), data)
        bundle, origin = self._open(target, cache=False)
        with Procedure.load(bundle) as procedure:
            data = describe_procedure(procedure)
        data.update(target=origin["target"], revision=origin["revision"], draft=origin["kind"] != "name")
        data = self._model_warned(data)
        return Description(data["name"], data["bundle_id"], data["description"], data["inputs"], data["result"], data["steps"],
                           text, origin["revision"], data)

    def model_warning(self, steps: list[JSON]) -> str | None:
        """What to say before running a procedure with these steps: None, unless one is a
        `Decide` and this client has no decision model, in which case the run fails when it
        gets there (it may never: a route may go another way), so this is a warning."""
        decides = [s["name"] for s in steps if s.get("kind") == "Decide"]
        if not decides or self.decision_client is not None or self.settings.decision_model_configured:
            return None
        from aip.model.types import DECISION_MODEL_HINT

        return (f"no decision model is configured, and this procedure asks one at {', '.join(decides)}: a run that reaches "
                f"{'it' if len(decides) == 1 else 'one of them'} fails there with no_decision_model until one is set ({DECISION_MODEL_HINT})")

    def _model_warned(self, data: JSON) -> JSON:
        warning = self.model_warning(data.get("steps") or [])
        return {**data, "warning": warning} if warning else data

    # ------------------------------------------------------------------ runs

    def _engine(self, workdir: Path, batch: int | None, on_step: OnStep | None = None) -> Engine:
        """The engine for one call. `on_step` gets each history entry's progress line the
        moment the entry is written, so a batch of `For` passes reports as it goes."""
        s = self.settings
        resolver = TypeSafeResolver.from_environment(client=self.decision_client, api_key=s.decision_model_key, url=s.decision_model_url)
        on_entry = (lambda entry: on_step(progress_line(entry))) if on_step is not None else None
        return Engine(resolver, home=self.home, workdir=workdir, batch=batch or s.batch, on_entry=on_entry)

    def run(self, target: str | Path, inputs: JSON, *, batch: int | None = None, agent: str | None = None,
            session: str | None = None, workdir: str | Path | None = None, on_step: OnStep | None = None,
            on_pause: OnPause | None = None, force: bool = False, agent_version: str | None = None,
            on_warning: Callable[[str], None] | None = None) -> Result:
        """Run `target` (a program directory, an `.rl`, or `name[@rev]`) on `inputs`, the Start
        step's object, until it pauses or is done. `workdir` is where its scripts read and write
        files (default the current directory); `batch` how many `For` passes run at once;
        `agent` and `session` the run's identity, `agent_version` the agent's own version when
        it has one to give. `on_step` gets each history entry's progress line as it is written;
        `on_pause`, if given, answers each pause in-process (returning None stops there).
        A `name@revision` that is retired is refused (`RetiredRevision`) unless `force`. When the
        procedure has a `Decide` and no decision model is configured, the run is not refused,
        since it may never reach the step: `on_warning` is told before the first step runs, and
        the result (or the `RunError`) carries the same sentence as `warning`.
        Raises `RunError` when the run stops on an error, `CompileError`, `InvalidBundle`,
        `NotFound`, `RetiredRevision` or `NoServer` when the target cannot be run."""
        if not isinstance(inputs, dict):
            raise InvalidInput(f"the inputs are a JSON object, got {type(inputs).__name__}")
        if batch is not None and batch < 1:
            raise InvalidInput(f"the batch size is at least 1, not {batch}")
        bundle, origin = self._open(target)
        if origin.get("retired") and not force:
            raise RetiredRevision(f"{bundle.name}@{origin['revision']} is retired: it is kept for the runs that reference it and no "
                          "longer runs by default; run it anyway with force (`aip run ... --force`), or publish it again to bring it back")
        where = Path(workdir if workdir is not None else Path.cwd()).resolve()
        engine = self._engine(where, batch, on_step)
        identity = config.identity(agent, session, default_agent=self.agent, agent_version=agent_version)
        with Procedure.load(bundle) as procedure:
            try:
                check_inputs(procedure.step(procedure.start), inputs)
                warning = self.model_warning(procedure.describe()["steps"])
                if warning and on_warning is not None:   # said before the first step, and only for a run that starts
                    on_warning(warning)
                run = engine.start(procedure, inputs, identity=identity)
            except StepError as exc:  # the inputs do not fit: nothing ran, nothing to resume
                raise RunError(error_outcome({**exc.to_dict(), "pass": None, "passes": []}, None, None, None, False), exc) from exc
            handle = RunFile(new_run_id(), bundle.id, bundle.name, origin["target"], origin["kind"], run.to_dict(), str(where),
                             origin["revision"], server=self.server.url if self.server else None)
            return self._settle(engine, run, handle, on_pause, warning)

    def resume(self, run: str | Path | Paused | RunError, answers: Any = None, *, agent: str | None = None,
               session: str | None = None, on_step: OnStep | None = None, on_pause: OnPause | None = None) -> Result:
        """Carry the agent's answers to a paused run, or with no answers retry the step a failed
        run stopped at. `run` is a run id, a run file's path, or the `Paused`/`RunError` a call
        returned; `answers` is keyed by task index (`{"0": {...}}`), a list in task order, or the
        one answer object when the pause has one task, and answers every task of the pause. An
        answer that does not fit (a key or a task missing, or one the pause did not ask for), an
        answer to a run that is not paused, or a retry of one that has not failed or that a
        retry cannot help (`loop_cap`) is a `RunError` naming the run (`invalid_output`,
        `not_paused`, `invalid_input`) and changes nothing: a refused answer leaves the pause
        as it was, to be answered again. `agent` and `session` say who answers, for the task's
        `answered_by` (default `AIP_AGENT` / the client's `agent`, and `AIP_SESSION`, else the
        run's own)."""
        path = self.run_file(run)
        handle = RunFile.load(path)
        try:
            bundle = bundles.load(handle.bundle_id, self.home)
        except KeyError:
            raise InvalidInput(f"the bundle {handle.bundle_id[:12]}… of run {handle.run_id} is no longer in the bundle cache "
                               f"({bundles.bundle_path(handle.bundle_id, self.home)}); run it again") from None
        except BundleError as exc:
            raise InvalidBundle(exc) from exc
        engine = self._engine(Path(handle.workdir), handle.run.get("batch"), on_step)
        with Procedure.load(bundle) as procedure:
            state = Run.from_dict(procedure, handle.run)
            state = self._apply(engine, state, answers, handle, path, agent, session)
            return self._settle(engine, state, handle, on_pause)

    def _apply(self, engine: Engine, run: Run, answers: Any, handle: RunFile, path: Path, agent: str | None = None,
               session: str | None = None) -> Run:
        """The answers into a paused run, or a retry of a failed one. A bad answer is a
        resumable `RunError` and the pause stands; its object says `recorded: false` where a
        server is configured, since the refusal changed nothing and nothing was sent."""
        recorded = False if handle.server else None

        def refuse(kind: str, step: str | None, message: str, resumable: bool) -> RunError:
            return RunError(error_outcome({"error": kind, "step": step, "message": message, **_where(run)}, handle.run_id, path,
                                          recorded, resumable), stopped=False)

        if answers is None:
            if run.status == PAUSED:
                raise refuse("invalid_input", run.pause["step"], f"run {handle.run_id} is paused at {run.pause['step']}: give the "
                             f"answers to its {len(run.pause['tasks'])} task(s); only a failed run is retried without any", True)
            if run.status != FAILED:
                raise refuse("not_paused", None, f"run {handle.run_id} is {run.status}; there is nothing to resume", False)
            if not resumable(run.error):
                raise refuse("not_paused", run.error.get("step"), f"run {handle.run_id} failed with {run.error['error']}, which a "
                             "retry would only repeat; there is nothing to resume", False)
            return engine.retry(run)
        if run.status != PAUSED:
            raise refuse("not_paused", (run.error or {}).get("step"), f"run {handle.run_id} is {run.status}, not paused; an answer "
                         "needs a pause" + (" (resume it with no answers to retry the failed step)" if run.status == FAILED else ""),
                         run.status == FAILED)
        try:
            return engine.resume(run, answers, identity=config.identity(agent, session, default_agent=self.agent))
        except (InvalidOutput, NotPaused) as exc:
            raise RunError(error_outcome({**exc.to_dict(), **_where(run)}, handle.run_id, path, recorded, True), exc, stopped=False) from exc

    def _settle(self, engine: Engine, run: Run, handle: RunFile, on_pause: OnPause | None, warning: str | None = None) -> Result:
        """Record the stop (server and run file), and return it as a result or raise it; with
        `on_pause`, answer pauses in-process and go on. `warning` is `run`'s, carried on the
        object of the stop it leads to."""
        while True:
            handle.run = run.to_dict()
            recorded = self._record(handle)
            path = handle.save(home=self.home)
            block = outcome(run, handle.run_id, path, recorded)
            if warning:
                block["warning"] = warning
            if run.status == FAILED:
                raise RunError(block)
            if run.status == DONE:
                return Done(handle.run_id, run.result or {}, path, recorded, block)
            paused = Paused(run.pause["kind"], run.pause["step"], [Task.from_dict(t) for t in run.pause["tasks"]], handle.run_id,
                            path, recorded, block)
            if on_pause is None:
                return paused
            answers = on_pause(paused)
            if answers is None:
                return paused
            run = self._apply(engine, run, answers, handle, path)

    def _record(self, handle: RunFile) -> bool | None:
        """Post the run where it stopped. None without a server; False, with the reason in
        `recording_error`, when the server did not take it (the run goes on regardless)."""
        if self.server is None:
            return None
        handle.server = self.server.url
        handle.updated = utc_now()                # this stop's time, not the last save's: the server lists by it
        try:
            if handle.uploads and handle.bundle_id not in self._uploaded:
                self.server.draft(bundles.read_bytes(handle.bundle_id, self.home))
                self._uploaded.add(handle.bundle_id)
            reply = self.server.record(handle.recording())
            if isinstance(reply, dict) and reply.get("user"):
                handle.run.setdefault("identity", {})["user"] = reply["user"]
            if isinstance(reply, dict) and "draft" in reply:      # the store says which revision the bundle is, if any
                handle.revision = reply.get("revision")
        except ServerError as exc:
            self.recording_error = str(exc)
            handle.recorded = False
            return False
        self.recording_error = None
        handle.recorded = True
        return True

    def run_file(self, run: str | Path | Paused | Done | RunError) -> Path:
        """The run file of a run id, a path, or a result."""
        if isinstance(run, (Paused, Done, RunError)):
            if run.run_file is None:
                raise InvalidInput(f"run {run.run_id!r} has no run file: there is nothing to resume")
            return Path(run.run_file)
        ref = str(run)
        if isinstance(run, Path) or Path(ref).is_file() or not RUN_ID.fullmatch(ref):
            if not Path(ref).is_file():
                raise InvalidInput(f"no run file {ref}")
            return Path(ref)
        path = run_path(ref, self.home)
        if not path.is_file():
            raise InvalidInput(f"no run {ref!r} on this machine (looked for {path})")
        return path

    def runs(self, name: str | None = None, status: str | None = None, agent: str | None = None, session: str | None = None,
             limit: int = 50, user: str | None = None, draft: bool | None = None) -> list[RunSummary]:
        """Runs, newest first, filtered by name, status, agent, session, user, or whether the
        run was of a draft: the server's when one is configured, else this machine's run files."""
        if self.server is not None:
            return [_record(RunSummary, r) for r in self.server.runs(name, status, agent, session, limit, user, draft)]
        rows = [r.summary() for r in local_runs(self.home)]
        for key, wanted in (("name", name), ("status", status), ("draft", draft)):
            if wanted is not None:
                rows = [r for r in rows if r.get(key) == wanted]
        for key, wanted in (("agent", agent), ("session", session), ("user", user)):
            if wanted:
                rows = [r for r in rows if (r.get("identity") or {}).get(key) == wanted]
        return [_record(RunSummary, r) for r in rows[:limit]]

    def run_record(self, run_id: str) -> RunRecord:
        """One run: the local run file when this machine has it, else the server's record."""
        known = RUN_ID.fullmatch(run_id) is not None
        if known and run_path(run_id, self.home).is_file():
            return _record(RunRecord, RunFile.load(run_path(run_id, self.home)).record())
        if self.server is None:
            raise InvalidInput(f"no run {run_id} on this machine" + (f" (looked for {run_path(run_id, self.home)})" if known else ""))
        return _record(RunRecord, self.server.run(run_id))

    # --------------------------------------------------------------------- catalog

    def search(self, query: str, limit: int = 10) -> list[Hit]:
        """Published procedures by what they do, best first; the ranking is the server's."""
        return [_record(Hit, h) for h in self._server().search(query, limit)]

    def list(self) -> list[Entry]:
        """Every published name with its revisions."""
        return [_record(Entry, r) for r in self._server().list()]

    def pull(self, ref: str) -> Pulled:
        """Put the bundle a catalog reference resolves to in the bundle cache, so `run` works
        without the server."""
        if not bundles.is_ref(ref):
            raise InvalidInput(f"{ref!r} is not a catalog reference (`name` or `name@rev`)")
        self._server()
        bundle, revision, fetched = self._fetch(ref)
        return Pulled(ref, bundle.name, revision, bundle.id, bundles.bundle_path(bundle.id, self.home), fetched)

    def pull_all(self) -> list[Pulled]:
        """Pull every published name's resolved revision."""
        return [self.pull(f"{e.name}@{e.resolves}") for e in self.list() if e.resolves]

    def publish(self, target: str | Path, draft: bool = False) -> Published:
        """Publish a program directory (compiled here) or an `.rl` under its procedure's name;
        the server assigns the next revision, or finds the bundle already there. With `draft`
        the bundle is uploaded with no revision instead, as a run of the folder would hold it:
        it is in the store, out of the catalog, and a later `publish` of the same bundle gives
        it its revision (`draft` comes back False when it already has one)."""
        server = self._server()
        bundle, origin = self._open(target)
        if origin["kind"] == "name":
            raise InvalidInput(f"{target!r} is a catalog reference; publish takes a program directory or an {BUNDLE_SUFFIX} file")
        if draft:
            held = server.draft(bundles.read_bytes(bundle.id, self.home))
            return Published(held["name"], None, held["bundle_id"], bool(held.get("existed")), bool(held.get("draft")))
        reply = server.publish(bundles.read_bytes(bundle.id, self.home))
        bundles.remember(f"{reply['name']}@{reply['revision']}", reply["bundle_id"], reply["revision"], self.home)
        return Published(reply["name"], str(reply["revision"]), reply["bundle_id"], bool(reply.get("existed")))

    def upgrade(self) -> list[Published]:
        """Publish the procedures this package ships (`aip.server.builtins`: `make_procedure`) to
        the server, as `publish` would: a bundle the server already holds keeps its revision. A
        server does this for itself when it first starts; this is for one that runs an older
        package than this client."""
        from aip.server.builtins import builtin_files

        self._server()
        return [self.publish(path) for path in builtin_files()]

    def get(self, ref: str, out: str | Path, force: bool = False) -> Fetched:
        """Write the program directory of a catalog reference at `out` (`aip export` of the
        pulled bundle)."""
        bundle, revision, _ = self._fetch(ref)
        try:
            path = export_bundle(bundle, Path(out), force=force)
        except BundleError as exc:
            raise InvalidInput(exc.message) from exc
        return Fetched(path, bundle.name, bundle.id, revision)

    def export_skill(self, target: str | Path, out: str | Path, force: bool = False) -> SkillExported:
        """Write a procedure as a plain Agent Skill at `out` (`aip export <target> --skill DIR`):
        a `SKILL.md` that walks the steps for an agent with no runtime, and the bundle's files.
        `target` is a program directory, an `.rl` or a catalog reference, pulled as `get` does."""
        from aip.compiler.skill import SKILL_FILE, export_skill, skill_name

        bundle, origin = self._open(target, cache=False)
        run_with = str(target) if origin["kind"] == "name" else None
        try:
            path = export_skill(bundle, Path(out), force=force, run_with=run_with)
        except BundleError as exc:
            raise InvalidInput(exc.message) from exc
        return SkillExported(path, path / SKILL_FILE, bundle.name, skill_name(bundle.name), bundle.id, origin["revision"])

    def pin(self, name: str, revision: str | None) -> Pinned:
        """Make `name` resolve to `revision`; None clears the pin."""
        self._server().pin(name, revision)
        return Pinned(name, revision)

    def retire(self, ref: str) -> Retired:
        """Stop `name@revision` resolving (it is kept for the runs that reference it)."""
        name, revision = bundles.split_ref(ref)
        if not revision or revision == "latest":
            raise InvalidInput(f"retire takes `name@revision`, not {ref!r}")
        self._server().retire(name, revision)
        return Retired(name, revision)

    # ------------------------------------------------------------------- audit

    def audit(self, query: str | None = None, **params: Any) -> list[Any]:
        """With no query, the queries the server answers (`AuditQuery`); with one, its rows.
        `params` are the query's: `name`, `agent`, `session`, `user`, `draft` (filters on the
        runs), `window` (how many recent runs), `limit`, `repeats`, `key`."""
        server = self._server()
        if query is None:
            return [_record(AuditQuery, q) for q in server.audit()]
        return server.audit(query, **params)

    def save_audit(self, name: str, cypher: str, description: str = "") -> AuditQuery:
        """Store a query of your own on the server under `name`; `aip audit <name>` runs it."""
        return _record(AuditQuery, self._server().save_audit(name, cypher, description))

    def delete_audit(self, name: str) -> None:
        """Remove a stored query."""
        self._server().delete_audit(name)

    def export_runs(self, output: str | Path, name: str | None = None, *, since: str | None = None, agent: str | None = None,
                    session: str | None = None, user: str | None = None, draft: bool | None = None, force: bool = False) -> Exported:
        """Write the server's runs that match, and the procedures they ran, as one Relate file
        at `output`: the record and the bundles' graphs side by side, for whoever audits them
        with the engine's own tools. `since` is a date or a timestamp a run started at or after."""
        path = Path(output)
        if path.exists() and not force:
            raise InvalidInput(f"{path} exists; give another path, or force")
        data, runs, exported, procedures = self._server().export_runs(name=name, since=since, agent=agent, session=session, user=user,
                                                                      draft=draft)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return Exported(path, runs, exported, procedures)


# --------------------------------------------------------------------------- describing


def describe_procedure(procedure: Procedure) -> JSON:
    """The description of a loaded procedure: the header, the inputs with their types and
    descriptions, the result keys, the steps and loops."""
    data = procedure.describe()
    start = procedure.step(procedure.start)
    end_name = next((s["name"] for s in data["steps"] if s["kind"] == "End"), None)
    end = procedure.step_named(end_name) if end_name else None
    data["inputs"] = {p.key: p.type for p in start.produces}
    data["input_descriptions"] = {p.key: p.description or "" for p in start.produces}
    data["result"] = {r.name: (r.type or procedure.key_type(r.key)) if r.field is None else None for r in end.declared_reads} if end else {}
    data["result_on_some_paths"] = [k for k in result_on_some_paths(procedure.source) if k in data["result"]]
    data["example_inputs"] = {k: EXAMPLE_VALUES.get(t or "", None) for k, t in data["inputs"].items()}
    return data


__all__ = [
    "AipError", "AuditQuery", "Client", "Compiled", "CompileError", "Description", "Done", "Entry", "Exported", "Fetched", "Hit",
    "InvalidBundle", "InvalidInput", "NoServer", "NotFound", "Paused", "Pinned", "Published", "Pulled", "Result", "Retired", "RetiredRevision",
    "RunError", "RunRecord", "RunSummary", "ServerError", "Settings", "SkillExported", "Task", "configure", "describe_procedure", "settings",
]
