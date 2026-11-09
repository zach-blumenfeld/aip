"""The `aip` command line entry point.

    aip run <target> --inputs JSON      run a program directory, an .rl bundle or a catalog name; pauses print as JSON
    aip resume <run_id> --answers JSON  answer a pause (or, with no answers, retry a failed run)
    aip compile | export | fmt          the language's tooling (aip.compiler)
    aip info <target>                   what a procedure is and what to give it
    aip pull | publish | get            move bundles between the cache and the catalog
    aip search | list | pin | retire    the catalog
    aip runs                            this machine's runs, or the server's; one run step by step
    aip governance                      the server's governance queries
    aip config                          where the client points: the server, the token, the decision model's endpoint and key, the batch size
    aip server | db                     serve, or load Neo4j directly

Every client command is a wrapper over the SDK (`aip.Client`, `docs/sdk.md`): it parses its
arguments, calls one SDK method and prints the result. `run` and `resume` print one JSON
object (`docs/cli-json.md`); the rest print text, or JSON with `--json`. `aip run` with no
server configured ends with one line on stderr saying the run is not recorded and how to change
that; the run's resumes do not repeat it.
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
    """`aip export <bundle.rl> --out DIR`: the program directory back from a bundle."""
    from aip.compiler.cli import export_command as compiler_export

    return compiler_export(argv, prog="aip export")


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
        print(f"aip: {exc}", file=sys.stderr)
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
    _run_flags(parser)
    args = parser.parse_args(argv)
    client = _client()

    def go(on_step):
        inputs = _read_json(args.inputs, "--inputs")
        return client.run(args.target, {} if inputs is None else inputs, batch=args.batch, agent=args.agent,
                          session=args.session, workdir=args.workdir, on_step=on_step)
    return _outcome(go, client, args.progress, args.debug, starting=True)


def resume_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="aip resume", description="Continue a run: answer its pause, or with no answers "
                                     "retry the step a failed run stopped at.")
    parser.add_argument("run", metavar="run_id|run_file", help="the run id every outcome prints, or a run file's path")
    parser.add_argument("--answers", "-a", default=None, metavar="JSON",
                        help="the answers to every task of the pause, keyed by task index ({\"0\": {...}}), a list in task "
                             "order, or the one answer object for a single task: JSON inline, @path for a file, or - for stdin")
    _run_flags(parser)
    args = parser.parse_args(argv)
    client = _client()

    def go(on_step):
        return client.resume(args.run, _read_json(args.answers, "--answers"), on_step=on_step)
    return _outcome(go, client, args.progress, args.debug, starting=False)


# ------------------------------------------------------------------ the catalog


def search_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="aip search", description="Find published procedures by what they do; the ranking is the server's.")
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
            print(f"{h.name}@{h.revision}  {h.score:.3f}  {h.description or ''}".rstrip())
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
            print(f"{r.name.ljust(width)}  @{r.resolves or '-'}  {len(r.revisions or [])} revision(s){flag}  {r.description or ''}".rstrip())
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
    args = parser.parse_args(argv)

    def go() -> int:
        p = _client().publish(args.target)
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
    parser = argparse.ArgumentParser(prog="aip pin", description="Make a name resolve to one revision; --clear removes the pin.")
    parser.add_argument("name")
    parser.add_argument("revision", nargs="?", default=None)
    parser.add_argument("--clear", action="store_true")
    args = parser.parse_args(argv)
    if (args.revision is None) == (not args.clear):
        parser.error("give a revision, or --clear")

    def go() -> int:
        pinned = _client().pin(args.name, None if args.clear else args.revision)
        print(f"{pinned.name} pin cleared" if pinned.revision is None else f"{pinned.name} -> {pinned.revision}")
        return 0
    return _serving(go)


def retire_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="aip retire", description="Stop a name resolving to a revision (kept for the runs that reference it).")
    parser.add_argument("ref", help="`name@revision`")
    args = parser.parse_args(argv)

    def go() -> int:
        retired = _client().retire(args.ref)
        print(f"retired {retired.name}@{retired.revision}")
        return 0
    return _serving(go)


def runs_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="aip runs", description="Runs, newest first: the server's when one is configured, else "
                                     "this machine's run files. With a run id, that run step by step (this machine's run file "
                                     "when it has one): each step, its pass, when, how long, and who answered or where it went.")
    parser.add_argument("run_id", nargs="?", default=None)
    parser.add_argument("--name", default=None, help="only runs of this procedure")
    parser.add_argument("--status", default=None, help="only runs with this status (paused, done, failed)")
    parser.add_argument("--agent", default=None, help="only runs this agent made")
    parser.add_argument("--session", default=None, help="only runs of this session")
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
        rows = client.runs(args.name, args.status, args.agent, args.session, args.limit)
        if args.json:
            print(json.dumps([r.data for r in rows], indent=2))
            return 0
        if not rows:
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


def governance_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="aip governance", description="The server's governance queries; with a query, its rows as JSON.")
    parser.add_argument("query", nargs="?", default=None)
    parser.add_argument("--name", default=None, help="only this procedure")
    parser.add_argument("--agent", default=None)
    parser.add_argument("--session", default=None)
    parser.add_argument("--window", type=int, default=None, help="how many recent runs to look at")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    def go() -> int:
        rows = _client().governance(args.query, name=args.name, agent=args.agent, session=args.session, window=args.window,
                                    limit=args.limit)
        if args.query is None:
            width = max((len(q.query) for q in rows), default=0)
            for q in rows:
                print(f"{q.query.ljust(width)}  {q.description}")
            return 0
        print(json.dumps(rows, indent=2))
        return 0
    return _serving(go)


def config_command(argv: list[str]) -> int:
    from aip.model.typesafe import DEFAULT_URL
    from aip.sdk import configure, settings

    parser = argparse.ArgumentParser(prog="aip config", description="Where the client points and how it runs. With no flags, "
                                     "show it. AIP_SERVER, AIP_TOKEN, AIP_DECISION_MODEL, AIP_DECISION_MODEL_KEY and AIP_BATCH "
                                     "override the file. The decision model is an endpoint with the TypeSafe API shape; without "
                                     "one a Decide step fails the run (no_decision_model) until one is set and the run is resumed.")
    parser.add_argument("--server", default=None, metavar="URL", help="the server that records runs and holds the catalog (an empty string forgets it)")
    parser.add_argument("--token", default=None, help="the bearer token for the server (an empty string forgets it)")
    parser.add_argument("--decision-model", default=None, metavar="URL",
                        help=f"the decision model's endpoint (default {DEFAULT_URL}, TypeSafe's; an empty string forgets it)")
    parser.add_argument("--decision-model-key", default=None, metavar="KEY",
                        help="the decision model's API key (an empty string forgets it); never printed")
    parser.add_argument("--batch", type=int, default=None, metavar="N", help="how many For passes run at once by default")
    parser.add_argument("--clear", action="store_true", help="forget everything")
    args = parser.parse_args(argv)
    writes = args.clear or any(v is not None for v in (args.server, args.token, args.decision_model, args.decision_model_key, args.batch))
    try:
        s = configure(args.server, args.token, args.decision_model, args.decision_model_key, args.batch, clear=args.clear) if writes else settings()
    except ValueError as exc:
        parser.error(str(exc))
    if writes:
        print(f"{'cleared' if args.clear else 'wrote'} {s.path}")
    if s.server is None:
        print(f"server: none (runs are not recorded; {CONFIGURE_HINT})")
    else:
        print(f"server: {s.server}  (from {s.source})")
        print(f"token:  {'set' if s.token_set else 'none'}")
    print(s.decision_model)
    print(f"batch: {s.batch}")
    return 0


# ------------------------------------------------------------------ the server and Neo4j


def db_command(argv: list[str]) -> int:
    """`aip db load|list|export`: Neo4j directly. Not on 0.9 yet: the server milestone (plan S1) moves it to bundles."""
    from aip.db.neo4j import Connection, export, list_skills, load

    connection = argparse.ArgumentParser(add_help=False)
    connection.add_argument("--uri", default=None, help="Neo4j URI; default $NEO4J_URI or neo4j://localhost:7687")
    connection.add_argument("--user", default=None, help="default $NEO4J_USERNAME or neo4j")
    connection.add_argument("--password", default=None, help="default $NEO4J_PASSWORD")
    connection.add_argument("--database", default=None, help="default $NEO4J_DATABASE or neo4j")

    parser = argparse.ArgumentParser(prog="aip db", description="The Neo4j store, directly, without a server. Not on 0.9 yet: "
                                     "these subcommands read and write the format before the language and do not take a "
                                     "procedure.aip or an .rl bundle. To store a 0.9 procedure, `aip publish` it to a server.")
    sub = parser.add_subparsers(dest="op", required=True)
    p_load = sub.add_parser("load", parents=[connection], help="write a folder to the database")
    p_load.add_argument("skill_dir", type=Path, metavar="folder")
    sub.add_parser("list", parents=[connection], help="what the database holds, newest revision first")
    p_export = sub.add_parser("export", parents=[connection], help="rebuild a folder from the database, byte for byte")
    p_export.add_argument("name")
    p_export.add_argument("--revision", default=None, help="a specific revision; default is the latest")
    p_export.add_argument("--out", type=Path, default=Path("."), help="parent folder; the skill lands at <out>/<name>")
    args = parser.parse_args(argv)

    conn = Connection()
    for attr, value in (("uri", args.uri), ("user", args.user), ("password", args.password), ("database", args.database)):
        if value is not None:
            setattr(conn, attr, value)

    if args.op == "load":
        try:
            skill_id = load(args.skill_dir, conn)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 1
        print(f"loaded {skill_id}")
        return 0
    if args.op == "list":
        rows = list_skills(conn)
        if not rows:
            print("no skills loaded")
            return 0
        width = max(len(r["name"]) for r in rows)
        for r in rows:
            flags = "".join(f"  {flag}" for flag, on in (("pinned", r.get("pinned")), ("retired", r.get("retired"))) if on)
            print(f"{r['name'].ljust(width)}  {r['revision']}  aip {r['aip_version']}  {r['steps']} steps  "
                  f"{r['files']} files  {r['published_at']}{flags}")
        return 0
    try:
        target = export(args.name, args.out, revision=args.revision, conn=conn)
    except KeyError as exc:
        print(f"aip: {exc}", file=sys.stderr)
        return 1
    print(f"exported {target}")
    return 0


def server_command(argv: list[str]) -> int:
    """`aip server`: the HTTP API. The 0.8 server until S1 (plan aip-dev#1) rewrites it over the new store."""
    from aip.server.config import (CONFIG_ENV, CONFIG_FILE, DEFAULT_ROOT, ENV_FILE, EXAMPLE, ConfigError, apply_config,
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
    parser.add_argument("--backend", choices=["filesystem", "neo4j"], default="filesystem")
    parser.add_argument("--root", type=Path, default=None, help=f"filesystem backend: the root directory (default {DEFAULT_ROOT})")
    parser.add_argument("--uri", default=None, help="neo4j backend: bolt URI; default $NEO4J_URI or neo4j://localhost:7687")
    parser.add_argument("--user", default=None, help="neo4j: default $NEO4J_USERNAME or neo4j")
    parser.add_argument("--password", default=None, help="neo4j: default $NEO4J_PASSWORD")
    parser.add_argument("--database", default=None, help="neo4j: default $NEO4J_DATABASE or neo4j")
    parser.add_argument("--cache-dir", type=Path, default=None, help="neo4j: where revisions are materialised (default ~/.cache/aip)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--token", default=None, help="bearer token granting the read and publish scopes")
    parser.add_argument("--read-token", default=None, help="bearer token granting the read scope only")
    parser.add_argument("--no-localhost", action="store_true", help="require a token from loopback clients too")
    parser.add_argument("--allow-origin", action="append", default=None, metavar="ORIGIN",
                        help="a web origin whose pages may call this server (CORS); repeatable. Loopback origins, "
                             "where the console runs, always may")
    parser.add_argument("--log-level", default="info")

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

    if args.backend == "filesystem":
        from aip.server.backends.filesystem import FilesystemBackend
        root = args.root or DEFAULT_ROOT.expanduser()
        backend = FilesystemBackend(root)
        where = f"filesystem backend at {root.resolve()}"
    else:
        from aip.server.backends.neo4j import Connection, Neo4jBackend
        conn = Connection()
        for attr, value in (("uri", args.uri), ("user", args.user), ("password", args.password), ("database", args.database)):
            if value is not None:
                setattr(conn, attr, value)
        try:
            backend = Neo4jBackend(conn, cache_dir=args.cache_dir)
        except Exception as exc:                      # driver missing, unreachable, bad credentials
            print(f"aip server: cannot open the neo4j backend at {conn.uri}: {exc}", file=sys.stderr)
            return 1
        where = f"neo4j backend at {conn.uri}"

    tokens = {}
    if args.token:
        tokens[args.token] = {"read", "publish"}
    if args.read_token:
        tokens[args.read_token] = {"read"}
    if not tokens and args.host not in ("127.0.0.1", "localhost", "::1"):
        print(f"aip server: warning: listening on {args.host} with no --token; anyone who can reach it can publish "
              "and record here", file=sys.stderr)
    app = create_app(backend, tokens=tokens, localhost_open=not args.no_localhost, allow_origins=args.allow_origin)
    if loaded:
        print(f"aip server: configured from {', '.join(loaded)}", file=sys.stderr)
    print(f"aip server: {where}; http://{args.host}:{args.port}", file=sys.stderr)
    if tokens:
        print(f"aip server: {len(tokens)} bearer token(s); loopback clients "
              f"{'need one too' if args.no_localhost else 'need none'}", file=sys.stderr)
    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)
    finally:
        if hasattr(backend, "close"):
            backend.close()
    return 0


COMMANDS = {
    "run": run_command,
    "resume": resume_command,
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
    "governance": governance_command,
    "config": config_command,
    "server": server_command,
    "db": db_command,
}
ALIASES = {"describe": "info"}

# One line per command, for `aip --help`.
SUMMARIES = {
    "run": "run a procedure (a folder, an .rl bundle or a published name) until it pauses or is done",
    "resume": "answer a paused run, or retry the step a failed run stopped at",
    "compile": "check a program directory and write its .rl bundle",
    "export": "write a bundle's program directory back",
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
    "governance": "the server's governance queries over the runs",
    "config": "where this client points: the server, the decision model, the batch size",
    "server": "serve the catalog and the record of runs over HTTP",
    "db": "the Neo4j store directly (not on 0.9 yet)",
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
              "(`aip pull` caches one; a server is configured with `aip config --server URL`).")
        return 0
    command, rest = ALIASES.get(argv[0], argv[0]), argv[1:]
    if command in COMMANDS:
        return COMMANDS[command](rest)
    print(f"aip: unknown command {command!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
