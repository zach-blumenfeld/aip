# Changelog

All notable changes to the AIP console are documented in this file. The console is an npm package,
`aip-console`, with its own version; it declares the oldest `aip` it works with (`MINIMUM_AIP` in
`bin/aip-console.mjs`) and its version tracks the runtime release it targets.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Targets aip 0.8.0 and format 0.8 (explicit start step, free producers, confidence instead of thresholds; the aip repo's plan issue #18).

### Changed
- **The Studio's model, serializer and linter follow format 0.8.** A step of kind `start` holds the procedure's inputs and names the first runnable step (any position; the export writes it first). A decision has a `confidence` list (the questions whose `<question>_confidence` it emits) and a `fallback` flag instead of `thresholds`; a router has an optional confidence check (`key`, `below`, `to`), applied before its branches. The linter adds `missing_start_step`, `multiple_start_steps`, `edge_into_start`, `unknown_confidence_question` and `unbranchable_type`, drops the one-producer rule (`duplicate_producer` is now **info**, a new tier, with every producer named), generalises type agreement to every declaration of a key (the first in step order is the reference), checks a router's confidence key as a `float` produced on some path to it, and classifies what feeds each router as deterministic, measured or unmeasured (`classifySources`), warning on `confidence_on_unmeasured_source` and `unmeasured_route` and noting `declared_confidence`. `unknown_threshold_question` and the Studio-only `no_thresholds` warning are gone. `docs/studio-lint.md` lists the codes.
- **Lint parity covers every severity.** `e2e/lint-parity.spec.ts` compares the linter with `aip-spec validate` on errors, warnings and infos over the migrated fixtures.
- **The embedded runtime block is format 0.8** (`src/studio/runtime-0.8.ts`); an imported 0.5a1, 0.6a0 or 0.6a1 skill gets aip-spec's upgrade note, which names `aip upgrade`.

### Added
- **`POST /console/upgrade`**: the launcher runs `aip upgrade` on a skill's files and answers with the rewritten SKILL.md, the command's report and the validator's issues; `upgradeDraft` in `src/studio/import.ts` re-imports the result. The Studio's button for it comes with the views.

## [0.7.1] — 2026-11-02

The first release cut by the GitHub Actions workflow; 0.7.0 was published by hand from a laptop. No change to the console itself.

### Changed
- **The release workflow stages instead of publishing.** `npm stage publish --provenance` by trusted publishing puts the version in npm's staging area, and the maintainer approves it with 2FA on npmjs.com (or `npm stage approve`); nothing is installable before that. No npm token exists anywhere.

### Added
- **Apache-2.0 license**, the same as the aip repo: a `LICENSE` file in the package and `license` in `package.json`.

## [0.7.0] — 2026-11-02

The first release on npm: `npx aip-console`. It targets aip 0.7.0, the first release of the runtime on PyPI (`agent-instruction-protocol` and `aip-spec`), and refuses an older `aip`. Before this the console was run from a checkout of the repository, tagged alongside the runtime (`v0.6a1`).

### Added
- **The Studio** (`#/studio`): build a procedure in the browser, with the step graph, a step editor, typed inputs and outputs with key pickers, and a linter that runs on every edit. The linter is a TypeScript port of aip-spec's frontmatter, schema, graph and state rules in three tiers (error, unfinished, warning) plus Studio-only rules (`docs/studio-lint.md`); an e2e test keeps it in agreement with `aip-spec validate`. Import a skill zip or a catalog revision, keep several drafts, export a skill zip with a placeholder for each script and template, and publish it. **Complete with an agent** writes the scaffold to `<workdir>/studio/<name>/` with one prompt to paste into a coding agent; the Studio watches the folder, validates the agent's work with the real `aip-spec`, checks it against the design, runs its scripts, and only then lets you accept it. `--aip-spec PATH` (or `AIP_SPEC_BIN`) names the validator. Reference in `docs/studio.md`, a tutorial in `examples/studio/README.md`.
- **Skill zips**: download a revision from the catalog, publish one from a zip; names whose every revision is retired are hidden unless asked for.
- **Run traffic** on the procedure page: a third graph mode weights each edge by the runs that took it, for the selected revision.

### Changed
- **The step graph** draws loops on a rail outside the steps they span, bends an edge that skips layers around the steps between, and has a left-to-right toggle.
- **aip 0.7.0 is the minimum.** The install hints name the PyPI packages (`uv tool install agent-instruction-protocol`, `uv tool install aip-spec`) or the aip repo's installer; the format's files the tests compare against live at `packages/aip-spec` in the aip repo, and the agent prompt says so.
- **Releases** are cut by a manual GitHub Actions workflow (`.github/workflows/release.yml`): it refuses a version that is already tagged, builds and packs, tags, publishes to npm with provenance, and creates the GitHub Release from this file's section; `target: dry-run` is the rehearsal. (From 0.7.1 it stages instead, see there.) `AGENTS.md` carries the repo map and the release steps for agents, which prepare releases and never publish.
