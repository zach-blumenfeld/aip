# Changelog

All notable changes to the AIP format are documented in this file. The runtime (the `aip`
package: client, server, inspector) has its own changelog at
https://github.com/zach-blumenfeld/aip/blob/main/CHANGELOG.md; versions `0.3a3` and earlier
below predate the split and cover both.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Track changes here as you make them. On release, rename this section to the new version (e.g., `[0.6a2] — YYYY-MM-DD`) and start a new `[Unreleased]` at the top.

## [0.6a1] — 2026-10-19

A validator release: format `0.6a1` is `0.6a0` with one more rule and a new heading on the runtime block. A `0.6a0` skill still validates, with a `runtime_block_outdated` warning that says to regenerate the block and bump `metadata.aip-version`; nothing else in the skill changes.

### Added
- **Type agreement (`type_mismatch`).** A key has one type everywhere it is declared: the validator now checks that every step's `inputs` entry carries the type its producer declares (a start input's declaration, a decision question's collapsed type: `noul` is `boolean`, `choice` is `string`, `score` is `integer`, or an execution/client_task step's `outputs` entry). Before, only the key's presence was checked, so a consumer could declare `ticket_id` as `string` while its script printed an integer and the mismatch surfaced only at run time.

## [0.6a0] — 2026-10-18

Breaking: `0.5a1` skills do not validate. Upgrading one takes three edits: declare `outputs` on each `execution` and `client_task` step, add a `requires` block when the skill has scripts, and replace the runtime block with `aip-spec runtime` (setting `metadata.aip-version` to `"0.6a0"`). The validator's `runtime_block_outdated` message for a `0.5a1` skill says exactly that, ahead of the `missing_outputs` and `missing_requires` errors that name the steps; the `aip` repo's `docs/upgrading.md` walks through `billing-support` as the example.

- **Format `0.6a0` (breaking): declared outputs and the one-producer rule.** `execution` and `client_task` steps declare `outputs` (name, type, description, like `inputs`); a decision's outputs are its question names; routers and the end step add nothing, and the end step's `inputs` are the procedure's result. The validator adds three rules: every consumed key is produced on every path to its consumer or declared on the start step (`unproduced_input`); each key has exactly one producer and is never a start input (`duplicate_producer`); every `client_task` declares `outputs` (`missing_outputs`). The runtime block says the state only grows. `0.5a1` skills are recognised and rejected with `runtime_block_outdated` (now an error); `0.4a0` is no longer recognised. The `billing-support` example declares `escalate -> ticket_id, queue` and `reply -> reply`, and its script no longer echoes `message`.
- Decision steps take `history` (default `false`): when set, the run's history goes to the decision model alongside the declared inputs. An execution script's stdin is described as `{state, assets, expects}` with `state` holding only the declared inputs; `billing-support`'s script reads `state`.
- The `0.6a0` runtime block says each step sees only its declared inputs: a script's stdin is `{"state": <the step's inputs>, ...}`, a decision is answered from the step's inputs (and the run so far only with `history: true`), a client-task template renders from the step's inputs, and a failing script stops the run to be reported, not done by hand.
- **`requires` and `command`.** A procedure with `execution` steps must declare `requires`: `interpreter` (`name`, optional minimum `version`), `packages` (pip names, optionally `name>=version`), and `tools` (executables on PATH); without it the validator reports `missing_requires`. An execution step may set `command`, the argument list that launches its script from the script's folder (default `python <script>`); its first item must be the interpreter or a declared tool (`undeclared_launcher`). The runtime block tells the agent to check `requires` before the first script and to honour `command`. `billing-support` requires python 3.10.

## [0.5a1] — 2026-10-06

The first tagged release of the spec as its own repo. It carries the `0.4a0` and `0.5a0` format work below, which were cut in the `aip` repo without a release section.

### Added
- **`aip-spec`, the format as its own distribution.** The spec moved out of the `aip` repo into this one: the pydantic models, the validator, the runtime block, the `aip` authoring skill, and the `billing-support` example. The package is `aip_spec`, its version is the format version, and it needs only pydantic and pyyaml; `aip` now depends on it. `SPEC_URL` and the schema `$id` point at this repo.
- The `aip-spec` CLI: `validate <folder>` (the output contract below), `schema [--write PATH]`, `runtime`, `skill install [agent] [--path DIR]` / `skill list` / `skill remove`, `example <name> --out DIR`, and `--version`. `scripts/validate.py` is gone: the CLI is the one validator, and the installer puts it on PATH. `aip_spec.skill_dir()` and `aip_spec.example_dir(name)` return the authoring skill and an example as bundled in the wheel (hatchling `force-include` of the repo-root files), falling back to the checkout.
- `install.sh`: installs uv if missing, `uv tool install`s this package at its tag, and runs `aip-spec skill install`, non-fatal when no agent is detected. Agent detection (`aip_spec.agents`) covers Claude Code, Cursor, Windsurf, Copilot, Gemini CLI, Cline, Codex, Pi, OpenCode, and Junie, and is shared with `aip skill install`.
- `SKILL.md`: the validator line is `aip-spec validate ./<skill-name>`; the functional-test step runs the skill with the `aip-runtime` skill when installed and otherwise by executing the procedure per the runtime block, naming no `aip` command; `compatibility` names `uv`.

### Changed
- **Format `0.5a1`: the runtime block addresses the executing agent, not an AIP client.** The "Running" section (`aip run`, `aip search`, the pause and resume loop) is gone, and the Client and Server roles collapse into "You": the agent supplies each step's input, runs its script, answers its questions, performs its task, follows its router, and has the final say. A skill compiled to the spec stands on its own as a structure any agent can execute; the client-side story lives in the `aip-runtime` skill shipped with the `aip` package. The authoring skill's guidance says "the agent" or "free-form reasoning" where it said "the client", and names no `aip` command outside the validator lines and the functional-test step. `0.5a0` skills do not get a legacy entry: their block no longer validates.
- **One format, defined in code (`0.4a0`).** AIP no longer has schema families. The procedure format is defined by pydantic models in `src/aip_spec/models.py`; `assets/procedure.schema.json` is generated from them (`aip-spec schema`) and kept in sync by a test. Steps are typed by `kind`: `decision` (SystemOne questions with per-question review `thresholds`), `execution` (a script under `scripts/` with eager `assets`), `client_task` (a template under `assets/` with lazy `references`), `router` (server-side branching on a client-chosen value via `branch_on` and `branches`), and `end` (the final state shape). The first step is the start; edges are `inputs_to` by step name. Every runnable step declares `inputs` in the AIP type vocabulary, which the server enforces at runtime. Dropped `depends_on`, `parallel`, `one_of`, per-step `outputs`, and the top-level `scope_and_approval`, `modes`, `search_shortcuts`, `integrations`, and `scenarios`. Carried over: `purpose`, `trigger_when`, `do_not_use_when`, `steps`, `anti_patterns`.
- **Frontmatter** collapses `metadata.aip.spec` and `metadata.aip.schemaId` into one string key, `metadata.aip-version`, making `metadata` a plain string→string map per the Agent Skills spec.
- **`source/`** stays required for the material the skill was compiled from; it no longer bundles a schema copy.
- **Portable semantics.** The body begins with the AIP runtime block, verbatim: what AIP is, the client and server roles, the state, and what each step kind does at run time. Every skill carries it so an agent can run the skill with no aip tooling present; it loads with the body, not on demand. The canonical text ships in the package, `aip-spec runtime` prints it, and the validator rejects a missing or edited block.
- **Validation** moved into the package and is exposed as `aip-spec validate`. Graph checks run after the models accept the body: unique step names, runnable start, exactly one end, every edge resolves, every step reachable from the start and able to reach the end, unique input names, thresholds name real questions, and every referenced asset, reference, and script exists on disk. Routers branch on collapsed answers of any type: `true`/`false` for a noul, the label for a choice, the level number for a score, matched against the YAML's string keys; the validator checks a router fed by a decision only branches on values that question can produce (`unknown_branch_value`).
- Format `0.5a0`: the runtime block's Running paragraph gains one sentence for the server case; skills still carrying the `0.4a0` block or `metadata.aip-version: "0.4a0"` validate with a single `runtime_block_outdated` warning. AIP format version bumped `0.3a3` → `0.4a0` → `0.5a0`.
- `examples/billing-support`: a complete procedure skill exercising every step kind. It is the validator fixture here and runs end to end through the loader and runtime in the `aip` repo's tests.

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
