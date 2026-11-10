# AGENTS.md (console)

The repository's `AGENTS.md`, one level up, is the one to read first: the privacy rule, the plan
issue, the conventions and the release rules all hold here. This file says only what differs for
`console/`.

## What this folder is

The console for AIP, the npm package `aip-console`: the catalog, each procedure as a step graph
and a card canvas with its source, the run console, history and the audit queries. It was a repository of its own
(`aip-console`) through 0.8 and moved here at plan milestone C1 with its history (`git log --
console/`). One small Node launcher (`bin/aip-console.mjs`) serves the built page and runs
procedures through the `aip` CLI on this machine; the aip server serves no UI. The package
installs two commands, `aip-console` and `aip-inspector` (the old name, kept one more release).

It never vendors the Python package: the launcher runs whatever `aip` is on the PATH, and the
e2e harness runs this checkout's (`AIP_REPO`, default `..`) behind `uv run`.

## Map

| Path | What's there |
|---|---|
| `bin/aip-console.mjs` | the launcher: arguments, `aip --version` against `MINIMUM_AIP`, the `/console/*` endpoints (run, resume, cancel, procedure, graph, record, runs, wake), the static server; loopback only. Its header comment lists every endpoint |
| `src/api/` | `types.ts` the shapes the page reads (the server's replies, the run record); `client.ts` the server's API, called directly; `console.ts` the launcher's endpoints and the CLI's JSON lines |
| `src/canvas/` | **the card canvas**, a component on its own with no console state: `model.ts` (a bundle's graph as cards, ports and frames), `layout.ts` (where they go; fixed sizes that `canvas.css` repeats), `Canvas.tsx`. The procedure page draws a revision with it; E2 bundles this folder into the VS Code extension and C2 adds editing on top, so nothing here may import from outside the folder |
| `src/graph/` | **the step graph**, the procedure page's main view: `model.ts` (steps as nodes, loops as frames, the control edges as arrows, built on the canvas's model), `layout.ts` (a layered layout done per level, innermost loop first, so a loop is a frame placed like a node; down or right), `dataflow.ts` (who produces and who reads each key), `traffic.ts` (a run's path over the graph from its history, and many runs folded into traffic). `views/StepGraph.tsx` draws it, `views/Steps.tsx` is the section with its modes and the run's path, `views/Traffic.tsx` reads the runs |
| `src/highlight/` | `textmate.ts`, a small TextMate tokenizer, and `Code.tsx`, which runs it over the grammar and the colours of `../editors/vscode` (imported at build time: there is no copy of the grammar or of a keyword list here) |
| `src/record/model.ts` | a run's flat history nested under its loops, pass by pass, and the words for why a pass ran and why a loop ended |
| `src/run/answers.ts` | a form's fields as the JSON `aip run --inputs` and `aip resume --answers` take |
| `src/views/` | the pages: `Catalog`, `Procedure` (and `FolderProcedure`), `Source`, `Diff`, `Run`, `History` (the list and one run), `Record` (the record view both run pages share), `Audit`, `Server` |
| `test/` | `npm test`: node's test runner over the modules above that need no browser, on fixtures written by the real compiler and server (`test/fixtures/`) |
| `e2e/` | `npm run e2e`: Playwright specs and the harness. `prepare.mjs` writes `.aip-e2e/` from `../examples/language`, `model.mjs` is a decision model that answers from marks in the text (`[angry]`, `[unsure]`, `[break:WORD]`), `aip.ts` runs the checkout's CLI, `global-setup.ts` publishes; `playwright.config.ts` starts the model, the aip server and two consoles |
| `docs/plans/` | the historical plans; current plans are issues |
| `CHANGELOG.md` | the console's changelog |

## Conventions that differ

- **Node 24, npm** (22.18 is the least for `npm test`, which runs TypeScript as it is). `npm
  install` to set up; `npm run typecheck && npm test && npm run e2e` must pass before a commit
  that touches this folder. The e2e suite needs `uv`, Relate installed in the checkout's `.venv`
  (`../scripts/install-relate.sh`; the server it starts stores in it) and a browser (`npx
  playwright install chromium`, or `PLAYWRIGHT_CHANNEL=chrome`).
- **Keep dependencies few.** Add a library only when a milestone names the need: the canvas
  layout, the diff and the grammar tokenizer are hand-rolled for that reason. There is no
  runtime dependency: the launcher is Node's standard library and the page is built.
- **The modules `test/` imports** (`canvas/model.ts`, `canvas/layout.ts`, `graph/*.ts`,
  `highlight/textmate.ts`, `record/model.ts`, `run/answers.ts`) import each other with the `.ts` extension and use only
  syntax node can strip (no enums, no parameter properties), so they run under node unbuilt.
- **Where the console and the runtime disagree, the runtime wins**: `../docs/cli-json.md` for the
  CLI's JSON, `../docs/server-design.md` and `../src/aip/server/app.py` for the API,
  `../docs/language/bundle.md` for the graph the canvas reads. Fix the console in the same
  commit as the change it follows.

## Versioning and releasing

The console has its own version (`package.json`, kept in step with `package-lock.json` by `npm
version X.Y.Z --no-git-tag-version`) and its own tag, `console-vX.Y.Z`; it tracks the runtime
release it targets. `MINIMUM_AIP` in `bin/aip-console.mjs` is the oldest `aip` the launcher
accepts and moves when the console starts to depend on something newer in the CLI's JSON or the
server's API.

Releases are cut by `.github/workflows/console-release.yml`, run by hand after the release PR is
merged: it builds and packs from `console/`, pushes the tag, **stages** the version on npm with
trusted publishing (no token), and cuts a GitHub Release from the matching `## [X.Y.Z]` section
of `console/CHANGELOG.md`. A staged version is not installable until the maintainer approves it
with 2FA on npmjs.com (or `npm stage approve <stage-id>`); `target: dry-run` rehearses without
uploading or tagging. An agent's job is prep only: set the version, finalize the changelog
(one `## [X.Y.Z] — <date>` section, the heading format is awk-matched), open the PR. Never build,
tag, stage, approve or publish by hand. npm's trusted publisher for `aip-console` has to name
this repository and `console-release.yml` (it named the old repository's `release.yml`).
