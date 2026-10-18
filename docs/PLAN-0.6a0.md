# Plan: format 0.6a0, the state contract and client-side execution

A fresh agent implements one milestone per session:

    /clear
    Implement the next unchecked milestone in @docs/PLAN-0.6a0.md. Run the tests, tick it off, commit.

Read "Context" and "Rules", then only your milestone. Each milestone names the test or command
that proves it.

## Context

Design: `docs/client-execution.md` (accepted; supersedes `server-design.md` §6 and §7),
`docs/state.md` (how state moves, the gaps, the proposed pause shapes), `docs/run-modes.md`
(local versus served runs). Read all three once; they are short.

Two tracks. **A, the state contract**: steps declare outputs, the validator proves every key has
one producer, the runtime hands each step only its declared inputs, pauses are trimmed to what
the step needs, run files live under the user's home. **B, the client runs everything**: scripts
and decisions move from the server to the client, which executes next to the data and reports
results with attribution; the server keeps the procedure, the routing, the validation and the
one copy of each run's state and history. A is format work in aip-spec
plus small runtime changes and is testable on a laptop with `billing-support`; B builds on A.
Together they are breaking, so this is format **0.6a0**: a new `format:` value, a validator that
accepts 0.6a0 only, and `runtime_block_outdated` for skills that still carry the 0.5 block.

Repos: `~/dev/aip-spec` (format, validator, authoring skill), `~/dev/aip` (runtime, client,
server, SDK), `~/dev/aip-inspector` (the UI bundle). aip depends on aip-spec by git URL, so every
aip-spec milestone ends with a tag and a bump of that URL in aip.

**Packaging decisions (2026-10-18).** One runtime, in Python, exposed as a Python SDK; the CLI
and agent frameworks (ADK, LangGraph) sit on it. No TypeScript runtime: a TypeScript SDK, if one
is ever wanted, must have full parity, so it is a separate product decision, not part of this
plan. The UI is renamed **console** (`aip-console`), with **inspector** kept as a synonym: the npm
package installs both commands and the docs say "the console (formerly inspector)" once. It is
a separate repo and an npm package: `npx aip-console --server URL` (or a folder) starts a Node process that serves the UI, calls the server directly for catalog, runs
and governance, and for interactive runs spawns the `aip` CLI (`aip run --progress`,
`aip resume --progress`) and relays its JSON lines to the page. The CLI's JSON output is therefore
a documented contract (A3): fixed shapes for pauses, done, and errors, one line per step under
`--progress`, tracebacks only under `--debug`. The server serves no UI and no executor; `aip
server --inspector` is removed. The console checks `aip --version` at startup and refuses
versions below its minimum. Future console features (publish button, graph editor,
drag-and-drop compile) use the same two channels: server API for data, CLI subprocess for
anything that touches the local machine; compile additionally needs authoring to become
`aip-spec author` rather than living in aip-skillbench's `convert`. Not 0.6a0 work.

## Rules

- Branch `aip-0.6a0` in aip, `v0.6a0-dev` in aip-spec, `inspector-0.6a0` in aip-inspector. Commit
  each milestone; push only when the milestone says.
- Never change the 0.5a1 behaviour on `main` or `aip-0.5a0`; everything lands on the new branches.
- Every milestone's test is the proof. No milestone is ticked without its command passing.
- Keep docs current as you go: `docs/state.md`, `docs/run-modes.md`, `docs/running.md`, and the
  aip-runtime meta-skill text are part of the deliverable when behaviour they describe changes.
- Nobody is watching. Do not ask questions; if blocked, write `BLOCKED: <why>` under the
  milestone and stop.

---

## Track A: the state contract

### - [x] A1 (aip-spec): declared outputs and the one-producer rule

Done 2026-10-18: aip-spec `94d45ad` (format, validator, example) and `45b5191` (authoring SKILL.md, a
separate commit for line-by-line review), tagged `v0.6a0-dev1` locally, not pushed. aip's aip-spec
URL is still on 0.5a1: A2 does the bump, which needs the tag pushed so uv can resolve it.

Add `outputs` to execution and client_task steps (same shape as `inputs`: name, type,
description). Decision steps' outputs are their question names. Routers and the end step add no
keys to the state: a router consumes its branch key and records the choice in history only; the
end step's `inputs` are the procedure's result, the keys handed back at `done`, and under A2 the
final state is exactly those keys. The start step's `inputs` are what the client supplies. Validator rules, each with its own
message:

1. every key a step consumes is produced by a step on every path to it, or declared on the
   start step;
2. each key is produced by exactly one step and is not a start input (no overwrites, no
   collisions);
3. a client_task's `outputs` are what `answer_with` will show, so they must be declared.

Bump `format: 0.6a0`. Update the authoring skill so it writes `outputs` and explains the rules.

Test: `uv run pytest -q` with new cases: `billing-support` validates after gaining `outputs`
(`escalate` -> `ticket_id, queue`; `reply` -> `reply`); the aip-skillbench dialogue-parser skill
fails rule 1 naming `script_path, output_json, dot_path, image_path`; a fixture with two steps
producing `tone` fails rule 2. Tag `v0.6a0-dev1`.

### - [x] A2 (aip): the runtime hands each step only its declared inputs

Done 2026-10-18. Needed a small format addition first: aip-spec `ad84e4d` adds `history` (default
false) to decision steps and has `billing-support`'s script read `state`, tagged `v0.6a0-dev2`.
Tags `v0.6a0-dev1` and `v0.6a0-dev2` are pushed (the branch is not) so uv can resolve the pin; aip
now pins `v0.6a0-dev2`, so B2's tag becomes `v0.6a0-dev3`. Following A1, the done state is the
state projected to the end step's `inputs`: for `billing-support` that is just `message`, and
`ticket_id`/`reply` are only in the history. The client-task pause's `expects` is now the step's
`outputs`.

In `aip.model`: a step's `render` projects the state to its declared `inputs` before anything
sees it. Scripts get `{"state": <declared keys>, "assets": ..., "expects": ...}` on stdin
(`currentState` renamed; keep reading the old key for one version). Decisions send
`{"state": <declared keys>}` to the decision model, with `history` only when the step declares
`history: true`. A step's result is validated against its declared `outputs` (missing or
mistyped keys fail the step) and merged into the server-held full state. Bump the aip-spec URL.

Test: `uv run pytest -q` with cases: the escalate script's stdin contains exactly `message` and
`tone`; a script that returns an undeclared key fails with the key named; a decision payload has
no `history` unless declared. `aip run ./billing-support` end to end on both branches.

### - [ ] A3 (aip): the three outcomes, the pause shapes, and the meta-skill

A run stops one of three ways and the CLI prints one JSON object for each, exit code 0 for
paused and done, non-zero for error:

- **paused**: shapes as specified in `docs/state.md`: `paused`, `step`, `task`, `state`
  (declared keys only), `references`, `answer_with`, `run_id` for client tasks; `questions` and
  `state` for decisions; `state`, `proposed_answers`, `review` for reviews. Remove `suggested`,
  the `resume` string, and the framing paragraph prepended to client-task templates. Answers
  merge over the held state, not over a resent copy.
- **done**: `done`, `run_id`, `state`.
- **error**: `error` (kind: `script_failed`, `invalid_input`, `invalid_output`, `requires_unmet`,
  `timeout`, `server`), `step`, `run_id`, `resumable`, and per kind: `script`, `exit_code`,
  `stderr`; or `missing`/`invalid` key lists; or the unmet requirement. No traceback unless
  `--debug`. The run keeps the state before the failing step; `aip resume <run_id>` with no
  input retries that step.

`--progress` on `run` and `resume` emits one JSON line per completed step
(`{"event":"step","step":...,"kind":...,"to"|"resolver"|"seconds"}`) before the final object.
Without it, output is the final object only. Document all shapes in `docs/cli-json.md`.
Rewrite the aip-runtime meta-skill and the runtime block text for 0.6a0; re-record
`docs/examples/aip-runtime-session.md`.

Test: `uv run pytest -q` asserting the pause, done and error JSONs in the docs against the CLI's
actual output (run id normalised); a failing escalate script yields `script_failed` with its
stderr and exit code 1, and `aip resume` retries it; `--progress` on the angry branch emits
three step lines; the meta-skill validates; `aip-spec validate` on a 0.5a1 skill reports
`runtime_block_outdated`.

### - [ ] A4 (aip): run files under the user's home, keyed by run id

`aip run` writes `~/.aip/runs/<run-id>.json` (override with `AIP_HOME`), prints the id in every
pause, and `aip resume <run-id>` finds it; `--run-file` keeps working for explicit paths. Local
runs get a generated id.

Test: `aip run ./billing-support --input start.json`, `cd /tmp`, `aip resume <id> --input
answer.json` continues. `uv run pytest -q`.

---

## Track B: the client runs everything; the server keeps the run

The theme of this track. Today the server executes scripts and answers decisions, and the
client resends the whole state and history on every call. After this track the roles are
reversed and clean: the **client** executes every execution step next to the data, resolves
every decision with its own decision model, performs client tasks, and reports each result with
attribution; the **server** is responsible for control flo, holds the procedure at a pinned revision, routes, validates inputs
and outputs, keeps the one copy of each run's state and history, and answers governance. The
server never runs user code and never holds a model key. Local runs with no server are the same
client doing both jobs in one process. B1 moves the run record to the server; B2 gives the
client what it must check before executing; B3 moves scripts; B4 moves decisions.


### - [ ] B1 (aip): the server holds the run

New request shape for served runs: `POST /runs` with the start input opens a run and returns
the first pause or the first execution step to perform; `POST /runs/{id}/result` carries one
thing (a script result, decision answers with attribution, or a client-task answer). The server
loads the run from its backend, validates, merges, routes, stores, and replies with the next
pause or execution step, filtered per A2. Nothing per run stays in process memory. The backend
`append` takes an expected version and refuses a stale write. Thresholds are the author's, from SKILL.md, and nothing else: remove the per-name override
endpoint (`/catalog/{name}/thresholds`) and the `--threshold` run flag, so a run's behaviour is
fixed by its revision. When the server hands the client a decision step it sends the questions
and their thresholds together (the client holds only scripts and assets). A failed step is recorded on the run with the state before it and
status `failed`; a `result` post with no body retries it. The client run file shrinks to id,
server, revision, pending pause; `aip resume` sends only the answer. Keep `/step` and `/answer` for one version behind a
deprecation header.

Test: `uv run pytest -q` with: two `create_app` instances over one filesystem root serve
alternating requests of a single run; two concurrent `result` posts for one run, one 409;
`GET /runs/{id}` shows state and history identical to what a local run of the same inputs
produces. The run file after a pause contains no `history` and no accumulated state.

### - [ ] B2 (aip-spec, then aip): environment declaration and launch command

Format: skills with execution steps must carry `requires` (interpreter and minimum version,
packages, tools) and an execution step may carry `command` (default `["python", "<script>"]`).
Validator requires `requires` when execution steps exist. Authoring skill updated. Tag
`v0.6a0-dev3`. aip: the client checks `requires` against the local machine before the first
execution step and stops with one message naming every missing item; `command` is honoured.

Test: aip-spec `uv run pytest -q` (skill with scripts and no `requires` fails); aip `uv run
pytest -q` (a skill requiring package `nosuchpkg` stops before any script with `nosuchpkg` in the
message; a `command: ["bash", "x.sh"]` step runs).

### - [ ] B3 (aip): the client executes scripts

On a served run the client fetches the pinned revision's `scripts/` and `assets/` into
`~/.aip/cache/<name>@<revision>/` (content-hashed, verified against the manifest, never
`SKILL.md`), and when the server replies with an execution step it runs the script locally with
the A2 stdin contract, cwd the cached script folder, file side effects relative to the run's
recorded working directory, and posts the result. On failure it posts exit code, stderr and
timeout so the server's failing-scripts query still works. The server stops executing scripts
entirely; delete its interpreter-building code and the `/step` executor path once B1's
deprecation window closes. Interactive human runs happen in the console, which is a client
(Track I).

Test: `uv run pytest -q` with a served `billing-support` whose escalate script writes a file:
server and client in separate temp roots, the file appears on the client side, the server's
run record holds the result; a script that exits 2 shows in `GET /governance/failing-scripts`.
Contract test: `aip get` then `aip publish` still round-trips the revision.

### - [ ] B4 (aip): the client resolves decisions with attribution

The client answers decision steps with the decision model when `TYPESAFE_API_KEY` is configured
on the client (`aip config --decision-model`), applies the step's thresholds as sent by the server,
pauses for review when a question falls under its threshold, and posts answers with attribution
`{resolver: typesafe|manual, model, confidence, reviewed}`. The server validates against the
question types and records attribution in history; it no longer reads a model key.
`capabilities.decision_model` is removed from the server's capabilities. Governance:
`overridden-decisions` reports the resolver; add `manual-decisions` (answered with no model).

Test: `uv run pytest -q` with a fake decision client: history entries carry attribution; a
below-threshold answer yields a review pause with `proposed_answers`; `aip run` with no key
pauses as a manual decision and records `resolver: manual`.

---

## Track S: the SDK

### - [ ] S1 (aip): a public Python SDK surface

`aip.Client(server=None, token=None)` with `search`, `info`, `run`, `resume`, `publish`, `get`,
`validate`, `runs`, `governance`, `pin`, `retire`, each returning typed results and raising
typed errors; a
folder instead of a server gives the local backend. The CLI commands become thin wrappers over
it (no logic left in `cli.py` that the SDK cannot do). Documented in `docs/sdk.md` with a
LangGraph-style tool example.

Test: `uv run pytest -q` runs `billing-support` end to end through `aip.Client` against both a
folder and a served catalog; every CLI command has a test asserting it calls the SDK.

## Track I: the console (formerly inspector) ships on its own

The console already lives in its own repo (`~/dev/aip-inspector`; rename to `aip-console` when
convenient, with the old name kept as a GitHub redirect), but today it is delivered
through aip: `npm run sync` copies the built bundle into `src/aip/server/inspector/`, aip's
wheel carries it, and `aip server --inspector` serves it. This track changes the delivery, not
the repo: the console becomes its own npm package with its own Node launcher, the sync step
and the server mount are removed, and aip ships no UI. The console then needs the `aip` CLI on
the machine for interactive runs and talks to the server directly for everything else.


### - [ ] I1 (aip): remove the served UI; version handshake

Delete `aip server --inspector`, the StaticFiles mount, and `src/aip/server/inspector/`.
`aip --version` prints `aip <version> format <format>` on one line for the console's startup
check. Nothing else in aip is console-specific.

Test: `uv run pytest -q`; the server answers 404 on `/inspector/`; `aip --version` output
matches the documented pattern.

### - [ ] I2 (aip-console): the Node launcher and the local run view

`npx aip-console --server URL | FOLDER` (also installed as `aip-inspector`): a Node process that serves the UI, proxies nothing
(the page calls the server directly, as today), and exposes the run view through spawned
`aip run --progress` / `aip resume --progress` subprocesses, relaying each JSON line to the page
over a local event stream; cancel kills the subprocess. Reads `aip config` for the server when
`--server` is omitted. Refuses to start the console if `aip` is missing or below the minimum
version, and says so. Folder mode hides catalog, history and governance.

Test: `npm run e2e` against a 0.6a0 server with `billing-support` published: both branches
driven from the console, the escalate script's file lands on the local machine, a failing script
shows the error object and a retry button that resumes, the run appears in history with
attribution; folder mode runs the same skill with no server; an old `aip` on the path yields the
version message.

### - [ ] I3 (aip-console): the new views

The run page shows each step's `state` in and out from the declared keys and which machine ran
it; decision entries show attribution and review status; the catalog page shows `requires`; the
graph view draws key-level data flow from `outputs` to `inputs`; governance gains
`manual-decisions` and the resolver breakdown and loses threshold editing; failing-scripts shows
client-reported stderr.

Test: `npm run e2e` with fixtures containing both resolver kinds and a failed run.

## Track C: close out

### - [ ] C1: docs and release

`docs/running.md` rewritten for served runs under the new request shape; `docs/state.md` gaps
list reduced to what remains; `docs/run-modes.md` "planned" becomes "today"; README quickstart
re-run. Upgrade note for 0.5a1 skills: they fail 0.6a0 validation for missing `outputs` and
`requires` and the outdated runtime block; the validator's message must say "0.5a1 skill: add
outputs to each execution and client_task step, a requires block, and regenerate the runtime
block" rather than read like a bug, and `docs/upgrading.md` lists the three edits with the
billing-support diff as the example. Tag aip-spec `v0.6a0`, bump aip's URL, tag aip `v0.6a0`. Push all three branches.

Test: README quickstart executed top to bottom on a clean checkout; all three test suites green.

### - [ ] C2: harness follow-ups (in `~/dev/aip-skillbench`, its own branch)

The compile step emits `outputs` and `requires`; `AIP_REF.json` pins 0.6a0; the five skills
from the campaign-28 report are re-authored under the new rules; `--decision-model` puts the key
in the solver's environment instead of the server's; aip-runtime mode starts the in-container
server without a model key. Proof: `bootstrap --force`, one aip-runtime trial of
exoplanet-detection-period passes, the trial's `config.json` shows no server key.
