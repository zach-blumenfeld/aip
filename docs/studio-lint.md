# Studio lint rules

The Studio's linter (`src/studio/lint.ts`) runs on every edit. It has four tiers:

- **error**: aip-spec would reject the skill (or, for the Studio-only error, the skill has a matching aip-spec
  error too).
- **warning**: aip-spec's own warnings (a route an LLM steers with nothing recorded), and Studio-only advice.
- **info**: aip-spec's information: a key with several producers, a confidence a script or task declared itself.
- **unfinished**: valid, or fine for a template, but not done yet.

**Upstream** means the code is aip-spec's own (`packages/aip-spec/src/aip_spec/skill.py`, `models.py` in the aip repo), and
`e2e/lint-parity.spec.ts` checks that both validators agree on it, at every severity. **Studio-only** rules exist
only here. They are candidates to propose to aip-spec later. That would be a separate change in the aip repo (see
"Open items" in `plans/STUDIO-PLAN.md`).

## Errors from aip-spec (upstream)

| Code | When |
|---|---|
| `missing_required_frontmatter` | the skill has no `name` |
| `invalid_name` | `name` is not 1–64 lowercase letters, digits and single hyphens |
| `invalid_description` | `description` is empty or over 1024 characters |
| `invalid_compatibility` | `compatibility` is set but not 1–500 characters |
| `schema_violation` | a model rule: step name not kebab-case, question name not an identifier (in `questions` or in a decision's `confidence` list), a script/asset/template/reference path outside its folder, a `choice` with fewer than 2 labels, a `score` with other than 2–10 levels, a router with fewer than 2 branches, a router's confidence check with no key, no bound, a bound outside 0 to 1 or no step to go to, no `trigger_when`, fewer than 3 steps, a start or runnable step with no `inputs_to`, a bad type, package or version |
| `duplicate_question_name`, `duplicate_choice_label`, `duplicate_branch_value` | a name or value given twice in one step |
| `duplicate_step_name` | two steps share a name |
| `missing_start_step`, `multiple_start_steps` | there is not exactly one `start` (any position; the export writes it first) |
| `edge_into_start` | an edge (`inputs_to`, a branch or a check's `to`) names the start step; a run begins there and nothing returns to it |
| `missing_end_step`, `multiple_end_steps` | there is not exactly one `end` |
| `unknown_step_reference` | an edge names a step that does not exist |
| `unreachable_step` | the start cannot reach a step |
| `no_path_to_end` | a step cannot reach the end |
| `unknown_branch_value` | a router fed directly by a decision has a branch value that question can never answer |
| `unknown_confidence_question` | a decision's `confidence` list names a question the step does not have |
| `unproduced_input` | a step reads a key that is not produced on every path to it (the start step produces its inputs). On a router the message names `branch_on`; a router's confidence key must be produced on *some* path to it, and the message names the check |
| `type_mismatch` | two declarations of a key disagree on its type; the first in step order is the reference. A decision's question is a `boolean`, `string` or `integer` by its type, a confidence key is a `float`, and a router's check reads its key as a `float` |
| `unbranchable_type` | a router branches on a key that is not a `boolean`, `string` or `integer` |
| `missing_outputs` | a client task declares no outputs |
| `duplicate_input_name`, `duplicate_output_name` | a step declares a key twice |
| `missing_requires` | the procedure runs scripts but has no `requires` |
| `undeclared_launcher` | a script's launcher is neither the interpreter nor a declared tool |

aip-spec's `missing_resource` (a referenced file is missing on disk) is not a Studio error. The export writes every
referenced file, and a file that is still a placeholder is `placeholder_file` (unfinished).

## Warnings and information from aip-spec (upstream)

What feeds a router is classified by every producer of its `branch_on` key from which the router can be reached,
the worst producer winning: **deterministic** (a start input, or a script's output the router reads no confidence
from), **measured** (a decision with `fallback` off whose `confidence` list names the branch question and the
router checks `<question>_confidence`, or a script or client task whose own declared number the router checks) or
**unmeasured** (a decision with `fallback` on, a decision whose confidence is not emitted or not checked, or a client
task's output the router does not check). `classifySources` in `lint.ts` gives the class per router, the one the
server stores and the Procedure page shows.

| Code | Tier | When |
|---|---|---|
| `confidence_on_unmeasured_source` | warning | a router with a confidence check whose source is unmeasured: the check reads a number nothing calibrated. The shipped billing-support example trips this on purpose: it keeps `fallback: true` so the quickstart runs without a decision model |
| `unmeasured_route` | warning | a router with no check whose source is unmeasured: a probabilistic choice routes the run and nothing records how sure it was |
| `declared_confidence` | info | a router checks a confidence a script (legitimate when the code is calibrated) or a client task (discouraged: an agent cannot calibrate itself) declared itself |
| `duplicate_producer` | info | a key has more than one producer (the start step counts as the producer of its inputs); where a run passes through both, the later one overwrites the value |

A deterministic route says nothing.

## Unfinished (Studio-only)

| Code | When |
|---|---|
| `empty_purpose` | `purpose` is empty |
| `empty_trigger_when` | a `trigger_when` entry is empty |
| `empty_description` | a step other than `start` and `end` has no description |
| `empty_instructions` | a question has no instructions |
| `end_without_inputs` | the `end` declares no inputs, so the procedure returns nothing |
| `placeholder_file` | a referenced script, template, asset or reference still holds `AIP-STUDIO-PLACEHOLDER` |
| `non_python_launcher` | an execution step is launched with something other than `python`. Studio writes Python stubs only |
| `branch_value_not_an_answer` | a router branches on a key whose values are known (a question's answers, or a boolean), but the question does not feed the router directly, and a branch value is none of them. aip-spec checks only a router fed directly by its decision, so this is a hint, never an error |

## Studio-only rules (S5)

| Code | Tier | When |
|---|---|---|
| `loop_without_router` | error | a chain of runnable steps leads back to itself with no router on it, so it can never leave. aip-spec reports such a loop as `no_path_to_end`; this code names the loop. It is left out of the parity comparison (`STUDIO_ONLY_ERRORS`) |
| `redundant_branches` | warning | two branches of one router go to the same step |
| `numeric_choice_labels` | warning | a choice question's labels are all numbers. It is probably a score |
| `duplicate_score_levels` | warning | a score rubric describes two levels with the same text |
| `execution_without_outputs` | warning | an execution step declares no outputs |
| `dead_key` | warning | an execution or client task output that no step reads (a router's check reads its key), although some step could (the key reaches it on every path). A key produced on only some paths, which no step after the paths join can read, is not reported, because adding an input cannot fix it |
| `name_collision` | warning | a step has the same name as a key (an input, an output or a question). billing-support's step `reply` and its key `reply` trip this |

The Studio-only warnings are listed in `STUDIO_ONLY_WARNINGS` and left out of the parity comparison.

Not a rule: "a start input nothing consumes". The start step's inputs are what the client supplies, the initial
state (the runtime block: "the state starts as the `start` step's `inputs`"); a start input nothing reads is a
`dead_key` candidate at most, and the rule is not applied to the start step.

## Autofixes

The lint panel shows a button on an issue when the fix is unambiguous (`src/studio/fixes.ts`):

| Code | Fix |
|---|---|
| `missing_requires` | add `requires` with `python` 3.10 |
| `undeclared_launcher` | add the launcher to `requires.tools` |
| `schema_violation` on `inputs_to` (unset) | hand off to the `end` step, when there is exactly one |
| `unproduced_input` | declare the key as a start input, or as an output of a chosen step (a choice, so a button and a picker) |

## Keyboard

- F8 and Shift+F8: select the next or previous issue, in the panel's order. This works from anywhere, including a
  text field.
- Outside a form field: Delete removes the selected step, Cmd/Ctrl+Z undoes, and Shift+Cmd/Ctrl+Z or Ctrl+Y redoes.
- Undo keeps the last 100 Draft snapshots. Keystrokes in one text field less than 0.8 s apart count as one step.
