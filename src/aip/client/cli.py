"""The `aip` command line entry point.

    aip run <target> --inputs JSON      run a program directory, an .rl bundle or a catalog name; pauses print as JSON
    aip resume <run_id> --answers JSON  answer a pause (or, with no answers, retry a failed run)
    aip agent "<task>"                  a chat model outside the run drives the `assist` procedure; again with --session: the reply
    aip agent --answer <run_id>         that model answers the pause of any run, once, and resumes it (the console's model steps)
    aip compile | export | fmt          the language's tooling (aip.compiler)
    aip export runs [name] -o FILE      the server's runs and the procedures they ran, as one Relate file
    aip export <target> --skill DIR     a procedure as a plain Agent Skill, followed by hand with no runtime
    aip info <target>                   what a procedure is and what to give it
    aip pull | publish | get            move bundles between the cache and the catalog
    aip search | list | pin | retire    the catalog
    aip runs                            this machine's runs, or the server's; one run step by step
    aip audit                           the server's audit queries over the runs and the catalog
    aip config                          where the client points: the server (`aip config server local | URL | none`), the token,
                                        the decision model's endpoint and key, the batch size, the script timeout;
                                        `aip config agent`: the chat model `aip agent` asks
    aip server                          serve the catalog and the record of runs
    aip mcp                             the same client as an MCP server, for agent frameworks and coding agents
    aip skill install | list | remove   the `aip` skill, the page an agent reads to run and write procedures
    aip upgrade                         publish the procedures this package ships (`make_procedure`, `build_procedure`, `edit_procedure`) to the server

Every client command is a wrapper over the SDK (`aip.Client`, `docs/sdk.md`): it parses its
arguments, calls one SDK method and prints the result. `run` and `resume` print one
JSON object (`docs/cli-json.md`); the rest print text, or JSON with `--json`. `aip run` with no
server configured ends with one line on stderr saying the run is not recorded and how to change
that; the run's resumes do not repeat it. With `aip config server local` nothing has to be
started first: the first command that needs the server starts it (`aip.client.local`).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

from aip.client.config import CONFIGURE_HINT

CLI_AGENT = "cli"


# ------------------------------------------------------------------ the language's tooling


def compile_command(argv: list[str]) -> int:
    """`aip compile <path> [-o FILE] [--check] [--json] [--stdin]`: the language's compiler."""
    from aip.compiler.cli import compile_command as compiler_compile

    return compiler_compile(argv, prog="aip compile")


def export_command(argv: list[str]) -> int:
    """`aip export <bundle.rl> --out DIR`: the program directory back from a bundle.
    `aip export runs [name] -o FILE`: the server's runs and the procedures they ran, as one file."""
    if argv and argv[0] == "runs":
        return export_runs_command(argv[1:])
    if any(a == "--skill" or a.startswith("--skill=") for a in argv):
        return export_skill_command(argv)
    from aip.compiler.cli import export_command as compiler_export

    return compiler_export(argv, prog="aip export", epilog="`aip export <target> --skill DIR` writes the procedure as a plain "
                           "Agent Skill instead (`aip export --skill DIR --help`); `aip export runs [name] -o FILE` is the other "
                           "export: the server's runs and the procedures they ran, as one file (`aip export runs --help`).")


def export_skill_command(argv: list[str]) -> int:
    """`aip export <folder | bundle.rl | name[@rev]> --skill DIR`: the procedure as a plain Agent
    Skill, a `SKILL.md` an agent with no runtime follows by hand, and the bundle's files."""
    parser = argparse.ArgumentParser(
        prog="aip export", usage="aip export TARGET --skill DIR [--force]",
        description="Write a procedure as a plain Agent Skill: a SKILL.md that walks its steps in order, for an agent with "
                    "no aip to follow by hand, with none of the runtime's guarantees, and the bundle's files beside it. "
                    "Name DIR after the skill (the procedure's name with hyphens) when an agent is to find it.")
    parser.add_argument("target", help="a program directory, an .rl bundle, or a published `name` or `name@rev` (pulled from the server)")
    parser.add_argument("--skill", type=Path, required=True, metavar="DIR", help="the skill folder to write; must not exist or be empty")
    parser.add_argument("--force", action="store_true", help="write into a directory that is not empty")
    args = parser.parse_args(argv)

    def go() -> int:
        e = _client().export_skill(args.target, args.skill, force=args.force)
        where = f"{e.name}@{e.revision}" if e.revision else e.name
        print(f"wrote the skill {e.skill} from {where} (bundle {e.bundle_id[:12]}) to {e.path}")
        if e.path.resolve().name != e.skill:
            print(f"note: an agent expects the folder to be named after the skill, {e.skill}")
        return 0
    return _serving(go)


def fmt_command(argv: list[str]) -> int:
    """`aip fmt <path>...`: the language's formatter."""
    from aip.compiler.cli import fmt_command as compiler_fmt

    return compiler_fmt(argv, prog="aip fmt")


# ------------------------------------------------------------------ the client


def _server():
    """The configured server, or None. One seam for tests to point at an in-process app."""
    from aip.client.server import configured

    return configured()


def _client():
    """The SDK client every command is a wrapper over."""
    from aip.sdk import Client

    return Client(_server(), agent=CLI_AGENT)


def _serving(call: Callable[[], int]) -> int:
    """Run a client action; an `AipError` becomes one line on stderr and exit 1."""
    from aip.errors import AipError
    from aip.sdk import CompileError

    try:
        return call()
    except CompileError as exc:
        for d in exc.diagnostics:
            print(d, file=sys.stderr)
        print(f"aip: {exc.summary}", file=sys.stderr)       # the diagnostics are above: none is said twice
        return 1
    except AipError as exc:
        print(f"aip: {exc}", file=sys.stderr)
        return 1


class _BadJson(ValueError):
    """`--inputs` or `--answers` is not readable JSON."""


def _read_json(spec: str | None, flag: str) -> Any:
    """Inline JSON, `@path` for a file, `-` for stdin, or None when the flag was not given."""
    if spec is None:
        return None
    try:
        if spec == "-":
            text = sys.stdin.read()
        elif spec.startswith("@"):
            text = Path(spec[1:]).read_text(encoding="utf-8")
        else:
            text = spec
        return json.loads(text)
    except (OSError, ValueError) as exc:
        raise _BadJson(f"{flag} {spec!r}: {exc}; give JSON inline, @path for a file, or - for stdin") from exc


def info_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="aip info", description="Describe a procedure: what it does, the inputs it expects, "
                                     "its steps and its result.")
    parser.add_argument("target", help="a program directory, an .rl bundle, or a catalog reference (`name`, `name@rev`)")
    parser.add_argument("--json", action="store_true", help="the description as JSON instead of the summary")
    parser.add_argument("--example-inputs", action="store_true", help="print only example inputs as JSON, to edit and pass to run")
    args = parser.parse_args(argv)

    def go() -> int:
        description = _client().describe(args.target)
        if args.json:
            print(json.dumps(description.data, indent=2))
        elif args.example_inputs:
            print(json.dumps(description.example_inputs, indent=2))
        else:
            sys.stdout.write(description.summary())
        return 0
    return _serving(go)


def _run_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--progress", action="store_true",
                        help="print one JSON line per history entry as the run writes it, then the final object on one line")
    parser.add_argument("--debug", action="store_true", help="print a traceback on stderr when the command fails")


def _print_block(block: dict, progress: bool) -> None:
    print(json.dumps(block) if progress else json.dumps(block, indent=2))


def _outcome(call: Callable[[Callable[[dict], None]], Any], client: Any, progress: bool, debug: bool, starting: bool) -> int:
    """`run` and `resume`: print where the run stopped as one object, exit 0 for paused or done
    and 1 for an error; then the recording line on stderr (`docs/cli-json.md`). Whatever else
    fails is still one error object, kind `invalid_input` for a target, inputs or run reference
    that cannot be used, `server` for the rest. `starting` is True for `run`, which is where a
    run with no server says so, once."""
    from aip.client.runs import EXIT_ERROR, EXIT_OK, error_outcome
    from aip.errors import AipError
    from aip.sdk import CompileError, RunError

    on_step = (lambda line: print(json.dumps(line), flush=True)) if progress else None
    try:
        result = call(on_step)
    except RunError as exc:
        if debug and exc.cause is not None:
            import traceback
            traceback.print_exception(exc.cause, file=sys.stderr)
        _print_block(exc.to_json(), progress)
        _recording_line(client, exc.recorded, exc.run_id is not None and exc.stopped, starting)
        return EXIT_ERROR
    except Exception as exc:
        if debug:
            import traceback
            traceback.print_exception(exc, file=sys.stderr)
        if isinstance(exc, CompileError):
            for d in exc.diagnostics:
                print(d, file=sys.stderr)
        kind = "invalid_input" if isinstance(exc, (_BadJson, AipError)) else "server"
        detail = {"kind": exc.kind} if isinstance(exc, AipError) and exc.kind not in (kind, "error") else {}
        _print_block(error_outcome({"error": kind, "step": None, "message": str(exc), **detail}, None, None, None, False), progress)
        return EXIT_ERROR
    _print_block(result.to_json(), progress)
    _recording_line(client, result.recorded, True, starting)
    return EXIT_OK


def _recording_line(client: Any, recorded: bool | None, stopped: bool, starting: bool) -> None:
    """The closing line, on stderr: nothing when the stop was recorded, or when the command
    changed nothing (a refused answer). With no server, one line when the run starts and none on
    its resumes; when a server is configured and did not take the stop, why, every time."""
    if not stopped or recorded is True:
        return
    if recorded is None:
        if starting:
            print(f"aip: not recorded: no server is configured; {CONFIGURE_HINT}", file=sys.stderr)
    else:
        why = getattr(client, "recording_error", None) or "the server did not take it"
        print(f"aip: not recorded: {why}; the next stop will try again", file=sys.stderr)


def run_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="aip run", description="Run a procedure: a program directory, an .rl bundle, or a "
                                     "catalog reference. It runs here; when a server is configured the run is recorded there. "
                                     "Prints one JSON object: paused or done (exit 0), or error (exit 1); see docs/cli-json.md.")
    parser.add_argument("target", metavar="folder|bundle.rl|name[@rev]")
    parser.add_argument("--inputs", "-i", default=None, metavar="JSON",
                        help="the Start step's inputs: JSON inline, @path for a file, or - for stdin (default: an empty object)")
    parser.add_argument("--batch", type=int, default=None, metavar="N", help="how many For passes run at once (default 10; AIP_BATCH or `aip config --batch`)")
    parser.add_argument("--agent", default=None, help="who is running, for the record (default AIP_AGENT, else `cli`)")
    parser.add_argument("--session", default=None, help="an id grouping this run with others, for the record (default AIP_SESSION)")
    parser.add_argument("--workdir", type=Path, default=None,
                        help="the run's working directory, where its scripts read and write files (AIP_WORKDIR); "
                             "kept in the run file so resume works from anywhere (default the current directory)")
    parser.add_argument("--force", action="store_true", help="run `name@rev` although that revision is retired")
    _run_flags(parser)
    args = parser.parse_args(argv)
    client = _client()

    def go(on_step):
        inputs = _read_json(args.inputs, "--inputs")
        return client.run(args.target, {} if inputs is None else inputs, batch=args.batch, agent=args.agent,
                          session=args.session, workdir=args.workdir, on_step=on_step, force=args.force,
                          on_warning=lambda text: print(f"aip: warning: {text}", file=sys.stderr, flush=True))
    return _outcome(go, client, args.progress, args.debug, starting=True)


def resume_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="aip resume", description="Continue a run: answer its pause, or with no answers "
                                     "retry the step a failed run stopped at.")
    parser.add_argument("run", metavar="run_id|run_file", help="the run id every outcome prints, or a run file's path")
    parser.add_argument("--answers", "-a", default=None, metavar="JSON",
                        help="the answers to every task of the pause, keyed by task index ({\"0\": {...}}), a list in task "
                             "order, or the one answer object for a single task: JSON inline, @path for a file, or - for stdin")
    parser.add_argument("--work", default=None, metavar="JSON",
                        help="what you spent answering, for the record, which keeps it marked `reported` (aip checks none of "
                             "it): {\"model\": ID, \"tool_calls\": N, \"tokens\": N, \"seconds\": S}, any of them; keyed by "
                             "task index like --answers when the pause has several tasks")
    _run_flags(parser)
    args = parser.parse_args(argv)
    client = _client()

    def go(on_step):
        return client.resume(args.run, _read_json(args.answers, "--answers"), on_step=on_step, work=_read_json(args.work, "--work"))
    return _outcome(go, client, args.progress, args.debug, starting=False)


def agent_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="aip agent", usage='aip agent "<task>" [--session ID] [--progress]\n       aip agent --answer RUN [--session ID] [--progress]',
        description="Do a task with the catalog's procedures: a chat model outside the run drives the `assist` procedure, "
                    "answering each of its pauses with one call and no tools; assist searches the catalog, runs what fits, "
                    "builds a procedure with build_procedure when nothing does, and finishes with the result or a question "
                    "for you. Prints where assist's run stopped, as `aip run` does, with the session; run it again in that "
                    "session (--session ID, or AIP_SESSION) to answer the question: the text is your reply, and what was "
                    "asked comes from the record. Every run it starts is recorded as agent `agent` in the session "
                    "(`aip runs --session ID`). Needs `aip config agent --model-key KEY` (or AIP_AGENT_MODEL_KEY); aip "
                    "calls no chat model otherwise (docs/agent.md).")
    parser.add_argument("text", metavar="task", nargs="?", help="what is to be done; in a session that asked you something, your reply")
    parser.add_argument("--session", default=None, metavar="ID", help="the session: continue it, or start it under this id "
                        "(default AIP_SESSION, else a new one); with --answer, the session the answer is recorded in")
    parser.add_argument("--answer", default=None, metavar="RUN",
                        help="instead of a task: have the model answer the pause RUN waits at, once, and resume it; prints "
                             "what `aip resume` prints, or the paused object with `gave_up` (exit 1) when no answer would "
                             "hold. Any run of any procedure; the answer is recorded as AIP_AGENT's (the console uses it)")
    _run_flags(parser)
    args = parser.parse_args(argv)
    if args.answer is not None:
        if args.text is not None:
            parser.error("--answer takes a run id and no task")
        return _answer_pause(args)
    if args.text is None:
        parser.error("the task is required: what is to be done, in your words")
    from aip.chat import ANSWERS, ChatError
    from aip.client.runs import EXIT_ERROR
    from aip.sdk import Paused, RunError, agent_session

    client = _client()
    session = agent_session(args.session)
    print(f"aip: session: {session} (`export AIP_SESSION={session}` to continue it)", file=sys.stderr, flush=True)
    gave_up = []

    def go(on_step):
        client.on_step = on_step                       # the run's step lines; the loop adds none of its own
        try:
            result = client.ask(args.text, session=session)
        except RunError as exc:
            exc.error["session"] = session
            raise
        except ChatError as exc:                       # the run is left where it was; the loop does not catch this
            print(f"aip agent: the model's endpoint failed: {exc}", file=sys.stderr, flush=True)
            raise
        if isinstance(result, Paused):                 # the loop gave up: four answers at this step, none held
            gave_up.append(result.step)
            print(f"aip agent: gave up at {result.step} after {ANSWERS} answers: {client.gave_up}", file=sys.stderr, flush=True)
        return _InSession(result, session)
    code = _outcome(go, client, args.progress, args.debug, starting=True)
    return EXIT_ERROR if gave_up else code


class _InSession:
    """`aip agent`'s result: where assist's run stopped, as `aip run` prints it, with the session."""

    def __init__(self, result: Any, session: str):
        self.result, self.session, self.recorded = result, session, result.recorded

    def to_json(self) -> dict:
        return {**self.result.to_json(), "session": self.session}


class _GaveUp:
    """`aip agent --answer` when no answer would hold: the run's paused object as it was, with why."""

    def __init__(self, paused: Any, reason: str):
        self.paused, self.reason, self.recorded = paused, reason, paused.recorded

    def to_json(self) -> dict:
        return {**self.paused.to_json(), "gave_up": self.reason}


def _answer_pause(args: argparse.Namespace) -> int:
    """`aip agent --answer RUN`: one pause answered by the model (`Client.answer`), printed as
    `aip resume` prints its outcome; the model's calls are `--progress` lines of their own."""
    from aip.client.runs import EXIT_ERROR

    client = _client()
    on_event = (lambda event: print(json.dumps(event), flush=True)) if args.progress else None
    gave_up = []

    def go(on_step):
        result, reason = client.answer(args.answer, session=args.session, on_event=on_event, on_step=on_step)
        if reason is None:
            return result
        gave_up.append(reason)
        return _GaveUp(result, reason)
    code = _outcome(go, client, args.progress, args.debug, starting=False)
    return EXIT_ERROR if gave_up else code


# ------------------------------------------------------------------ the catalog


def search_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="aip search", description="Find published procedures by what they do; the ranking is the "
                                     "server's. The score is BM25's: it orders the hits of one search and means nothing across "
                                     "searches, and a query that fits nothing still ranks whatever shares a word with it.")
    parser.add_argument("query")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    def go() -> int:
        hits = _client().search(args.query, args.limit)
        if args.json:
            print(json.dumps([h.data for h in hits], indent=2))
        elif not hits:
            print("no matches")
        for h in hits if not args.json else []:
            print(f"{h.name}@{h.revision}  score {h.score:.3f}  {' '.join((h.description or '').split())}".rstrip())
        return 0
    return _serving(go)


def list_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="aip list", description="Every published name with the revision it resolves to.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    def go() -> int:
        rows = _client().list()
        if args.json:
            print(json.dumps([r.data for r in rows], indent=2))
            return 0
        if not rows:
            print("nothing published")
            return 0
        width = max(len(r.name) for r in rows)
        for r in rows:
            flag = "  pinned" if r.pinned else ""
            resolves = f"@{r.resolves}" if r.resolves else "@- (retired)"      # every revision is retired: the name resolves to none
            print(f"{r.name.ljust(width)}  {resolves}  {len(r.revisions or [])} revision(s){flag}  "
                  f"{' '.join((r.description or '').split())}".rstrip())
        return 0
    return _serving(go)


def pull_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="aip pull", description="Put a published procedure's bundle in the local cache, so "
                                     "`aip run <name>` works without the server.")
    parser.add_argument("ref", nargs="?", default=None, help="`name` or `name@rev`")
    parser.add_argument("--all", action="store_true", help="every published name's resolved revision")
    args = parser.parse_args(argv)
    if (args.ref is None) == (not args.all):
        parser.error("give a reference, or --all")

    def go() -> int:
        client = _client()
        for p in client.pull_all() if args.all else [client.pull(args.ref)]:
            print(f"{'pulled' if p.fetched else 'cached'} {p.name}@{p.revision or '?'}  bundle {p.bundle_id[:12]}  {p.path}")
        return 0
    return _serving(go)


def publish_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="aip publish", description="Compile a program directory (or take an .rl), upload the "
                                     "bundle, and print `name@revision`.")
    parser.add_argument("target", metavar="folder|bundle.rl")
    parser.add_argument("--draft", action="store_true", help="upload it with no revision, as a draft: out of the catalog until "
                        "it is published without --draft")
    parser.add_argument("--json", action="store_true", help="print `{name, revision, bundle_id, existed, draft}`")
    args = parser.parse_args(argv)

    def go() -> int:
        p = _client().publish(args.target, draft=args.draft)
        if args.json:
            print(json.dumps({"name": p.name, "revision": p.revision, "bundle_id": p.bundle_id, "existed": p.existed,
                              "draft": p.draft}, indent=2))
        elif p.revision is None:
            print(f"{p.name} (draft)  bundle {p.bundle_id[:12]}" + ("  (already in the store)" if p.existed else ""))
        elif args.draft:
            print(f"{p.name}  bundle {p.bundle_id[:12]}  is already published; it has a revision, so it is no draft")
        else:
            print(f"{p.name}@{p.revision}  bundle {p.bundle_id[:12]}" + ("  (already in the store)" if p.existed else ""))
        return 0
    return _serving(go)


def get_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="aip get", description="Write a published procedure's program directory from its bundle.")
    parser.add_argument("ref", help="`name`, `name@rev`")
    parser.add_argument("--out", type=Path, required=True, metavar="DIR", help="the directory to write; must not exist or be empty")
    parser.add_argument("--force", action="store_true", help="write into a directory that is not empty")
    args = parser.parse_args(argv)

    def go() -> int:
        f = _client().get(args.ref, args.out, force=args.force)
        print(f"wrote {f.name}@{f.revision or '?'} (bundle {f.bundle_id[:12]}) to {f.path}")
        return 0
    return _serving(go)


def pin_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="aip pin", description="Make a name resolve to one revision: `aip pin name@revision`. "
                                     "`aip pin name --clear` removes the pin. A retired revision is not pinned.")
    parser.add_argument("ref", help="`name@revision`; with --clear, the `name`")
    parser.add_argument("extra", nargs="?", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--clear", action="store_true", help="remove the pin: the name resolves to its newest live revision again")
    args = parser.parse_args(argv)
    name, _, revision = args.ref.partition("@")
    _one_ref(parser, args, "pin")
    if bool(revision) == args.clear:
        parser.error(f"give `{name}@<revision>` to pin one, or `{name} --clear` to remove the pin")

    def go() -> int:
        pinned = _client().pin(name, None if args.clear else revision)
        print(f"{pinned.name} pin cleared" if pinned.revision is None else f"{pinned.name} -> {pinned.revision}")
        return 0
    return _serving(go)


def _one_ref(parser: argparse.ArgumentParser, args: argparse.Namespace, command: str) -> None:
    """`pin` and `retire` take one `name@revision`: a revision given as a second word is
    answered with the spelling that works."""
    if args.extra is not None:
        parser.error(f"the revision is part of the reference: aip {command} {args.ref.partition('@')[0]}@{args.extra}")


def retire_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="aip retire", description="Stop a name resolving to a revision: `aip retire "
                                     "name@revision`. The revision is kept for the runs that reference it; `aip run name@revision` "
                                     "refuses it unless --force, a pin on it is cleared, and publishing its bundle again brings it back.")
    parser.add_argument("ref", help="`name@revision`")
    parser.add_argument("extra", nargs="?", default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    _one_ref(parser, args, "retire")

    def go() -> int:
        retired = _client().retire(args.ref)
        print(f"retired {retired.name}@{retired.revision}")
        return 0
    return _serving(go)


def runs_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="aip runs", description="Runs, the most recently started first: the server's when one "
                                     "is configured, else this machine's run files. With a run id, that run step by step (this machine's run file "
                                     "when it has one): each step, its pass, when, how long, and who answered or where it went.")
    parser.add_argument("run_id", nargs="?", default=None)
    parser.add_argument("--name", default=None, help="only runs of this procedure")
    parser.add_argument("--status", default=None, help="only runs with this status (paused, done, failed)")
    _run_filters(parser)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--json", action="store_true", help="the list, or the run's whole record, as JSON")
    args = parser.parse_args(argv)

    def go() -> int:
        client = _client()
        if args.run_id is not None:
            record = client.run_record(args.run_id)
            if args.json:
                print(json.dumps(record.data, indent=2))
            else:
                sys.stdout.write(record.table())
            return 0
        rows = client.runs(args.name, args.status, args.agent, args.session, args.limit, args.user, args.draft)
        if args.json:
            print(json.dumps([r.data for r in rows], indent=2))
            return 0
        if not rows:
            if args.name and _no_runs_of(client, args.name):
                print(f"no runs of `{args.name}`; names are `aip list`'s")
            else:
                print("no runs" if client.server is not None else "no runs on this machine")
            return 0
        table = [("RUN", "NAME", "STATUS", "AGENT", "STARTED", "UPDATED")]
        for r in rows:
            name = f"{r.name}@{r.revision}" if r.revision else f"{r.name}"
            table.append((r.run_id, name + (" (draft)" if r.draft else ""), r.status, (r.identity or {}).get("agent") or "-",
                          r.started or r.created or "-", r.updated or "-"))
        widths = [max(len(row[i]) for row in table) for i in range(6)]
        for row in table:
            print("  ".join(cell.ljust(width) for cell, width in zip(row, widths)).rstrip())
        return 0
    return _serving(go)


def _no_runs_of(client: Any, name: str) -> bool:
    """Whether `--name` itself is why nothing matched: there is no run of that name at all, and
    it is not a published name either (a name mistyped, or a folder's spelling with `-`)."""
    if client.runs(name, limit=1):
        return False
    return client.server is None or all(entry.name != name for entry in client.list())


def _run_filters(parser: argparse.ArgumentParser) -> None:
    """The flags that say which runs: by who ran them and whether the bundle was a draft."""
    parser.add_argument("--agent", default=None, help="only runs this agent made")
    parser.add_argument("--session", default=None, help="only runs of this session")
    parser.add_argument("--user", default=None, help="only runs recorded with this user's token")
    which = parser.add_mutually_exclusive_group()
    which.add_argument("--draft", dest="draft", action="store_const", const=True, default=None,
                       help="only runs of a draft (a folder or a file that is not a published revision)")
    which.add_argument("--published", dest="draft", action="store_const", const=False, help="only runs of a published revision")


def audit_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="aip audit", description="The server's audit queries over the record of runs and the "
                                     "catalog. With no query, list them; with one, print its rows as JSON. --save keeps a "
                                     "query of your own on the server, --delete removes it.")
    parser.add_argument("query", nargs="?", default=None)
    parser.add_argument("--name", default=None, help="only this procedure")
    _run_filters(parser)
    parser.add_argument("--window", type=int, default=None, help="how many recent runs to look at (default 100)")
    parser.add_argument("--limit", type=int, default=None, help="how many rows to print (default 50)")
    parser.add_argument("--repeats", type=int, default=None, help="repeated-cycles: more passes than this (default 1)")
    parser.add_argument("--key", default=None, help="lineage: the key to trace")
    parser.add_argument("--save", default=None, metavar="NAME", help="store --cypher on the server as the query NAME")
    parser.add_argument("--cypher", default=None, metavar="CYPHER", help="with --save: the query, inline or @path for a file")
    parser.add_argument("--description", default="", help="with --save: one line on what the query answers")
    parser.add_argument("--delete", default=None, metavar="NAME", help="remove a stored query")
    parser.add_argument("--json", action="store_true", help="with no query: the list of queries as JSON (a query's rows always are)")
    args = parser.parse_args(argv)
    if args.save and not args.cypher:
        parser.error("--save needs --cypher")

    def go() -> int:
        client = _client()
        if args.save:
            cypher = Path(args.cypher[1:]).read_text(encoding="utf-8") if args.cypher.startswith("@") else args.cypher
            saved = client.save_audit(args.save, cypher, args.description)
            print(f"stored {saved.query}; run it with: aip audit {saved.query}")
            return 0
        if args.delete:
            client.delete_audit(args.delete)
            print(f"removed {args.delete}")
            return 0
        rows = client.audit(args.query, name=args.name, agent=args.agent, session=args.session, user=args.user, draft=args.draft,
                            window=args.window, limit=args.limit, repeats=args.repeats, key=args.key)
        if args.query is not None:
            print(json.dumps(rows, indent=2))
            if not rows and args.name and _no_runs_of(client, args.name):
                print(f"aip: no runs of `{args.name}`; names are `aip list`'s", file=sys.stderr)
        elif args.json:
            print(json.dumps([q.data for q in rows], indent=2))
        else:
            width = max((len(q.query) for q in rows), default=0)
            for q in rows:
                print(f"{q.query.ljust(width)}  {q.description}" + ("" if q.builtin else "  (stored)"))
        return 0
    return _serving(go)


def export_runs_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="aip export runs", description="Write the server's runs, and the procedures they ran, "
                                     "as one Relate file: every run's record beside the graph of the bundle it ran, to open "
                                     "with the engine's own tools and the queries of docs/language/queries.md.")
    parser.add_argument("name", nargs="?", default=None, help="only runs of this procedure")
    parser.add_argument("--since", default=None, metavar="DATE", help="only runs started on or after this date or timestamp (2026-11-01)")
    _run_filters(parser)
    parser.add_argument("-o", "--output", type=Path, required=True, metavar="FILE", help="the file to write (an .rl)")
    parser.add_argument("--force", action="store_true", help="replace FILE if it exists")
    args = parser.parse_args(argv)

    def go() -> int:
        e = _client().export_runs(args.output, args.name, since=args.since, agent=args.agent, session=args.session, user=args.user,
                                  draft=args.draft, force=args.force)
        bundles = "" if e.bundles == e.procedures else f" ({e.bundles} bundles: each revision and each draft is one)"
        print(f"wrote {e.runs} run(s) of {e.procedures} procedure(s){bundles} to {e.path}")
        return 0
    return _serving(go)


SCRIPT_TIMEOUT_HELP = ("seconds one script may run, wherever a script runs: run, resume, agent, the client of a served run (the "
                       "server itself never runs a script). Default 300; 0 or none for no cap; an empty string forgets it. "
                       "AIP_SCRIPT_TIMEOUT overrides it")


def config_command(argv: list[str]) -> int:
    if argv and argv[0] == "agent":
        return config_agent_command(argv[1:])
    from aip.model.typesafe import DEFAULT_URL
    from aip.sdk import configure, settings

    parser = argparse.ArgumentParser(prog="aip config", description="Where the client points and how it runs. With no arguments, "
                                     "show it. `aip config server local` records runs on this machine: a server is started "
                                     "when a command needs one and stops when idle. `aip config server URL` points at a server "
                                     "elsewhere (give its bearer token with --token); `aip config server none` records nothing. "
                                     "AIP_SERVER, AIP_TOKEN, AIP_DECISION_MODEL, AIP_DECISION_MODEL_KEY, AIP_BATCH and "
                                     "AIP_SCRIPT_TIMEOUT override the file. The decision model is an endpoint with the TypeSafe "
                                     "API shape; without one a Decide step fails the run (no_decision_model) until one is set and "
                                     "the run is resumed. `aip config agent --help`: the chat model `aip agent` asks.")
    parser.add_argument("setting", nargs="*", metavar="server local|URL|none", help="where runs are recorded and the catalog is")
    parser.add_argument("--server", default=None, metavar="URL", help="the same as `server URL` (an empty string forgets it)")
    parser.add_argument("--token", default=None, help="the bearer token for the server (an empty string forgets it)")
    parser.add_argument("--decision-model", default=None, metavar="URL",
                        help=f"the decision model's endpoint (default {DEFAULT_URL}, TypeSafe's; an empty string forgets it)")
    parser.add_argument("--decision-model-key", default=None, metavar="KEY",
                        help="the decision model's API key (an empty string forgets it); never printed")
    parser.add_argument("--batch", type=int, default=None, metavar="N", help="how many For passes run at once by default")
    parser.add_argument("--script-timeout", default=None, metavar="N", help=SCRIPT_TIMEOUT_HELP)
    parser.add_argument("--clear", action="store_true", help="forget everything")
    args = parser.parse_args(argv)
    if args.setting:
        if len(args.setting) != 2 or args.setting[0] != "server" or args.server is not None:
            parser.error("the one setting given by name is the server: `aip config server local`, `aip config server URL` or "
                         "`aip config server none`; `aip config agent` sets the model `aip agent` asks; the rest are flags")
        args.server = args.setting[1]
    writes = args.clear or any(v is not None for v in (args.server, args.token, args.decision_model, args.decision_model_key, args.batch,
                                                       args.script_timeout))
    try:
        s = configure(args.server, args.token, args.decision_model, args.decision_model_key, args.batch, clear=args.clear,
                      script_timeout=args.script_timeout) if writes else settings()
    except ValueError as exc:
        parser.error(str(exc))
    if writes:
        print(f"{'cleared' if args.clear else 'wrote'} {s.path}")
    if s.server is None:
        print(f"server: none (runs are not recorded; {CONFIGURE_HINT})")
    elif s.local:
        from aip.client import local

        print(f"server: local  {s.server}, started when a command needs it; its store is {local.store_path()}  (from {s.source})")
    else:
        print(f"server: {s.server}  (from {s.source})")
        print(f"token:  {'set' if s.token_set else 'none'}")
    print(s.decision_model)
    print(f"batch: {s.batch}")
    print(s.script_cap)
    print(s.agent)
    return 0


def config_agent_command(argv: list[str]) -> int:
    from aip.client.config import DEFAULT_AGENT_MODEL_NAME, DEFAULT_AGENT_MODEL_URI
    from aip.sdk import configure_agent, settings

    parser = argparse.ArgumentParser(
        prog="aip config agent", description="The chat model `aip agent` asks at each pause of the runs it drives. With no "
        "arguments, show it. aip calls no chat model except in `aip agent`. AIP_AGENT_MODEL_URI, AIP_AGENT_MODEL_NAME and "
        "AIP_AGENT_MODEL_KEY override the file.")
    parser.add_argument("--model-uri", default=None, metavar="URL",
                        help=f"an OpenAI Chat Completions endpoint, POST {{URL}}/chat/completions (default {DEFAULT_AGENT_MODEL_URI}, "
                             "Anthropic's; https://api.openai.com/v1, Gemini's, Ollama's and others serve the same shape; an "
                             "empty string forgets it)")
    parser.add_argument("--model-name", default=None, metavar="NAME",
                        help=f"the model to ask for (default {DEFAULT_AGENT_MODEL_NAME}); the record keeps the id the endpoint "
                             "reports in its reply")
    parser.add_argument("--model-key", default=None, metavar="KEY",
                        help="the endpoint's API key, sent as a bearer token; never printed; an empty string forgets it")
    args = parser.parse_args(argv)
    values = {"model_uri": args.model_uri, "model_name": args.model_name, "model_key": args.model_key}
    writes = any(v is not None for v in values.values())
    s = configure_agent(**values) if writes else settings()
    if writes:
        print(f"wrote {s.path}")
    print(s.agent)
    return 0


def upgrade_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="aip upgrade", description="Publish the procedures this package ships (make_procedure, build_procedure, edit_procedure) "
                                     "to the configured server. A server publishes them itself when it first starts; this is "
                                     "for a server that runs an older aip than this one. A bundle the server already holds "
                                     "is left as it is.")
    parser.parse_args(argv)

    def go() -> int:
        published = _client().upgrade()
        for p in published:
            print(f"{p.name}@{p.revision}  bundle {p.bundle_id[:12]}" + ("  (already in the store)" if p.existed else ""))
        if not published:
            print("this package ships no procedure")
        return 0
    return _serving(go)


# ------------------------------------------------------------------ the skill


def skill_command(argv: list[str]) -> int:
    """`aip skill install | list | remove | prune`: the `aip` skill (`skills/aip/`, shipped in the
    package) in the skills directory of the agents on this machine. `install` records what it
    wrote and removes its own earlier folders that are no longer its skill (the two skills of
    0.8); `prune` removes folders under those retired names that no record knows of."""
    from aip.compiler import agents
    from aip.compiler.resources import LEGACY_SKILL_NAMES, SKILL_ENTRIES, SKILL_NAME, skill_dir

    parser = argparse.ArgumentParser(prog="aip skill", description=f"Install the `{SKILL_NAME}` skill, the page an agent reads to "
                                     "run and to write procedures, into the agents on this machine.")
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("install", help="into every detected agent, one named agent, or a skills directory")
    p.add_argument("agent", nargs="?", help=f"one of: {', '.join(agents.AGENTS)}")
    p.add_argument("--path", type=Path, default=None, metavar="DIR", help=f"a skills directory; writes DIR/{SKILL_NAME}/")
    sub.add_parser("list", help="supported agents, whether each is detected, and whether the skill is installed")
    p = sub.add_parser("remove", help="from one agent, a skills directory, or every agent that has it")
    p.add_argument("agent", nargs="?")
    p.add_argument("--path", type=Path, default=None, metavar="DIR")
    p = sub.add_parser("prune", help=f"remove skill folders installed under a retired name ({', '.join(LEGACY_SKILL_NAMES)}) "
                                     "from every detected agent, one agent, or a skills directory")
    p.add_argument("agent", nargs="?")
    p.add_argument("--path", type=Path, default=None, metavar="DIR")
    p.add_argument("--dry-run", action="store_true", help="report what would be removed, remove nothing")
    args = parser.parse_args(argv)

    if args.action == "list":
        print(agents.table([SKILL_NAME]))
        return 0
    try:
        if args.action == "prune":
            removed, skipped = agents.prune(LEGACY_SKILL_NAMES, args.agent, args.path, dry_run=args.dry_run)
            for folder in removed:
                print(f"{'would remove' if args.dry_run else 'removed'} {folder}  (a retired skill name)")
            for folder, reason in skipped:
                print(f"aip skill prune: left {folder} alone: {reason}", file=sys.stderr)
            if not removed and not skipped:
                print(f"nothing to prune: no {', '.join(LEGACY_SKILL_NAMES)} skill folder in any agent `aip skill list` looks at")
            return 0
        if args.action == "install":
            written, removed = agents.install([(skill_dir(), SKILL_ENTRIES)], args.agent, args.path, tool="aip")
            for label, folder in written:
                print(f"installed {folder.name} -> {folder}  ({label})")
            for folder in removed:
                print(f"removed {folder}  (installed by an earlier aip, no longer its skill)")
            return 0
        removed = agents.remove([SKILL_NAME], args.agent, args.path)
        for folder in removed:
            print(f"removed {folder}")
        if not removed:
            print(f"the {SKILL_NAME} skill is not installed anywhere `aip skill list` looks")
        return 0
    except (KeyError, agents.NoAgentDetected) as exc:
        print(f"aip skill: {exc.args[0]}", file=sys.stderr)
        return 1


# ------------------------------------------------------------------ the MCP server


def mcp_command(argv: list[str]) -> int:
    """`aip mcp`: the SDK as an MCP server (`aip.mcp`, `docs/mcp.md`)."""
    parser = argparse.ArgumentParser(prog="aip mcp", description="Serve this client to an MCP client (an agent framework, a coding "
                                     "agent): the tools search, describe, compile, run, resume, agent and pull, each answering with the "
                                     "JSON the command of that name prints (docs/cli-json.md). Over stdio by default, which is "
                                     "how an MCP client starts it: give it the command `aip mcp`. Runs are recorded where `aip "
                                     "config` points, under the MCP client's own name as the agent.")
    parser.add_argument("--http", type=int, default=None, metavar="PORT",
                        help="serve over streamable HTTP at http://HOST:PORT/mcp instead of stdio")
    parser.add_argument("--host", default="127.0.0.1", help="with --http: the address to listen on (default 127.0.0.1)")
    parser.add_argument("--agent", default=None, help="who is running, for the record, instead of the MCP client's own name "
                        "(with neither: AIP_AGENT, else `mcp`)")
    parser.add_argument("--session", default=None, help="the session of every run a call gives none (default AIP_SESSION, "
                        "else an id made when this server starts)")
    args = parser.parse_args(argv)
    if args.http is None and args.host != "127.0.0.1":
        parser.error("--host goes with --http PORT")
    from aip.mcp import serve
    from aip.sdk import Client

    try:
        serve(Client(_server()), http=args.http, host=args.host, agent=args.agent, session=args.session)
    except KeyboardInterrupt:
        pass
    return 0


# ------------------------------------------------------------------ the server


def server_command(argv: list[str]) -> int:
    """`aip server`: the HTTP API over the store, a Relate file by default or a Neo4j database."""
    from aip.server.config import (CONFIG_ENV, CONFIG_FILE, DEFAULT_STORE, ENV_FILE, EXAMPLE, ConfigError, apply_config,
                                   find_config, load_env_file, read_config, user_config_path, write_example)

    parser = argparse.ArgumentParser(prog="aip server", description="Serve the AIP catalog and the record of runs.",
                                     epilog="Configuration, highest precedence first: these flags, the environment "
                                            "(NEO4J_*; a .env file is loaded into it), the config file, "
                                            "defaults. `--example-config` prints a complete file. "
                                            "Without --token the server is open; keep --host on localhost.")
    parser.add_argument("--config", type=Path, default=None, metavar="FILE",
                        help=f"TOML config file (default ${CONFIG_ENV}, else ./{CONFIG_FILE}, else "
                             f"{user_config_path()})")
    parser.add_argument("--init", nargs="?", const=True, default=None, metavar="FILE",
                        help=f"write a complete config file to edit, to {user_config_path()} or FILE, and exit")
    parser.add_argument("--env-file", type=Path, default=None, metavar="FILE",
                        help=f"KEY=value file loaded into the environment without overriding it (default ./{ENV_FILE} if present)")
    parser.add_argument("--example-config", action="store_true", help=f"print a complete {CONFIG_FILE} and exit")
    parser.add_argument("--backend", choices=["relate", "neo4j"], default="relate",
                        help="where the store is: one Relate file this server alone writes (the default), or a Neo4j database")
    parser.add_argument("--path", type=Path, default=None, help=f"relate backend: the store file (default {DEFAULT_STORE})")
    parser.add_argument("--uri", default=None, help="neo4j backend: bolt URI; default $NEO4J_URI or neo4j://localhost:7687")
    parser.add_argument("--user", default=None, help="neo4j: default $NEO4J_USERNAME or neo4j")
    parser.add_argument("--password", default=None, help="neo4j: default $NEO4J_PASSWORD")
    parser.add_argument("--database", default=None, help="neo4j: default $NEO4J_DATABASE or neo4j")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--token", default=None, help="bearer token granting every scope (read, record runs, publish); the "
                        "config file's [tokens] table names one per person")
    parser.add_argument("--read-token", default=None, help="bearer token granting the read scope only")
    parser.add_argument("--no-localhost", action="store_true", help="require a token from loopback clients too")
    parser.add_argument("--allow-origin", action="append", default=None, metavar="ORIGIN",
                        help="a web origin whose pages may call this server (CORS); repeatable. Loopback origins, "
                             "where the console runs, always may")
    parser.add_argument("--log-level", default="info")
    parser.add_argument("--local", action="store_true",
                        help="the server a client starts for itself (`aip config server local`): loopback only, the Relate store "
                             "under the user data directory, no config file read, and it stops when idle")
    parser.add_argument("--stop", action="store_true", help="with --local: stop the local server if it is running, and exit")
    parser.add_argument("--idle-exit", type=float, default=None, metavar="SECONDS",
                        help="stop when no request has arrived for this long (--local: AIP_LOCAL_IDLE, default 900; 0 never stops)")

    # Files first, so their values become the defaults the flags override.
    pre, _ = parser.parse_known_args(argv)
    if pre.example_config:
        print(EXAMPLE, end="")
        return 0
    if pre.init is not None:
        target = user_config_path() if pre.init is True else Path(pre.init)
        try:
            write_example(target)
        except ConfigError as exc:
            print(f"aip server: {exc}", file=sys.stderr)
            return 1
        print(f"wrote {target}\nedit it (the backend, the tokens), then run: aip server")
        return 0
    env_file = pre.env_file if pre.env_file is not None else (Path(ENV_FILE) if Path(ENV_FILE).is_file() else None)
    config_file = find_config(pre.config)
    if pre.stop and not pre.local:
        parser.error("--stop stops the local server: aip server --local --stop")
    if pre.local:                                     # the same server whichever directory the client stood in
        from aip.client import local
        from aip.errors import AipError

        if pre.stop:
            try:
                pid = local.stop()
            except AipError as exc:
                print(f"aip server: {exc}", file=sys.stderr)
                return 1
            print(f"stopped the local server (pid {pid}) at {local.url()}" if pid else f"no local server is running at {local.url()}")
            return 0
        env_file = config_file = None
        parser.set_defaults(host=local.HOST, port=local.port(), path=local.store_path(), idle_exit=local.idle_seconds(),
                            log_level="warning")
    loaded: list[str] = []
    try:
        if env_file is not None:
            applied = load_env_file(env_file)
            loaded.append(f"{env_file} ({len(applied)} set)")
        if config_file is not None:
            parser.set_defaults(**apply_config(read_config(config_file)))
            loaded.append(str(config_file))
    except ConfigError as exc:
        print(f"aip server: {exc}", file=sys.stderr)
        return 1
    args = parser.parse_args(argv)

    try:
        import uvicorn
        from aip.server.app import create_app
    except ImportError:
        print("aip server needs the server extra: `uv sync --extra server` (or `pip install 'agent-instruction-protocol[server]'`)",
              file=sys.stderr)
        return 1

    if args.backend == "relate":
        from aip.compiler.relate import RelateMissing
        from aip.server.backends.relate import RelateBackend
        try:
            backend = RelateBackend(args.path or DEFAULT_STORE.expanduser())
        except RelateMissing as exc:
            print(f"aip server: {exc}", file=sys.stderr)
            return 1
        except Exception as exc:                      # another server holds the file, or it is not a store
            print(f"aip server: cannot open the store at {args.path or DEFAULT_STORE.expanduser()}: {exc}", file=sys.stderr)
            return 1
        where = f"relate store at {backend.path}"
    else:
        from aip.server.backends.neo4j import Connection, Neo4jBackend
        conn = Connection()
        for attr, value in (("uri", args.uri), ("user", args.user), ("password", args.password), ("database", args.database)):
            if value is not None:
                setattr(conn, attr, value)
        try:
            backend = Neo4jBackend(conn)
        except Exception as exc:                      # driver missing, unreachable, bad credentials
            print(f"aip server: cannot open the neo4j backend at {conn.uri}: {exc}", file=sys.stderr)
            return 1
        where = f"neo4j backend at {conn.uri}"

    from aip.server.app import ALL_SCOPES, READ, Token

    tokens = {}
    if args.token:
        tokens[args.token] = Token(ALL_SCOPES)
    if args.read_token:
        tokens[args.read_token] = Token(frozenset({READ}))
    for name, token in (getattr(args, "named_tokens", None) or {}).items():
        tokens[token] = Token(ALL_SCOPES, name)
    if not tokens and args.host not in ("127.0.0.1", "localhost", "::1"):
        print(f"aip server: warning: listening on {args.host} with no --token; anyone who can reach it can publish "
              "and record here", file=sys.stderr)
    app = create_app(backend, tokens=tokens, localhost_open=not args.no_localhost, allow_origins=args.allow_origin, local=args.local)
    if loaded:
        print(f"aip server: configured from {', '.join(loaded)}", file=sys.stderr)
    print(f"aip server: {where}; http://{args.host}:{args.port}", file=sys.stderr)
    if tokens:
        print(f"aip server: {len(tokens)} bearer token(s); loopback clients "
              f"{'need one too' if args.no_localhost else 'need none'}", file=sys.stderr)
    server = uvicorn.Server(uvicorn.Config(app, host=args.host, port=args.port, log_level=args.log_level))
    if args.idle_exit:
        import threading
        import time

        def stop_when_idle() -> None:
            while not server.should_exit:
                time.sleep(min(1.0, args.idle_exit / 4))
                if time.monotonic() - app.state.last_request > args.idle_exit:
                    print(f"aip server: no request for {args.idle_exit:g}s; stopping", file=sys.stderr)
                    server.should_exit = True
        threading.Thread(target=stop_when_idle, name="aip-idle", daemon=True).start()
    try:
        server.run()
    finally:
        if hasattr(backend, "close"):
            backend.close()
    return 0 if server.started or server.should_exit else 1


COMMANDS = {
    "run": run_command,
    "resume": resume_command,
    "agent": agent_command,
    "compile": compile_command,
    "export": export_command,
    "fmt": fmt_command,
    "info": info_command,
    "pull": pull_command,
    "publish": publish_command,
    "get": get_command,
    "search": search_command,
    "list": list_command,
    "pin": pin_command,
    "retire": retire_command,
    "runs": runs_command,
    "audit": audit_command,
    "config": config_command,
    "server": server_command,
    "mcp": mcp_command,
    "skill": skill_command,
    "upgrade": upgrade_command,
}
ALIASES = {"describe": "info"}
RENAMED = {"governance": "audit"}       # said once, so a 0.8 habit lands somewhere

# One line per command, for `aip --help`.
SUMMARIES = {
    "run": "run a procedure (a folder, an .rl bundle or a published name) until it pauses or is done",
    "resume": "answer a paused run, or retry the step a failed run stopped at",
    "agent": "do a task: a chat model outside the run drives assist; again in the same shell to answer its question",
    "compile": "check a program directory and write its .rl bundle",
    "export": "write a bundle's program directory back; `--skill DIR`: as a plain Agent Skill; `export runs`: the server's runs as one Relate file",
    "fmt": "rewrite procedure.aip in the canonical form",
    "info": "what a procedure does: its inputs, its steps and loops, its result",
    "pull": "put a published procedure's bundle in this machine's cache",
    "publish": "upload a folder or a bundle to the server under its name",
    "get": "write a published procedure's program directory",
    "search": "find published procedures by what they do",
    "list": "every published name and the revision it resolves to",
    "pin": "make a name resolve to one revision",
    "retire": "stop a revision resolving",
    "runs": "list runs (this machine's, or the server's), or show one run step by step",
    "audit": "the server's audit queries over the runs and the catalog",
    "config": "where this client points: the server (local, a URL or none), the decision model, the batch size, the script "
              "timeout; `config agent`: the model `aip agent` asks",
    "server": "serve the catalog and the record of runs over HTTP",
    "mcp": "serve this client to an MCP client: search, describe, compile, run, resume, agent and pull as tools",
    "skill": "install the aip skill, the page an agent reads to run and write procedures, into the agents here",
    "upgrade": "publish the procedures this package ships (make_procedure, build_procedure, edit_procedure) to the server",
}


def version_line() -> str:
    """`aip --version`: `aip <version> language <language version>` on one line, which the console checks at startup."""
    from importlib.metadata import version

    from aip.compiler import LANGUAGE_VERSION

    return f"aip {version('agent-instruction-protocol')} language {LANGUAGE_VERSION}"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "--version":
        print(version_line())
        return 0
    if not argv or argv[0] in ("-h", "--help"):
        width = max(len(c) for c in COMMANDS)
        print("usage: aip <command> [args]\n       aip <command> --help\n       aip --version\n\ncommands:\n"
              + "\n".join(f"  {c.ljust(width)}  {SUMMARIES[c]}" for c in COMMANDS)
              + "\n\n`run` and `info` take a program directory, an .rl bundle, or a published name "
              "(`aip pull` caches one; `aip config server local` records runs on this machine, "
              "`aip config server URL` on a server elsewhere).")
        return 0
    command, rest = ALIASES.get(argv[0], argv[0]), argv[1:]
    if command in COMMANDS:
        return COMMANDS[command](rest)
    if command in RENAMED:
        print(f"aip: `aip {command}` is `aip {RENAMED[command]}` since 0.9", file=sys.stderr)
        return 2
    print(f"aip: unknown command {command!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
