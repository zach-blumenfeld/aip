# Changelog

All notable changes to AIP are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Track changes here as you make them. On release, rename this section to the new version (e.g., `[0.3] — YYYY-MM-DD`) and start a new `[Unreleased]` at the top.

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
