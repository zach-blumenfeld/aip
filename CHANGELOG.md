# Changelog

All notable changes to AIP are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Track changes here as you make them. On release, rename this section to the new version (e.g., `[0.3] — YYYY-MM-DD`) and start a new `[Unreleased]` at the top.

### Changed
- **One format, defined in code (`0.4a0`).** AIP no longer has schema families. The procedure format is defined by pydantic models in `src/aip/spec/models.py`; `assets/procedure.schema.json` is generated from them (`aip schema`) and kept in sync by a test. Steps are typed by `kind`: `decision` (SystemOne questions with per-question review `thresholds`), `execution` (a script under `scripts/` with eager `assets`), `client_task` (a template under `assets/` with lazy `references`), `router` (server-side branching on a client-chosen value via `branch_on` and `branches`), and `end` (the final state shape). The first step is the start; edges are `inputs_to` by step name. Every runnable step declares `inputs` in the AIP type vocabulary, which the server enforces at runtime. Dropped `depends_on`, `parallel`, `one_of`, per-step `outputs`, and the top-level `scope_and_approval`, `modes`, `search_shortcuts`, `integrations`, and `scenarios`. Carried over: `purpose`, `trigger_when`, `do_not_use_when`, `steps`, `anti_patterns`.
- **Frontmatter** collapses `metadata.aip.spec` and `metadata.aip.schemaId` into one string key, `metadata.aip-version`, making `metadata` a plain string→string map per the Agent Skills spec.
- **`source/`** stays required for the material the skill was compiled from; it no longer bundles a schema copy.
- **Portable semantics.** The body begins with the AIP runtime block, verbatim: what AIP is, the client and server roles, the state, and what each step kind does at run time. Every skill carries it so an agent can run the skill with no aip tooling present; it loads with the body, not on demand. The canonical text ships in the package, `aip runtime` prints it, and the validator rejects a missing or edited block. `SKILL.md` gains an Execution Semantics section with the same text.
- **Validation** moved into the package (`aip.spec`) and is exposed as `aip validate`. `scripts/validate.py` is a thin wrapper that works from a plain git clone. Graph checks run after the models accept the body: unique step names, runnable start, exactly one end, every edge resolves, every step reachable from the start and able to reach the end, unique input names, thresholds name real questions, and every referenced asset, reference, and script exists on disk.
- AIP format version bumped `0.3a3` → `0.4a0`, then `0.4a0` → `0.5a0` (M4; `0.4a0` skills still validate, with a warning).

### Added
- The `aip-runtime` meta-skill (M5): `skills/aip-runtime/SKILL.md`, a plain Agent Skill under 120 lines that tells an agent to `aip search` first, read `aip info`, `aip run` the match, and answer each pause kind through `aip resume` rather than doing the steps by hand; it names the trust boundary (scripts run on the server) and is versioned with the format (`metadata.aip-version`). A copy ships in the package (`aip.spec.runtime_skill_text()`), and `aip runtime --skill [--out DIR]` prints it or writes `DIR/aip-runtime/SKILL.md`. `tests/test_runtime_skill.py` checks the frontmatter under the Agent Skills rules, that every command it names exists, the line budget, and that the two copies match. `docs/examples/aip-runtime-session.md` is the transcript of a fresh `claude -p` session that completed `billing-support` with only this skill and `AIP_SERVER` set.
- Client over HTTP (M4): `aip.client.backend.HttpBackend` implements the runner's `Backend` over `/procedures/{name}@{revision}/...`, pinning the name to one revision on first use and carrying the server's `run_id`; the run file gains `server`, `name`, `revision`, and `run_id`, and `aip resume` rebuilds the right backend from it. New commands `aip search`, `list`, `publish`, `get` (lossless, hash-verified, then validated), `pin`, `retire`, and `config` (`~/.config/aip/config.json`; `AIP_SERVER` and `AIP_TOKEN` override); `aip info` and `aip run` take a published name when a server is configured, and a folder path still bypasses it. `httpx` becomes a dependency. Format `0.5a0`: the runtime block's Running paragraph gains one sentence for the server case; skills still carrying the `0.4a0` block or `metadata.aip-version: "0.4a0"` validate with a single `runtime_block_outdated` warning.
- `aip.server.records` (M1): `SkillRecord`, `FileRecord`, `NameSummary`, `SearchHit`, `RunRecord`, `RunSummary`, with `snapshot`, `materialize`, and `revision` lifted out of `aip.db.neo4j` (which now imports them; `Bundle` stays as an alias). `aip.server.backend` defines the `CatalogBackend` and `RunBackend` protocols from the server design, and `aip.server.backends.filesystem` implements both over one directory (`catalog.json`, `skills/<name>/<revision>/` with an `.aip-manifest.json`, `runs/<id>.jsonl`, weighted term-overlap search, atomic writes). `tests/server/test_contract.py` is the backend contract suite, parametrised so the Neo4j backend can register at M2.
- `aip.server.backends.neo4j` (M2): the `CatalogBackend` and `RunBackend` contract over Neo4j, built on the 0.4 projection. Adds `Name {name, pinned}` with `HAS_REVISION` edges, `published_at` and `retired` on `Skill`, a `manifest` property so `get` returns the published record without re-deriving it from the graph, `Run` and `StepRun` nodes (`OF_SKILL`, `STEP_RUN`, `NEXT`, `OF_STEP`), a full-text index over name, description, purpose, and triggers for `search` (hits filtered to what each name resolves to, exact name boosted), and a materialisation cache under `~/.cache/aip/<name>@<rev>/<name>/` (`AIP_CACHE_DIR`) that is reused only while every file matches its hash. Both backends keep the executable copy in a folder named after the skill, with `.aip-manifest.json` beside it rather than inside it, so the loader's folder-name check holds and the published tree carries nothing extra. `aip.db.neo4j` is now a shim whose `load`, `fetch`, `export`, and `list_skills` call the backend; `aip db` keeps its subcommands, and `list` prints `published_at` with `pinned`/`retired` flags. `tests/test_db.py` is split: the record tests move to `tests/server/test_records.py`, and the database half becomes the `neo4j` parametrisation of `tests/server/test_contract.py` (skipped without `NEO4J_URI`) plus Neo4j-only tests for the shim round trip, the projection, run-to-step links, and cache invalidation.
- `aip.server.app` (M3): the HTTP API from the server design over either backend, as `create_app(backend)` on FastAPI (`server` extra: `fastapi`, `uvicorn`). Catalog endpoints (`GET /catalog`, `/catalog/search`, `/catalog/{ref}` returning the `describe()` document plus the `aip info` fields and an example start input, `/catalog/{ref}/files` as a manifest or `?archive=tar` as a deterministic tar of the folder plus its manifest, `/catalog/{ref}/files/{path}`, `POST /catalog` taking `{files: [{path, bytes_b64, mode}]}` and answering 422 with the validator's issues, `POST /catalog/{name}/pin|retire`), execution endpoints (`/procedures/{ref}/peek|step|answer|capabilities`, one per client `Backend` method; the procedure is loaded from the backend's folder for that revision and cached, `Procedure.run` does the work, and scripts run in the server process), and runs (`POST /runs`, `GET /runs`, `GET /runs/{id}`; every `step` and `answer` appends to the run named by its `run_id`, creating one when absent, with `status` running/paused/done/error and the pause block; 501 without a `RunBackend`). Errors use one envelope, `{"error": {"kind", "message", "location"?}}`, reusing `invalid_input` with the step as location. Auth is a bearer token with `read` and `publish` scopes; with no token configured the server is open, and a loopback client needs none either way. `aip server --backend filesystem|neo4j [--root DIR | --uri URI] --port N [--token T] [--read-token R]` runs it. The `CatalogBackend` protocol gains `revisions(name)` and `folder(name, revision)`, which both backends already had in substance. `tests/server/test_http.py` drives the filesystem server through the test client, including both branches of the `running.md` worked example and a hash-verified tar download.
- `dev` dependency group (`pytest`, `neo4j`) so `uv sync --group dev && uv run pytest -q` runs the suite; `docs/PLAN.md` tracks the 0.5a0 client-server rebuild milestone by milestone and is linked from the README.
- `src/aip`: the runtime package. `aip.spec` (format models, skill validation, loader), `aip.model` (stateless `Procedure.run`, input validation, server-side routing, decision collapse and review, script execution), and the `aip` CLI with `validate`, `schema`, and `info`.
- Routers branch on collapsed answers of any type: `true`/`false` for a noul, the label for a choice, the level number for a score, matched against the YAML's string keys. Previously only choice labels routed. The validator now checks a router fed by a decision only branches on values that question can produce (`unknown_branch_value`).
- `aip info`: a readable summary of a skill (purpose, triggers, the start input with types and descriptions, an example start JSON, every step with its questions, script, template, and references, and the end shape); `--example-input` prints just the start JSON, `--json` the machine form.
- `aip db load|list|export`: lossless Neo4j projection of skills (`aip.db.neo4j`, driver as the optional `neo4j` extra). Every file is stored with its bytes, mode, and sha256 so `export` rebuilds the folder byte for byte; the parsed procedure is projected as `Procedure`, `Step`, `Input`, and `Question` nodes with `INPUTS_TO`, `BRANCH`, `DECLARES_INPUT`, `ASKS`, and `USES` edges into the `File` nodes. Skills are keyed `name@revision` (content hash), so many skills and revisions coexist and reloads are idempotent.
- `aip run` and `aip resume`: a local runner over the same engine the server will use. Follows suggested inputs, pauses to a run file (exit code 3) for client tasks, low-confidence decisions, or, without a decision model, for the client to answer questions itself; `--interactive` prompts instead. Decisions answered by the client are recorded in history as manual.
- `examples/billing-support`: a complete procedure skill exercising every step kind. It is the validator fixture and runs end to end through the loader and runtime in tests.

### Removed
- `assets/base.schema.json`, `assets/aip-schemas/`, `scripts/validate_schema.py`, and the schema-family conventions (`$id` matching, bundled schema in `source/`, `aip.tag`). With one format there is nothing for them to check.

## [0.3a3] — 2026-05-28

Addresses [#6](https://github.com/zach-blumenfeld/aip/issues/6) — benchmarking surfaced regressions caused by authored scripts (not the AIP format).

### Changed
- `SKILL.md` "Prioritize `scripts/`" Best Practice: softened the absolute "MUST be backed by a script" rule. Scripting is now scoped to **deterministic/mechanical** logic over structured inputs; conditionals that hinge on interpreting or judging input data should stay **prose steps**. Added a "How to Choose Between Script and Prose Steps" subsection (Script if / Do not script if) and a "When Writing Scripts" note on leanness and runtime budget (prefer a maintained library over re-implementing a heavy solver; slow scripts risk timing out).
- `SKILL.md` functional-test step 6.4: added a **Correctness** check — run each script against the task's actual example inputs and expected outputs, not just "no errors"; logic bugs (e.g. a wrong key mapping in a conditional) only surface against real fixtures.
- AIP protocol version bumped `v0.3a2` → `v0.3a3`. All live references updated.

## [0.3a2] — 2026-05-27

### Changed
- `SKILL.md` checklist step 6.4 (functional test) tightened in response to dogfood evidence (agent skipped the step when phrased as a capability check). Named concrete mechanisms — Agent/Task tool, `claude -p` via bash, whatever the runtime exposes — converting the gate from a fuzzy capability question to a tool check. Removed the conditional "if subprocesses are available"; testing is now mandatory. Fallback when no fresh-agent mechanism exists: self-test instead of skip, with a user-facing message that clarifies fresh-agent verification did not run.
- AIP protocol version bumped `v0.3a1` → `v0.3a2`. All live references updated.

## [0.3a1] — 2026-05-27

### Added
- Anti-pattern: encoding rules, lookup tables, numeric calculations/thresholds, or other scriptable logic as prose instead of via scripts.

### Changed
- `SKILL.md` checklist: author skills in the current working directory (`./<skill-name>/`) instead of `/tmp`. Host agents often cannot spawn subprocesses under `/tmp` (blocking the functional-test step), and CWD is also where users expect the folder if they choose not to install. All references in steps 5–7 updated; the "Leave it as-is" branch now requires no move.
- `SKILL.md` "Prioritize `scripts/`" Best Practice tightened in response to dogfood evidence (agents under-using scripts). Concrete trigger list (domain-specific logic, if/then/else, lookup tables, numeric calculations/thresholds, validation against fixed rules); MUST clause when a step's description contains "if", "unless", "only when", a numeric threshold, or a table; narrow escape hatch (inputs unavailable as structured data, documented in `source/README.md`).
- AIP protocol version bumped `v0.3a0` → `v0.3a1`. All live references updated.

## [0.3a0] — 2026-05-27

### Added
- Execution-graph fields on `steps[]` items in `procedure.schema.json`: `script` (relative path under `scripts/` backing the node), `inputs` and `outputs` (named edges between nodes). A procedure body can now declare a graph of script-backed nodes connected by I/O.
- `$defs.io_item` in `procedure.schema.json` — shared shape for `inputs` and `outputs` items: `name` (required), `type` (short label, optional), `nullable` (boolean, optional, defaults to false), `description` (optional one-line summary).
- `SKILL.md` § Use Simple Type Vocabulary (under Best Practices) — small AIP type vocabulary (`string`, `integer`, `float`, `boolean`, `object`, `list[*]`) for AIP fields that declare types, starting with step inputs and outputs. Not machine-enforced; detailed type checks belong in the backing script.
- `references/author-schema.md` "Design for execution graphs" Best Practice — type the graph shape (nodes, edges, script refs); leave prose freeform on nodes where code can't carry it; push logic (decisions, branching) into `scripts/`, not typed fields. Includes a pointer to the type vocabulary.
- `SKILL.md` checklist step 6.4: optional functional test of the authored skill. Spawn 2–3 fresh host-agent sessions against the temp skill folder; evaluate against script errors, response quality, intent capture, and over-restriction. Soft step — when the runtime cannot spawn subprocesses, surface that to the user with an explicit note that structural validation and completeness check did run.

### Changed
- `SKILL.md` Best Practices: replaced "Selective Typing" with "Prioritize `scripts/`". Skills are framed as execution graphs of script-backed nodes; conditional logic belongs in `scripts/`, not in typed schema fields. Prose nodes are first-class alongside script-backed nodes — the rule is "use prose where a script would overly-restrict logic & reasoning."
- `SKILL.md` worked YAML example reworked end-to-end: demonstrates `script` / `inputs` / `outputs` on steps, drops the now-removed `decisions:` block, and runs a 3-prose / 2-script mix (`evaluate` and `record-recommendation` are script-backed; `need-analysis`, `parallel-search`, and `decide` carry reasoning in prose).
- `procedure.schema.json` top-level description and `steps` / `modes` / `scenarios` field descriptions reframed around the execution-graph model.
- `procedure.schema.json` `aip.version` bumped `0.1` → `0.3a0` (the schema's own version, kept aligned with the AIP protocol version).
- AIP protocol version bumped `v0.2` → `v0.3a0`. All live references updated across `SKILL.md`, `README.md`, `assets/base.schema.json`, `assets/aip-schemas/procedure.schema.json`, and a stale test comment.
- `README.md` content sweep: field list updated (`decisions`/`tools` dropped, script-backed nodes and I/O edges added); schema procedure description references execution-graph framing instead of "permissive-by-default"; Best Practices summary lists "designing for execution graphs"; bumping checklist dropped the stale "Current AIP version anchor" reference.

### Removed
- `decisions` field from `procedure.schema.json`. Conditional `{signal, action}` tables are runtime branching logic and now belong in `scripts/`. **Breaking:** skills validating against the procedure schema that use `decisions:` will fail validation until reworked.

## [0.2] — 2026-05-25

### Added
- `metadata.aip.version` field on the AIP skill's own `SKILL.md` frontmatter — declares which AIP protocol version the skill encodes.
- `aip.spec` field on AIP schemas — declares the AIP protocol version each schema targets, distinct from the schema's own `aip.version`.
- Validators (`validate.py`, `validate_schema.py`) cross-check that each artifact's `aip.spec` matches the version declared in this skill's `SKILL.md`; mismatch surfaces as `aip_spec_mismatch`.
- `assets/base.schema.json` — universal floor (`purpose`, `trigger_when`, plus optional `do_not_use_when` and `anti_patterns`) that every AIP schema copies from.
- `references/author-schema.md` — canonical schema-authoring reference (requirements, best practices, checklist, the chevron-replace vs. literal-copy zones in the base schema).
- Tests for `validate.py` (67 unit tests under `tests/test_validate.py`).

### Changed
- AIP skill directory structure: schema bundled in `source/` (per-skill) instead of a separate `schema/` directory. Skills now travel standalone.
- Validator output unified: both scripts emit JSON Lines with a `severity` field; warnings are advisory and don't fail the exit code.
- `validate.py` runs AIP-compliance checks on the bundled schema in-process (delegates to `validate_schema.run_all_checks`).
- Frontmatter validation tightened: name format rules (length, charset, hyphen rules), `description` length cap + whitespace rejection, `compatibility` length range, `allowed-tools` type, `license` type, non-AIP `metadata.*` string-value rule, and `metadata.aip.spec` URI form.
- Example URLs migrated to the GitHub tree URL at the version tag (e.g., `https://github.com/zach-blumenfeld/aip/tree/v0.2`).

### Removed
- Per-skill `schema/` directory (folded into `source/`).
- `validate_schema.py`'s reserved-property-name check (`id`, `schemaId`, `key`, `idx`, `_source`) — connector framing no longer load-bearing for v0.x.
- UUID-URN form requirement on `$id`; restored as a general URI form check (must contain a colon).
- Most legacy walkthrough UX in `SKILL.md` (depth selector, four always-confirm checkpoints, three-scenario explicit framing).

## [0.1] — 2026-05-17

### Added
- AIP protocol draft.
- Reference validators (`validate.py`, `validate_schema.py`).
- `aip` skill scaffold.
