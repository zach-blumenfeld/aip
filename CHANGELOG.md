# Changelog

All notable changes to AIP are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Track changes here as you make them. On release, rename this section to the new version (e.g., `[0.3] — YYYY-MM-DD`) and start a new `[Unreleased]` at the top.

### Added
- Execution-graph fields on `steps[]` items in `procedure.schema.json`: `script` (relative path under `scripts/` backing the node), `inputs` and `outputs` (named edges between nodes). A procedure body can now declare a graph of script-backed nodes connected by I/O.
- `$defs.io_item` in `procedure.schema.json` — shared shape for `inputs` and `outputs` items: `name` (required), `type` (short label, optional), `nullable` (boolean, optional, defaults to false), `description` (optional one-line summary).
- `SKILL.md` § Use Simple Type Vocabulary (under Best Practices) — small AIP type vocabulary (`string`, `integer`, `float`, `boolean`, `object`, `list[*]`) for AIP fields that declare types, starting with step inputs and outputs. Not machine-enforced; detailed type checks belong in the backing script.
- `references/author-schema.md` "Design for execution graphs" Best Practice — type the graph shape (nodes, edges, script refs); leave prose freeform on nodes where code can't carry it; push logic (decisions, branching) into `scripts/`, not typed fields. Includes a pointer to the type vocabulary.

### Changed
- `SKILL.md` Best Practices: replaced "Selective Typing" with "Prioritize `scripts/`". Skills are framed as execution graphs of script-backed nodes; conditional logic belongs in `scripts/`, not in typed schema fields.
- `SKILL.md` worked YAML example reworked to demonstrate `script` / `inputs` / `outputs` on steps and to drop the now-removed `decisions:` block.
- `procedure.schema.json` top-level description and `steps` / `modes` / `scenarios` field descriptions reframed around the execution-graph model.
- `procedure.schema.json` `aip.version` bumped `0.1` → `0.3` (the schema's own version, not the AIP protocol version).

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
