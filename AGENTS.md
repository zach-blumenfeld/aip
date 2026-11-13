# AGENTS.md

Instructions for AI agents working **on** this repository. If you are an agent being asked to
*use* AIP, read `skills/aip/SKILL.md` (running a procedure, and writing one) instead.

## What this repo is

The Agent Instruction Protocol (AIP): a language for procedures that an agent runs step by step,
the compiler that turns a procedure into a bundle, and the runtime that executes it. One Python
package, `agent-instruction-protocol` (`src/aip/`): the `aip` command, the Python SDK, the
compiler (`aip.compiler`: parser, checker, formatter, graph, bundle), the engine (`aip.model`),
`aip server` with its backends, and the skills. The distribution name is
`agent-instruction-protocol` (PyPI blocks `aip` as a look-alike of an existing project); its
module and command are `aip`. Until 0.9 the language was a second package, `aip-spec`, in a uv
workspace under `packages/`; it folded in at plan milestone L5 (2026-11-09) and the `aip-spec`
distribution stays at 0.8 on PyPI with no further release. The web console, the npm package
`aip-console`, is `console/` in this repository since plan milestone C1 (2026-11-09; it was the
repository [aip-console](https://github.com/zach-blumenfeld/aip-console) through 0.8, and its
history came with it): its own npm version, changelog and release workflow, and nothing of it in
the Python build. `console/AGENTS.md` says what differs there.

## The 0.9 branch

0.9 is built on branch `release-0.9.0` of this repository. From 2026-11-08 to 2026-11-11 it was
built in the private mirror `zach-blumenfeld/aip-dev` (now archived) because Relate, the engine a
bundle is written in, was unannounced; Relate was announced on 2026-11-11 (https://neo4j.com/press-releases/announcing-relate-by-neo4j/)
and the branch moved here with its history. Rules:

- **The 0.9 plan is issue #29 on this repository** (https://github.com/zach-blumenfeld/aip/issues/29), in the format the 0.7 and 0.8 plans used.
  One milestone per session, run its proof, tick it, comment, commit, push `release-0.9.0` to `origin`.
- **Start with `docs/language/sources.md`**: where the old code, the console, Relate's docs and wheels, and the
  decision model live, with what is stale. Then the plan issue.
- **The language lives under `docs/language/`** (the spec, runtime requirements, limitations, why
  there are no expressions, the end-to-end scenes, the settled plan questions), its programs under
  `examples/language/`, the VS Code extension under `editors/vscode`. They came from the private
  `aip-lang` repository on 2026-11-08 (its commit 9845671); that repository is the design
  archive.
- **`main` keeps moving** with 0.8 fixes. Merge `main` into `release-0.9.0` when it does; the
  release PR (D4) merges the other way.

## Repo map

| Path | What's there |
|---|---|
| `pyproject.toml` | the one package, `agent-instruction-protocol`; its `[tool.hatch.build.targets.wheel.force-include]` puts `examples/` and `skills/aip/` into the wheel under `aip/compiler/`; `testpaths` is `tests` |
| `src/aip/client/` | the `aip` command (`cli.py`, a thin wrapper over the SDK), `config.py` (the per-user config: server, token, decision-model key, batch, `aip agent`'s model; the identity from `AIP_AGENT`/`AIP_SESSION`), `bundles.py` (the bundle cache every run runs from, `~/.aip/bundles/<id>.rl`, and the refs a catalog name resolved to), `local.py` (the local server `aip config server local` points at: started by the first request that finds none, stopped when idle), `runs.py` (run files and their listing, the outcome objects of `docs/cli-json.md`, the `--progress` lines, the step table `aip runs <id>` prints), `server.py` (the HTTP client; its docstring lists every call the server must answer, the contract S1 implements) |
| `src/aip/model/` | the execution engine: `procedure.py` reads a bundle's graph behind a Relate connection (one Cypher query per thing a step or loop needs; `Procedure.load(bundle)` puts a verified bundle in an in-memory store), `steps.py` is what each step kind does (and the loop head, the batched request), `engine.py` the run loop (`Engine`, `Run`, loop frames, `For` passes as cursors run in batches, pauses, the record), `types.py` the type checks and the error kinds, `answers.py` the answer objects of spec 2.4, `resolver.py` the decision-model interface and the scripted test resolver, `typesafe.py` the TypeSafe resolver, `cache.py` the files unpacked once per bundle id, `environment.py` the `Requires` check and the script cap (`script_timeout`, `AIP_SCRIPT_TIMEOUT`, 300 s). The engine never calls a chat model; `tests/test_scripts.py` holds `scripts=False` and the script cap |
| `src/aip/server/` | `aip server` (`docs/server-design.md`): `store.py` is the store, bundles, revisions, drafts and runs in one graph and the one body of Cypher over it; `backends/` the two adapters it runs through (`relate.py`, one file, the default; `neo4j.py`); `app.py` the FastAPI app, which never runs a procedure; `audit.py` the named audit queries (`aip audit`) and the stored ones; `builtins.py` the hook that publishes the bundles shipped in the package, and `bundles/` the four that ship, `make_procedure.rl`, `build_procedure.rl`, `edit_procedure.rl` and `assist.rl` (what `aip agent` drives), each compiled from its folder under `examples/language/` (its docstring has the command to run when a folder changes); `search.py` BM25; `config.py` the TOML and `.env` |
| `src/aip/agent.py`, `src/aip/chat.py` | `aip agent` (`docs/agent.md`): a chat model outside the run drives the built-in `assist` (`examples/language/assist`), `run` then one model call and one `resume` per pause, no tools. `agent.py` is that loop and nothing else (under 40 lines, three functions; a session is read from the record, `--session` or `AIP_SESSION`). `chat.py` is the one Chat Completions client and the plumbing around it (the message a pause becomes, parsing, refusals, the work reported). `Client.ask` is its SDK call, the MCP tool `agent` its MCP one. `tests/test_agent.py` drives it with a scripted stand-in model: the module's size, sessions from the record, refusals, a child run's pause answered by `plan`, and `act.py`'s six verbs |
| `src/aip/sdk.py` | `aip.Client`, the runtime as a library (`docs/sdk.md`): resolves a target (folder, `.rl`, catalog name) into the bundle cache, runs it through the engine, writes the run file at every stop and records the stop on the configured server; the typed results (`Paused` with its `Task`s, `Done`, `RunError`, `Description`, ...) |
| `src/aip/mcp.py` | `aip mcp`, the SDK as an MCP server (`docs/mcp.md`): seven tools (`search`, `describe`, `compile`, `run`, `resume`, `agent`, `pull`), each one `Client` call answering with the CLI's object; the MCP client's name is the run's `agent`. The one module that imports the MCP SDK (`mcp` 2.x: `MCPServer`, not 1.x's `FastMCP`); `tests/test_mcp.py` drives it in process, over stdio and over HTTP; `examples/agents/mcp-smoke/` is the example client |
| `tests/` | the runtime's tests: `test_engine.py` is the engine's, `test_cli_json.py` checks every example in `docs/cli-json.md` against the CLI's real output, `test_sdk.py` the SDK and that every `aip` command calls it (all three skip without Relate); `served.py` is the real server in process over an in-memory store, which the client's tests run against; `tests/server/` is the server's own suite, run over both backends (Neo4j when `NEO4J_URI` is set): `test_contract.py` the HTTP contract through the client, `test_queries.py` every query in `docs/language/queries.md`, the audit queries, the export and what the store keeps of a run, `scenes.py` the store they read; `test_local_server.py` starts the on-demand local server as a real process; `test_skill.py` holds the skill to the CLI (every command and flag it shows exists, its example compiles, `aip skill install`); `test_make_procedure.py` runs `make_procedure` and fails when a shipped bundle is not its folder's |
| `src/aip/compiler/` | **where the language lives**: `keywords.py` (every keyword with its aliases, the executable copy of the spec's glossary; the type vocabulary), `lexer.py`, `parser.py` (recursive descent; `ParseError` in `errors.py`), `syntax.py` (the tree every later pass reads), `checker.py` (every check of spec 2.2 to 2.5 as diagnostics; `CODES` is the spec's code table), `graph.py` (the bundle's graph, spec 3; the schema is `docs/language/bundle.md`), `bundle.py` (compile a folder, the bundle id, write, read with verification, export), `relate.py` (the one module that imports the engine, `relate`, the `relate-db` package, and knows the `.rl` suffix), `formatter.py` (canonical form), `skill.py` (`aip export --skill`: a procedure as a plain Agent Skill, rendered from the graph), `cli.py` (`aip compile`, `export`, `fmt`, dispatched from `aip.client.cli`), `resources.py` (finds the example programs and the `aip` skill in a checkout or a wheel), `agents.py` (the agent skills directories `aip skill install` writes to). `LANGUAGE_VERSION` is in `language.py`; `docs/language/compiler.md` walks the stages, code to output. The language's tests are `tests/test_parse.py`, `test_errors.py`, `test_format.py`, `test_check.py`, `test_bundle.py` |
| `editors/vscode/` | the VS Code extension: the grammar (`syntaxes/`), `src/compiler.js` (runs `aip compile --check --json --stdin`, no `vscode` import), `src/extension.js` (squiggles, status bar, the graph preview's panels, the compile/run/publish/import commands), `src/preview.js` and `src/terminal.js` (their logic, no `vscode` import), `src/webview/` (the preview: the console's step graph from `console/src/graph` and `console/src/views/StepGraph.tsx`, control and data flow, down or right, bundled with React by `esbuild.mjs` into `dist/preview.js`; since E3, the cards stay in the console), `icons/` (the `.aip` file icon); `npm install && npm run build && npm test` (esbuild; node's test runner over the tokenizer harness, a one-error fixture and the preview rendered over the compiler's graph, against `uv run aip`); `npm run package` writes `aip-lang.vsix`; `dist/`, `node_modules/` and the `.vsix` are not committed |
| `console/` | the web console, the npm package `aip-console` (Node, React, Vite; its own `package.json`, `CHANGELOG.md` and `AGENTS.md`): `bin/aip-console.mjs` the launcher that serves the page and runs procedures through the `aip` CLI, `src/graph/` the step graph (control flow, data flow, run traffic, a run's path; `bundle.ts` the bundle's graph read as steps and loops; `graph.css` its styles; the extension's preview bundles it with `views/StepGraph.tsx`), `src/studio/` the Studio's field edits at the compiler's spans and its chat's words (the card canvas went at C4), `src/highlight/` the tokenizer that colours `procedure.aip` from `editors/vscode`'s grammar, `src/views/` the pages (`Studio.tsx` since C4: a chat that runs `build_procedure` and `edit_procedure` through `aip runah`, the step graph, forms for field edits; `console/docs/studio.md`), `test/` its unit tests (`npm test`), `e2e/` its Playwright suite against this checkout's `aip` (`npm run e2e`); `pyproject.toml` keeps it out of the sdist |
| `scripts/` | `fresh-venv.sh` is L3's proof, a fresh venv installing this package (Relate with it) and compiling an example, run by CI on every push |
| `docs/specification-0.8.md` | the prose of the 0.8 YAML format, which nothing implements any more; its fate is the docs milestone's (D4). The language's spec is `docs/language/spec.md` |
| `skills/aip/` | the one skill (since K1; it replaced `aip-runtime` and `aip-compile`): `SKILL.md`, how an agent finds and runs a procedure, answers a pause and writes one, and `references/language.md`, the language on one page. `aip skill install` writes it into an agent. Reviewed line by line, keep diffs small. `examples/language/make_procedure/assets/language.md` is a copy of the language page (a bundle carries only its own folder's files); `tests/test_skill.py` fails when they differ, and a change to it means compiling `make_procedure` again |
| `examples/language/` | the example programs, which must compile and be in the formatter's form; `make_procedure`, `build_procedure` and `edit_procedure` also ship as built-in bundles |
| `examples/billing-support/` | the bundled example skill; validation fails on `aip_version_mismatch` if the format moves without it |
| `docs/` | design and reference: `running.md` (0.9 since A2), `agent.md`, `run-modes.md`, `state.md`, `client-execution.md`, `server-design.md`, `sdk.md`, `mcp.md`, `cli-json.md`, `upgrading.md` |
| `CHANGELOG.md` | one changelog for both packages; before `0.7.0` the two histories are interleaved and marked `(aip)` or `(aip-spec)` |
| `install.sh` | the one-command installer: uv, `agent-instruction-protocol[server]`, the `aip` skill, `aip skill prune` |
| `.github/workflows/release.yml` | the release workflow, below |
| `.github/workflows/console-release.yml` | the console's release workflow: builds from `console/`, tags `console-vX.Y.Z`, stages `aip-console` on npm for the maintainer's approval (`console/AGENTS.md`) |
| `.github/workflows/tests.yml` | CI: pytest on Linux and Windows, the extension's build and tests, the console's build and unit tests |

## Conventions

- **Python, built with `uv` and `hatchling`.** `uv sync --group dev` to set up; `uv run pytest -q`
  at the root runs every test and must pass before any commit. No `pip install`, no
  `python -m venv`. Relate is the `relate-db` dependency from PyPI, so `uv sync` installs it;
  the bundle and engine tests skip only in an environment without it.
- **One package, one version.** `pyproject.toml` is the only pyproject; `aip --version` prints one
  line, `aip <version> language <language version>`.
- **Change the language in one place and let the tests find the rest.** `docs/language/spec.md`
  is normative and its glossary is the only list of keywords in prose; `keywords.py` is the
  executable copy, and a keyword or alias added to one is added to the other in the same commit.
  The examples under `examples/language/` must parse and be in the formatter's form (`aip fmt
  --check examples/language`, which CI runs: formatting a procedure changes its bundle id).
- **Do not change behaviour in a release branch.** If a test must change for a path, say so in
  the commit; if it must change for a behaviour, stop and write it down in the plan issue.
- **Plans live in issues, not in the repo.** The roadmap is
  [#20](https://github.com/zach-blumenfeld/aip/issues/20); each release has a plan issue with a
  checklist of milestones, each naming the command that proves it. A fresh agent implements one
  milestone per session: read the plan's "Context" and "Rules", then only the first unchecked
  milestone; run its proof, tick it, comment `Done <date>, commit <sha>: <one sentence>`, commit.
  Product-visible questions sit under "Open items" with a default; take the default and say so.

## Changing what a run does

A change to run semantics (how a step kind behaves, what a router reads, what a decision
writes, what the history records) is never one file. Before touching the code, list the
places below and change them in the same commit; the drift tests catch some, not all.

| Where | What to change |
|---|---|
| `src/aip/model/steps.py` | the step's behaviour; `engine.py` drives the loop, writes the pause and the record (`recorded_history` is the history a record shows: the engine's, plus the entries of the `For` passes still open in a run that stopped inside one; `aip.client.runs` posts and prints that); `procedure.py` reads the graph and changes only when `docs/language/bundle.md` does |
| `src/aip/server/store.py` | what the store keeps of the record: `run_properties`, `entry_properties` and `answer_rows` turn a posted run into nodes, so a field added to a history entry is added there, to the tables in `docs/server-design.md`, and to the queries in `docs/language/queries.md` that should see it |
| `docs/language/spec.md` and `docs/language/runtime.md` | the language and what running it requires: the same rule in words. This is the language: it moves `LANGUAGE_VERSION` unless the release is still unreleased |
| `skills/aip/SKILL.md` and `skills/aip/references/language.md` | the skill: what an agent is told a pause, an answer and an error look like, including the worked example at the end; and the language page, with its copy under `examples/language/make_procedure/assets/` (then compile `make_procedure` again) |
| `examples/billing-support/SKILL.md` | the runtime block copy and the comments that explain the run |
| `docs/running.md`, `docs/state.md`, `docs/cli-json.md`, `docs/client-execution.md`, `README.md` | every walkthrough that narrates the old behaviour; grep for the old history `reason` values and the old wording |
| `tests/` | the assertions on history entries, `--progress` lines, and the checker's diagnostics |
| `CHANGELOG.md` | under `## [Unreleased]`, in the user's terms |

The audit queries (`src/aip/server/audit.py`) read the `Run`, `Entry` and `Answer` nodes, so a new
`reason`, error kind or `answered_by` value needs a look there too.

## Versioning

The rules, decided 2026-11-01 in the roadmap (#20):

- **Package version** `X.Y.Z` in `pyproject.toml`, SemVer, pre-1.0 so breaking changes bump the
  minor. Moves every release. PyPI distribution name: `agent-instruction-protocol` (import and
  command `aip`); `aip-spec` was the language's own distribution through 0.8 and stays there.
- **Format version** `X.Y` (`FORMAT_VERSION` in `models.py`, the runtime block heading of every
  `SKILL.md`). It is the package's `major.minor` at the last release that changed the format. A
  format change is breaking by definition, so it never happens in a patch release; the format has
  no third number. An additive change (a new optional field) may ride on a patch release without
  moving the format version.
- Concretely: 0.7.0 ships format `0.6a1`; 0.8.0 introduces `0.8`; 0.8.1 stays `0.8`; 0.9.0
  introduces `0.9`.
- **Every format change ships `aip upgrade <folder>`** that rewrites a skill where the change is
  mechanical, reports what it could not migrate, and validates the result. The validator's
  outdated-format message names it. (That was the rule through 0.8. 0.9 has no such tool, since
  0.8 procedures do not run; since K1 `aip upgrade`, with no folder, publishes the procedures the
  package ships to the configured server.)
- The console has its own package version (npm, `console/package.json`), its own tag
  (`console-vX.Y.Z`; `vX.Y.Z` is this package's) and declares the minimum `aip` it works with
  (`MINIMUM_AIP` in `console/bin/aip-console.mjs`).

## Releasing

Releases are cut by the **`.github/workflows/release.yml`** workflow, **triggered manually**
(Actions → *Release to PyPI* → Run workflow) by a maintainer **after the release PR is merged to
`main`**. The workflow reads the version from `pyproject.toml` and refuses if the tag already
exists, builds the wheel and the sdist (`uv build`), tags `vX.Y.Z`, publishes
`agent-instruction-protocol` to PyPI with Trusted Publishing (the `release` GitHub environment;
the `release-spec` environment published `aip-spec` through 0.8 and is unused now), and cuts a
GitHub Release whose body is the matching `## [X.Y.Z]` section of `CHANGELOG.md`.

Running it with `target: testpypi` is the dry run for a new or changed workflow: same checks,
same build, the upload goes to test.pypi.org, no tag and no GitHub Release, and the run ends by
printing the `pip install` line to verify with. TestPyPI refuses a filename it has seen before,
so a failed dry run cannot be repeated at the same version: fix the workflow, then rerun with
the version temporarily suffixed `.dev1` on a scratch branch, or accept one dry run per version.

So an agent's job for a release is **prep only — never build, tag, or publish by hand:**

1. **Set the version** in `pyproject.toml` (`version = "X.Y.Z"`; SemVer, pre-1.0 → breaking
   changes bump the minor), then `uv lock`.
2. **Finalize `CHANGELOG.md`**: roll `## [Unreleased]` into a single `## [X.Y.Z] — <date>`
   section (one section per release — the workflow extracts just that one). The `## [X.Y.Z]`
   heading format is **load-bearing** (awk-matched); leave a fresh empty `## [Unreleased]` above
   it.
3. Open the release PR. The maintainer merges it and triggers the workflow.

Never move or force-push a published tag.

## When you're unsure

- For what a procedure may contain, `docs/language/spec.md` is the law and `aip/compiler/syntax.py`
  is the tree it parses to.
- For how a run moves, `docs/language/runtime.md` and `docs/cli-json.md` (`docs/state.md`,
  `docs/run-modes.md` and `docs/client-execution.md` still describe 0.8, until D4); for the server and its store, `docs/server-design.md`.
- For what the console reads, the same three: `docs/cli-json.md` (the launcher relays the CLI's
  JSON), `docs/server-design.md` (the page calls the API) and `docs/language/bundle.md` (the
  step graph draws it). A change to any of them that the console shows changes `console/` in
  the same commit.
- For what agents see, `skills/aip/SKILL.md` is the contract; a change to the runtime's
  behaviour that it describes changes it in the same commit.
