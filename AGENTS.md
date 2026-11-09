# AGENTS.md

Instructions for AI agents working **on** this repository. If you are an agent being asked to
*use* AIP, read `skills/aip-runtime/SKILL.md` (running a published procedure) or
`skills/aip-compile/SKILL.md` (compiling material into one) instead.

## What this repo is

The Agent Instruction Protocol (AIP): a format for procedures as graph-shaped Agent Skills, and
the runtime that executes them. Two Python packages live here as one uv workspace and release
together under one version:

| package | where | what |
|---|---|---|
| `agent-instruction-protocol` | the root (`src/aip/`) | the runtime: the `aip` command, the Python SDK, `aip server`, the Neo4j and filesystem backends, the `aip-runtime` skill |
| `aip-spec` | `packages/aip-spec/` | the language: the parser, the syntax tree, the formatter (`aip-spec fmt`), the example programs; the checker and the bundle arrive with the 0.9 milestones. Until 0.9 ships it still bundles the `aip-compile` skill |

The distribution name of the runtime is `agent-instruction-protocol` (PyPI blocks `aip` as a
look-alike of an existing project); its module and command are `aip`. The runtime depends on
`aip-spec==<the same version>`. The web console is a separate repository,
[aip-console](https://github.com/zach-blumenfeld/aip-console), with its own npm version.

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
| `pyproject.toml` | the `agent-instruction-protocol` package and the uv workspace root (`[tool.uv.workspace] members = ["packages/*"]`); `testpaths` lists both packages' tests |
| `src/aip/client/` | the `aip` command (`cli.py`), the local runner, the executor that runs scripts and asks the decision model, the resolver, the HTTP client; `aip-runtime/SKILL.md` is the bundled copy of the runtime skill |
| `src/aip/model/` | the execution engine: steps, types, the environment a run carries, the procedure graph |
| `src/aip/server/` | `aip server`: the FastAPI app, catalog search, run records, governance, and `backends/` (Neo4j, filesystem) |
| `src/aip/spec/` | loads a skill folder through `aip_spec` into the runtime's model |
| `src/aip/sdk.py` | `aip.Client`, the runtime as a library; the CLI is a thin wrapper over it (`docs/sdk.md`) |
| `tests/` | the runtime's tests; `tests/server/` drives the HTTP API; the Neo4j backend tests skip unless `NEO4J_URI` is set |
| `packages/aip-spec/src/aip_spec/` | **where the language lives**: `keywords.py` (every keyword with its aliases, the executable copy of the spec's glossary; the type vocabulary), `lexer.py`, `parser.py` (recursive descent; `ParseError` in `errors.py`), `syntax.py` (the tree every later pass reads), `formatter.py` (canonical form), `cli.py` (`aip-spec fmt`), `resources.py` (finds the example programs and, for now, the `aip-compile` skill in a checkout or a wheel), `agents.py` (the agent skills directories). `LANGUAGE_VERSION` is in `__init__.py` |
| `packages/aip-spec/docs/specification.md` | the prose of the 0.8 YAML format, which this package no longer implements; its fate is the docs milestone's (D4). The language's spec is `docs/language/spec.md` |
| `packages/aip-spec/tests/` | the language's tests: the examples parse and round-trip, a test per syntax error with its position, the formatter and `fmt` |
| `packages/aip-spec/hatch_build.py` | bundles `skills/aip-compile/` and `examples/` into the `aip_spec` wheel from the checkout or from the sdist |
| `skills/aip-compile/` | the authoring skill (`SKILL.md`, `references/`, `assets/procedure.schema.json`); reviewed line by line, keep diffs small |
| `skills/aip-runtime/` | the runtime skill agents read to run published procedures; `tests/test_runtime_skill.py` fails if it drifts from the copy under `src/aip/client/` or lags `FORMAT_VERSION` |
| `examples/billing-support/` | the bundled example skill; validation fails on `aip_version_mismatch` if the format moves without it |
| `docs/` | design and reference: `running.md`, `run-modes.md`, `state.md`, `client-execution.md`, `server-design.md`, `sdk.md`, `cli-json.md`, `upgrading.md` |
| `CHANGELOG.md` | one changelog for both packages; before `0.7.0` the two histories are interleaved and marked `(aip)` or `(aip-spec)` |
| `install.sh` | the one-command installer: uv, `aip-spec`, `agent-instruction-protocol[server]`, both skills, `aip skill prune` |
| `.github/workflows/release.yml` | the release workflow, below |

## Conventions

- **Python, built with `uv` and `hatchling`.** `uv sync --group dev` to set up; `uv run pytest -q`
  at the root runs both packages' tests and must pass before any commit. No `pip install`, no
  `python -m venv`.
- **One version, two pyprojects.** `pyproject.toml` and `packages/aip-spec/pyproject.toml` carry
  the same `version`, and the root's dependency pin `aip-spec==<version>` matches. The workflow
  refuses to release if the three differ.
- **Change the language in one place and let the tests find the rest.** `docs/language/spec.md`
  is normative and its glossary is the only list of keywords in prose; `keywords.py` is the
  executable copy, and a keyword or alias added to one is added to the other in the same commit.
  The examples under `examples/language/` must parse and round-trip through the formatter.
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
| `src/aip/model/steps.py` | the step's behaviour; `procedure.py` (`resolve`) walks routers, `engine.py` drives the loop |
| `src/aip/server/app.py` | the server's own `resolve` call sites (`execute`, `peek`) mirror the engine |
| `docs/language/spec.md` and `docs/language/runtime.md` | the language and what running it requires: the same rule in words. This is the language: it moves `LANGUAGE_VERSION` unless the release is still unreleased |
| `skills/aip-runtime/SKILL.md` and `src/aip/client/aip-runtime/SKILL.md` | the runtime skill, both copies, including the worked example at the end (replaced by one `aip` skill at K1) |
| `examples/billing-support/SKILL.md` | the runtime block copy and the comments that explain the run |
| `docs/running.md`, `docs/state.md`, `docs/cli-json.md`, `docs/client-execution.md`, `README.md` | every walkthrough that narrates the old behaviour; grep for the old history `reason` values and the old wording |
| `tests/` and `packages/aip-spec/tests/` | the assertions on history entries, `--progress` lines, and validator issues |
| `CHANGELOG.md` | under `## [Unreleased]`, in the user's terms |

Governance queries (`src/aip/server/`) read history entries, so a new `reason` or attribution
value needs a look there too.

## Versioning

The rules, decided 2026-11-01 in the roadmap (#20):

- **Package version** `X.Y.Z` in both pyprojects, SemVer, pre-1.0 so breaking changes bump the
  minor. Moves every release. PyPI distribution names: `agent-instruction-protocol` (import and
  command `aip`) and `aip-spec`.
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
`main`**. The workflow reads the version from both pyprojects and refuses if they differ or if
the tag already exists, builds all four distributions (`uv build --all-packages`), tags
`vX.Y.Z`, publishes `aip-spec` and then `agent-instruction-protocol` to PyPI with Trusted
Publishing (two jobs, two GitHub environments, `release-spec` then `release`, because PyPI
allows one publisher per environment; the spec goes first so the runtime's exact pin resolves
the moment it lands), and cuts a GitHub Release whose body is the matching `## [X.Y.Z]` section
of `CHANGELOG.md`.

Running it with `target: testpypi` is the dry run for a new or changed workflow: same checks,
same build, both uploads go to test.pypi.org, no tag and no GitHub Release, and the run ends by
printing the `pip install` line to verify with. TestPyPI refuses a filename it has seen before,
so a failed dry run cannot be repeated at the same version: fix the workflow, then rerun with
the version temporarily suffixed `.dev1` in both pyprojects on a scratch branch, or accept one
dry run per version.

So an agent's job for a release is **prep only — never build, tag, or publish by hand:**

1. **Align the version** in both `pyproject.toml` files and in the root's `aip-spec==` pin
   (`version = "X.Y.Z"`; SemVer, pre-1.0 → breaking changes bump the minor), then `uv lock`.
2. **Finalize `CHANGELOG.md`**: roll `## [Unreleased]` into a single `## [X.Y.Z] — <date>`
   section (one section per release — the workflow extracts just that one). The `## [X.Y.Z]`
   heading format is **load-bearing** (awk-matched); leave a fresh empty `## [Unreleased]` above
   it.
3. Open the release PR. The maintainer merges it and triggers the workflow.

The tags `vX.Y.Z` are shared by both packages; never move or force-push a published tag.

## When you're unsure

- For what a procedure may contain, `docs/language/spec.md` is the law and `aip_spec/syntax.py`
  is the tree it parses to.
- For how a run moves, `docs/running.md`, `docs/state.md` and `docs/run-modes.md`; for the
  server, `docs/server-design.md` with `docs/client-execution.md` on top.
- For what agents see, the two `SKILL.md` files are the contract; a change to the runtime's
  behaviour that they describe changes them in the same commit.
