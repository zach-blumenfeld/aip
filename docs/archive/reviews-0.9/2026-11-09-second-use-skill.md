# AIP 0.9 skill review: a support-inbox procedure from the skill alone, then `make_procedure`

Binary `aip 0.9.0 language 0.9` (`/Users/zach/dev/aip-0.9/.venv/bin/aip`). Every command ran with
`AIP_HOME`, `AIP_LOCAL_DATA`, `AIP_LOCAL_PORT=8277` and `AIP_SERVER=local` pointed at a scratch dir;
the user's config supplied the decision model. Part 1 was done from `skills/aip/SKILL.md` and
`skills/aip/references/language.md` only. 8 decision-model runs, 2 `make_procedure` passes,
12 compiles of deliberate variants. `aip skill install` was not run; the skill was read from the tree.

Scratch: `/private/tmp/claude-501/-Users-zach-dev-aip-inspector/d5af9594-fff2-4108-a674-4b81eab53c08/scratchpad/review-skill/`
(`support_inbox/` is the Part 1 procedure, `v1`..`v11` the variants, `mp_work/support_inbox_mp/` the
folder `make_procedure` produced, `mp_prompt1.md` / `mp_prompt2.md` the two task prompts it handed me).

## What I ran (in order)

| # | Command | Outcome |
|---|---|---|
| 1 | read `SKILL.md` (147 lines) and `references/language.md` (220 lines) | wrote `support_inbox/` (procedure + 2 scripts) in one sitting; see "The procedure" below |
| 2 | `aip compile --check support_inbox` | **`ok support_inbox: 9 steps, 2 files, bundle b8de4288546c`, first try**, although `End` reads `outcome` and `tags`, which no single path produces together (finding 1) |
| 3 | `aip config` | **not run**: the harness blocked the command as it may print the key; `aip config --help` read instead |
| 4 | `aip fmt --check support_inbox` | `would reformat`, exit 1: moves each `Use_When`/`Do_Not_Use_When` string onto its own indented line and adds a blank line before the `For`'s exit line |
| 5 | `aip info support_inbox`, `--example-inputs` | good; RESULT lists `classification  decision` (a type name neither page uses); the whole `Task_Agent` prompt is printed as the step description |
| 6 | variants v1..v11 (table in finding section) | 2 compile that the pages say should not; 1 error code not in the page's list; the rest as documented |
| 7 | `aip run support_inbox` refund 40 | done in one call: `classify` -> `by_kind` -> `check_amount` -> `by_limit` -> `approve`; `outcome: "APPROVED: refund of 40 ..."`; result has no `tags` key |
| 8 | `aip run support_inbox` refund 350 | paused at `human_review`, one task, `answer_with {outcome: string}`, `{amount}` and `{message}` interpolated |
| 9 | `aip run support_inbox` bug report, 3 areas | paused at `tag_area` with **3 tasks** (`index` 0..2, `pass` 0..2, `passes: [{loop: tag_areas, pass: n}]`), hint `answer all 3 tasks at once, by index` |
| 10 | `aip run support_inbox` "dark mode looks great" | done via `other -> end`; result is `message` + `classification` only |
| 11 | `aip resume <8> --answers '{"outcome": "DECLINED: ..."}'` | done |
| 12 | `aip resume <9> --answers '{"tag": "..."}'` (one object for 3 tasks) | `invalid_output`: `the pause has 3 tasks: the answers are an object keyed by task index ({"0": {...}, "1": {...}}) or a list in task order` |
| 13 | `aip resume <9>` with tasks 0 and 1 only | `invalid_output`: `no answer for task 2; every task of the pause is answered at once`, `missing_tasks: [2]` |
| 14 | `aip resume <9>` with all three | done; `tags` is the list of three strings in order |
| 15 | `aip runs` | a table (RUN, NAME, STATUS, AGENT, STARTED, UPDATED) of the four draft runs; works with `AIP_SERVER=local` |
| 16 | `aip run support_inbox` with 4 areas (cap 3) | `loop_cap`: `areas has 4 items, more than the 3 that tag_areas allows (At_Most)`, `resumable: false`, before any step ran |
| 17 | `aip upgrade` | `make_procedure@1  bundle 3392fc88771c  (already in the store)`: the local server started on demand and had published it itself |
| 18 | `aip list`, `aip info make_procedure`, `--example-inputs` | 3 inputs `description`, `materials`, `name`; steps `write` (Task_Agent) -> `compile` (Execute) -> `revise` (Loop Until compiled, At_Most 5, Else_Fail) { `fix` (Task_Agent) } -> `end`; result `path`, `bundle_id`, `diagnostics` |
| 19 | `aip run make_procedure --inputs {name, description=<brief>, materials: ""}` from `mp_work/` | paused at `write`; the prompt (14.4 KB) is a 40-line brief plus the language page, **byte-identical to `references/language.md`**, then "Answer with `path`: the absolute path of the folder you wrote" |
| 20 | wrote `mp_work/support_inbox_mp/` with two deliberate first-draft slips (`Produce tag` without a type; the body step ending `Next_Step end`), `aip resume <19> --answers '{"path": "<abs>"}'` | paused at `fix` (pass 0 of `revise`); `state.diagnostics` carried **both** errors with line:col and a `(step tag_area)` suffix; prompt says "Start with the first error; a later one is often its consequence" and names the `aip compile --check <folder>` command to run myself |
| 21 | fixed both lines, `aip resume <19>` with the same path | `done`; result `{path: <abs folder>, bundle_id: 0e70..., diagnostics: []}`. **Two passes** (write, one fix) |
| 22 | `aip fmt --check mp_work/support_inbox_mp` | `unchanged`: the `compile` step had rewritten my file in canonical form in place (my `Use_When "..."` is now on two lines) |
| 23 | `aip runs <19>` | a human step table: `write  Task_Agent  ... answered by cli after 36.8s -> path`, `revise  Loop  exit: until at head, 1 pass`, then `result: {...}` |
| 24 | `aip run mp_work/support_inbox_mp` "Love the product!" | done via `other -> end` |
| 25 | `AIP_DECISION_MODEL_KEY="" aip compile --check` / `info` / `run support_inbox` | **no warning anywhere, and the empty variable does not unset the key**: the run called the configured model and finished. Same with `AIP_DECISION_MODEL=""` added |
| 26 | `AIP_DECISION_MODEL_KEY=not-a-real-key aip run support_inbox` | `decision_model_failed` at `classify`: `the decision model typesafe at https://api.typesafe.ai failed on classify: TypeSafeAuthenticationError: ... 401 ...`, `resumable: true`; the key itself is not echoed |
| 27 | `AIP_DECISION_MODEL=http://127.0.0.1:9/ aip run support_inbox` | `decision_model_failed`: `Connection refused`, exit 1, `resumable: true` |
| 28 | `grep` of `docs/` for how to unset the key | `aip config --help`: `--decision-model-key KEY ... (an empty string forgets it); never printed`. No page says how to unset it through the environment |
| 29 | `aip server --local --stop` | see the end of this report |

## Findings, ranked by how much they would mislead an agent reading the skill

### 1. "A step may read only keys that every path to it has produced" is not what the compiler enforces for `End`

`references/language.md`, "The rules that matter":

> **A key has one producer on any path.** [...] A step may read only keys that every path to it
> has produced.

and "Mistakes the compiler will name":

> `unknown_key` and `unavailable_key` (read but not produced on every path)

My `End` reads `message, classification, outcome, tags`. `outcome` exists only on the refund
paths and `tags` only on the bug path; no path produces both. The compiler:

```
ok support_inbox: 9 steps, 2 files, bundle b8de4288546c
```

and at run time a result simply omits the keys that were not produced (run 7 has `outcome` and
no `tags`; run 10 has neither). Reading the page literally, I spent the first draft looking for a
way to merge the three arms before `End` (there is none without a step on every arm) and nearly
wrote a worse procedure. The rule does hold for every other step: variant v1 (a `Task_Agent`
`wrap` reading `outcome, tags` after `approve`) gives

```
v1/procedure.aip:69:69: error unavailable_key: tags is not available at wrap: tag_areas does not run before it on every path
```

And the compiler's own wording is wrong in the one case it does fire on `End`: in v7 (the `For`
with no exit line, so `tag_areas` reaches `end` on **no** path) it says

```
v7/procedure.aip:69:42: error unavailable_key: tags is not available at end: tag_areas does not run before it on every path
```

while the same `tag_areas`, running before `end` on *some* paths, compiles. The rule for `End`
appears to be "produced on at least one path, and the result carries what was produced"; neither
page says so, and `info`'s RESULT table lists all four keys as if every run returned them.

### 2. The duplicate-producer rule is stricter on the page than in the compiler

`references/language.md`, "The rules that matter":

> Two steps may produce the same key only when they are the arms of one route, or when the
> second is inside a loop body

`approve` and `human_review` (arms of `by_limit`) both produce `outcome`, which fits. Variant v2
adds a third producer `note_other` on the `other` arm of `by_kind`, a *different* route one level
up. I expected `duplicate_producer`. The compiler:

```
ok support_inbox: 10 steps, 2 files, bundle 15b352cb1658
```

The actual rule looks like "no two producers on one path", which is what the page's own first
sentence and its error description ("two producers on one path outside a loop") say. The
"arms of one route" sentence narrows it in a way an agent will obey and so avoid a legitimate
design (one `outcome` per terminal arm) that would have made my result uniform and fixed finding 1.

### 3. One error code an agent will meet is missing from the page's list

`references/language.md`, "Mistakes the compiler will name", lists fourteen codes. Writing
`Next_Step end` inside a `For` body (v8, and my deliberate slip in `make_procedure`) gives a
fifteenth:

```
v8/procedure.aip:64:5: error flow_leaves_body: Task_Agent tag_area is inside tag_areas, and a step in a loop body leaves it only with Continue, Again <step>, or the loop's own exit line; End is not reachable inside a loop body
```

The message is excellent and self-sufficient, so this is low harm, but the page says the list
is what "the compiler will name", and `Next_Step end` from a body is the single most natural
mistake in a procedure whose brief says "bug reports ... other ends". The "Loops" section does
say "nothing jumps into or out of a body", so the rule is there; the code is not.

### 4. There is no "human task" in the language, and neither page says what to use for one

The brief said "hands to a human task". `SKILL.md` frames every task as "tasks it hands to you"
and the step table has `Task_Agent` ("the agent running the procedure") and nothing else that
pauses. I used `Task_Agent human_review` and wrote "a person decides it" in the prompt; nothing
in the compiler or runtime distinguishes it (the pause is `paused: "task"` like any other, `aip
runs` records `answered by cli`). An agent asked for a human-in-the-loop step has no way to
express it and no sentence telling it that `Task_Agent` is the only choice. I could not verify
whether the spec has a human step kind; the two pages do not.

### 5. `SKILL.md` describes the pause object incompletely

`SKILL.md`, step 4:

> A pause has `step` and `tasks`. Each task has `prompt` [...], `state` [...], `references`
> [...], `answer_with` [...] and `labels` [...]. [...] A task with `"last_pass": true` is the
> last attempt its loop allows

What a task actually carried (runs 8, 9, 19, 20): `index`, `pass`, `passes`, `prompt`, `state`,
`references`, `answer_with`, `labels`. `pass` and `passes` are not mentioned (`passes: [{"loop":
"tag_areas", "pass": 1}]` is how a batch task says which item it is). `last_pass` never appeared,
not even on `fix` at pass 0 of a 5-cap loop, so I could not confirm the shape. Every outcome also
carried `run_file` and `recorded`, which the skill does not name; harmless, but the first time I
saw `"recorded": true` I checked whether something had been pushed to a server I did not configure
(it had: the local one).

### 6. The `Confidence_Below` example in `SKILL.md`'s "Example" and the page's model are hard to reach

Not a contradiction, but every classification in 8 runs came back `confidence: 1.0` with
`probabilities` of `1.0 / 0.0 / 0.0`, including "Hi, I was charged $40 for a plan I cancelled"
(refund vs. other is debatable). An agent that adds `Confidence_Below 0.6 -> human_review` (v4
compiled fine) will never see it fire and cannot tell from the pages whether that is the model or
its procedure.

### 7. Nothing warns up front about a `Decide` with no decision model, and the documented "empty string" does not unset the key from the environment

The question I was asked to test. `SKILL.md`, "Check once":

> `aip config`  # ... whether a decision model is set

and `make_procedure`'s `write` prompt, item 4:

> If you write a `Decide`, tell the requester when you report: the procedure runs only where a
> decision model is configured (`aip config` shows whether one is).

So the only up-front signal is for the agent to run `aip config` and read it; `aip compile
--check`, `aip info` and `aip run` say nothing before the `Decide` step runs. `aip info` does mark
the key as `decision` in RESULT and `Decide` in STEPS, which is enough to notice if you know to
look. With a wrong key (#26) or a dead endpoint (#27) the run fails **at** the `Decide` with
`decision_model_failed`, a clear message, `resumable: true`, and `SKILL.md` step 5 covers it
correctly. I could not produce `no_decision_model`: `AIP_DECISION_MODEL_KEY=""` (and
`AIP_DECISION_MODEL=""`) fell through to the configured key and the run succeeded (#25), so an
empty environment variable means "not set", not "forget it", while `aip config --help` says of
the flag "an empty string forgets it". No doc I found says how to clear the model through the
environment short of editing the config file, which I was told not to touch.

## Confusing or smaller

- **`aip fmt` has a canonical layout the page does not describe.** `fmt --check` rejected my
  file (header strings on their own indented line; a blank line before a loop's exit line).
  `make_procedure`'s `compile` step runs `fmt` and rewrites the folder in place; the step
  description says so, the result does not, and an agent that kept editing its own copy of the
  file would be writing over the canonical one.
- **`info` prints the whole prompt as the step description.** My `human_review` description was
  the prompt (per "the description is the prompt"), so `aip info` shows a 300-character row with
  `{amount}` unfilled. `make_procedure`'s prompt tells you to put prompts longer than a sentence in
  `assets/`; `references/language.md` mentions `Prompt assets/task.md` only in the step table.
- **Type `decision`** appears in `aip info`'s RESULT (`classification  decision`) and nowhere in
  either page's type list.
- **The brief's "amount field"** had to become a `Start` input. There is no way for a script to
  extract it from the message without an extra `Execute`, and `make_procedure`'s prompt says "no
  extra inputs". I took the input; the alternative is a stub script, which the same prompt forbids
  ("never pretends"). Both procedures therefore ask the caller for `amount`.
- **The `fix` prompt renders the diagnostics twice**, once as a JSON list inside the prose and
  once in `state.diagnostics`. Fine for two lines; a long list would be hard to read inside a
  JSON string.
- **Old flag spellings in the docs I grepped (outside the two pages)**: `README.md:414` and
  `docs/running.md:36` say `aip config --decision-model KEY`; the flag is `--decision-model-key`.

## What worked well

- **The language page is enough to write a correct procedure on the first compile.** Every
  construct I needed (a `Decide` with criteria lines, a `choice` route to `end`, a script answer
  routed on `true`/`false`, two arms producing one key, a `For` with `Collect` and `Continue`,
  `{key}` interpolation, the stdin/stdout script contract) was there, and all eleven variants I
  built from its rules behaved as described except the two above.
- **Diagnostics are exact and already say the fix.** `missing_type: Produce tag needs a type:
  tag: <type>`; `missing_requires: ... add Requires <interpreter> <version>, such as Requires
  python 3.10`; `condition_on_plain_value: ... A script or an agent task that drives one produces
  an answer type`; `missing_loop_exit: ... its block ends with Next_Step <step>`. In
  `make_procedure` both errors came back in one pass, with line:col and the step name, and one
  fix pass was enough.
- **The run contract matches `SKILL.md`.** One JSON object per stop, `done`/`paused`/`error`,
  `run_id` everywhere, the `hint` shows the batch shape, and the two wrong-shaped batch answers
  (#12, #13) were refused with messages that say exactly what the shape is and `missing_tasks`.
- **`make_procedure` end to end: 2 passes, result names the folder.** `result.path` is the
  absolute folder, `bundle_id` the compiled id, `diagnostics: []`. The `write` prompt's five
  shaping rules ("start from the result", "name who does each", "add nothing they did not ask")
  are good guidance and the embedded page is the same bytes as the skill's reference, so there is
  one language text, not two.
- **`aip runs` and `aip runs <id>` work locally now**, and the per-run view (`answered by cli
  after 36.8s -> path`, `exit: until at head, 1 pass`) reads well.
- **`loop_cap` on a `For` fires before any step runs**, exactly as the page says, with the count
  and the cap in the message.
- **Scripts got `state`, `assets`, `expects`** as documented; `amount: 40` (a JSON integer for a
  `float` input) was accepted and passed through unchanged.

## Not verified

- `aip config` output (blocked by the harness, so whether it "shows whether a decision model is
  set" in a way an agent can read is unconfirmed).
- `no_decision_model` itself: I could not reach the state without editing the user's config.
- `last_pass: true` on a task, and `Else_Exit`, `Loop ... Times`, `Loop ... Over`, `Aggregate`,
  `Use`, `references/` with a "when to load it" string, triple-quoted strings and named strings:
  none were needed for the brief and none were compiled.
- Whether the spec (`docs/language/spec.md`) has a human step kind (finding 4); I read only the
  two pages for Part 1.

## The procedure I wrote (Part 1, from the two pages, unchanged after the first compile)

`support_inbox/procedure.aip`:

```aip
Procedure support_inbox
  "Sort one customer message into a refund request, a bug report or other, and handle each: refunds within the limit are approved by a script, larger ones go to a human, bug reports are tagged per product area."

  Use_When "A customer message has arrived in the support inbox and needs a first pass."
  Do_Not_Use_When "The message is already a tagged ticket."
  Requires python 3.10

Start "The customer's message, the amount they ask for and the product areas." {
  message: string "The customer's message, verbatim."
  amount: float   "The amount the customer asks to be refunded; 0 when the message names none."
  areas: list     "The product areas a bug report is tagged against, one string each (three)."
  Next_Step classify
}

Decide classify "Is this a refund request, a bug report or something else?" {
  Read message
  Answer_Questions {
    kind: choice [refund, bug, other] "What is the customer asking for?"
      refund: "The customer wants money back for a charge."
      bug:    "The customer reports that the product misbehaves."
      other:  "Anything else: a question, praise, spam."
  }
  Produce classification
  Next_Step by_kind
}

Route by_kind "Refunds go to the limit check, bug reports to tagging, anything else ends." {
  Read classification.kind
  refund -> check_amount
  bug    -> tag_areas
  other  -> end
}

Execute check_amount "Is the amount at or under the 100 limit?" {
  Read amount
  Run_Script scripts/check_amount.py
  Produce within_limit: true_or_false
  Next_Step by_limit
}

Route by_limit "Within the limit is approved by the script; above it a human decides." {
  Read within_limit
  true  -> approve
  false -> human_review
}

Execute approve "Approve the refund and record it." {
  Read message, amount
  Run_Script scripts/approve.py
  Produce outcome: string
  Next_Step end
}

Task_Agent human_review "A refund of {amount} is above the automatic limit of 100. Read the customer's message and decide whether to approve or decline it, and say why in one or two sentences. Customer message: {message}. Answer with outcome: a sentence that starts with APPROVED or DECLINED." {
  Read message, amount
  Produce outcome: string
  Next_Step end
}

For tag_areas Over areas As area, At_Most 3, Collect tag Into tags {
  Task_Agent tag_area "Does this bug report concern the product area {area}? Customer message: {message}. Answer with tag: the area name followed by a colon and 'affected' or 'not affected', with a few words of reason." {
    Read message, area
    Produce tag: string
    Continue
  }
  Next_Step end
}

End "The message is classified; a refund is approved or decided by a human, a bug report is tagged per area." {
  Read message, classification, outcome, tags
}
```

`scripts/check_amount.py`:

```python
import json, sys

payload = json.load(sys.stdin)
amount = float(payload["state"]["amount"])
print(json.dumps({"within_limit": amount <= 100}))
```

`scripts/approve.py`:

```python
import json, sys

payload = json.load(sys.stdin)
amount = payload["state"]["amount"]
print(json.dumps({"outcome": f"APPROVED: refund of {amount} is within the automatic limit of 100."}))
```

The `make_procedure` folder (`mp_work/support_inbox_mp/`) is the same design with the two
`Task_Agent` prompts moved to `assets/human_review.md` and `assets/tag_area.md` per its prompt's
instruction, and `procedure.aip` rewritten by `aip fmt` as part of the run.
