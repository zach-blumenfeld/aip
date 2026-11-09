# AGENTS.md

Instructions for AI agents working **on** this repository. If you are an agent being asked to
*use* AIP, read `skills/aip-runtime/SKILL.md` (running a published procedure) or
`skills/aip-compile/SKILL.md` (compiling material into one) instead.

## What this repo is

The Agent Instruction Protocol (AIP): a language for procedures that an agent runs step by step,
the compiler that turns a procedure into a bundle, and the runtime that executes it. One Python
package, `agent-instruction-protocol` (`src/aip/`): the `aip` command, the Python SDK, the
compiler (`aip.compiler`: parser, checker, formatter, graph, bundle), the engine (`aip.model`),
`aip server` with its backends, and the skills. The distribution name is
`agent-instruction-protocol` (PyPI blocks `aip` as a look-alike of an existing project); its
module and command are `aip`. Until 0.9 the language was a second package, `aip-spec`, in a uv
workspace under `packages/`; it folded in at plan milestone L5 (2026-11-09) and the `aip-spec`
distribution stays at 0.8 on PyPI with no further release. The web console,
[aip-console](https://github.com/zach-blumenfeld/aip-console) on npm, moves into this repository
as `console/` at plan milestone C1 (its own npm version and release workflow; excluded from the
Python build); until then it is the separate `aip-console-dev` mirror named in `docs/language/sources.md`.

## This is the private 0.9 mirror

`zach-blumenfeld/aip-dev` is a private copy of the public `zach-blumenfeld/aip` repository, made on
2026-11-08 so that 0.9 can be built before one of its dependencies is public. Rules:

- **Relate (formerly CypherLite) is unreleased.** Nothing that mentions it, in code, docs, commit
  messages, issues or PR text, goes to the public `aip` or `aip-console` repositories until Zach
  explicitly gives the go-ahead. Push 0.9 work to the `dev` remote only. The `release-0.9.0`
  branch's `pushRemote` is set to `dev`; keep it so.
- **The 0.9 plan is issue #1 on this repository** (https://github.com/zach-blumenfeld/aip-dev/issues/1), in the format the 0.7 and 0.8 plans used on the
  public repo. One milestone per session, run its proof, tick it, comment, commit.
- **Start with `docs/language/sources.md`**: where the old code, the console, Relate's docs and wheels, and the
  decision model live, with what is stale. Then the plan issue.
- **The language lives under `docs/language/`** (the spec, runtime requirements, limitations, why
  there are no expressions, the end-to-end scenes, the settled plan questions), its programs under
  `examples/language/`, the VS Code extension under `editors/vscode`. They came from the private
  `aip-lang` repository on 2026-11-08 (its commit 9845671); that repository is now the design
  archive. Final paths are decided by the compiler milestone.
- **Public `main` keeps moving** with 0.8 fixes. Merge `origin/main` into `release-0.9.0` when it
  does; never the other way until the go-ahead.
- When Zach clears it: push `release-0.9.0` to the public repo, open the release PR there, transfer
  the plan issue with `gh issue transfer`, archive this mirror.

## Repo map

| Path | What's there |
|---|---|
| `pyproject.toml` | the one package, `agent-instruction-protocol`; its `[tool.hatch.build.targets.wheel.force-include]` puts `examples/` and `skills/aip-compile/` into the wheel under `aip/compiler/`; `testpaths` is `tests` |
| `src/aip/client/` | the `aip` command (`cli.py`, a thin wrapper over the SDK), `config.py` (the per-user config: server, token, decision-model key, batch; the identity from `AIP_AGENT`/`AIP_SESSION`), `bundles.py` (the bundle cache every run runs from, `~/.aip/bundles/<id>.rl`, and the refs a catalog name resolved to), `local.py` (the local server `aip config server local` points at: started by the first request that finds none, stopped when idle), `runs.py` (run files and their listing, the outcome objects of `docs/cli-json.md`, the `--progress` lines, the step table `aip runs <id>` prints), `server.py` (the HTTP client; its docstring lists every call the server must answer, the contract S1 implements); `aip-runtime/SKILL.md` is the 0.8 skill's bundled copy until K1 |
| `src/aip/model/` | the execution engine: `procedure.py` reads a bundle's graph behind a Relate connection (one Cypher query per thing a step or loop needs; `Procedure.load(bundle)` puts a verified bundle in an in-memory store), `steps.py` is what each step kind does (and the loop head, the batched request), `engine.py` the run loop (`Engine`, `Run`, loop frames, `For` passes as cursors run in batches, pauses, the record), `types.py` the type checks and the error kinds, `answers.py` the answer objects of spec 2.4, `resolver.py` the decision-model interface and the scripted test resolver, `typesafe.py` the TypeSafe resolver, `cache.py` the files unpacked once per bundle id, `environment.py` the `Requires` check |
| `src/aip/server/` | `aip server` (`docs/server-design.md`): `store.py` is the store, bundles, revisions, drafts and runs in one graph and the one body of Cypher over it; `backends/` the two adapters it runs through (`relate.py`, one file, the default; `neo4j.py`); `app.py` the FastAPI app, which never runs a procedure; `audit.py` the named audit queries (`aip audit`) and the stored ones; `builtins.py` the hook that publishes the bundles shipped in the package; `search.py` BM25; `config.py` the TOML and `.env` |
| `src/aip/sdk.py` | `aip.Client`, the runtime as a library (`docs/sdk.md`): resolves a target (folder, `.rl`, catalog name) into the bundle cache, runs it through the engine, writes the run file at every stop and records the stop on the configured server; the typed results (`Paused` with its `Task`s, `Done`, `RunError`, `Description`, ...) |
| `tests/` | the runtime's tests: `test_engine.py` is the engine's, `test_cli_json.py` checks every example in `docs/cli-json.md` against the CLI's real output, `test_sdk.py` the SDK and that every `aip` command calls it (all three skip without Relate); `served.py` is the real server in process over an in-memory store, which the client's tests run against; `tests/server/` is the server's own suite, run over both backends (Neo4j when `NEO4J_URI` is set): `test_contract.py` the HTTP contract through the client, `test_queries.py` every query in `docs/language/queries.md`, the audit queries, the export and what the store keeps of a run, `scenes.py` the store they read; `test_local_server.py` starts the on-demand local server as a real process; `test_runtime_skill.py` is listed in `conftest.py` and not collected until K1 rewrites the skill |
| `src/aip/compiler/` | **where the language lives**: `keywords.py` (every keyword with its aliases, the executable copy of the spec's glossary; the type vocabulary), `lexer.py`, `parser.py` (recursive descent; `ParseError` in `errors.py`), `syntax.py` (the tree every later pass reads), `checker.py` (every check of spec 2.2 to 2.5 as diagnostics; `CODES` is the spec's code table), `graph.py` (the bundle's graph, spec 3; the schema is `docs/language/bundle.md`), `bundle.py` (compile a folder, the bundle id, write, read with verification, export), `relate.py` (the one module that imports the engine, `relate` or `cypherlite`, and knows the `.rl` suffix), `formatter.py` (canonical form), `cli.py` (`aip compile`, `export`, `fmt`, dispatched from `aip.client.cli`), `resources.py` (finds the example programs and, for now, the `aip-compile` skill in a checkout or a wheel), `agents.py` (the agent skills directories). `LANGUAGE_VERSION` is in `language.py`. The language's tests are `tests/test_parse.py`, `test_errors.py`, `test_format.py`, `test_check.py`, `test_bundle.py` |
| `editors/vscode/` | the VS Code extension: the grammar (`syntaxes/`), `src/compiler.js` (runs `aip compile --check --json --stdin`, no `vscode` import) and `src/extension.js` (squiggles, status bar); `npm install && npm run build && npm test` (esbuild; node's test runner over the tokenizer harness and a one-error fixture, against `uv run aip`); `dist/` and `node_modules/` are not committed |
| `scripts/` | `install-relate.sh` installs the pinned Relate wheel (not on PyPI; see `docs/language/sources.md`); `fresh-venv.sh` is L3's proof, a fresh venv installing this package and compiling an example, run by CI when it has the release token |
| `docs/specification-0.8.md` | the prose of the 0.8 YAML format, which nothing implements any more; its fate is the docs milestone's (D4). The language's spec is `docs/language/spec.md` |
| `skills/aip-compile/` | the authoring skill (`SKILL.md`, `references/`, `assets/procedure.schema.json`); reviewed line by line, keep diffs small |
| `skills/aip-runtime/` | the runtime skill agents read to run published procedures; `tests/test_runtime_skill.py` fails if it drifts from the copy under `src/aip/client/` or lags `FORMAT_VERSION` |
| `examples/billing-support/` | the bundled example skill; validation fails on `aip_version_mismatch` if the format moves without it |
| `docs/` | design and reference: `running.md`, `run-modes.md`, `state.md`, `client-execution.md`, `server-design.md`, `sdk.md`, `cli-json.md`, `upgrading.md` |
| `CHANGELOG.md` | one changelog for both packages; before `0.7.0` the two histories are interleaved and marked `(aip)` or `(aip-spec)` |
| `install.sh` | the one-command installer: uv, `agent-instruction-protocol[server]`, both skills, `aip skill prune` |
| `.github/workflows/release.yml` | the release workflow, below |

## Conventions

- **Python, built with `uv` and `hatchling`.** `uv sync --group dev` to set up; `uv run pytest -q`
  at the root runs every test and must pass before any commit. No `pip install`, no
  `python -m venv`. Relate is not on PyPI: `scripts/install-relate.sh` puts it in `.venv`, and the
  bundle and engine tests skip without it.
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
| `src/aip/model/steps.py` | the step's behaviour; `engine.py` drives the loop, writes the pause and the record; `procedure.py` reads the graph and changes only when `docs/language/bundle.md` does |
| `src/aip/server/store.py` | what the store keeps of the record: `run_properties`, `entry_properties` and `answer_rows` turn a posted run into nodes, so a field added to a history entry is added there, to the tables in `docs/server-design.md`, and to the queries in `docs/language/queries.md` that should see it |
| `docs/language/spec.md` and `docs/language/runtime.md` | the language and what running it requires: the same rule in words. This is the language: it moves `LANGUAGE_VERSION` unless the release is still unreleased |
| `skills/aip-runtime/SKILL.md` and `src/aip/client/aip-runtime/SKILL.md` | the runtime skill, both copies, including the worked example at the end (replaced by one `aip` skill at K1) |
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
  outdated-format message names it.
- The console has its own package version (npm) and declares the minimum `aip` it works with
  (`MINIMUM_AIP` in its `bin/aip-console.mjs`).

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
- For how a run moves, `docs/language/runtime.md` and `docs/cli-json.md` (`docs/running.md`,
  `docs/state.md`, `docs/run-modes.md` and `docs/client-execution.md` still describe 0.8, until
  D4); for the server and its store, `docs/server-design.md`.
- For what agents see, the two `SKILL.md` files are the contract; a change to the runtime's
  behaviour that they describe changes them in the same commit.
