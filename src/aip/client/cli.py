"""The `aip` command line entry point.

Local: validate, schema, runtime (the block, or `--skill` for the `aip-runtime` meta-skill),
skill (install both skills into the agents on this machine), info, run, resume, db, server.
Against a configured server (`aip config`, or `AIP_SERVER`): search, list, publish, get, pin,
retire, and `info`/`run` by name. A folder path always bypasses the server.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


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
    from aip_spec import validate_skill

    parser = argparse.ArgumentParser(prog="aip validate", description="Validate an AIP skill folder.")
    parser.add_argument("skill_dir", type=Path, help="path to the skill folder (containing SKILL.md)")
    args = parser.parse_args(argv)

    loaded, issues = validate_skill(args.skill_dir)
    errors, warnings = _emit(issues)
    suffix = f" ({warnings} warning(s) — see stderr)" if warnings else ""
    if errors == 0 and loaded is not None:
        print(f"VALID: {args.skill_dir} (name: {loaded.frontmatter.get('name')}){suffix}")
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


def _example_input(items) -> dict:
    from aip.model.types import example_input

    return example_input({item.name: item.type.value for item in items})


def _inputs_table(items) -> str:
    if not items:
        return "  (none)\n"
    width = max(len(i.name) for i in items)
    return "".join(f"  {i.name.ljust(width)}  {i.type.value:8}  {i.description or ''}".rstrip() + "\n" for i in items)


def describe_skill(loaded) -> str:
    """Human-readable summary of a skill: what it does, what to give it, how it flows."""
    fm, spec = loaded.frontmatter, loaded.spec
    start = spec.start
    lines = [f"{fm['name']}  (AIP {fm.get('metadata', {}).get('aip-version', '?')})", "", fm.get("description", ""), ""]
    lines += ["PURPOSE", "  " + " ".join(spec.purpose.split()), ""]
    lines += ["TRIGGER WHEN"] + [f"  - {t}" for t in spec.trigger_when]
    if spec.do_not_use_when:
        lines += ["DO NOT USE WHEN"] + [f"  - {t}" for t in spec.do_not_use_when]
    lines += ["", f"START INPUT  (step `{start.name}`, {start.kind})", _inputs_table(start.inputs).rstrip(), "",
              "  example start.json:", "  " + json.dumps(_example_input(start.inputs)), "",
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


def _server():
    """The configured server, or None. One seam for tests to point at an in-process app."""
    from aip.client.server import configured

    return configured()


def _target(arg: str) -> tuple[str, Any]:
    """`("folder", Path)` when `arg` is a skill folder on disk, else `("name", Server)` when a
    server is configured. A folder never goes through the server."""
    path = Path(arg)
    if path.is_dir() or path.exists():
        return "folder", path
    server = _server()
    if server is None:
        raise SystemExit(f"aip: {arg!r} is not a skill folder, and no server is configured to look it up by name "
                         "(set AIP_SERVER or run `aip config --server URL`)")
    if "/" in arg or "\\" in arg:
        raise SystemExit(f"aip: no such folder {arg!r}")
    return "name", server


def _remote_skill(server, ref: str):
    """A `LoadedSkill` built from the published SKILL.md, so `describe_skill` renders it as for a folder."""
    from aip_spec.skill import LoadedSkill, parse_skill_md, parse_spec
    import tempfile

    text = server.file(ref, "SKILL.md").decode("utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        md = Path(tmp) / "SKILL.md"
        md.write_text(text)
        doc, issues = parse_skill_md(md)
    if doc is None:
        raise SystemExit(f"aip: the server's SKILL.md for {ref} did not parse: " + "; ".join(i.message for i in issues))
    spec, issues = parse_spec(doc.yaml_text, "SKILL.md")
    if spec is None:
        raise SystemExit(f"aip: the server's SKILL.md for {ref} did not parse: " + "; ".join(i.message for i in issues))
    return LoadedSkill(skill_dir=Path(ref), frontmatter=doc.frontmatter, spec=spec)


def info_command(argv: list[str]) -> int:
    from aip.spec import load_skill

    parser = argparse.ArgumentParser(prog="aip info", description="Describe a skill: what it does, the input it expects, and how it flows.")
    parser.add_argument("skill", metavar="skill_dir|name", help="a skill folder, or a published name (`name`, `name@rev`, `name@latest`)")
    parser.add_argument("--json", action="store_true", help="machine-readable description instead of the summary")
    parser.add_argument("--example-input", action="store_true", help="print only an example start input as JSON")
    args = parser.parse_args(argv)
    kind, where = _target(args.skill)
    if kind == "name":
        def remote() -> int:
            if args.json:
                print(json.dumps(where.info(args.skill), indent=2))
            elif args.example_input:
                print(json.dumps(where.info(args.skill)["example_input"], indent=2))
            else:
                sys.stdout.write(describe_skill(_remote_skill(where, args.skill)))
            return 0
        return _serving(remote)
    try:
        loaded = load_skill(where)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    if args.example_input:
        print(json.dumps(_example_input(loaded.spec.start.inputs), indent=2))
        return 0
    if args.json:
        from aip.spec.loader import build_procedure
        print(json.dumps(build_procedure(loaded).describe(), indent=2))
        return 0
    sys.stdout.write(describe_skill(loaded))
    return 0


def _read_input(spec: str | None) -> dict | None:
    """`--input path.json`, `--input -` for stdin, or None."""
    if spec is None:
        return None
    text = sys.stdin.read() if spec == "-" else Path(spec).read_text()
    data = json.loads(text)
    if not isinstance(data, dict):
        raise SystemExit("aip: input must be a JSON object")
    return data


def _thresholds(pairs: list[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for pair in pairs:
        name, _, value = pair.partition("=")
        if not name or not value:
            raise SystemExit(f"aip: --threshold expects name=value, got {pair!r}")
        out[name] = float(value)
    return out


def run_command(argv: list[str]) -> int:
    from aip.client.backend import HttpBackend, LocalBackend
    from aip.client.runner import Runner

    parser = argparse.ArgumentParser(prog="aip run", description="Run a procedure, pausing when the client must decide: "
                                     "a skill folder runs locally, a published name runs on the server.")
    parser.add_argument("skill", metavar="skill_dir|name")
    parser.add_argument("--input", "-i", help="JSON object for the start step; `-` reads stdin")
    parser.add_argument("--interactive", action="store_true", help="prompt on the terminal instead of pausing to a run file")
    parser.add_argument("--run-file", type=Path, default=None, help="where to write the run file on pause")
    parser.add_argument("--threshold", action="append", default=[], metavar="NAME=VALUE", help="override a decision threshold")
    args = parser.parse_args(argv)
    kind, where = _target(args.skill)
    if kind == "name":
        backend = HttpBackend(where, name=args.skill)
    else:
        try:
            backend = LocalBackend(where)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 1
    runner = Runner(backend, Path(args.skill), run_file=args.run_file, interactive=args.interactive)
    return _serving(lambda: runner.start(_read_input(args.input), _thresholds(args.threshold)).code)


def resume_command(argv: list[str]) -> int:
    from aip.client.runner import RunFile, Runner, backend_for
    from aip.client.server import settings

    parser = argparse.ArgumentParser(prog="aip resume", description="Continue a paused run, locally or on the server the run file names.")
    parser.add_argument("run_file", type=Path)
    parser.add_argument("--input", "-i", help="JSON object answering the pause; `-` reads stdin")
    parser.add_argument("--interactive", action="store_true")
    args = parser.parse_args(argv)
    run = RunFile.load(args.run_file)
    configured = settings()
    token = configured["token"] if run.server and configured["server"] == run.server else None
    backend = backend_for(run, token=token, session=_session_for(run.server))
    runner = Runner(backend, Path(run.skill_dir), run_file=args.run_file, interactive=args.interactive)
    return _serving(lambda: runner.resume(run, _read_input(args.input)).code)


def _session_for(url: str | None):
    """The configured server's session when the run file points at that server (tests inject one)."""
    if url is None:
        return None
    server = _server()
    return server._session if server is not None and server.url == url.rstrip("/") else None


def _serving(call):
    """Run a client action; a server error becomes one line on stderr and exit 1."""
    from aip.client.server import ServerError

    try:
        return call()
    except ServerError as exc:
        print(f"aip: {exc}", file=sys.stderr)
        return 1


# ----------------------------------------------------------------------- catalog


def _require_server():
    server = _server()
    if server is None:
        raise SystemExit("aip: no server configured (set AIP_SERVER or run `aip config --server URL`)")
    return server


def search_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="aip search", description="Find published procedures by what they do; the ranking is the server's.")
    parser.add_argument("query")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    server = _require_server()

    def go() -> int:
        hits = server.search(args.query, args.limit)
        if args.json:
            print(json.dumps(hits, indent=2))
            return 0
        if not hits:
            print("no matches")
            return 0
        for h in hits:
            print(f"{h['name']}@{h['revision']}  {h['score']:.3f}  {h.get('description') or ''}".rstrip())
        return 0
    return _serving(go)


def list_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="aip list", description="Every published name with the revision it resolves to.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    server = _require_server()

    def go() -> int:
        rows = server.list()
        if args.json:
            print(json.dumps(rows, indent=2))
            return 0
        if not rows:
            print("no skills published")
            return 0
        width = max(len(r["name"]) for r in rows)
        for r in rows:
            live = [v for v in r["revisions"] if not v.get("retired")]
            resolves = r.get("pinned") or r.get("latest") or (live[0]["revision"] if live else "-")
            flag = "  pinned" if r.get("pinned") else ""
            print(f"{r['name'].ljust(width)}  {resolves}  {len(r['revisions'])} revision(s){flag}  {r.get('description') or ''}".rstrip())
        return 0
    return _serving(go)


def publish_command(argv: list[str]) -> int:
    from aip.spec import validate_skill

    parser = argparse.ArgumentParser(prog="aip publish", description="Validate a skill folder locally, upload it, and print `name@revision`.")
    parser.add_argument("skill_dir", type=Path)
    args = parser.parse_args(argv)
    server = _require_server()
    loaded, issues = validate_skill(args.skill_dir)
    errors, _ = _emit(issues)
    if errors or loaded is None:
        print(f"INVALID: {errors} error(s) — not published", file=sys.stderr)
        return 1

    def go() -> int:
        result = server.publish(args.skill_dir)
        for w in result.get("warnings", []):
            print(json.dumps(w), file=sys.stderr)
        print(f"{result['name']}@{result['revision']}")
        return 0
    return _serving(go)


def get_command(argv: list[str]) -> int:
    from aip.spec import validate_skill

    parser = argparse.ArgumentParser(prog="aip get", description="Download a published revision losslessly to <out>/<name>/, "
                                     "verify every file against the manifest, and validate it.")
    parser.add_argument("ref", help="`name`, `name@rev`, or `name@latest`")
    parser.add_argument("--out", type=Path, default=Path("."), help="parent folder; the skill lands at <out>/<name>")
    args = parser.parse_args(argv)
    server = _require_server()

    def go() -> int:
        target = server.download(args.ref, args.out)
        loaded, issues = validate_skill(target)
        errors, _ = _emit(issues)
        if errors or loaded is None:
            print(f"wrote {target}, but it does not validate here ({errors} error(s))", file=sys.stderr)
            return 1
        print(f"wrote {target}")
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
    server = _require_server()

    def go() -> int:
        server.pin(args.name, None if args.clear else args.revision)
        print(f"{args.name} pin cleared" if args.clear else f"{args.name} -> {args.revision}")
        return 0
    return _serving(go)


def retire_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="aip retire", description="Stop a name resolving to a revision (kept for the runs that reference it).")
    parser.add_argument("ref", help="`name@revision`")
    args = parser.parse_args(argv)
    name, sep, revision = args.ref.partition("@")
    if not sep or not revision or revision == "latest":
        parser.error("retire takes `name@revision`")
    server = _require_server()

    def go() -> int:
        server.retire(name, revision)
        print(f"retired {name}@{revision}")
        return 0
    return _serving(go)


def config_command(argv: list[str]) -> int:
    from aip.client.server import config_path, load_config, save_config, settings

    parser = argparse.ArgumentParser(prog="aip config", description="Where the client points. With no flags, show it. "
                                     "AIP_SERVER and AIP_TOKEN override the file.")
    parser.add_argument("--server", default=None, help="the server URL")
    parser.add_argument("--token", default=None, help="the bearer token")
    parser.add_argument("--clear", action="store_true", help="forget the server and token")
    args = parser.parse_args(argv)
    if args.clear:
        path = save_config({})
        print(f"cleared {path}")
        return 0
    if args.server is not None or args.token is not None:
        config = load_config()
        if args.server is not None:
            config["server"] = args.server.rstrip("/")
        if args.token is not None:
            config["token"] = args.token
        path = save_config(config)
        print(f"wrote {path}")
    s = settings()
    if s["server"] is None:
        print(f"no server configured (local folders only); set AIP_SERVER or `aip config --server URL` ({config_path()})")
        return 0
    print(f"server: {s['server']}  (from {s['source']})")
    print(f"token:  {'set' if s['token'] else 'none'}")
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
                                   decision_model_status, find_config, load_env_file, read_config,
                                   user_config_path, write_example)

    parser = argparse.ArgumentParser(prog="aip server", description="Serve the AIP catalog and execution API.",
                                     epilog="Configuration, highest precedence first: these flags, the environment "
                                            "(NEO4J_*, TYPESAFE_*; a .env file is loaded into it), the config file, "
                                            "defaults. `--example-config` prints a complete file. Decision steps are "
                                            "answered by TypeSafe when TYPESAFE_API_KEY (or decision_model.api_key) is "
                                            "set; otherwise every decision pauses for the client. Publishing is code "
                                            "execution on this server: scripts run here with its privileges. Without "
                                            "--token the server is open; keep --host on localhost.")
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
        print(f"wrote {target}\nedit it (the decision model key, the backend), then run: aip server")
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
    print(f"aip server: {decision_model_status()}", file=sys.stderr)
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
