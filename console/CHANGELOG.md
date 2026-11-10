# Changelog

All notable changes to the AIP console are documented in this file. The console is an npm package,
`aip-console`, with its own version; it declares the oldest `aip` it works with (`MINIMUM_AIP` in
`bin/aip-console.mjs`) and its version tracks the runtime release it targets.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Targets aip 0.9.0: procedures are written in the language (`procedure.aip`) and compiled to bundles, the server keeps
bundles, drafts and the record of runs in one graph, and a run pauses only for the agent (the aip repo's plan, C1).
The console now lives in the aip repository, under `console/`; its history came with it. The work the 0.8 console had
under way (the Studio on format 0.8) was never released and is superseded by this.

### Added
- **The step graph is back as the procedure page's main view** (the aip repo's plan, C3), drawn from the 0.9 bundle's graph: steps as nodes with their kind, a route's branches and its confidence check on its arrows. A `For` or a `Loop` is a node of its own, with its name, its kind and one line of what it runs over or until and its cap; its body hangs beside it (to the right drawn down, below drawn to the right) like an indented block, the way in is a short arrow from the loop node to the body's first step, `Continue` comes back to the loop node along a rail between the two, and the loop's exit carries straight on past the body, so a loop reads as a cycle and a nested loop as a cycle hung off another. There are no frames. Its modes are **control flow**, **data flow** (pick a key or a step and its arrows are drawn, from each producer to each reader; a table of every key is the overview, with the source class on a route's read), **run traffic** (arrows weighted and badged by the recorded runs of the revision that took them, with a summary and a table) and **cards**, the card canvas. A **direction** toggle draws every mode down or to the right, and the choice is remembered. `#/p/<ref>?view=data|traffic|cards` opens a mode.
- **A run's page draws the run's path over the graph**, beside its record: the steps it reached and the arrows it took heavy, an arrow a loop repeated badged with how many times, a loop node badged with the passes the run made of it, the step it waits at or failed at marked. A procedure with loops is wider than the column beside the record, so its path takes the row and the record is below it. The run console draws it at every stop. Folder mode draws all of it from `aip compile --json`, with traffic from this machine's runs of the folder.

### Changed
- **The procedure page is a card canvas.** One card per step, with its kind as a badge, its description as the title, what it reads and produces, a decision's questions, an aggregate's aggregations, and one port per way out that quotes the description of the step it leads to. A route has a port per label and one for its confidence check, and says whose answer steers it. Loops are frames around their cards. Pan, zoom, fit; click a card to read the lines of `procedure.aip` that wrote it. It is drawn from the bundle's own graph (`GET /catalog/{ref}/graph`, or `aip compile --json` for a folder) by a component with no console state in it (`src/canvas/`), which the VS Code extension will reuse.
- **The source view shows the stored `procedure.aip` in the colours of the grammar the VS Code extension ships**, read from the extension at build time (`src/highlight/`: a small TextMate tokenizer, no copy of the grammar or of a keyword list), beside the bundle's files. The diff compares two revisions file by file, `procedure.aip` among them.
- **A run's page reads the 0.9 record.** Each step says how long it took and the run where its time went (its steps, the model, waiting on agents); a decision says which model answered and how sure it was; a task says which agent and session answered and after how long; a route says what it read, where it went, and whether its check fired and on what numbers; an aggregate says how each answer counted and which the confidence bar turned, and that it has no confidence of its own. A loop's passes are nested under the loop, each with the test that let it run, and the loop says why it ended. The same view is on the run console at every stop.
- **A pause may carry several tasks.** The passes of a `For` batch waiting at one step are shown together, each with its prompt, state and a field per key it answers with (radios for a `true_or_false`, a `choice` or a `score`), and are answered together by one resume. A task in the last pass a loop's cap allows says so. There is no decision pause any more: a `Decide` is the decision model's, and a run with none fails with `no_decision_model` and says how to configure one.
- **History filters by agent, session, user, and draft or published**, beside procedure and status, and the address carries the filters. Every run the console starts is recorded as agent `console` in the browser tab's session.
- **Drafts.** A bundle the server holds with no revision (from a run of a folder or an `.rl` file) wears a `draft` badge, on its page and on each of its runs. Drafts are not in the catalog; a toggle lists them apart.
- **Governance is Audit**: the tab and the route (`#/audit`) follow `aip audit` and `GET /audit`. The filters are the queries' parameters (procedure, agent, session, user, draft or published, how many recent runs, how many rows, and the key `lineage` needs); a query that cannot run without a parameter says which. Stored queries work on both of the server's backends.
- **Folder mode takes a program directory** (`procedure.aip`), shows its canvas and the compiler's diagnostics, runs it unrecorded, and lists this machine's runs of it.
- **The launcher calls the 0.9 CLI.** `MINIMUM_AIP` is `0.9.0` and the version line it reads is `aip <version> language <language>`. `/console/run` and `/console/resume` pass `--inputs` and `--answers`; `/console/procedure` is `aip info --json`; `/console/graph` is `aip compile --check --json` on the folder; `/console/record` and `/console/runs` are `aip runs --json`; `/console/wake` starts the local server (`aip config server local`) when it has stopped, which the page asks for when nothing answers. The stream's first event is `process` (it was `session`, which now means the run's session).
- **The release workflow** is `.github/workflows/console-release.yml` in the aip repository, runs from `console/`, and tags `console-vX.Y.Z`.

### Removed
- **The arrow back to an earlier step.** The language no longer has `Again` (the aip repo's plan, L7): a loop's check is written inside the loop, so every cycle in a procedure is a loop node, in by the arrow from the loop to the first step of its body and back by `continue`. The step graph draws no rail on the far side of a body, the card canvas has no `again` port, and a pass in the record holds its own check.
- **The Studio** (`src/studio`, its views, `docs/studio.md`, `docs/studio-lint.md`, `examples/studio`, its specs and the runtime-block parity test), with the launcher's `validate`, `upgrade`, `probe` and `handoff` endpoints and the `--aip-spec` option. It was a second model of a procedure with its own serializer and linter. It returns as the card canvas with editing, where every operation is a text edit in `procedure.aip` checked by the compiler (the aip repo's plan, C2).
- **Skill zips** (upload on the catalog, download on a procedure): a procedure is published as a bundle with `aip publish` and fetched with `aip get`.
- The hand-rolled step graph and its data-flow and run-traffic modes: the canvas shows what a step reads and produces on its card.

### Added
- **`npm test`**: node's test runner over the modules that need no browser (the tokenizer, the canvas's model and layout, the history nested under its loops, the forms' typing, the launcher's reading of what `aip` prints).
- **A decision model for the e2e run** (`e2e/model.mjs`): an endpoint with the TypeSafe API shape that answers from marks in the text it is given, so a spec steers every branch of a procedure from the inputs it types.

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
