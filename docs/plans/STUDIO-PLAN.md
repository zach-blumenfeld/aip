# Plan: the Studio tab

A new `#/studio` page in aip-console for building a procedure, or a partial template of one, in a
GUI: create steps, wire them, declare their I/O, get placeholder files for the scripts and templates
they need, and see a linter's verdict on the graph as it is built. The output is a **skill scaffold
zip** in the Agent Skills layout, the same shape `src/zip.ts` already packs for download and
publish.

This follows the conventions of `docs/plans/PLAN.md` (one milestone per session, each leaves
`npm run typecheck` and `npm run e2e` green, tick the heading and add a `Done <date>, commit <sha>:`
line, commit with the attribution trailer given by the session).

## How to run this plan

For an agent told "implement the next unchecked Studio milestone":

- Read this file and `docs/plans/PLAN.md`'s "How to use this plan"; find the first `- [ ]` heading.
- Do only that milestone. Run `npm run typecheck && npm run e2e` (needs `uv`, and
  `PLAYWRIGHT_CHANNEL=chrome` if chromium is not installed). Do not edit `../aip-spec` or `../aip`.
- Change `- [ ]` to `- [x]`, add `Done <date>, commit <sha>: <one sentence>` under the heading,
  commit, and stop. Report what the proof printed. A fresh session takes the next milestone.
- If the plan and the spec in `../aip-spec` disagree, the spec wins; say so in the commit.
- Do not reopen the decisions below. Surface anything under "Open items" rather than guessing.

## Decisions already made (do not re-litigate)

| Question | Decision |
|---|---|
| What does Studio produce? | A skill scaffold zip: `SKILL.md` (frontmatter, runtime block, YAML graph) plus placeholder files under `scripts/`, `assets/`. The only write to disk is the agent handoff folder (S6b). |
| Where does a design start? | Blank, or imported from a catalog revision or a zip. Autosaved in the browser (`localStorage`); the zip is also a save/restore format. |
| How is the graph built? | The existing auto-layout graph (`src/graph/layout.ts`, `StepGraph.tsx`) plus a side panel. No free canvas, no dragging wires. Edges are fields (`inputs_to`, router `branches`), so "one outbound edge" is true by construction. |
| Linter strictness? | Three tiers: **error** (violates the spec), **unfinished** (placeholder or empty, fine for a template), **warning**. Export is never blocked; the zip is flagged draft in its `source/` note when errors remain. |
| Milestone order | Model and lint first, UI second (below). |
| Validator placement | A TypeScript port of the spec's graph and state rules, run in the browser on every edit. The real `aip-spec validate` stays the authority: a test (not the UI) runs both over the same fixtures and fails on any disagreement. |
| Agent fill-in | Added as S6. Local-only for now (hosting for others is later). The agent never judges its own success: the console re-validates and checks adherence to the user's draft. The console never runs the agent: it writes the scaffold to a folder and the user pastes one prompt into their own coding agent (changed 2026-10-31, replacing a spawned agent). |
| Script language | Python only in v1, enforced: the editor offers only the default launcher or an explicit `python`; a step with any other `command` (typed, or from an imported skill) is an `unfinished` issue and blocks the agent button, so no step can end up with an empty or unrunnable script. Widening this later means adding the launcher's stub, contract probe and agent instructions together. |
| Requirement: fill-in is complete | **A successful agent fill-in always yields an end-to-end operational, publishable skill.** See "Definition of done" under S6a. Anything short of it is a failed fill-in, never a partial accept. |
| Agent scope | The agent writes files (scripts, templates, references, assets) and fills **empty** prose fields (step `description`, question `instructions` and `criteria` text, empty `trigger_when` entries). Anything the user already wrote is frozen, as are the graph, I/O, names and types. |
| No `aip-spec` | S6 checks refuse to run without the real `aip-spec` on the console machine; the TS linter is never final for an agent result. |
| Agent retries | None automatic: the Studio re-checks whenever the folder changes, and the user pastes the failures back to the agent. |
| Agent prompt | A shipped default, shown in the info panel and editable per run; the edited text is saved with the draft. |
| Server publish | Verified in `aip/src/aip/server/app.py`: `POST /catalog` runs `validate_skill`, rejects errors with 422 `invalid_skill`, passes warnings. It checks referenced files exist, not their content, so a scaffold with placeholders publishes if the graph is valid. |

## Ground truth to read before starting

The format is defined in the sibling repo `~/dev/aip-spec` (format `0.6a1`), not in `~/dev/aip`
(which only builds a runtime `Procedure` from it in `src/aip/spec/loader.py`).

- `src/aip_spec/models.py`: the pydantic models are the spec. Step kinds `decision`, `execution`,
  `client_task`, `router`, `end`; field patterns (`STEP_NAME_PATTERN`, `QUESTION_NAME_PATTERN`,
  `AssetPath` is `^assets/.+`, script is `^scripts/.+`, reference is `^references/.+`); `DataType`
  is `string|integer|float|boolean|object|list[*]`; `Requires`; every object is closed (unknown keys
  are errors).
- `src/aip_spec/skill.py`: `check_frontmatter`, `parse_spec`, `check_graph`, `check_state`,
  `check_requires`. These hold every rule listed in the S0 table below. `QUESTION_TYPES` maps a
  question to the type its answer lands as in the state (noul to boolean, choice to string, score to
  integer).
- `src/aip_spec/runtime.md`: the runtime block every `SKILL.md` carries **verbatim** at the top of its
  body. `examples/billing-support/` is a complete valid skill to compare exports against.
- `assets/procedure.schema.json`: the JSON Schema generated from the models (useful for field
  descriptions in the side panel; do not hand-copy descriptions, import them).
- `tests/fixtures/dialogue-graph.yaml` and `tests/test_spec.py`: existing validator cases to mirror.

Console side: `src/router.ts` (add the route), `src/views/StepGraph.tsx` and `src/graph/layout.ts`
(reuse for drawing), `src/zip.ts` (`packSkill`, `unpackSkill`), `src/views/Zip.tsx` (download and
publish-to-catalog flow to reuse), `src/api/types.ts` (`StepDetail`, `ProcedureInfo`, shapes the
server returns for import), `src/graph/dataflow.ts`.

The rules the data model already enforces, so the GUI must enforce them by construction and must
**not** offer a way to break them: a decision/execution/client_task step has exactly one `inputs_to`;
only a `router` has `branches` (at least 2); `end` has no outbound edge; there is exactly one `end`;
the first step is the start and must be runnable. The editor offers "next step" as a picker, never an
"add another edge" control.

## - [x] S0: Draft model and the linter

Done 2026-10-29, commit 9170e35: Draft model, SKILL.md round-trip and a TS port of aip-spec's frontmatter, schema, graph and state rules (three tiers); 38 parity fixtures agree with `aip-spec validate`. The runtime block is `runtime-0.6a1.ts` (a string export, not a `.md` import) so Playwright's Node loader can import it.

No UI. Pure TypeScript under `src/studio/`, unit-tested with Node's test runner or a Playwright
`test` without a browser (follow whatever `e2e/` already does; add `vitest` only if neither fits).

- `src/studio/draft.ts`: the **Draft** type. It mirrors `ProcedureSpec` but is allowed to be
  incomplete: fields optional, step names possibly empty or duplicate, edges possibly unset. Include
  frontmatter fields (`name`, `description`, `compatibility`, `license`, `allowed-tools`) and the
  `requires` block. A step carries a stable internal `id` separate from its `name`, so renaming a
  step does not break edges (edges reference ids in the Draft, names only on export).
- `src/studio/serialize.ts`: `draftToSkillMd(draft)` and `skillMdToDraft(text)`. Add the `yaml`
  package (named need: the body is YAML and must round-trip; keep key order matching
  `billing-support`). Embed the runtime block by copying `aip-spec/src/aip_spec/runtime.md` into
  `src/studio/runtime-0.6a1.md` and importing it as text; a test compares it byte for byte to the
  file in `../aip-spec` when that checkout exists.
- `src/studio/lint.ts`: `lint(draft) -> Issue[]` where `Issue = { tier: "error"|"unfinished"|"warning",
  code, message, stepId?, field? }`. Port, with the same `code` strings as aip-spec where one exists:
  - Errors from aip-spec: `duplicate_step_name`, `invalid_start_step`, `missing_end_step`,
    `multiple_end_steps`, `unknown_step_reference`, `unreachable_step`, `no_path_to_end`,
    `unknown_branch_value` (router fed directly by a decision), `unproduced_input`,
    `duplicate_producer` (including against start inputs), `type_mismatch`, `missing_outputs`
    (client_task), `duplicate_output_name`, `duplicate_input_name`, `unknown_threshold_question`,
    `missing_requires`, `undeclared_launcher`, `invalid_name`, `name_mismatch` (frontmatter name vs
    the zip's folder, always the same in Studio so it is moot), and the schema patterns (step name
    kebab-case, question name identifier, asset/script/reference path prefixes, `choice` needs 2+
    labels, `score` 2 to 10 levels, router 2+ branches, `trigger_when` 1+, `steps` 2+).
  - `missing_resource` is **not** an error in Studio: a referenced script or template that is only a
    placeholder is `unfinished`.
  - Unfinished tier: empty `description`, `purpose`, `trigger_when` entries, question
    `instructions`; a script or template still holding the placeholder marker (S3); an `end` with no
    inputs.
  - Warnings (beyond aip-spec): see S5.
- Implementation notes. `unproduced_input` is a must-availability fixed point over the graph, cycles
  included; port `check_state` literally, do not re-derive it. Tests must include a router loop.
- Parity test: `e2e/lint-parity.mjs` (or equivalent) takes a set of fixture skills (the repo's
  `billing-support`, `dialogue-graph.yaml`, plus ones written per error code), runs `aip-spec
  validate --json` on each (find the CLI the way `e2e/aip.ts` finds `aip`), runs the TS linter on
  the same text, and asserts the **set of error codes** is equal. Skip with a clear message when
  `aip-spec` is not installed; the harness already needs `uv`.

Proof: `npm run typecheck && npm run e2e` with the new lint tests passing, and the parity test
printing the number of fixtures compared and zero disagreements.

## - [x] S1: The Studio tab: graph and step editor

Done 2026-10-29, commit cdebfae: `#/studio` with the selectable step graph (add-after splice, delete re-link, set start), a side panel per step kind and for the procedure, a live lint panel with node markers, and localStorage autosave; the tab also shows in folder mode. Inputs and outputs are not editable until S2, so the proof asserts the wiring rules clean, not the whole lint.

- Route `#/studio` (and `#/studio/<draftId>` if more than one draft is kept; v1 may keep one). Add to
  `Route`, `parseHash`, `href`, and the nav in `App.tsx`. The tab appears in folder mode too (it
  needs no server).
- Layout: the step graph on the left (reuse `StepGraph`, fed from the Draft's steps and edges; it
  already takes `steps`, `edges`, `branches`, `start`, `end`), side panel on the right.
- Graph interactions: click a node to select it. "Add step after X" on the selected node opens a
  kind picker (`decision`, `execution`, `client_task`, `router`, `end`) and inserts the new step
  between X and X's old next step (splice, so the chain stays connected). Delete step (re-links the
  predecessors to its successor when it has exactly one; for a router, asks which branch to keep or
  drops the dangling edges and lets the linter say so). Set start (move to index 0, only for a
  runnable step). Direction toggle reuses `DirectionToggle`.
- Side panel by kind, fields straight from `models.py`:
  - all: `name` (live kebab-case check), `description`, next step picker (`inputs_to`) for runnable
    kinds.
  - `router`: `branch_on` picker over keys available at this point (S2 gives the key list; until
    then free text), and a branches table (value to target step). Add/remove branch rows. When the
    feeding step is a decision with a `choice` or `noul` question matching `branch_on`, prefill the
    rows from its labels (`true`/`false` for noul).
  - `decision`: questions list (type noul/choice/score, `instructions`, `criteria` editor per
    type), `thresholds` per question, `history` toggle.
  - `execution`: `script` path, `assets`, `timeout`; `command` is limited to the default or
    `python` (v1). (File creation in S3.)
  - `client_task`: `template` path, `assets`, `references` (path plus description), `framing`.
  - `end`: its `inputs` become the result. (Typed editor arrives in S2.)
- Procedure-level panel (when nothing is selected): `name`, `description`, `purpose`,
  `trigger_when`, `do_not_use_when`, `anti_patterns`, `requires` (interpreter, version, packages,
  tools).
- Lint panel under the graph (basic in S1): runs `lint` on every edit, lists issues grouped by tier,
  clicking one selects the step and focuses the field; each node in the graph shows a small marker by
  the worst tier on it.
- Autosave the Draft to `localStorage` on every change, debounced (key `aip-console:studio:draft`).
  Wrap reads and writes in try/catch; the page works without storage.
- Reuse existing visual language in `src/styles.css`; do not add a UI library.

Proof: e2e builds the `billing-support` graph by hand in the UI (a decision, a router with two
branches, an execution, a client task, an end), reloads the page, and asserts the draft is still
there and the lint panel shows no errors in the wired part.

## - [x] S2: I/O editing with key pickers and type checks

Done 2026-10-30, commit 50ec0cf: an I/O editor on every step with the key picker (`availableKeys`, exported from `lint.ts`, shares the must-availability fixed point), read-only decision outputs, a `branch_on` picker showing possible values, a data-flow toggle, and two quick fixes on `unproduced_input` (now reported once per key). Router branch rows also gained a per-row "new step" control (67757ed).

- Inputs and outputs editor for every step: rows of `name`, `type` (the six `DataType`s),
  `description`. The **start** step's inputs are labelled "what the client supplies".
- Key picker: when adding an input row, offer the keys available at this step (start inputs plus
  everything produced on every path to here; reuse the same must-availability computation as
  `lint`, exported from `lint.ts`), with their types. Choosing one fills name and type, so
  `type_mismatch` cannot be created by the pick. Typing a new name is allowed and the linter reports
  `unproduced_input`; offer a one-click "declare as start input" and "make this an output of step Y"
  fix on that issue.
- A decision step shows its outputs read-only: one key per question, with the type from
  `QUESTION_TYPES`. A router shows `branch_on` against this same list; if the chosen key's producer
  is a choice/noul/score question, show its possible values.
- `end` inputs use the same picker.
- Data view: a toggle that overlays the key flow on the graph, reusing `src/graph/dataflow.ts`.

Proof: e2e builds a two-step chain, adds a consuming input via the picker, then renames the
producer's output and asserts the linter reports `unproduced_input` on the consumer and that the
quick fix clears it.

## - [x] S3: Placeholders and the scaffold zip

Done 2026-10-31, commit eb4cc57: `src/studio/scaffold.ts` derives a working Python stub, template, reference and asset placeholder for every path a step names (live lint sees them as `placeholder_file`), `source/README.md` lists them and flags `DRAFT: N errors remain`, and the Export panel downloads the zip and publishes it (disabled with the reason while errors remain). A `.json` asset holds `{"AIP-STUDIO-PLACEHOLDER": …}` instead of a bare `{}` so the marker fits; renaming a step moves a script or template still at its default path.

- Placeholder generation, derived from the Draft on export, never stored in it:
  - `execution` step: `scripts/<name>.py`. Python only (see decisions); other launchers get no
    stub and an `unfinished` issue. The Python stub reads one JSON object from stdin (`{state, assets,
    expects}`), and prints a JSON object holding exactly the declared `outputs` with a typed dummy
    value each (`""`, `0`, `0.0`, `false`, `{}`, `[]`), with a `TODO` comment and the input/output
    contract in the docstring. It must be a working script, so a scaffold can run end to end.
  - `client_task` step: `assets/<name>.md` template listing each input as `{key}` and each expected
    output, with a `TODO` heading.
  - Each declared `references` entry: `references/<name>.md` with a `TODO` line. Each declared
    `assets` entry: a file created at the path given when it does not exist, empty except for a
    `TODO` where the type permits (`.json` gets `{}`).
  - Every placeholder starts with a fixed marker line (`AIP-STUDIO-PLACEHOLDER`) that the linter
    uses for the `unfinished` tier; replacing the file content removes the marker.
- The file paths a step names are editable in the panel; the generator creates exactly what the
  Draft references and nothing more, and a rename moves the placeholder with it. Orphan files from
  an import (S4) are carried through untouched.
- `source/README.md` in the zip states it was generated by Studio, lists unfinished placeholders,
  and says `DRAFT: N errors remain` when the linter has errors.
- Export button: runs `lint` first, shows the summary (errors, unfinished, warnings), then packs with
  `packSkill` and downloads, and offers "publish to catalog" through the existing flow in `Zip.tsx`
  when a server is configured (the server's own validation warnings are shown as `Zip.tsx` already
  does).
- Check against the real validator: a test generates a scaffold for a **complete** draft (no
  errors, no unfinished except placeholders), unzips it to a temp dir, and runs `aip-spec validate`
  on it; it must pass with `missing_resource` impossible. For a draft with errors, assert the CLI
  also fails, with an overlapping code.

Proof: e2e exports a scaffold, unzips it with `unpackSkill`, validates it with the CLI, and asserts
the file tree (SKILL.md, one script per execution step, one template per client task).

## - [x] S4: Import and draft management

Done 2026-10-31, commit 54ced43: import from a catalog revision ("edit in Studio") or a zip into a new draft that carries every other file, an export that writes edits into the imported SKILL.md text (`patch.ts`) so one edited description is a one-line diff, a format-version banner with aip-spec's message, and several drafts in localStorage (new, rename, switch, delete, reset). An imported `source/README.md` is kept, so the Studio's notes go to `source/STUDIO.md` instead.

- Import from a catalog revision: reuse `src/api/client.ts` to fetch the manifest and files, same as
  the download in `Zip.tsx`; from a zip: `unpackSkill`. Parse `SKILL.md` with `skillMdToDraft`. An
  imported skill may be invalid; load it anyway and let the linter report. Files the steps do not
  reference are kept and re-emitted on export. Never lose bytes: a round-trip test imports
  `billing-support`, exports without edits, and the YAML body must be semantically equal (compare
  parsed values; formatting may differ).
- A format-version mismatch (`metadata.aip-version` not `0.6a1`) is reported as a banner with the
  spec's own message, and the export stamps `0.6a1`.
- Draft management: new draft, rename, delete, switch between several drafts held in
  `localStorage`; "Reset" with a confirmation. An in-page notice if storage is unavailable.
- Entry points: a "Edit in Studio" link on the procedure page and a "New in Studio" link in the
  catalog.

Proof: e2e publishes `billing-support`, imports it into Studio from the catalog, edits one
description, exports, and asserts the diff against the original is only that line (reuse the line
diff from `src/diff/lines.ts` in the assertion).

## - [x] S5: Lint polish and GUI-only rules

Done 2026-10-31, commit 533763d: nine Studio-only rules documented in `docs/studio-lint.md` (`loop_without_router` an error masked from parity, `branch_value_not_an_answer` unfinished, the rest warnings), autofix buttons, undo/redo, F8 through the issues and Delete on a step. "A start input nothing consumes" is not a rule, because the start step reads its own inputs (runtime block); billing-support now warns `name_collision` on `reply`.

Rules the spec does not state but a graph builder needs. All are `warning` unless noted.

- A router with two branches that go to the same step (redundant).
- A router `branch_on` key that nothing produces (already an error through `unproduced_input`, but
  say it on the router's own field).
- A router branch value that is not among the possible answers when the feeder is not a direct
  decision (cannot be checked; surface as an `unfinished` hint, never an error).
- A loop (a cycle) with no router on it: a runnable chain that can never leave. Error, since
  `no_path_to_end` already covers most cases; add the dedicated message.
- A decision with no thresholds, a decision question with a `choice` whose labels are numeric only,
  a `score` rubric with duplicate levels.
- An `execution` step with no outputs, or an output no later step consumes (dead key); a start
  input nothing consumes.
- Names: a step name that matches a question name or key (confusing in traces).
- Autofix actions on issues where the fix is unambiguous (add the missing `requires.interpreter`,
  declare a start input, set `inputs_to`), shown as buttons in the lint panel.
- Keyboard: select next/previous issue, `Delete` for a step, undo and redo for Draft edits (keep a
  bounded history of Draft snapshots).
- Document each rule's code and message in `docs/studio-lint.md`; mark those that exist upstream and
  those that are Studio-only, so the Studio-only ones can be proposed to aip-spec later.

Proof: e2e builds a draft that trips each new rule once, asserts each code appears with the right
tier, applies one autofix, and asserts the issue clears.

## - [x] S6: Agent fill-in ("Complete with an agent")

Depends on S3 (placeholders, zip) and S4 (import). Two parts, each a green commit.

### - [x] S6a: prompt, checks, copy and import (no spawning)

Done 2026-10-31, commit a3472da: the gate, info panel, editable prompt with a generated frozen contract, and import of an agent's zip checked by `POST /console/validate` (real aip-spec, refused without it), adherence, `POST /console/probe` with outputs fed forward, template fields and completeness; Accept only when all pass. The prompt is `agentPrompt.ts` (a string export, like the runtime block), the `{key}` check covers templates only (the runtime never renders a reference), and I/O and reference descriptions are frozen per the agent-scope decision. S6's heading stays open until S6b.

- **Gate** (`src/studio/agentGate.ts`): the button is enabled only when `purpose`, the skill `description`,
  `trigger_when`, and every step's I/O are filled in and `lint` reports no `error` tier issues.
  Step-level prose (step descriptions, question instructions) may be empty; the agent fills those.
  It is also disabled while any execution step uses a non-Python launcher. A disabled button lists
  each reason, and each reason links to its step or field.
- **Info panel** shown before anything runs: what the agent is asked to do (replace every
  `AIP-STUDIO-PLACEHOLDER` file with a working script or template, and fill empty prose fields),
  what it may change (placeholder files and empty prose fields; nothing in the graph or in anything
  already written), what it must run (`aip-spec validate`), and that its work comes
  back as a diff to accept or reject. When spawning is available (S6b) it also shows the exact
  command, working directory, retry count, and that the agent runs with the user's permissions and
  may cost money.
- **Prompt** (`src/studio/agent-prompt.md`, shipped default, shown in the info panel and
  editable per run; an edited prompt is saved with the draft): the frozen
  contract (list every step, kind, edge, I/O name and type, question, and path it must not change),
  the script stdin/stdout contract from the runtime block, where the spec is (`~/dev/aip-spec`
  path if known, else the runtime block inline), the instruction to run `aip-spec validate` until it
  passes, and what to leave alone. "Copy prompt" copies it; the scaffold zip is the file input.
- **Import result** takes the zip the agent returns and runs the checks below. The result is shown
  as a diff against the exported scaffold (`src/diff/lines.ts`, manifest status as in `Diff.tsx`);
  Accept replaces the placeholders in the Draft's file set, Reject discards. The Draft's graph is
  never replaced by an agent's.
- **Checks** (`src/studio/agentCheck.ts`), all programmatic:
  1. `aip-spec validate` on the result. This runs in the console's process (`POST /console/validate`,
     loopback only, same style as the existing endpoints); when `aip-spec` is not found the checks refuse to
     run and say how to install it; the TS `lint` is not a substitute here.
  2. **Adherence**: parse the result's `SKILL.md` with `skillMdToDraft` and compare it to the Draft
     on everything frozen: step names, kinds, edges, branches, I/O names and types, question
     names and types, and every prose field that was non-empty in the Draft. Empty prose fields the
     agent filled are allowed and listed in the diff for review; `requires` is frozen unless the
     Draft's was empty and the agent only added to it, in which case flag it for the user. Any
     other difference is a failure naming the field.
  3. **Script contract**: run each generated script with synthetic inputs of the declared types
     (`POST /console/probe`, in a temp dir, with a timeout) and assert stdout is one JSON object
     holding exactly the declared outputs with matching types. Templates: every `{key}` placeholder
     resolves against the step's inputs.
  4. **Completeness**: no `AIP-STUDIO-PLACEHOLDER` marker remains anywhere, no required prose field
     is empty, and no file the graph references is empty or only comments.

#### Definition of done (a requirement, not a goal)

A fill-in is accepted only if **all** hold; otherwise it is a failed fill-in (retried per S6b, then
reported) and Accept stays disabled. Accept never admits a partial result.

- `aip-spec validate` reports no errors, and the result is publishable to the catalog as is
  (nothing the server would reject with 422 `invalid_skill`).
- The adherence check passes (the user's graph, I/O and written prose are untouched).
- Every execution step's script passes the contract probe: runs under the declared `requires`
  interpreter, prints exactly the declared outputs with the declared types, for synthetic inputs.
  The probe also feeds one script's outputs forward as the next script's inputs along the graph,
  so the data flow is exercised, not just each script alone.
- Every template and reference the graph names exists, is non-empty, and resolves its `{key}`
  placeholders.
- Completeness (check 4) passes: zero `unfinished`-tier lint issues remain.

What this does not prove: decisions need a decision model and client tasks need a client, so a
full `aip run` is not part of the check. State that in the info panel so "operational" is not
over-read.

### - [x] S6b: hand the folder to the user's agent

Done 2026-10-31, commit dabce90: Start writes the scaffold to `<workdir>/studio/<name>/` (an existing folder is moved to `studio/.previous/`), the panel shows one prompt naming it, and the Studio polls the folder and runs the S6a checks each time it settles; Accept needs every check. Replaces the spawned-agent design at the user's request, and the panel's zip download and import with it.

- `POST /console/handoff {name, files}` writes the scaffold to `<workdir>/studio/<name>/`; a folder already
  there is moved to `<workdir>/studio/.previous/<name>-<time>/`, never deleted.
- `POST /console/handoff/read {name}` returns the folder's regular files and a hash of them. The page reads it
  every second and checks once the hash has moved off the scaffold's and two reads agree.
- The prompt is the editable instructions, then the folder path and the frozen contract (not editable).
- The handoff is saved with the draft, so a reload goes on watching. Start over writes a fresh scaffold.

Proof (S6a): e2e asserts a draft with a `bash` execution step keeps the agent button disabled with
that reason, and a result that leaves one placeholder marker or one empty script cannot be accepted.
Then e2e builds a complete draft, exports, then imports (1) a hand-made correct result and
asserts Accept works, (2) a copy with one step renamed and asserts the adherence failure names it,
(3) a copy whose script prints a wrong key and asserts the contract failure names it.
Proof (S6b): e2e clicks Start, asserts the folder and the prompt, then plays the agent by writing into the
folder: a renamed step, a wrong key, a leftover marker and an empty script each get a failing check, and the
correct files pass and are accepted. Start again moves the folder to `.previous/`.

## Out of scope for v1

Free-form canvas and dragging wires; writing scaffolds into a folder on disk (beyond the agent handoff); running the scaffold
from Studio; editing script or template file content (placeholders are produced, the user edits them
in their own editor); multi-user editing; authoring `source/` documents; AI-assisted generation of
steps or graph structure (S6 fills in files only; the `aip` authoring skill is the tool for graphs);
spawning an agent from the console; hosting the console for other users.

## Open items to surface rather than guess

- The server rejects a draft that has lint errors (422 `invalid_skill`). "Publish to catalog" in S3
  is therefore disabled with the reason shown while errors remain; Download is never blocked.
- Whether any Studio-only rule from S5 should be proposed upstream to aip-spec; that is a separate
  change in that repo and is not made from here.
