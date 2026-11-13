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

- **Three built-ins shipped** (`build_procedure`, `edit_procedure`, `make_procedure`; `assist`
  since R7); the counts in `tests/test_make_procedure.py`, `test_local_server.py`,
  `server/test_contract.py` and `console/e2e/catalog.spec.ts` name them. Rebuild a `.rl` with the
  command in `src/aip/server/builtins.py` when its folder changes.
- A1's answerer (a chat model inside the run, `src/aip/model/answerer/`), A2's run-ahead verb,
  R7's runs started from runs and R8's person marker were all removed by A3, below; their
  history is in git (commits 18a540d, 9d49b53, d0bedb1, e6460bc).

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

## What A3 left (2026-11-12)

- **`aip agent` is `src/aip/agent.py`** (`docs/agent.md`): `Client.ask` runs `assist` and answers
  each pause with one call to `aip.chat.ChatClient` (moved from the removed answerer package), no
  tools, then `resume`. Sessions were `~/.aip/agent/` until A4, which reads them from the record.
  Config is `aip config agent` / `AIP_AGENT_MODEL_URI`, `_NAME`, `_KEY`; this machine's shell sets
  `AIP_AGENT_MODEL_KEY` and `AIP_AGENT_MODEL_NAME`, and a config file's blocks from earlier 0.9
  checkouts (A1's `agent_model`, A2's) are no longer read. `tests/conftest.py` clears the three for every test;
  `tests/test_agent.py` drives everything with a scripted stand-in model, so no key is needed.
- **The runtime passes `AIP_AGENT` and `AIP_SESSION` to scripts** (`Client._script_env`), with
  `AIP_RUN_ID`, `AIP_STEP`, `AIP_PASS`, `AIP_HOME`: that is how the runs `assist`'s `act` starts
  are the same agent's and session's. Nothing links a child run to its parent any more.
- **A `choice` reaches a script as its answer object** (`{"value": "run"}`, spec 2.4), so
  `act.py` reads `verb["value"]`; a script reading a choice must do the same.
- **The builders hand over text and write what they get back**: `prepare`/`snapshot` read the
  documents into `texts`, `compile` hands back the folder as `contents`, `draft`/`rewrite`/`fix`
  answer `{path: text}` objects that `scripts/write.py` writes. Each builder carries the language
  page as `references/language.md`, held equal to the skill's by `tests/test_skill.py`.
- **The live proof ran on an isolated store** (`scratch/a3/proof.py`, not committed: `AIP_HOME`,
  `AIP_LOCAL_DATA` under `scratch/a3/state`, port 8293, the notes in `scratch/a3/proof/`). Session
  `agent-20261112-202808-6b9e`: `assist` `c06b51983554455d` ran `build_procedure` `8faee3ee26244326`,
  published `count_mentions@1`, ran it (`727c321086a54db8`), monday 2, tuesday 0, wednesday 3; the same
  task again (`b8e54f2c7a2043e0`) built nothing and answered from that run in one model call. Session
  `agent-20261112-202918-fd8d`: `./meeting-notes` ran `count_mentions` straight away, which failed,
  and finished with a question; the reply ran it on `./notes` with the right counts. A first attempt
  (`scratch/a3/attempt1/`) found `act`'s publish taking a folder named like the procedure for a
  taken catalog name; fixed, with a test.
- **The console called the run-ahead verb until C6** (below). Old run files with R7's keys still
  load (`RunFile.load` drops keys it does not know).

## What C6 left (2026-11-12)

- **The console drives a run as `aip agent` does.** The launcher (`console/bin/aip-console.mjs`,
  `stream` and `nextOf`) runs `aip run --progress`; at a pause whose step is not one of the run's
  `person` steps it runs `aip agent --answer <run_id> --progress` (`Client.answer` in the SDK, the
  same four tries `aip agent` makes at a pause, `aip.chat.answer_once` since A4) on the same event stream, until the run is done,
  fails, or waits for a person. It holds back each process's final object and relays only the last,
  with `answerer: {person, reason}`. The Studio's person step is `ask_user` (`STUDIO_PERSON`, in the
  launcher and in `src/api/console.ts`); the run console's picker starts with nothing ticked.
- **Every answer in such a run is the page's agent** (`console` or `studio`): the model's carry
  `model` in `answered_by` and `work: "reported"` with tokens and seconds, the person's no model.
  That is how the record tells them apart now that no `runah` agent exists.
- **The e2e stand-in model** (`console/e2e/agent.mjs`) answers A3's builders with no tools: `draft`
  with `{procedure, drafted: {path: text}}`, `rewrite` with `rewritten`, read off `before`. The
  approval brief's `approve` step lost its person marker; the spec ticks it in the picker.
- `console/e2e/orchestrated.spec.ts` (R7's parent link) is removed, and with it the record's
  `parent`, `tokens`, `children` and `budget_tokens` in `src/api/types.ts` and `Record.tsx`.

## What A4 left (2026-11-12)

- **`src/aip/agent.py` is the loop, whole** (19 lines, one function of four parameters, shown
  verbatim in `docs/agent.md`; `tests/test_agent.py` fails if it grows past 40 lines, gains a
  function or a parameter): run `assist` on the text and the session's history, and at each
  pause one answer and up to three corrections, catching `RunError` and nothing else. The
  plumbing is in `aip.chat`: `history` (the session from the record, oldest first; it replaced
  `inputs` and `continuation`), `message_for`, `parse` (a reply with no JSON object is a
  `RunError` that changed nothing, so the one `except` covers it), `refused` (which raises a
  `RunError` that `stopped` the run again), `reason`, `work_of`, `references_of`, `pause_view`
  (which `assist`'s `act.py` imports), `answer_once` (the same four tries, for `Client.answer`
  and the console's `aip agent --answer`; six lines twice, so the file stays the point),
  `refusal_of` and `observed`, which wraps `chat` to say `aip agent --answer`'s `answer` and
  `refused` lines. `ChatClient` is the `chat` callable (`ChatClient(url, key, model)(messages)`),
  timing its call. Progress is the client's own: `Client.on_step` is what `run` and `resume` use
  when a call names none, so `aip agent --progress` sets it and the loop carries nothing. The
  command says on stderr why it stopped short: `aip agent: gave up at <step> after 4 answers:
  <last reason>` (the run left paused, exit 1; `Client.ask` sets `gave_up` from the last reply and
  `last_refusal`, the reason `resume` gave) or `aip agent: the model's endpoint failed: <why>`
  (`ChatError`, uncaught by the loop).
- **No session files.** `--session ID`, else `AIP_SESSION`, else `aip.new_session()`; the command
  prints `session:` and the export line on stderr. `--new` and `--json` went; `aip agent` prints
  `aip run`'s object plus `session`. `Outcome`, `Sessions`, `pause_view` in `aip.agent`, the
  `on_event` of `Client.ask` and its progress events went; `AgentError` is `aip.NoAgentModel`.
- **A same-session repeat** still reads as a reply to the last note, as in A3.

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
