# Plan: rebuild toward the server design

Milestones to get from the 0.4a0 code (tag `v0.4a0`) to format 0.5a0, the client-server
architecture in [`server-design.md`](server-design.md). This is a new line, not a patch
on 0.4: the work happens on branch `aip-0.5a0`, and 0.4a0 stays what it is. Each milestone says what it keeps, replaces, or
deletes, and ends with a command or test that proves it works. Milestones are ordered;
each is independently mergeable and leaves `aip run <folder>` working.

Baseline today (`uv run --with pytest --with neo4j pytest -q`): 60 passed, 1 skipped
(the Neo4j test without `NEO4J_URI`), 16 subtests. Keep that green at every milestone.

## How to use this plan

For an agent told "implement the next unchecked milestone, run the tests, tick it
off, commit":

- Work on branch `aip-0.5a0` in this repo. Do not touch `main` or `aip-s1` and do
  not merge; `main` is still the 0.3a3 line and is merged by hand later. Do not push
  unless asked.
- The design is [`server-design.md`](server-design.md); read the sections a
  milestone cites before coding. Where this plan and the design disagree, the
  design wins; note the disagreement in the commit message.
- Run tests with `uv run pytest -q` once M0 has landed; before that,
  `uv run --with pytest --with neo4j pytest -q`.
- Use `uv run aip ...` for the CLI. A globally installed `aip` on this machine may
  point at a different clone (the `aip-skillbench` bootstrap installs its own), so
  never rely on it to prove a milestone here.
- The `aip-skillbench` harness bootstraps from tag `v0.4a0`, so nothing here affects
  it until it is re-bootstrapped; do not edit that repo from here.
- Docker is available for the Neo4j milestones; the proof blocks give the exact
  `docker run` line. Stop the container when done.
- Each milestone is one commit (or a few, each green). Ticking off means changing
  `- [ ]` to `- [x]` on the milestone heading and adding one line under it:
  `Done <date>, commit <short sha>: <one-sentence note>`. Then `CHANGELOG.md`
  "[Unreleased]" gets a line. End commit messages with
  `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Do not start the next milestone in the same session; stop after the commit and
  report what the proof command printed.
- M7 lives in a separate repo and is not part of this loop; skip it when it is the
  next unchecked item and say so.

## Inventory and verdicts

| Path | Verdict | Why |
|---|---|---|
| `src/aip/spec/` (models, skill, loader, runtime.md) | keep | the format; the runtime block text and version change (M4) |
| `src/aip/model/` (procedure, steps, resources, types) | keep | `Procedure.run` is the server's engine as-is |
| `src/aip/client/backend.py` | keep, extend | `Backend` protocol stays; `HttpBackend` is added beside `LocalBackend` |
| `src/aip/client/runner.py` | keep, extend | `RunFile` gains server fields; the loop does not change |
| `src/aip/client/cli.py` | keep, extend | new commands added; `db` re-pointed |
| `src/aip/db/neo4j.py` | replace | split: the records and hashing move to `aip.server.records`; the Cypher becomes `aip.server.backends.neo4j`; `aip db` becomes a thin alias over the backend |
| `src/aip/server/__init__.py` | replace | one-line docstring today; becomes the package |
| `tests/test_db.py` | replace | becomes the Neo4j half of the backend contract tests |
| `tests/test_spec.py`, `test_model.py`, `test_runner.py` | keep | extended, never rewritten |
| `scripts/validate.py` | keep | plain-clone validator, unchanged |
| `examples/billing-support/` | keep | the fixture for every milestone |
| `SKILL.md`, `references/`, `assets/procedure.schema.json` | keep | the authoring skill; §Running gains the server case (M4) |
| `docs/running.md` | keep, amend | add the HTTP case (M4) |
| `README.md`, `CHANGELOG.md` | keep, amend | per milestone |
| `pyproject.toml` | amend | `server` extra (fastapi/uvicorn or starlette), `dev` group with pytest |
| `notes.md` | delete | stale 0.3 to-do list; superseded by this file (it is gitignored anyway) |
| `.claude/skills/search-first/` | delete | a 0.2-format experiment inside the repo; untracked, confuses the project-skill scan |
| `scratch/` | leave | gitignored working notes; not part of the build |

## - [x] M0 — Test tooling and housekeeping

Done 2026-10-03, commit 39a636e: dev group and README link landed, dead files removed, 60 passed / 1 skipped.

Scope: make the tests runnable without ad-hoc `--with`; clear the dead experiments.

- Add `[dependency-groups] dev = ["pytest>=8", "neo4j>=6"]` to `pyproject.toml`.
- Delete `.claude/skills/search-first/` and `notes.md` from the working tree.
- Add `docs/PLAN.md` (this file) and link it from the README.

Proof:

```
uv sync --group dev && uv run pytest -q        # 60 passed, 1 skipped
ls .claude/skills notes.md 2>&1 | grep -c "No such"   # 2
```

## - [x] M1 — Records and the backend interface, filesystem backend

Done 2026-10-03, commit 19ea0d8: records, protocols, and filesystem backend landed; contract suite 13 passed, full suite 73 passed / 1 skipped, `aip db` round trip verified against Neo4j.

Scope: the storage contract from §5 of the design, with one implementation that
needs nothing but a directory.

- New `src/aip/server/records.py`: `SkillRecord`, `FileRecord`, `NameSummary`,
  `SearchHit`, `RunRecord`, `RunSummary`; `snapshot(folder) -> SkillRecord`,
  `materialize(record, out_dir)`, `revision(files)`. These are `Bundle`, `snapshot`,
  `materialize`, `_revision` lifted out of `db/neo4j.py` unchanged in behaviour.
- New `src/aip/server/backend.py`: the `CatalogBackend` and `RunBackend` protocols.
- New `src/aip/server/backends/filesystem.py`: `catalog.json`, `skills/<name>/<rev>/`,
  `.aip-manifest.json`, `runs/<id>.jsonl`, in-memory term-overlap search, atomic
  writes.
- New `tests/server/test_contract.py`, parametrised over backends (only the
  filesystem backend registers at this milestone): publish `examples/billing-support`;
  `resolve("billing-support")`, `"billing-support@<rev>"`, `"@latest"`; `search("refund")`
  ranks it first and `search("zzz")` is empty; `files()` round-trips byte for byte
  through `materialize`; `publish` of the materialised copy yields the same revision;
  `pin`/`retire` change `resolve`; `create`/`append`/`get`/`list` on runs.
- `db/neo4j.py` imports its record helpers from `aip.server.records`; `aip db`
  behaviour unchanged.

Proof:

```
uv run pytest -q tests/server/test_contract.py -k filesystem
uv run pytest -q                                 # old suite still green
```

## - [x] M2 — Neo4j backend on the existing projection

Done 2026-10-03, commit faa3339: Neo4j backend, `aip db` shim, and the Neo4j contract parametrisation landed; server suite 38 passed against Docker Neo4j (host port 17687, since 7687 was held by a stale gvproxy mapping), full suite 92 passed with `NEO4J_URI` and 74 passed / 18 skipped without; `aip db load` twice gave the same id and `db list` showed one revision. Follow-up: both executable copies now sit in a folder named after the skill (`skills/<name>/<rev>/<name>/`, `<cache>/<name>@<rev>/<name>/`) with the manifest beside it, so the loader's folder-name check holds and the published tree carries nothing extra.

Scope: the default backend, built from the Cypher that exists today.

- New `src/aip/server/backends/neo4j.py`: the projection queries move here; adds
  `Name {name, pinned}` with `HAS_REVISION`, `published_at` and `retired` on `Skill`,
  `Run` and `StepRun` nodes (`NEXT`, `OF_STEP`), a full-text index over description,
  purpose, and triggers for `search`, and a materialisation cache under
  `~/.cache/aip/<name>@<rev>/` verified by hash.
- `src/aip/db/neo4j.py` becomes a compatibility shim: `load`, `fetch`, `export`,
  `list_skills` call the backend. `aip db` keeps its CLI shape.
- `tests/test_db.py` is folded into `tests/server/test_contract.py` as the Neo4j
  parametrisation (skipped without `NEO4J_URI`), plus the existing byte-for-byte
  export assertion.

Proof (against a local Neo4j):

```
docker run -d --name aip-neo4j -p 7687:7687 -e NEO4J_AUTH=neo4j/password neo4j:5
NEO4J_URI=neo4j://localhost:7687 NEO4J_PASSWORD=password uv run pytest -q tests/server
NEO4J_URI=neo4j://localhost:7687 NEO4J_PASSWORD=password uv run aip db load examples/billing-support
NEO4J_URI=neo4j://localhost:7687 NEO4J_PASSWORD=password uv run aip db list     # billing-support, one revision
docker rm -f aip-neo4j
```

## - [x] M3 — HTTP server

Done 2026-10-03, commit 90bf51a: FastAPI app over either backend with catalog, execution, and runs endpoints, the error envelope, bearer scopes, and `aip server`; `tests/server/test_http.py` 12 passed, full suite 87 passed / 19 skipped without `NEO4J_URI` and 106 passed with Docker Neo4j on port 17687; the proof printed `[]` from `/catalog`, and a curl traversal published `billing-support`, ran the angry branch's script server-side (`ticket_id` returned), and listed the run as `done` with 4 steps. Uploads are JSON only (no multipart); `step`/`answer` responses also carry `name` and `revision` for the client's run file.

Scope: §4.2 of the design over either backend; the server executes scripts.

- `pyproject.toml`: `server = ["fastapi", "uvicorn"]` extra.
- New `src/aip/server/app.py`: catalog endpoints (`/catalog`, `/catalog/search`,
  `/catalog/{name}`, `/files` with `?archive=tar`, `/files/{path}`, `publish`, `pin`,
  `retire`), execution endpoints (`/procedures/{name}/peek|step|answer|capabilities`),
  runs (`/runs`, `/runs/{id}`), error envelope, bearer token with `read`/`publish`
  scopes, localhost-without-token.
- Execution: `load_procedure` on the backend's folder (filesystem: in place; Neo4j:
  the cache), `Procedure.run` per request, `run_id` appended through `RunBackend`.
- `aip server --backend filesystem|neo4j --root DIR | --uri URI --port N --token T`.
- New `tests/server/test_http.py` using FastAPI's test client over the filesystem
  backend: publish, search, info, a full traversal of `billing-support` through
  `/step` and `/answer` reproducing the `running.md` worked example (angry branch
  runs the script server-side, calm branch pauses as a client task), tar download
  hash-verified, 401 on publish without the scope, 501-free runs listing.

Proof:

```
uv run pytest -q tests/server/test_http.py
uv run aip server --backend filesystem --root /tmp/aip-root --port 8000 &
curl -s localhost:8000/catalog | jq .                    # []
kill %1
```

## - [x] M4 — Client over HTTP, catalog commands, runtime block, format 0.5a0

Done 2026-10-03, commit 4914cbb: `HttpBackend`, server-aware run files and `resume`, the seven catalog commands, `info`/`run` by name, and format 0.5a0 with the 0.4a0 block and version accepted under one `runtime_block_outdated` warning; full suite 100 passed / 20 skipped without `NEO4J_URI`, and the proof against a live filesystem server printed `billing-support@124d4a7b6208abed` from publish, ranked it first for "refund", paused `aip run billing-support` on `decision` (exit 3), resumed to `"done": true` with `ticket_id`, showed `"done"` from `/runs`, and `aip get` + `aip validate` passed. `httpx` became a core dependency; the `aip-skillbench` packs (other repo) were not touched and will validate with the warning.

Scope: §4.1 and §8 of the design. After this milestone an agent needs only the
client and the server URL.

- `src/aip/client/backend.py`: `HttpBackend(server, token, name)` implementing the
  five `Backend` methods; `run`/`answer_decision` carry `run_id`.
- `src/aip/client/runner.py`: `RunFile` gains `server`, `name`, `revision`, `run_id`;
  `resume` rebuilds the right backend from the file. Loop unchanged.
- `src/aip/client/cli.py`: `search`, `list`, `publish`, `get`, `retire`, `pin`,
  `config`; `info` and `run` accept a name when a server is configured
  (`~/.config/aip/config.json`, `AIP_SERVER` overrides); folder paths bypass the
  server as today.
- `src/aip/spec/runtime.md`: one added sentence for the server case; `FORMAT_VERSION`
  → `0.5a0` (also `metadata.aip-version` in the example, the schema `$id`, the
  CHANGELOG section); the validator accepts the 0.4a0 text and
  `metadata.aip-version: "0.4a0"` with a `runtime_block_outdated` warning, not an
  error, throughout the 0.5a line. `SKILL.md`, `docs/running.md`,
  `examples/billing-support/SKILL.md`, and the `aip-skillbench` packs re-validate.
- `tests/test_runner.py`: the existing runner tests re-run against `HttpBackend` via
  the test client (same assertions, backend parametrised).
- `tests/server/test_http.py`: `get` after `publish` reproduces the folder byte for
  byte and `publish` of that folder returns the same revision.

Proof:

```
uv run pytest -q
uv run aip server --backend filesystem --root /tmp/aip-root --port 8000 &
export AIP_SERVER=http://localhost:8000
uv run aip publish examples/billing-support                      # billing-support@<rev>
uv run aip search "refund"                                       # billing-support first
uv run aip info billing-support --example-input > start.json
uv run aip run billing-support --input start.json                # exit 3, pause: decision
echo '{"billing": true, "tone": "angry"}' > answers.json
uv run aip resume .aip/runs/<file> --input answers.json          # "done": true, ticket_id present
curl -s localhost:8000/runs | jq '.[0].status'                   # "done"
uv run aip get billing-support --out /tmp/x && uv run aip validate /tmp/x/billing-support
kill %1
```

Also: `uv run aip validate examples/billing-support` passes with the new runtime
block, and validating a copy that still carries the 0.4a0 text yields the
`runtime_block_outdated` warning and exit 0.

## - [x] M5 — The `aip-runtime` meta-skill

Done 2026-10-03, commit df4d854: `skills/aip-runtime/SKILL.md` (102 lines, versioned with the format) with its package copy, `runtime_skill_text()`, and `aip runtime --skill [--out DIR]`; `tests/test_runtime_skill.py` 9 passed, full suite 109 passed / 20 skipped without `NEO4J_URI`; the proof wrote `<out>/aip-runtime/SKILL.md` and `head -5` showed the frontmatter. Fresh-agent check done with `claude -p` from an empty directory (`--setting-sources project` so only this skill loaded, `AIP_SERVER` at a filesystem server on port 8765): it invoked the skill, ran `config` + `search` → `info` → `run` (paused on `decision`, exit 3) → `resume` to `"done": true` with `ticket_id`, 7 turns, and never fetched the procedure's SKILL.md (the one `/files/SKILL.md` request in the server log is `aip info` rendering its summary); transcript at `docs/examples/aip-runtime-session.md`, and `/runs` showed the run as `done`.

Scope: §9 of the design; the one page of directions, shipped with the package.

- New `skills/aip-runtime/SKILL.md` (plain Agent Skill, under 120 lines), copied
  into the package as `aip/spec/aip-runtime/SKILL.md`; `aip runtime --skill [--out DIR]`
  writes it.
- A test that the skill's frontmatter validates under the Agent Skills rules in
  `check_frontmatter` and that every command it names exists in `COMMANDS`.
- Fresh-agent check: spawn a subagent (or `claude -p` from an empty directory)
  with only this skill under `.claude/skills/` and `AIP_SERVER` set, give it the
  billing task in plain words, and confirm from its transcript that it completed
  `billing-support` through `search` → `info` → `run` → `resume` without reading
  the procedure's own SKILL.md. Save the transcript as
  `docs/examples/aip-runtime-session.md`. If no agent can be spawned, say so in
  the tick-off note and leave the file out; the unit test still gates the milestone.

Proof:

```
uv run pytest -q tests/test_runtime_skill.py
uv run aip runtime --skill --out /tmp/skills && head -5 /tmp/skills/aip-runtime/SKILL.md
```

## - [ ] M6 — Governance

Scope: §7 and §10.5 of the design on the server side.

- `POST /catalog/{name}/thresholds` and server-side per-question overrides merged
  under a request's `thresholds`.
- Named corpus queries in `aip.server.backends.neo4j.queries`: decisions most
  overridden, scripts failing most in the last N runs, procedures missing
  `do_not_use_when`, router branches never taken; the filesystem backend answers the
  first three by scanning run files and returns 501 for the graph-only ones.
- `GET /governance/{query}` serving them.
- Contract tests for the overrides and for each query against a seeded run history.

Proof:

```
uv run pytest -q tests/server -k governance
uv run aip server --backend filesystem --root /tmp/aip-root --port 8000 &
curl -s localhost:8000/governance/overridden-decisions | jq .   # a list (empty is fine)
kill %1
```

## - [ ] M7 — `aip-inspector`

Scope: §10 of the design, in its own repo, against the API only.

- Views in order: catalog with the step graph drawn; source and revision diff; run
  console (fill the example start input, step, answer pauses); history; governance.
- Served by `aip server --inspector` from a built bundle in the package, or standalone
  against any server URL.
- End-to-end test in that repo: start a filesystem-backed server with
  `billing-support` published, drive the run console through both branches in a
  headless browser, assert the run appears in history.

Proof:

```
aip server --backend filesystem --root /tmp/aip-root --inspector   # open http://localhost:8000/inspector
```

and the inspector repo's own e2e test.

## What `aip-skillbench` does after M5

Mode 4 (`aip-runtime`) becomes: `aip server --backend filesystem` in the trial
container, `aip publish` the task's pack at setup, mount only the `aip-runtime`
skill, memory file pointing at `AIP_SERVER=http://localhost:8000`. Mode 3 keeps
mounting the pack artifact. Its `prompts/four-modes-plan.md` is revised then.

## Not in this plan

- Editing procedures in the browser; authoring stays with the aip skill.
- Remote data access for scripts (an `assets` upload); scripts read what the server
  can read.
- The server running client tasks against a model of its own.
- Multi-tenant auth beyond one token with two scopes.
