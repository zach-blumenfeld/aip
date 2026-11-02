# Studio lint rules

The Studio's linter (`src/studio/lint.ts`) runs on every edit. It has three tiers:

- **error**: aip-spec would reject the skill (or, for the Studio-only error, the skill has a matching aip-spec
  error too).
- **unfinished**: valid, or fine for a template, but not done yet.
- **warning**: Studio-only advice. aip-spec says nothing about it.

**Upstream** means the code is aip-spec's own (`src/aip_spec/skill.py`, `models.py`), and
`e2e/lint-parity.spec.ts` checks that both validators agree on it. **Studio-only** rules exist only here. They are
candidates to propose to aip-spec later. That would be a separate change in that repo (see "Open items" in
`plans/STUDIO-PLAN.md`).

## Errors from aip-spec (upstream)

| Code | When |
|---|---|
| `missing_required_frontmatter` | the skill has no `name` |
| `invalid_name` | `name` is not 1–64 lowercase letters, digits and single hyphens |
| `invalid_description` | `description` is empty or over 1024 characters |
| `invalid_compatibility` | `compatibility` is set but not 1–500 characters |
| `schema_violation` | a model rule: step name not kebab-case, question name not an identifier, a script/asset/template/reference path outside its folder, a `choice` with fewer than 2 labels, a `score` with other than 2–10 levels, a router with fewer than 2 branches, no `trigger_when`, fewer than 2 steps, a runnable step with no `inputs_to`, a bad type, package or version |
| `duplicate_question_name`, `duplicate_choice_label`, `duplicate_branch_value` | a name or value given twice in one step |
| `duplicate_step_name` | two steps share a name |
| `invalid_start_step` | the first step is not runnable |
| `missing_end_step`, `multiple_end_steps` | there is not exactly one `end` |
| `unknown_step_reference` | an edge names a step that does not exist |
| `unreachable_step` | the start cannot reach a step |
| `no_path_to_end` | a step cannot reach the end |
| `unknown_branch_value` | a router fed directly by a decision has a branch value that question can never answer |
| `unproduced_input` | a step reads a key that is not produced on every path to it. On a router the message names `branch_on` |
| `duplicate_producer` | two steps produce one key, or a step produces a start input |
| `type_mismatch` | a key is declared with two types |
| `missing_outputs` | a client task declares no outputs |
| `duplicate_input_name`, `duplicate_output_name` | a step declares a key twice |
| `unknown_threshold_question` | a threshold names a question the step does not have |
| `missing_requires` | the procedure runs scripts but has no `requires` |
| `undeclared_launcher` | a script's launcher is neither the interpreter nor a declared tool |

aip-spec's `missing_resource` (a referenced file is missing on disk) is not a Studio error. The export writes every
referenced file, and a file that is still a placeholder is `placeholder_file` (unfinished).

## Unfinished (Studio-only)

| Code | When |
|---|---|
| `empty_purpose` | `purpose` is empty |
| `empty_trigger_when` | a `trigger_when` entry is empty |
| `empty_description` | a step other than `end` has no description |
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
| `no_thresholds` | warning | a decision with questions sets no review threshold, so no answer is ever flagged for the calling agent |
| `numeric_choice_labels` | warning | a choice question's labels are all numbers. It is probably a score |
| `duplicate_score_levels` | warning | a score rubric describes two levels with the same text |
| `execution_without_outputs` | warning | an execution step declares no outputs |
| `dead_key` | warning | an execution or client task output that no step reads, although some step could (the key reaches it on every path). A key produced on only some paths, which no step after the paths join can read, is not reported, because adding an input cannot fix it |
| `name_collision` | warning | a step has the same name as a key (an input, an output or a question). billing-support's step `reply` and its key `reply` trip this |

Not a rule: "a start input nothing consumes". The start step's inputs are both what the client supplies and what the
start step itself reads (the runtime block: "the state starts as the start step's `inputs`"). A start input always
has at least one consumer, so the rule could never fire.

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
