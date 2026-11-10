# Where everything is

For the agent implementing a milestone of the 0.9 plan (issue #1 on `zach-blumenfeld/aip-dev`).
Every pointer here was checked on 2026-11-09. If one is dead, fix it here in the same commit.

## This repository

- You are in a **private mirror** of the public `zach-blumenfeld/aip`. The worktree is
  `~/dev/aip-0.9` on branch `release-0.9.0`; its push remote is `dev` (the mirror). `origin` is
  the public repo: never push there (AGENTS.md, "This is the private 0.9 mirror").
- **The 0.8 code you are replacing is in this same tree**: the runtime under `src/aip/`, the server
  under `src/aip/server/`, the Neo4j backend at `src/aip/server/backends/neo4j.py`, the skills
  under `skills/`, the examples under `examples/`. The language is `src/aip/compiler/` (until L5,
  2026-11-09, it was the separate package `aip-spec` under `packages/`; the old format's prose
  is `docs/specification-0.8.md`).
  AGENTS.md's repo map describes it. Read the piece you replace before replacing it; the records,
  the governance queries and the HTTP contract carry over in shape.
- **The server is on the new store since S1** (2026-11-09): `src/aip/server/store.py` and the two
  backends, described in `docs/server-design.md`. Since S2 a client set to `aip config server local`
  starts one for itself (`src/aip/client/local.py`: port 8247, the default store file, stops when
  idle; `aip server --local --stop` stops it, and `AIP_LOCAL_PORT`, `AIP_LOCAL_DATA` move it for a
  proof that must not touch the real store). The branch `cypherlite-backend` on the mirror was
  the 0.8 attempt at a Relate backend and is only history now. The server's tests want a Neo4j to run their
  second half: on this machine the container `aip-test-neo4j` (bolt `localhost:17687`, user
  `neo4j`; the password is in its `NEO4J_AUTH`) is kept for that, and the suite deletes every node
  the store writes there, so never point `NEO4J_URI` at a database that matters.
- **The language**: `docs/language/spec.md` (and `docs/language/queries.md`, the Cypher queries over a bundle) (the law), `docs/language/runtime.md`,
  `docs/language/limitations.md`, `docs/language/no-expressions.md`, `docs/language/end-to-end.md`,
  `docs/language/plan-questions.md` (the 26 decisions and why). Programs under
  `examples/language/`. The VS Code grammar under `editors/vscode`.
- The design archive is the private repo `zach-blumenfeld/aip-lang` (copied at its commit
  9845671). Nothing there is newer than this tree.

## The console

**It is `console/` in this repository since C1** (2026-11-09, plan open item 13): `git subtree
add --prefix=console dev-console console-0.9.0` brought it with its history from
`zach-blumenfeld/aip-console-dev` (the private mirror of `zach-blumenfeld/aip-console`; this
checkout's remote `dev-console`, and the local checkout `~/dev/aip-inspector`), whose commit
f30ed95 is the last there. That mirror is the archive now: nothing newer is in it, and console
work happens here. `console/AGENTS.md` describes the launcher, the card canvas, the API client
and the tests; the e2e harness runs this checkout's `aip` (`AIP_REPO`, default `..`). It stays
its own npm package (`aip-console`) with its own version, changelog and release workflow
(`.github/workflows/console-release.yml`, tag `console-vX.Y.Z`), and `pyproject.toml` keeps
`console/` out of the sdist, so nothing of it reaches PyPI. Its tests need Node 24 and npm:
`npm install && npm run typecheck && npm test && npm run e2e` in `console/`.

## Relate (formerly CypherLite)

Embedded property-graph engine with Cypher, Neo4j Labs, Apache 2.0. **Unreleased and private;
nothing mentioning it leaves the mirrors.**

| What | Where | Note |
|---|---|---|
| Source and releases | `github.com/neo4j-labs/cypherlite` | visibility is *internal*: web fetches 404; `gh api repos/neo4j-labs/cypherlite/...` works with Zach's login. Moving to `github.com/relatedb/relate` (404 today). |
| Pinned release | **v0.16.1**, 2026-11-04 | the last release under the old name. Wheels: `neo4j_cypherlite-0.16.1-cp39-abi3-{macosx_10_12_x86_64, macosx_11_0_arm64, manylinux2014_x86_64, manylinux2014_aarch64, win_amd64}.whl` on the release's assets. **Install with `scripts/install-relate.sh`** (into `.venv`, or into the environment it is given): it fetches the platform's wheel through the GitHub API (`gh` logged in or `GH_TOKEN`; the plain download URL answers 404 while the repository is internal), checks its sha256 against the five pinned in the script (the release's `SHA256SUMS` covers only the CLI binaries), caches it under `~/.cache/aip/relate/`, and runs `uv pip install`. Not declared in any `pyproject.toml`: `uv lock` would have to fetch it and cannot (L3's note on open item 2). **Import name `cypherlite`.** CI installs it only when the secret `RELATE_GH_TOKEN` is set; otherwise the bundle tests skip. |
| The rename | main branch | `surfaces/relate-python/pyproject.toml` is already `relate-db`, module `relate`; the CLI is `relate`; bundles are `.rl`. The next release ships under those names. `aip/compiler/relate.py` is the one module that imports the engine (`relate`, else `cypherlite`) and names bundles `.rl`; since v0.16.1 recognises its single-file form by the `.cl` suffix alone, it writes beside the target as `<name>.rl.tmp.cl` and renames, and opens an `.rl` through a temporary `.cl` link. Both go when the rename ships. |
| The CLI binary | release assets `cypherlite-{darwin,linux}-{arm64,amd64}`, `cypherlite-windows-amd64.exe` | in `SHA256SUMS`. `cypherlite query --database x.rl "..."` does not open an `.rl` at v0.16.1 (it is read as a directory); copy or link the file to `x.cl` first, or use `aip.compiler.relate.open` from Python. |
| Docs site | https://neo4j-labs.github.io/cypherlite/ and https://relatedb.ai/ | public. `llms.txt` at either root is the whole reference in one file. |
| Reference docs, snapshotted at v0.16.1 | `docs/language/relate/` in this tree | `python-library.md` (connect, execute, parameters, `read_only=True`, Arrow), `storage-formats.md` (directory, `.cl`/`.rl` single file, codecs, format version), `cli-flags.md` (`--load`, `--read-only`, `clone`, `pull`, `push`, `serve`), `cypher-syntax.md`, `limitations.md`, `llms.txt`. Prefer these to live fetches; refresh them when the pin moves. |
| Repo docs not snapshotted | `docs/adr/`, `docs/api/python/`, `docs/guides/backup-restore.md`, `docs/engine-architecture.md` | via `gh api repos/neo4j-labs/cypherlite/contents/<path>?ref=v0.16.1`, base64 in `.content`. |
| Local wheel cache | `~/.cache/uv/archive-v0/rTrDDOAv8O-PEvqN/` | **CypherLite 0.13.0, stale.** Do not use it as the reference. The 0.16.1 wheels `install-relate.sh` fetched are under `~/.cache/aip/relate/`. |
| Python API, verified at v0.16.1 | `python-library.md` | `cypherlite.connect(path, read_only=False)`; a `.cl` path is one file, any other path a directory; `read_only=True` refuses writes (`WriteOnReadOnlyAccessDatabase`); `properties(n)`, `labels(n)`, `type(e)`, `UNWIND $rows ... SET n = r` with map parameters, list and string properties (tabs, newlines and NUL included) all work; no map-valued properties, no binary scalar (bytes are stored base64). |
| Concurrency rule | `python-library.md`, "read_only" | one writer per store; `connect(path, read_only=True)` opens a frozen view beside a writer; `relate serve --read-only` likewise. The server is the only writer of its store (plan question 5). A connection may only be used on the thread that opened it (`ProgrammingError` otherwise), so the server's backend gives it one worker thread. |
| The server's store file | `aip.compiler.relate.store`, `store_file` | asked for as `store.rl`, kept as `store.cl` while the pinned release names its single-file form by that suffix: the link `open()` makes for a bundle would not survive a long-lived writer. When the rename ships, rename the file. Verified at v0.16.1 for the store's Cypher: `MERGE`, `SET n = $map`, `UNWIND` of maps, `OPTIONAL MATCH`, `collect(DISTINCT ...)`, `CASE`, label predicates, composite indexes, uniqueness constraints with `IF NOT EXISTS`, explicit transactions. |

## The decision model

TypeSafe. The resolver is `src/aip/model/typesafe.py` (`TypeSafeResolver`, since R2; `typesafe_sdk`:
`TypeSafeClient`, `Noul`, `Choice`, `Score`; dependency `typesafe-sdk>=0.7.1` in `pyproject.toml`).
`src/aip/client/resolver.py` is the 0.8 one, dead until R3 rewrites the client around the new
resolver and the key in `aip config`. Answer shapes the language expects are spec 2.4; the mapping
from the SDK's `NoulAnswer`, `ChoiceAnswer`, `ScoreAnswer` is in `typesafe.answer_object`: `value`,
`confidence` (`|2·noul−1|` for noul, the SDK's own for the others), `probabilities`, and `score` for
a score question. Docs: https://docs.typesafe.ai/ (returned 308 to its new home on 2026-11-09;
follow the redirect). The key lives in `aip config`, never in the repo. Tests use the scripted
resolver and a fake client (`tests/test_typesafe.py`), so no key is needed for any proof before D1.

## The skill and `make_procedure` (since K1, 2026-11-09)

- **One skill, `skills/aip/`**: `SKILL.md` (find, run, answer a pause, write) and
  `references/language.md` (the language on one page). `aip skill install [agent | --path DIR]`
  writes it; `aip-runtime` and `aip-compile` are gone from the tree (they are on public `main`
  and in this repository's history), and `install` removes the folders an earlier `aip` recorded.
  Zach reviews this skill line by line: change it in small diffs.
- **`make_procedure`** is `examples/language/make_procedure/` and ships compiled as
  `src/aip/server/bundles/make_procedure.rl`, which every server publishes on its first start.
  The `.rl` is a binary committed to the repository; when the folder changes, or the graph the
  compiler derives does, compile it again with the command in `src/aip/server/builtins.py`
  (`tests/test_make_procedure.py` fails until you do). Its `assets/language.md` is a copy of the
  skill's language page, held equal by `tests/test_skill.py`; the page is interpolated into the
  procedure's prompts, so it must not contain `{name}`, `{description}`, `{materials}`, `{path}`
  or `{diagnostics}` in braces.
- Its `compile` step imports `aip.compiler` from the interpreter that runs `aip` (scripts are
  launched with `sys.executable`), so it needs no `aip` on `PATH` and no Relate.

## Agent frameworks (track D2)

`aip mcp` is `src/aip/mcp.py` since M1 (2026-11-09), described in `docs/mcp.md`, on the MCP
Python SDK **2.x** (`mcp` 2.3.0 in `uv.lock`): the server class is `mcp.server.mcpserver.MCPServer`
and the client `mcp.Client`; 1.x's `FastMCP` and its examples on the web no longer import. The
2026-07-28 protocol has no `initialize` handshake and makes the client's info optional, so read
the client's name per request (`ctx.session.client_params`), as `aip.mcp.client_name` does.
`examples/agents/mcp-smoke/run.py` is a working client to copy from.

Each is reached over MCP (`aip mcp`, stdio). Use each framework's own MCP client; their docs are
public and move fast, so read them at D2 time: Google ADK (`google-adk`, MCPToolset), LangGraph
(`langchain-mcp-adapters`), Microsoft Agent Framework (`agent-framework`, MCP tools), Strands
(`strands-agents`, MCP client). Claude Code and Codex CLI take an MCP server from their config
files.

## Process

- Plan: https://github.com/zach-blumenfeld/aip-dev/issues/1. Tick, comment, commit, push to `dev`.
- Public plan issues for context on how 0.7 and 0.8 were run: `gh issue view 18 -R
  zach-blumenfeld/aip` and `19` (19 is superseded by this plan; do not edit it).
- Zach's constraints that are not in code: the design conversation stays in his `~/Documents` and
  never enters a repo; keyword lists are maintained only in the spec's glossary (the console
  colours `procedure.aip` from the extension's grammar for that reason, and keeps no list of its
  own); the console stays its own npm package (it was to stay its own repository too, until plan
  open item 13 moved it into `console/` here).
