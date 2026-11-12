# Where everything is

For the agent implementing a milestone of the 0.9 plan (issue #29 on `zach-blumenfeld/aip`).
Every pointer here was checked on 2026-11-09 (the Relate section on 2026-11-11). If one is dead, fix it here in the same commit.

## This repository

- The worktree is `~/dev/aip-0.9` on branch `release-0.9.0` of the public `zach-blumenfeld/aip`;
  push to `origin`. Until 2026-11-11 it was the private mirror `zach-blumenfeld/aip-dev`, archived
  the day Relate was announced (AGENTS.md, "The 0.9 branch"); the checkout may still carry a `dev`
  remote pointing at it.
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
  proof that must not touch the real store). The old `cypherlite-backend` branch was
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
`zach-blumenfeld/aip-console-dev` (the private mirror of `zach-blumenfeld/aip-console`, archived 2026-11-11; this
checkout's remote `dev-console`, and the local checkout `~/dev/aip-inspector`), whose commit
f30ed95 is the last there. That mirror is the archive now: nothing newer is in it, and console
work happens here. `console/AGENTS.md` describes the launcher, the step graph, the Studio, the API client
and the tests; the e2e harness runs this checkout's `aip` (`AIP_REPO`, default `..`). It stays
its own npm package (`aip-console`) with its own version, changelog and release workflow
(`.github/workflows/console-release.yml`, tag `console-vX.Y.Z`), and `pyproject.toml` keeps
`console/` out of the sdist, so nothing of it reaches PyPI. Its tests need Node 24 and npm:
`npm install && npm run typecheck && npm test && npm run e2e` in `console/`.

**The step graph (C3, 2026-11-09)** is `console/src/graph/`, ported from the 0.8 console
(`git show 9cdf691^2:src/views/StepGraph.tsx`, `src/graph/layout.ts`, `dataflow.ts`,
`src/views/Traffic.tsx`) onto the 0.9 graph. `console/docs/screenshots/c3/` holds a picture of each
mode as C3 drew it, with loops as frames; `console/docs/screenshots/loops/` holds them as they are
drawn now, a loop as a node with its body beside it (both copied from `.aip-e2e/screenshots/`,
which `e2e/graph.spec.ts` writes on every run). Two
things the record taught it, for whoever reads a run next: a run paused inside a `For` has
`position` on the loop, and `pause.step` names the step; and an `Until` that holds where its
answer is produced ends the pass at that step (`exit.where`), so that step did not go on to the
next one.

## Relate

Embedded property-graph engine with Cypher, from Neo4j, Apache 2.0. **Announced 2026-11-11**
(https://neo4j.com/press-releases/announcing-relate-by-neo4j/) and public since: source and releases at
https://github.com/relatedb/relate, `relate-db` 1.0.0 on PyPI (`import relate`), the CLI `relate` as a
release binary, bundles `.rl`, docs at https://relatedb.ai/. The rename from CypherLite (the last release
under that name was 0.16.1, 2026-11-04) is the engine's ADR-0517: names changed, on-disk bytes did not.
**This tree depends on `relate-db>=1.0,<2` from PyPI since R6** (2026-11-11): `uv sync` installs it, CI
runs every bundle test on every push, and no token or wheel download is involved.

| What | Where | Note |
|---|---|---|
| Source and releases | **https://github.com/relatedb/relate**, release **v1.0.0** (2026-11-11) | Assets: CLI binaries `relate-{darwin,linux}-{amd64,arm64}` and `relate-windows-amd64.exe`, `install.sh`, `SHA256SUMS` and `SHA256SUMS.sig`, the wheels `relate_db-1.0.0-cp39-abi3-{macosx_10_12_x86_64, macosx_11_0_arm64, manylinux2014_x86_64, manylinux2014_aarch64, win_amd64}.whl` and `relate_db-1.0.0.tar.gz`, FFI tarballs, Java jars, npm tarballs, `releases.json`. |
| Python package | **`relate-db` 1.0.0 on PyPI**, `relate-db>=1.0,<2` in `pyproject.toml`, `import relate` only in `src/aip/compiler/relate.py` | Verified 2026-11-11 in a Python 3.14 venv: `relate.connect(path, read_only=False)` opens a `.rl` path as one file (`.cl` still opens, as the legacy extension; any other path is a directory), `CREATE`/`MATCH` round-trip, extras `arrow` (`pyarrow>=14`) and `pandas`; the wheel ships no CLI. The full record is `docs/language/relate/python-library.md`, "Verified in this tree". |
| CLI | the release binaries above, or `curl -sSfL https://relatedb.ai/install.sh \| bash` | `relate [OPTIONS] [--database PATH] [QUERY]`, `relate query`, `clone`, `info`, `pull`, `push`, `serve`, `--load`, `--read-only`: `docs/language/relate/cli-flags.md`. Per those docs `--database x.rl` opens the bundle; this cleanup did not run the binary, so the CLI's claims are copied, not verified. |
| Docs | https://relatedb.ai/ (docs home https://relatedb.ai/docs/), **`llms.txt` at https://relatedb.ai/llms.txt** is the whole reference in one file (a curated index at https://relatedb.ai/docs/llms.txt); the repo's `docs/` (`reference/`, `guides/`, `api/`, `adr/`, `limitations.md`, `engine-architecture.md`) | Read a repo page with `gh api repos/relatedb/relate/contents/<path>?ref=v1.0.0`, base64 in `.content`. |
| Reference docs, snapshotted at v1.0.0 | `docs/language/relate/` in this tree (2026-11-11) | `python-library.md` (connect, execute, parameters, `read_only=True`, Arrow, plus this tree's verification section), `storage-formats.md` (directory, `.rl` single file with `.cl` legacy, codecs, frozen on-disk names), `cli-flags.md`, `cypher-syntax.md`, `limitations.md`, `llms.txt`. Each starts with a header naming its source. All six were taken at v1.0.0, after the rename, so none predates it; the few `cypherlite` spellings in `storage-formats.md`, `python-library.md` and `cli-flags.md` are upstream's own (the frozen on-disk names, the legacy `.cl` extension, the rename's history). Prefer these to live fetches; refresh them when the pin moves. |
| What R6 removed (history) | git history before R6's commit | Until R6 the tree pinned the pre-release wheel `neo4j_cypherlite-0.16.1` (import name `cypherlite`), fetched by `scripts/install-relate.sh` from the pre-release repository with the secret `RELATE_GH_TOKEN`, and worked around 0.16.1 knowing its single-file form by `.cl` alone (`<name>.rl.tmp.cl` writes, `.cl` links on open, the server's store kept as `store.cl`). All of it is gone; `relate.py` passes `.rl` paths through. A `store.cl` left by an earlier 0.9 checkout is not read: the server starts a fresh `store.rl` (0.9 was never released, so no user has one). |
| 0.16.1 → 1.0.0 differences | verified in the venv unless marked *docs*; R6 ran the whole suite on 1.0.0 | (1) `.rl` opens as the single file; `.cl` stays accepted; at 0.16.1 `.rl` was a directory, so the `.tmp.cl` and link dance in `relate.py` goes. (2) Snapshot `format_version` 3 → 5: 1.0.0 reads a 0.16.1 bundle read-only unchanged but **upgrades it on the first writer open, even with no writes**, and 0.16.1 then refuses it (`unsupported snapshot version 5`); the committed `make_procedure.rl` and every server store become 1.0.0's once R6 touches them. (3) `elementId()` middle segment `cypherlite` → `rl-id`. (4) Distribution `neo4j-cypherlite` → `relate-db`, module `cypherlite` → `relate`, error texts say "Relate"; read-only open of a missing path says `database not found`. (5) *docs*: env vars `CYPHERLITE_*` → `RELATE_*` with no fallback; CLI `cypherlite` → `relate`, assets renamed, `install.sh` at relatedb.ai; the markdown vault sidecar and the lock, writer and WAL magics keep their `cypherlite` spelling on disk. (6) *docs*: the "3892/3892 TCK" claim is retired for a reporting-only spec harness, `FOR` left preview, vector index described as exact top-k, `clone` no longer mentions CDC slots. Unchanged, verified: the Python API surface (`Connection`, `Cursor`, `Database`, extras), thread affinity, `read_only` semantics, map-parameter `UNWIND`/`MERGE`/`SET n = $map`, list and string properties, no map properties, bytes as int lists. |
| Concurrency rule | `python-library.md`, "read_only" and "Verified in this tree" | One writer per store; a second writer is `storage locked`. `connect(path, read_only=True)` opens a frozen view beside a writer on a **directory** store; on a single-file bundle it is refused while a writer holds it (both versions), so readers of a live single-file store go through its writer. `relate serve --read-only` likewise (*docs*). The server is the only writer of its store (plan question 5). A connection may only be used on the thread that opened it (`ProgrammingError`), so the server's backend gives it one worker thread. |
| The server's store file | `aip.compiler.relate.store` | `store.rl`, one file, opened by 1.0.0 as it is. Verified at both versions for the store's Cypher: `MERGE`, `SET n = $map`, `UNWIND` of maps, `OPTIONAL MATCH`, `collect(DISTINCT ...)`, `CASE`, label predicates, composite indexes, uniqueness constraints with `IF NOT EXISTS`, explicit transactions through the connection. |

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

## What S3 left for whoever comes next (2026-11-09)

- **A run's record is not the run file's `history` alone.** The engine appends a `For` pass's
  entries when its batch completes; `aip.model.engine.recorded_history` adds the entries of the
  passes still open, and `RunFile.recording()` (what is posted) and `RunFile.record()` (`aip
  runs <id>`) use it. Read a run through those, not through `run["history"]`.
- **`tests/server` runs on Neo4j too with `uv run python scratch/s3/neo4j_tests.py`** (scratch is
  not committed: it reads the test container's password from `docker inspect` and sets
  `NEO4J_URI` to `bolt://localhost:17687`). S3 ran it: 70 passed.
- **`aip.mcp.Server`** subclasses the MCP SDK's `MCPServer` to answer argument-validation
  failures as ordinary results; it reads `self._tool_manager`, a private attribute of the SDK
  (2.3.0). `tests/test_mcp.py` fails if a new SDK moves it.

## What L7 left (2026-11-09)

- **`Again` is gone; every cycle is a loop node.** A check and its fix are both in the loop
  body (spec 2.6, plan question 46). Old material still shows the other shape: the reviews
  under `docs/language/reviews/`, the C3 screenshots in `console/docs/screenshots/c3/`, and the
  K1 and S3 comments on the plan. `console/docs/screenshots/loops/` is current.
- **The console's unit tests read `console/test/fixtures/<example>.graph.json`**, which is the
  `graph` of `aip compile --check --json examples/language/<example>` written with
  `json.dumps(graph, indent=1)` and a final newline. Write the file again when an example or
  the graph's schema changes (L7 did for ticket-triage); the `*.run.json` records beside them
  are runs of billing-support, fixed-policy and dynamic-policy, which L7 did not touch.

## What C2 left (2026-11-09)

- **The Studio edits text, never the graph.** `console/src/canvas/edit.ts` turns each card operation
  into text edits at the spans `aip compile --json` puts on nodes and edges (1-based, `end_column`
  exclusive), assuming the canonical form, which the Studio restores after every edit with `aip fmt
  --stdin`. A new operation is a function there and a test in `console/test/edit.test.ts`; the
  e2e spec `console/e2e/studio.spec.ts` checks the result with the real formatter and compiler.
- **A half-done program has a graph only with `--partial`** (`aip.compiler.bundle.partial_graph`):
  the checker's program assembled as the bundle would be, edges to missing steps left out, no id.
  If the compiler ever stops building a graph for some error, the Studio shows the last one that
  parsed and refuses edits, which is the right failure.
- **Saving is `aip publish --draft` on a folder the launcher keeps** (one per open Studio, under a
  temporary directory, holding the bundle's files as the server returned them). Publishing the
  same folder afterwards gives the draft its revision, since the store merges by bundle id.
- **Not done:** the VS Code preview draws the canvas but does not pass `editing` yet; the edits are
  plain ranges, so the extension can apply them as a `WorkspaceEdit` when it does. Folder mode has
  no Studio (there is no server to save a draft to).

## What K2 left (2026-11-09)

- **`aip export <target> --skill DIR`** is `src/aip/compiler/skill.py` (`render_skill` over the
  graph, `export_skill` writing the folder) and `Client.export_skill`; `tests/test_export_skill.py`
  renders every example and holds the frontmatter to the Agent Skills limits. A new step kind,
  loop form or edge type needs a line there, or the page says nothing about it.
- **Claude Code listing the folder as a skill was not run by K2's session**: its sandbox refused a
  nested `claude`. The check is to export into `<project>/.claude/skills/billing-support/` and ask
  `claude -p` in that project which skills it has.
- **A user-level `~/.config/aip/server.toml` with `server.inspector` in it stops `aip server`**
  (that key went in 0.6a0). The one on this machine has it; K2's proof passed `--config` a scratch file.

## What D1 left (2026-11-09)

- **`docs/demo/local.md` is the script.** Sections 0 to 4 and 6 ran on this machine from a clean
  config (`AIP_CONFIG`, `AIP_LOCAL_PORT`, `AIP_LOCAL_DATA` pointed at `/tmp/aip-d1`, the key
  copied in from the real config without printing it). The session doing it was itself Claude
  Code, acting as the agent in the demo. **Section 5, Codex, has not run**: `codex` is not
  installed here. Running it, pasting its output and the `aip runs --agent codex` lines ends D1.
- **Nobody sets `AIP_AGENT` for the agent.** The skill does not mention it, so a run made by
  Claude Code or Codex is recorded with no agent unless the person exports it before starting the
  agent, as the script does.
- **The decision model doubts a policy that says what the work must not do.** "Do not offer any
  discount or credit" came back true at confidence 0.04 to 0.36, under the aggregation's 0.7, and
  the run failed at its cap. The script uses policies that say what the work does.

## What A1 left (2026-11-10)

- **The answerer is `src/aip/model/answerer/`**, driven from `aip.sdk.Client._settle`; `docs/answerer.md`
  was the design (A2 made it `aip runah` and `docs/runah.md`, below). Its endpoint on this machine
  came from the shell (`AIP_AGENT_MODEL`, `AIP_AGENT_MODEL_KEY`, `AIP_AGENT_MODEL_NAME`; since A2
  `AIP_RUNAH_MODEL_URI`, `AIP_RUNAH_MODEL_KEY`, `AIP_RUNAH_MODEL_NAME`: Anthropic's OpenAI-compatible
  `https://api.anthropic.com/v1`, `claude-opus-5-5`), not from `aip config`. `tests/conftest.py`
  clears them for every test; `tests/test_answerer.py` reads them at import, so with the key set
  `uv run pytest -q` makes one real call (the angry branch of billing-support-agent, about a second).
- **Three built-ins ship now** (`build_procedure`, `edit_procedure`, `make_procedure`); the
  counts in `tests/test_make_procedure.py`, `test_local_server.py`, `server/test_contract.py`
  and `console/e2e/catalog.spec.ts` name them. Rebuild a `.rl` with the command in
  `src/aip/server/builtins.py` when its folder changes.
- **The proof's runs are in the local store** (`aip runs --agent a1-proof`); the folders the
  model wrote are under `scratch/a1/work/` (`refund-handling/`, and `billing-support/` as
  `edit_procedure` changed it), not committed.
- **Not done:** the MCP tools take no `answer_with` (an outside agent answers its own pauses);
  the console shows the model's entries as an agent's, without the tool calls (C4 is the chat
  pane); open item 17, a language marker for human steps, is Zach's.

## What C4 left (2026-11-10)

- **The card canvas is gone** (`console/src/canvas/`): the procedure page has no `cards` mode and a
  run's page no canvas. Its model moved to `console/src/graph/bundle.ts` (the step graph is built on
  it; the names `Card`, `Frame`, `Port` stayed) and the edits the forms still make to
  `console/src/studio/edit.ts`; the structural ones (add, remove, move, branches, reads, outputs) went,
  since the chat makes those. `console/docs/studio.md` is the design.
- **The chat runs the shipped procedures through the launcher** (`POST /console/studio/build`,
  `/edit`, and `/console/resume` with `studio: true`), `--answer-with model`, as agent `studio`. The
  draft's folder is `<workspace>/<name>`, the run's `--workdir` the workspace; a new procedure's
  folder is renamed from the brief before `build_procedure` runs, since the folder names the
  procedure. Undo copies sit beside the workspace, out of the model's reach.
- **The e2e suite runs the chat against `console/e2e/agent.mjs`**, a stand-in Chat Completions
  endpoint scripted per task (the first user message's `# Task: <step>` and the number of tool
  results so far). `e2e/aip.ts` puts its address in `CLI_ENV` as `AIP_AGENT_MODEL*`, which overrides
  whatever this machine's shell sets.
- **Not done:** the real pass with the configured model is Zach's (the plan's proof says so); the
  page shows a run's tool calls in the pane but not on History's record of it.

## What A2 left (2026-11-10)

- **`aip runah` replaced `--answer-with model`**: `Client.runah` in `src/aip/sdk.py` (the run-or-run-id
  dispatch is `_names_run`), the CLI verb, the MCP tool, `docs/runah.md`. Config is
  `aip config runah` / `AIP_RUNAH_MODEL_*`; a file holding A1's `agent_model` is read as the same
  block (`config._runah_block`). The record's model id is the reply's `model`, not the configured
  name; Anthropic's endpoint echoes the name asked for.
- **`scripts=False`** is the engine's `Engine(scripts=...)` and the run file's `scripts`; such a run
  is never posted (`Client._record`). The script cap is `aip.model.environment.script_timeout`.
- **`--work`** is `aip.sdk.reported_work`; the store keeps `work` and `work_seconds` on `Entry`, and
  `agent-work` (`src/aip/server/audit.py`) is the thirteenth audit query.
- **`build_procedure` takes a fourth input, `title`**, and its result a `procedure`; the console's
  Studio renames the draft folder to it after the run (`console/bin/aip-console.mjs`). The Studio
  has no run button, so "asks once" guards Save draft and Publish.
- **The proof's runs are in the local store** (`aip runs --agent a2-proof`); the folder the model
  built is `scratch/a2/build/inbox/`, not committed.
- **Not done:** Zach's Studio pass on a brief that needs a script (the proof's last step).

## What R7 left (2026-11-12)

- **The orchestrator is `examples/language/assist`** (shipped as `src/aip/server/bundles/assist.rl`)
  and `examples/harness/assist.py`; `docs/runah.md`, The orchestrator, is the design. `assist`'s
  `act` script (`scripts/runah.py`) is the only place with verbs: it starts each child in a
  detached process of its own (`runah.py --child <order>`) that writes the outcome to
  `<workdir>/.assist/<run id>.json`, and waits on that file within the script cap. A child has
  no run file until its first stop, so `act` knows its own children by the order files there.
- **Lineage is the engine's script environment plus the client's run file.** `Engine(script_env=,
  guard=)` (`aip.model.engine`), filled by `aip.sdk._Lineage`: `AIP_RUN_ID`, `AIP_STEP`,
  `AIP_PASS`, `AIP_RUNAH_DEPTH`, `AIP_RUNAH_BUDGET_TOKENS` (what is left), `AIP_HOME`, the
  parent's `AIP_AGENT`/`AIP_SESSION`; `steps.run_script` adds `AIP_SCRIPT_TIMEOUT`. A run file
  has `parent`, `depth`, `budget_tokens`, `tokens`; a parent's children are listed in
  `~/.aip/runs/children/<run id>` (`aip.client.runs.add_child`). The store links `SPAWNED` from
  either side (`LINK_TO_PARENT`, `LINK_TO_CHILDREN` in `store.py`). `tests/conftest.py` clears
  the five variables, since a test run from inside an aip script would inherit them.
- **The budget is checked before each step and each task's chat, not at `End`**: a run that
  passes it on its last step is done, its record showing the sum.
- **Choices made against the plan's text**, each a default: `assist` has a `search` step before
  the loop (the plan's sketch had no way for `plan` to see the catalog); what `build_procedure`
  builds is **published under its new name** (a revision, so the next search finds it, as the
  proof requires), and only a taken name goes up as a draft run by its folder; the plan step has
  runah's five workdir tools like any task (aip has no per-step tool switch), but no aip verb.
- **The proof's runs are in the local store** (`aip runs --agent r7-proof`): `build_procedure`
  run `fcef914bd57946fa` published `refund_line_counter@1`; sessions `r7-harness-2` and `-3` found
  it and built nothing; `assist` run `d3dda909b77940ea` (session `r7-assist-1`) has it as its child.
  The folder it built is `scratch/r7/proof/refund_line_counter/`, not committed.
- **Found, not fixed:** a model-written script resolved a relative path against its own
  directory (scripts run with the unpacked bundle as their current directory), not against
  `AIP_WORKDIR` as `references/language.md` says, so the first two harness runs answered "no
  folder notes". The third, with the full path in the task, counted right. Either the drafter's
  prompt says it louder or the engine starts scripts in the working directory: Zach's call.
- **Not done:** the MCP `runah` tool takes no `budget_tokens`; no e2e spec runs `assist` itself
  (`e2e/orchestrated.spec.ts` checks a parent and its child on the run pages).

## What R8 left (2026-11-12)

- **Human steps by default are `aip.model.answerer.human_steps(bundle)`** (`human.py`): a
  `Task_Agent` whose prompt opens "This is a task for a person, not for you" or whose description
  says "a person"/"the person" (or "a human") does it. The SDK applies it when `human` is None
  (so the CLI, the MCP tool and `examples/harness/assist.py` all get it); `none` or `[]` is none.
  The run file keeps `human` and `human_source` (`marked`/`listed`); a paused object's
  `answerer.human` says which. `describe` (local and the server's, `describe_bundle`, and filled
  in on read for a bundle stored before R8) carries `human_steps`; the console's picker reads it
  and keeps no rule. **The description rule is loose**: `assist`'s `plan` was caught by "a
  question for the person" in its description and had to be reworded; a drafter writing a
  description that mentions the person makes the step a person's.
- **`assist`'s `plan` answers `action: choice [run, ask, done]`** (was `done: true_or_false`);
  `Until action == done`, a `Route next_move` on it, and `ask_person` (prompt `assets/ask.md`,
  opening with the marker) produces `outcome` and `Continue`s. The audit `agent-routes` now lists
  `assist`'s route among the built-ins (`tests/test_local_server.py` leaves it out).
- **Scripts start in `AIP_WORKDIR`** (`steps.run_script`, which creates it if missing);
  `AIP_BUNDLE` is the unpacked bundle; a `Command` argument naming a bundle file is made its path
  under the bundle (`steps.launch`). R7's `refund_line_counter` counted `./notes` right with no
  full path in the R8 proof.
- **The proof's run is in the local store**: `assist` run `9623a175feca48ff` (agent `r8-proof`,
  session `r8-assist-1`), paused at `ask_person` after its first child found no `./meeting-notes`,
  answered with `aip runah 9623a175feca48ff --answers`, done with monday 2, tuesday 0, wednesday 3.
  The driver is `scratch/r8/proof.py`, not committed.

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

- Plan: https://github.com/zach-blumenfeld/aip/issues/29. Tick, comment, commit, push to `origin`.
- Public plan issues for context on how 0.7 and 0.8 were run: `gh issue view 18 -R
  zach-blumenfeld/aip` and `19` (closed 2026-11-11, superseded by this plan).
- Zach's constraints that are not in code: the design conversation stays in his `~/Documents` and
  never enters a repo; keyword lists are maintained only in the spec's glossary (the console
  colours `procedure.aip` from the extension's grammar for that reason, and keeps no list of its
  own); the console stays its own npm package (it was to stay its own repository too, until plan
  open item 13 moved it into `console/` here).
