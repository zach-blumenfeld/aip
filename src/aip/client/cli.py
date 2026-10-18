"""The `aip` command line entry point.

Local: validate, schema, runtime (the block, or `--skill` for the `aip-runtime` meta-skill),
skill (install both skills into the agents on this machine), info, run, resume, db, server.
Against a configured server (`aip config`, or `AIP_SERVER`): search, list, publish, get, pin,
retire, runs, governance, and `info`/`run` by name. A folder path always bypasses the server.

Every client command is a wrapper over the SDK (`aip.Client`, `docs/sdk.md`): it parses its
arguments, calls one SDK method, and prints the result. schema, runtime and skill are the
format's tooling, db loads Neo4j directly, and server serves: none of them is a client call.
"""

import argparse
import json
import sys
from pathlib import Path


def _emit(issues) -> tuple[int, int]:
    errors = warnings = 0
    for issue in issues:
        print(json.dumps(issue.to_record()), file=sys.stderr)
        if issue.severity == "warning":
            warnings += 1
        else:
            errors += 1
    return errors, warnings


def validate_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="aip validate", description="Validate an AIP skill folder.")
    parser.add_argument("skill_dir", type=Path, help="path to the skill folder (containing SKILL.md)")
    args = parser.parse_args(argv)

    result = _client().validate(args.skill_dir)
    errors, warnings = _emit(result.issues)
    suffix = f" ({warnings} warning(s) — see stderr)" if warnings else ""
    if result.valid:
        print(f"VALID: {args.skill_dir} (name: {result.name}){suffix}")
        return 0
    print(f"INVALID: {errors} error(s){suffix} — see stderr")
    return 1


def schema_command(argv: list[str]) -> int:
    from aip_spec import json_schema

    parser = argparse.ArgumentParser(prog="aip schema", description="Print the JSON Schema generated from the format models.")
    parser.add_argument("--write", type=Path, default=None, help="write to this path instead of stdout")
    args = parser.parse_args(argv)

    text = json.dumps(json_schema(), indent=2) + "\n"
    if args.write:
        args.write.write_text(text)
        print(f"wrote {args.write}")
    else:
        sys.stdout.write(text)
    return 0


def runtime_command(argv: list[str]) -> int:
    from aip_spec import runtime_text

    from aip.client import runtime_skill_text

    parser = argparse.ArgumentParser(prog="aip runtime", description="Print the AIP runtime block every authored skill carries "
                                     "at the top of its body; with --skill, the `aip-runtime` Agent Skill that tells an agent "
                                     "how to run published procedures through this client.")
    parser.add_argument("--skill", action="store_true", help="the `aip-runtime` meta-skill instead of the runtime block")
    parser.add_argument("--out", type=Path, default=None, metavar="DIR",
                        help="with --skill: write it as DIR/aip-runtime/SKILL.md (a skills directory)")
    parser.add_argument("--write", type=Path, default=None, help="write to this path instead of stdout")
    args = parser.parse_args(argv)
    if args.out is not None and not args.skill:
        parser.error("--out goes with --skill; use --write for the runtime block")
    text = runtime_skill_text() if args.skill else runtime_text()
    target = args.out / "aip-runtime" / "SKILL.md" if args.out is not None else args.write
    if target is not None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        print(f"wrote {target}")
    else:
        sys.stdout.write(text)
    return 0


def skill_command(argv: list[str]) -> int:
    """Install, list, or remove the two AIP skills: the `aip` authoring skill, bundled in
    `aip-spec`, and the `aip-runtime` meta-skill, bundled here. Agent detection is
    `aip_spec.agents`, the same catalog `aip-spec skill install` uses."""
    from aip_spec import agents, skill_dir
    from aip_spec.resources import SKILL_ENTRIES as AUTHORING_ENTRIES, SKILL_NAME as AUTHORING

    from aip.client import RUNTIME_SKILL, runtime_skill_dir

    names = [AUTHORING, RUNTIME_SKILL]
    parser = argparse.ArgumentParser(prog="aip skill", description=f"Install the AIP skills ({', '.join(names)}) "
                                     "into the agents on this machine.")
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("install", help="into every detected agent, one named agent, or a skills directory")
    p.add_argument("agent", nargs="?", help=f"one of: {', '.join(agents.AGENTS)}")
    p.add_argument("--path", type=Path, default=None, metavar="DIR", help="a skills directory; writes DIR/<skill>/ for each")
    sub.add_parser("list", help="supported agents, whether each is detected, and which skills are installed")
    p = sub.add_parser("remove", help="from one agent, or from every agent that has either skill")
    p.add_argument("agent", nargs="?")
    p.add_argument("--path", type=Path, default=None, metavar="DIR")
    args = parser.parse_args(argv)

    if args.action == "list":
        print(agents.table(names))
        return 0
    try:
        if args.action == "install":
            sources = [(skill_dir(), AUTHORING_ENTRIES), (runtime_skill_dir(), ("SKILL.md",))]
            for label, folder in agents.install(sources, args.agent, args.path):
                print(f"installed {folder.name} -> {folder}  ({label})")
            return 0
        removed = agents.remove(names, args.agent, args.path)
        for folder in removed:
            print(f"removed {folder}")
        if not removed:
            print(f"neither {' nor '.join(names)} is installed anywhere `aip skill list` looks")
        return 0
    except (KeyError, agents.NoAgentDetected) as exc:
        print(f"aip skill: {exc.args[0]}", file=sys.stderr)
        return 1


def _server():
    """The configured server, or None. One seam for tests to point at an in-process app."""
    from aip.client.server import configured

    return configured()


def _client():
    """The SDK client every command is a wrapper over, on `_server()`."""
    from aip.sdk import Client

    return Client.over(_server())


def _serving(call):
    """Run a client action. A server error becomes one line on stderr and exit 1; no server, or a
    name that is not a folder, exits with the message."""
    from aip.sdk import InvalidInput, NoServer, NotFound, ServerError

    try:
        return call()
    except ServerError as exc:
        print(f"aip: {exc}", file=sys.stderr)
        return 1
    except (NoServer, NotFound, InvalidInput) as exc:
        raise SystemExit(f"aip: {exc}") from exc


def info_command(argv: list[str]) -> int:
    from aip.sdk import InvalidSkill

    parser = argparse.ArgumentParser(prog="aip info", description="Describe a skill: what it does, the input it expects, and how it flows.")
    parser.add_argument("skill", metavar="skill_dir|name", help="a skill folder, or a published name (`name`, `name@rev`, `name@latest`)")
    parser.add_argument("--json", action="store_true", help="machine-readable description instead of the summary")
    parser.add_argument("--example-input", action="store_true", help="print only an example start input as JSON")
    args = parser.parse_args(argv)

    def go() -> int:
        try:
            info = _client().info(args.skill)
            if args.json:
                print(json.dumps(info.data, indent=2))
            elif args.example_input:
                print(json.dumps(info.example_input, indent=2))
            else:
                sys.stdout.write(info.summary())
        except InvalidSkill as exc:
            print(exc, file=sys.stderr)
            return 1
        return 0
    return _serving(go)


class _BadInput(ValueError):
    """`--input` is not a readable JSON object."""


def _read_input(spec: str | None) -> dict | None:
    """`--input path.json`, `--input -` for stdin, or None."""
    if spec is None:
        return None
    try:
        text = sys.stdin.read() if spec == "-" else Path(spec).read_text()
        data = json.loads(text)
    except (OSError, ValueError) as exc:
        raise _BadInput(f"--input {spec}: {exc}") from exc
    if not isinstance(data, dict):
        raise _BadInput(f"--input {spec}: must be a JSON object, got {type(data).__name__}")
    return data


def _outcome(call, debug: bool, progress: bool) -> int:
    """`run` and `resume`: whatever escapes the runner is still one error object on stdout, exit 1,
    with the traceback on stderr only under --debug (`docs/cli-json.md`). A skill or run that
    cannot be found, or an input that is not an object, is `invalid_input`."""
    from aip.client.runner import EXIT_ERROR, error_object
    from aip.sdk import AipError, ServerError

    try:
        return call()
    except Exception as exc:
        if debug:
            import traceback
            traceback.print_exception(exc, file=sys.stderr)
        error = ({"error": "invalid_input", "step": None, "message": str(exc), "missing": [], "invalid": []}
                 if isinstance(exc, (_BadInput, AipError)) and not isinstance(exc, ServerError) else error_object(exc))
        block = {**error, "run_id": None, "resumable": False}
        print(json.dumps(block) if progress else json.dumps(block, indent=2))
        return EXIT_ERROR


def _outcome_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--progress", action="store_true",
                        help="print one JSON line per completed step before the final object (itself one line)")
    parser.add_argument("--debug", action="store_true", help="print a traceback on stderr when the run fails")


def run_command(argv: list[str]) -> int:
    from aip.client.runner import Runner

    parser = argparse.ArgumentParser(prog="aip run", description="Run a procedure, pausing when the client must decide: "
                                     "a skill folder runs locally, a published name runs on the server. Prints one "
                                     "JSON object: paused or done (exit 0), or error (exit 1); see docs/cli-json.md.")
    parser.add_argument("skill", metavar="skill_dir|name")
    parser.add_argument("--input", "-i", help="JSON object for the start step; `-` reads stdin")
    parser.add_argument("--interactive", action="store_true", help="prompt on the terminal instead of pausing to a run file")
    parser.add_argument("--run-file", type=Path, default=None,
                        help="where to write the run file (default ~/.aip/runs/<run-id>.json; AIP_HOME moves it)")
    parser.add_argument("--workdir", type=Path, default=None,
                        help="the run's working directory, where its scripts read and write files (AIP_WORKDIR); "
                             "recorded in the run file so resume works from anywhere (default the current directory)")
    _outcome_flags(parser)
    args = parser.parse_args(argv)

    def go() -> int:
        client = _client()
        payload = _read_input(args.input)
        runner = Runner(None, interactive=args.interactive, progress=args.progress, debug=args.debug)
        if payload is None and args.interactive:
            payload = runner.start_input({"inputs": client.info(args.skill).inputs})
        return runner.show(lambda on_step, on_pause: client.run(
            args.skill, payload, workdir=args.workdir, run_file=args.run_file, on_step=on_step, on_pause=on_pause)).code
    return _outcome(go, args.debug, args.progress)


def resume_command(argv: list[str]) -> int:
    from aip.client.runner import RunFile, Runner

    parser = argparse.ArgumentParser(prog="aip resume", description="Continue a run, locally or on the server the run "
                                     "file names: answer its pause, or with no input retry the step that failed.")
    parser.add_argument("run", metavar="run_id|run_file",
                        help="the run id every outcome prints, or a run file's path")
    parser.add_argument("--input", "-i", help="JSON object answering the pause; `-` reads stdin")
    parser.add_argument("--interactive", action="store_true")
    _outcome_flags(parser)
    args = parser.parse_args(argv)

    def go() -> int:
        client = _client()
        payload = _read_input(args.input)
        runner = Runner(None, interactive=args.interactive, progress=args.progress, debug=args.debug)
        if payload is None and args.interactive:
            pause = RunFile.load(client.run_file(args.run)).pause
            if pause["kind"] not in ("error", "done"):
                payload = runner.ask(pause)
        return runner.show(lambda on_step, on_pause: client.resume(
            args.run, payload, on_step=on_step, on_pause=on_pause)).code
    return _outcome(go, args.debug, args.progress)


# ----------------------------------------------------------------------- catalog


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
            return 0
        if not hits:
            print("no matches")
            return 0
        for h in hits:
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
            print("no skills published")
            return 0
        width = max(len(r.name) for r in rows)
        for r in rows:
            flag = "  pinned" if r.pinned else ""
            print(f"{r.name.ljust(width)}  {r.resolves or '-'}  {len(r.revisions)} revision(s){flag}  {r.description or ''}".rstrip())
        return 0
    return _serving(go)


def publish_command(argv: list[str]) -> int:
    from aip.sdk import InvalidSkill

    parser = argparse.ArgumentParser(prog="aip publish", description="Validate a skill folder locally, upload it, and print `name@revision`.")
    parser.add_argument("skill_dir", type=Path)
    args = parser.parse_args(argv)

    def go() -> int:
        try:
            result = _client().publish(args.skill_dir)
        except InvalidSkill as exc:
            errors, _ = _emit(exc.validation.issues)
            print(f"INVALID: {errors} error(s) — not published", file=sys.stderr)
            return 1
        _emit(result.validation.issues)
        for w in result.warnings:
            print(json.dumps(w), file=sys.stderr)
        print(f"{result.name}@{result.revision}")
        return 0
    return _serving(go)


def get_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="aip get", description="Download a published revision losslessly to <out>/<name>/, "
                                     "verify every file against the manifest, and validate it.")
    parser.add_argument("ref", help="`name`, `name@rev`, or `name@latest`")
    parser.add_argument("--out", type=Path, default=Path("."), help="parent folder; the skill lands at <out>/<name>")
    args = parser.parse_args(argv)

    def go() -> int:
        fetched = _client().get(args.ref, args.out)
        errors, _ = _emit(fetched.validation.issues)
        if not fetched.validation.valid:
            print(f"wrote {fetched.path}, but it does not validate here ({errors} error(s))", file=sys.stderr)
            return 1
        print(f"wrote {fetched.path}")
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
    _, sep, revision = args.ref.partition("@")
    if not sep or not revision or revision == "latest":
        parser.error("retire takes `name@revision`")

    def go() -> int:
        retired = _client().retire(args.ref)
        print(f"retired {retired.name}@{retired.revision}")
        return 0
    return _serving(go)


def runs_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="aip runs", description="The server's runs, newest first; with a run id, that "
                                     "run's state and history (a local run's from its run file).")
    parser.add_argument("run_id", nargs="?", default=None)
    parser.add_argument("--name", default=None, help="only runs of this skill")
    parser.add_argument("--status", default=None, help="only runs with this status (paused, done, failed, ...)")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    def go() -> int:
        if args.run_id is not None:
            print(json.dumps(_client().run_record(args.run_id).data, indent=2))
            return 0
        rows = _client().runs(args.name, args.status, args.limit)
        if args.json:
            print(json.dumps([r.data for r in rows], indent=2))
            return 0
        if not rows:
            print("no runs")
            return 0
        for r in rows:
            print(f"{r.run_id}  {r.name}@{r.revision}  {r.status}  {r.steps} step(s)  {r.updated_at}")
        return 0
    return _serving(go)


def governance_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="aip governance", description="The server's governance queries; with a query, "
                                     "its rows as JSON.")
    parser.add_argument("query", nargs="?", default=None)
    parser.add_argument("--name", default=None, help="only this skill")
    parser.add_argument("--window", type=int, default=None, help="how many recent runs to look at")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    def go() -> int:
        rows = _client().governance(args.query, name=args.name, window=args.window, limit=args.limit)
        if args.query is None:
            width = max((len(q.query) for q in rows), default=0)
            for q in rows:
                print(f"{q.query.ljust(width)}  {q.description}")
            return 0
        print(json.dumps(rows, indent=2))
        return 0
    return _serving(go)


def config_command(argv: list[str]) -> int:
    from aip.sdk import configure

    parser = argparse.ArgumentParser(prog="aip config", description="Where the client points. With no flags, show it. "
                                     "AIP_SERVER and AIP_TOKEN override the file.")
    parser.add_argument("--server", default=None, help="the server URL")
    parser.add_argument("--token", default=None, help="the bearer token")
    parser.add_argument("--decision-model", default=None, metavar="KEY",
                        help="the TypeSafe API key this client resolves decisions with (TYPESAFE_API_KEY overrides; "
                             "an empty string forgets it). Without one, every decision pauses for you to answer")
    parser.add_argument("--clear", action="store_true", help="forget the server, token, and decision-model key")
    args = parser.parse_args(argv)
    writes = args.clear or any(v is not None for v in (args.server, args.token, args.decision_model))
    s = configure(args.server, args.token, args.decision_model, clear=args.clear)
    if args.clear:
        print(f"cleared {s.path}")
        return 0
    if writes:
        print(f"wrote {s.path}")
    if s.server is None:
        print(f"no server configured (local folders only); set AIP_SERVER or `aip config --server URL` ({s.path})")
    else:
        print(f"server: {s.server}  (from {s.source})")
        print(f"token:  {'set' if s.token_set else 'none'}")
    print(s.decision_model)
    return 0


def db_command(argv: list[str]) -> int:
    """`aip db load|list|export`: the Neo4j backend, 0.4 shape. Connection from NEO4J_* env or flags."""
    from aip.db.neo4j import Connection, export, list_skills, load

    connection = argparse.ArgumentParser(add_help=False)
    connection.add_argument("--uri", default=None, help="Neo4j URI; default $NEO4J_URI or neo4j://localhost:7687")
    connection.add_argument("--user", default=None, help="default $NEO4J_USERNAME or neo4j")
    connection.add_argument("--password", default=None, help="default $NEO4J_PASSWORD")
    connection.add_argument("--database", default=None, help="default $NEO4J_DATABASE or neo4j")

    parser = argparse.ArgumentParser(prog="aip db", description="Load skills into Neo4j losslessly, list them, export them back.")
    sub = parser.add_subparsers(dest="op", required=True)
    p_load = sub.add_parser("load", parents=[connection], help="validate a skill folder and write it to the database")
    p_load.add_argument("skill_dir", type=Path)
    sub.add_parser("list", parents=[connection], help="skills in the database, newest revision first")
    p_export = sub.add_parser("export", parents=[connection], help="rebuild a skill folder from the database, byte for byte")
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
    """`aip server`: the HTTP API over the filesystem or Neo4j backend. Scripts run in this process."""
    from aip.server.config import (CONFIG_ENV, CONFIG_FILE, DEFAULT_ROOT, ENV_FILE, EXAMPLE, ConfigError, apply_config,
                                   find_config, load_env_file, read_config, user_config_path, write_example)

    parser = argparse.ArgumentParser(prog="aip server", description="Serve the AIP catalog and execution API.",
                                     epilog="Configuration, highest precedence first: these flags, the environment "
                                            "(NEO4J_*; a .env file is loaded into it), the config file, "
                                            "defaults. `--example-config` prints a complete file. The server runs no "
                                            "scripts and holds no decision-model key: clients run scripts and resolve "
                                            "decisions (`aip config --decision-model`), and the server records them. "
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
    parser.add_argument("--inspector", nargs="?", const=True, default=None, metavar="DIR",
                        help="also serve the aip-inspector web client at /inspector/, from the bundle shipped in this "
                             "package or from DIR (a built `dist/`)")
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
        from aip.server.app import INSPECTOR_DIR, create_app
    except ImportError:
        print("aip server needs the server extra: `uv sync --extra server` (or `pip install 'aip[server]'`)", file=sys.stderr)
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
              "and execute code here", file=sys.stderr)
    inspector = None if args.inspector is None else (INSPECTOR_DIR if args.inspector is True else Path(args.inspector))
    app = create_app(backend, tokens=tokens, localhost_open=not args.no_localhost, inspector=inspector)
    if loaded:
        print(f"aip server: configured from {', '.join(loaded)}", file=sys.stderr)
    print(f"aip server: {where}; http://{args.host}:{args.port}", file=sys.stderr)
    if tokens:
        print(f"aip server: {len(tokens)} bearer token(s); loopback clients "
              f"{'need one too' if args.no_localhost else 'need none'}", file=sys.stderr)
    if inspector is not None:
        if (inspector / "index.html").is_file():
            print(f"aip server: inspector at http://{args.host}:{args.port}/inspector/ (from {inspector})", file=sys.stderr)
        else:
            print(f"aip server: warning: no inspector bundle in {inspector}; /inspector/ answers 404 until "
                  "`npm run build && npm run sync` in the aip-inspector repo", file=sys.stderr)
    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)
    finally:
        if hasattr(backend, "close"):
            backend.close()
    return 0


COMMANDS = {
    "validate": validate_command,
    "schema": schema_command,
    "runtime": runtime_command,
    "skill": skill_command,
    "info": info_command,
    "run": run_command,
    "resume": resume_command,
    "search": search_command,
    "list": list_command,
    "publish": publish_command,
    "get": get_command,
    "pin": pin_command,
    "retire": retire_command,
    "runs": runs_command,
    "governance": governance_command,
    "config": config_command,
    "db": db_command,
    "server": server_command,
}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: aip <command> [args]\n\ncommands:\n  " + "\n  ".join(COMMANDS)
              + "\n\n`info` and `run` take a skill folder, or a published name when a server is configured "
              "(`aip config`, or AIP_SERVER).")
        return 0
    command, rest = argv[0], argv[1:]
    if command in COMMANDS:
        return COMMANDS[command](rest)
    print(f"aip: unknown command {command!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
