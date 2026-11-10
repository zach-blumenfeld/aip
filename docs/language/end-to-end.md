# End to end: what we want to show

One walk-through, from an empty folder to a governed run and back out as a skill. Each scene
says what a person sees and what has to exist for them to see it. Together the scenes are the
requirements for building the language out; the checklist at the end collects them.

The commands are the reference implementation's (`aip`). The language and the runtime
requirements they implement are `docs/language/spec.md` and `docs/language/runtime.md`.

## Scene 1: write a procedure

A person opens an empty folder and writes `procedure.aip` for ticket triage: a `Start`, a
`Decide` with two questions, a `Route` with a confidence check, a `Task_Agent`, an `Execute`,
a `For` over the tickets with a review `Loop` inside it, an `End`. The editor colors the
keywords and folds the blocks. They save a policy as a named string and a prompt as an asset.

They run `aip compile ticket-triage/`. It reports three problems with line numbers: a step
nothing points at, a `Read` of a key no path produces, a route that misses one label of its
choice. They fix them, compile again, and get a bundle with an id.

Needs: the parser; every check in spec 2.2 through 2.5 with source positions; the formatter;
the bundle writer; the editor grammar (`editors/vscode`) and a linter the editor can run.

## Scene 2: run it on a laptop

`aip run ticket-triage/ --input start.json`. The folder compiles in memory. The agent driving
the run performs each `Task_Agent` step from its rendered prompt, the decision model answers
each `Decide`, scripts run from the cache, the `For` runs its single-`Decide` body ten passes
to a call, the review `Loop` goes round until the aggregation holds. The run ends with the
`End` step's keys and is recorded locally with the bundle id on every entry.

Then the same with no decision model configured: the run stops at the first `Decide` and says
so (`no_decision_model`), and `aip resume` asks the model once one is configured. A procedure
that must run without a model has the agent decide in a `Task_Agent` under declared labels, as
`billing-support-agent` does; its route branches on the agent's answer and checks no confidence.
(Revised 2026-11-09: `Agent_Fallback`, which let the agent answer a `Decide` by hand, is gone.)

Needs: everything in `docs/language/runtime.md`: loading, the state rules, each step kind, batching,
the record; the decision model client; the agent protocol for `Task_Agent`.

## Scene 3: look at a run

`aip runs` lists the run. Opening it shows each step in order with what it read and produced,
each decision's answers with their confidence and probabilities, the route's check and whether
it fired, each loop pass by number, the aggregation's per-answer resolution (which policy
failed, which answer was under the bar). A failed run shows where it stopped and why.

Needs: the record's shape as `docs/language/runtime.md` states it; a run view in the console that reads
it; `aip runs` and `aip runs <run_id>`.

## Scene 4: publish and run from a server

`aip publish ticket-triage/ --server URL`. The folder compiles, the server stores the bundle
as a revision named by its id and projects the graph. `aip run ticket-triage --server URL`
runs the stored bundle; the run is recorded on the server. A second publish after an edit is a
second revision; the first keeps its id and its runs.

Needs: a server with a record layer (store a bundle, list, search, append and read runs) and
a graph layer (the projection of bundles and runs); bundles immutable by id; the client's
`--server` and configuration.

## Scene 5: ask governance questions

In the console, with `aip audit`, or by query: which routes fired their confidence check this week and on which
revision; which routes branch on an agent's answer (the `source` on the route's `READ_BY` edge);
which policy fails the aggregation most often; what the lineage of the `End` step's `reply` is, back to
the decision and the ticket. Each question is one query over the projected graph, and the
answer names bundle ids.

`aip export runs ticket-triage --since DATE -o audit.rl` writes those runs as one queryable
file an auditor can open without the server.

Needs: the graph schema the compiler writes; the named audit queries (`aip audit`); the
console's audit view; export of runs and procedures as a standalone graph file.

## Scene 6: change it and see the difference

The person raises the route's confidence bar and adds a policy. Compile gives a new id;
publish gives a new revision. The console shows the two side by side: the source diff (two
lines) and the graph diff (one edge's property, one new question node). Runs that happened
before still point at the old bundle; the record never changes.

Needs: bundles immutable; revision history by id; source diff and graph diff in the console.

## Scene 7: hand it to an agent as a skill

Dropped on 2026-11-07. A procedure is handed to an agent as a bundle, not as a skill folder; an
agent runs it through `aip`. Export writes the program directory back for people, not a skill.

## Scene 8: bring an existing procedure across

Dropped on 2026-11-08 (`plan-questions.md`, item 20): there is no converter from the YAML
format. An old procedure worth keeping is rewritten by hand or with `make_procedure`, given the
old skill folder as its `materials`. (`aip upgrade` is a different thing since 0.9: it publishes
the procedures the package ships to the configured server.)

Needs: the upgrade tool; a list of what changes for scripts and templates; a compatibility
window in which the runtime still loads the old format with a warning.

## Checklist

| Piece | Scenes | Where it is specified | State |
|---|---|---|---|
| Parser and formatter | 1 | spec 2.1, glossary | done (plan L1, 2026-11-09) |
| Checks with source positions | 1 | spec 2.2 to 2.5 | done (plan L2, 2026-11-09): `aip.compiler.check`, `aip compile --check` |
| Bundle writer and reader | 1, 4, 6 | spec 3 | done (plan L3, 2026-11-09): `aip compile`, `aip export`, `docs/language/bundle.md` |
| Editor grammar | 1 | `editors/vscode` | done |
| Linter the editor can run | 1 | this page | done: `aip compile --check --json [--stdin] <folder>` prints every diagnostic with its span, and the extension shows them as squiggles on every change (plan E1, 2026-11-09) |
| Runtime: state, steps, loops, batching, record | 2, 3 | `docs/language/runtime.md` | done (R1 and R2, 2026-11-09, `src/aip/model`): the state, every step kind, answers, routes, aggregations, `For` and `Loop` in every form, batching with one model call per batch of single-`Decide` passes, batched pauses, the cache, the record with passes and the identity fields |
| Decision model client; decisions need a model | 2 | spec 2.4, runtime | done (R2, R3, L4, R4): `aip.model.typesafe.TypeSafeResolver` makes the answer objects and speaks to an endpoint with the TypeSafe API shape; the CLI and SDK wire the endpoint and key from `aip config --decision-model URL --decision-model-key KEY` or `AIP_DECISION_MODEL` / `AIP_DECISION_MODEL_KEY`; `Agent_Fallback` removed 2026-11-09, the agent decides in a `Task_Agent` under labels (`billing-support-agent`) |
| Run view | 3 | runtime: the record | exists for the old format; needs passes, aggregations, answer objects |
| Server: record layer, graph layer, immutable bundles | 4, 5, 6 | spec 3, runtime | exists for the old format; needs `.rl` bundles merged into the store |
| Governance queries and export to a graph file | 5 | runtime: the record | partly exists; needs aggregation and pass queries, export |
| Source and graph diff | 6 | this page | source diff exists; graph diff not started |
| Skill export and runtime block | 7 | this page | dropped 2026-11-07 |
| Agent skills rewritten | 7 | this page | not started |
| Upgrade tool and compatibility window | 8 | this page | not started |

The order that lets each scene be shown as soon as it can: 1, then 2 and 3, then 4 and 5, then
6, 7 and 8. Scene 1 alone is the parser, the checks and the bundle, and it is the piece nothing
else can start without.
