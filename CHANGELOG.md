# Changelog

All notable changes to AIP are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Track changes here as you make them. On release, rename this section to the new version (e.g., `[0.3] — YYYY-MM-DD`) and start a new `[Unreleased]` at the top.

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
