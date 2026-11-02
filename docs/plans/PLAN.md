# Plan: the inspector, view by view

Milestones for `aip-inspector`, the browser client of the AIP server API. This is M7 of
the aip repo's `docs/PLAN.md`, broken into pieces the same loop can work through. The
design is §10 of `docs/server-design.md` in the aip repo; the API is §4.2 and §7 there.
Each milestone leaves `npm run build` and `npm run e2e` green.

## How to use this plan

For an agent told "implement the next unchecked milestone, run the tests, tick it
off, commit":

- Work on `main` in this repo. The server lives in the sibling aip repo (`../aip`,
  branch `aip-0.5a0`); read its `src/aip/server/app.py` for the exact response shapes
  before typing them in `src/api/types.ts`. Do not edit the aip repo from here except
  where a milestone says so (I6).
- Where this plan and the design disagree, the design wins; note it in the commit.
- Tests: `npm run typecheck && npm run e2e`. The e2e harness needs `uv` and a chromium
  from `npx playwright install chromium`, or `PLAYWRIGHT_CHANNEL=chrome` to use an installed
  Chrome.
- Each milestone is one commit (or a few, each green). Ticking off means changing
  `- [ ]` to `- [x]` on the heading and adding one line under it:
  `Done <date>, commit <short sha>: <one-sentence note>`. End commit messages with
  `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Do not start the next milestone in the same session; stop after the commit and
  report what the proof printed.
- Keep dependencies few. React and Vite are decided; add a library only when a
  milestone names the need (graph layout in I1, diffing in I2).

## - [x] I0 — Scaffold

Done 2026-10-03: Vite + React + TypeScript, base `/inspector/`, dev proxy for the four
API prefixes, a typed `api` client with the error envelope and bearer token, a catalog
table, and a Playwright harness that boots `aip server` from `../aip`, publishes
`billing-support`, and asserts it appears.

## - [x] I1 — Catalog and the procedure page

Done 2026-10-04, commit 7258323: hash router, search over `/catalog/search`, the procedure page with revision switcher and per-step cards, and the step graph as inline SVG from a hand-rolled layered layout (no dagre/elkjs: a handful of nodes per procedure does not justify the dependency); `npm run typecheck` clean, `PLAYWRIGHT_CHANNEL=chrome npm run e2e` 4 passed, the drawn graph checked by screenshot.

Scope: view 1 of §10.

- Routing: a hash router (`#/`, `#/p/<name>[@rev]`, later `#/runs/<id>`), so the
  bundle serves from one path under `aip server --inspector` with no fallback rule.
  Hand-rolled or `react-router` in hash mode; either is fine.
- Catalog page: the table gains a search box over `/catalog/search` (the ranked hits
  replace the table while the query is non-empty) and links to the procedure page.
- Procedure page from `GET /catalog/{name}`: description, purpose, triggers,
  do-not-use-when, anti-patterns, the start input with the example JSON, the revision
  list with the pin marked, and the step graph: one node per step coloured by kind,
  `inputs_to` edges, router branches as labelled edges, the end step marked. Layered
  layout rendered as inline SVG (hand-rolled in `src/graph/layout.ts`; swap in dagre
  or elkjs only if a real procedure draws badly).
- Revision switcher (`name@rev`) re-fetches the page.

Proof:

```
npm run typecheck && npm run e2e     # new spec: procedure page shows every step name of billing-support as a graph node, and the router's branch labels
```

## - [x] I2 — Source and revision diff

Done 2026-10-05, commit 06608e7: source page with the manifest (size, sha256, mode) and a text/binary file viewer, diff page with manifest status by hash and a hand-rolled LCS line diff for changed text files (no diff library: files are a few KB); `npm run typecheck` clean, `PLAYWRIGHT_CHANNEL=chrome npm run e2e` 7 passed, both pages checked by screenshot.

Scope: view 2.

- File manifest from `/catalog/{name}/files` with size and sha256; a file viewer over
  `/catalog/{name}/files/{path}` (text shown monospace, binary offered as download).
- Diff between two revisions of the same name: manifest-level (added, removed,
  changed by hash) and a line diff for changed text files, computed client-side.

Proof: e2e publishes a second revision of `billing-support` with one line changed,
opens the diff, and asserts that line is the only change shown.

## - [x] I3 — Run console

Done 2026-10-05, commit 85fd66c: `#/run/<ref>` drives peek → step/answer like the CLI runner, with forms for the manual decision, the client task, and the review pause, per-step cards (distributions and threshold crossings, branch taken, script stdin/stdout, rendered task and references, state before and after), and per-run threshold overrides sent as `thresholds`; the calm branch asserts the drafted reply rather than `ticket_id`, since by the design it never runs the script; `npm run typecheck` and `npm run build` clean, `PLAYWRIGHT_CHANNEL=chrome npm run e2e` 10 passed, the console checked by screenshot at the decision, the client task, and the end.

Scope: view 3; the same `/step` and `/answer` calls the CLI makes.

- Pick a procedure, fill the start input from `example_input`, step. Each step card
  shows the state before and after, a decision's questions with full distributions and
  which crossed its threshold, the router's branch, a script's stdin and stdout, and a
  client task's rendered template with the references it may load.
- Pauses (decision without a model, client task) are answered in a form; the console
  posts `/answer` with the run's `run_id` and continues.
- Threshold overrides per question for this run, sent as `thresholds`.

Proof: e2e drives `billing-support` through both branches (angry runs the script
server-side; calm pauses as a client task and is answered in the UI) and asserts
`ticket_id` appears at the end of each; both runs show as `done` in `GET /runs`.

## - [x] I4 — History

Done 2026-10-05, commit cb148c8: `#/runs` lists `GET /runs` newest first with name and status filters in the hash query, and `#/runs/<id>` replays `GET /runs/{id}` over the I1 step graph (visited nodes and the exact edges walked, from consecutive history entries, highlighted) with the I3 step cards read-only and the pause block shown; the e2e drives both branches through `/answer` and `/step` itself since spec files run in parallel; `npm run typecheck` and `npm run build` clean, `PLAYWRIGHT_CHANNEL=chrome npm run e2e` 13 passed, both pages checked by screenshot.

Scope: view 4.

- `GET /runs` filtered by name and status; a run page from `GET /runs/{id}` replaying
  its history as a trace over the step graph from I1 (visited nodes and taken edges
  highlighted, step cards from I3 reused read-only).

Proof: e2e opens the runs from I3 and asserts the angry run's trace highlights the
script step and the calm run's highlights the client task.

## - [x] I5 — Governance

Done 2026-10-05, commit 84d4433: a Governance box on the procedure page (pin/unpin, retire behind an inline confirm, the per-question threshold overrides as one map), `#/governance` answering every `GET /governance` query as a table with name/window/limit filters and a 501 shown as "needs the Neo4j backend", and `#/server` for the URL and token; per the design (§11) the token lives in `sessionStorage`, not the `localStorage` this plan named; the proof's premise did not hold since the e2e server has no decision model and I3's manual decisions never count as overridden, so the spec seeds one model-answered run through the backend's `RunBackend` and asserts `overridden-decisions` lists `triage`/`tone`; `npm run typecheck` and `npm run build` clean, `PLAYWRIGHT_CHANNEL=chrome npm run e2e` 16 passed on both a fresh and a reused root, both pages checked by screenshot.

Scope: view 5 and §7.

- Pin and retire from the procedure page (publish scope; the token lives in the
  Server page's `localStorage`).
- Per-question threshold overrides via `GET|POST /catalog/{name}/thresholds`.
- The corpus queries from `GET /governance` rendered as lists; a 501 from the
  filesystem backend shows as "needs the Neo4j backend", not an error.

Proof: e2e pins a revision and sets a threshold override, reloads, and sees both;
`overridden-decisions` lists the decision the calm run overrode in I3.

## - [x] I6 — Packaging: `aip server --inspector`

Done 2026-10-05, commit 41adbf2: `npm run sync` copies `dist/` into `src/aip/server/inspector/` of `AIP_REPO`, replacing the directory; in the aip repo (commit 6be3247 on `aip-0.5a0`) `create_app(inspector=dir)` mounts the bundle with StaticFiles at `/inspector/` (bare `/inspector` redirects) and a missing bundle answers a 404 in the error envelope naming the directory and `npm run build && npm run sync`, `aip server --inspector [DIR]` takes the packaged directory or a given `dist/`, the synced bundle is committed there and lands in the wheel, and `tests/server/test_http.py` covers the mount, the 404, the flag and the packaged copy; here the e2e's aip server starts with `--inspector dist` after `npm run build`, and a second Playwright project `bundle` runs every spec against it after the `vite` project on the same root; `npm run typecheck` and `npm run build` clean, `uv run pytest tests` 128 passed, `PLAYWRIGHT_CHANNEL=chrome npm run e2e` 32 passed on a fresh and a reused root, and `aip server --inspector` served the page and both assets with 200.

Scope: the built bundle ships inside the aip package. This milestone edits the aip repo.

- A script here (`npm run build && npm run sync`) copies `dist/` to
  `src/aip/server/inspector/` in `AIP_REPO`.
- In the aip repo: `aip server --inspector` mounts that directory at `/inspector`
  (StaticFiles, `index.html` at the root); a test that `GET /inspector/` returns the
  page when the bundle is present and 404 with a clear message when it is not.
- This repo's e2e gains a second project that runs the same specs against the
  served bundle instead of Vite.

Proof:

```
cd ../aip && uv run aip server --backend filesystem --root /tmp/aip-root --inspector   # open http://localhost:8000/inspector/
```

## Not in this plan

Editing procedures in the browser; user accounts beyond the shared token; views across
more than one server.
