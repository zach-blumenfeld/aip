# AIP 0.9 first-use report: ticket-triage, from a reader's seat

Binary `aip 0.8.0 language 0.9` (`/Users/zach/dev/aip-0.9/.venv/bin/aip`, below `$AIP`). `$EX` is `examples/language/ticket-triage`. `$AIP_HOME` is the scratch home named in the brief; nothing in the repo was touched. Seven runs reached the decision model (3-ticket batch, 1 ticket, my own procedure, cap test, two index probes); three did not (empty list, 51 tickets, the retries). Total decision-model calls: 6 batches/calls.

Note on the brief: ticket-triage has **no `Aggregate` step**. After the `For` comes `Task_Agent summarize`; the "aggregation" is the `For`'s `Collect reply Into replies` and the runtime's `iterations` key. The brief's description of the example does not match the example; everything below reports what the example does.

## What I ran (commands, in order, with outcome one-liners)

| # | Command | Outcome |
|---|---|---|
| 1 | `$AIP compile --check $EX` | `ok ticket_triage: 9 steps, 2 files, bundle a50deb323ed2` |
| 2 | `$AIP compile --check --json $EX` | full graph: 27 nodes, ~75 edges, `diagnostics: []`; `READ_BY` on the route carries `"source": "measured"` |
| 3 | `$AIP info $EX` | readable card; `run:` line gives a copy-pasteable command; RESULT `summary string, replies list` |
| 4 | `$AIP fmt --check <copy>` then `$AIP fmt <copy>` | exit 1 "would reformat", then 4 changes (below); second `fmt` is a no-op (idempotent); `export` after `compile -o` reproduces the folder byte for byte |
| 5 | `$AIP run $EX --inputs @inputs3.json --progress` (complaint, how-to, cancellation) | exit 0; `--progress` printed only `start`, then `{"paused": "task", "step": "draft", "tasks": [index 0 = pass 1, index 1 = pass 2]}`; the angry ticket (pass 0) was already escalated silently |
| 6 | `$AIP resume 030f… --answers '{"0": {...}, "1": {...}}'` (reply 1 deliberately misses the policy sentence) | `{"paused": "task", "step": "fix", "tasks": [{"index": 0, "pass": 0, "passes": [each_ticket 2, revise 0]}]}`; still no progress lines |
| 7 | `$AIP resume 030f… --answers '{"0": {"reply": "...policy sentence..."}}'` | 16 progress lines arrive at once (whole batch), then paused at `summarize` with `replies` of 3 |
| 8 | `$AIP resume 030f… --answers '{"summary": "..."}'` | `{"done": true, "result": {"summary": ..., "replies": [3]}}` |
| 9 | `$AIP run $EX --inputs '{"tickets": ["Where do I change the email..."], ...}'` | paused at `draft`, one task, `pass: 0` |
| 10 | `$AIP resume f683… --answers '{"1": {...}}'` (wrong index on purpose) | exit 1 `invalid_output: the output of 'draft': no answer for task 0 (pass 0)`, `missing: ["0"]` |
| 11 | `$AIP resume f683… --answers '[{"reply": ...}]'` (correct, as a list) | exit 1 **`not_paused: run f6839a235e424ba0 is failed, not paused; an answer needs a pause (resume it with no answers to retry the failed step)`** |
| 12 | `$AIP resume f683…` (no answers) | re-pauses at `draft` with the same task |
| 13 | `$AIP resume f683… --answers '{"0": {...}}'` then `--answers '{"summary": ...}'` | `revise` exits `"exit": "until", "iterations": 0`; `each_ticket` `"exit": "items", "iterations": 1`; done |
| 14 | `$AIP run $EX --inputs '{"tickets": [], ...}'` | `each_ticket ... "exit": "items", "iterations": 0`, paused at `summarize` with `"replies": []`; answered → done. No model call |
| 15 | `$AIP run $EX --inputs @inputs51.json` (cap 50) | exit 1 `{"error": "loop_cap", "step": "each_ticket", "message": "tickets has 51 items, more than the 50 that each_ticket allows (At_Most)", "cap": 50, "count": 51, "resumable": true}`; run file written with status `failed` |
| 16 | `$AIP resume 09d2…` (retry the cap failure) | the identical `loop_cap` error again; `resumable: true` still |
| 17 | own procedure `expense-review`: `compile --check`, `info`, `run` (meals claim), `resume` | compiled first try; model: `category meals 1.0`, `receipt true 0.98`; route `-> review`; done with `assessment` object + `note` |
| 18 | 12 compile probes on my procedure, 7 more | see "Writing a procedure" |
| 19 | five breaks of ticket-triage, `compile --check` and `--json` | see "Breaking it" under Bugs/Confusing |
| 20 | cap test: 1 ticket, bad `draft`, bad `fix` ×3 | passes `revise 0,1,2` then exit 1 `loop_cap: revise ran 3 passes without its condition holding (At_Most 3, Else_Fail)`, `"pass": 3`; a 4th answer → `not_paused` |
| 21 | index probe: copy with `Execute check ... Read reply, policy, index`, 1 ticket, bad draft, bad fix ×2, good fix | `check` saw `index = 0, 0, 1, 2` across For pass 0 / revise passes 0,1,2; final `iterations = 1` (the For's; the inner `3` is gone) |
| 22 | `$AIP runs` | `aip: no server is configured...` — there is no local listing of `$AIP_HOME/runs` |

`fmt` changes on ticket-triage: dropped the blank line after the `For {`; aligned `tone:    choice` under `billing:`; split `Produce reply: string, queue: string` into two lines with the second indented to the column after `Produce `; added a blank line before the loop's `Continue`. Result is slightly nicer; the odd one is the continuation indent (`            queue: string`), which no human would type.

## Writing a procedure from the spec

I wrote `expense_review` (Start, Decide with a `choice` and a `true_or_false`, Route with `Confidence_Below` and `travel -> end`, Task_Agent, End reading a decision key and a key only one path produces) from the spec alone. **It compiled on the first attempt** (`ok expense_review: 5 steps, 0 files`). So the ordered-error sequence the brief wanted is empty; the useful substitute is the list of things I was unsure of while writing, each resolved by a one-line probe. In the order I hit them:

1. **Can a route branch go straight to `end`?** The spec only says `Next_Step end` (2.1 Flow). Probe: `travel -> end` compiles and runs. Spec should say "a branch target may be `end` or `Continue`" in the Route row.
2. **Does a Route also need `Next_Step`?** Spec says "Its branch lines are its Next_Step" (table 2.1) but every other card ends with one. Probe `Next_Step review` inside a Route: `26:3: error syntax_error: 'Next_Step' is not a clause of Route; Route takes Read, Confidence_Below, <value> -> <step>`. Good message. Learnt: the table is the law.
3. **Do I read `assessment.category` or `assessment.category.value`?** 2.4 says a template names `{triage_decision.tone.value}` and "an answer's value and confidence are the only field access… in a Read, a route, a script or a template", which reads as if `.value` is allowed in a Read. Probe on the Route: `21:8: error condition_on_plain_value: assessment.category.value is a string; a route is on an answer (true_or_false, choice or score), never a plain value.` Learnt: a Route reads the answer, not its field. But `Task_Agent ... Read assessment.category.value` and `.confidence` both **compile fine**, so `.value` is a legal Read path after all — the spec never shows one. Say so, with an example, and say a Route refuses it.
4. **Does `Confidence_Below` have to come before the branches?** 2.1 lists "then the check… and one value -> step line per label". Probe with the check last: compiles. Spec should say "in any order".
5. **Where does the header end?** I first wrote `Use_When` under `Procedure`, which works. Probe moving it below Start: `9:1: error syntax_error: expected a step (Start, Decide, Route, Aggregate, Execute, Task_Agent, End), a loop (For, Loop) or a named string, got 'Use_When'`. Right line; a newcomer would not learn from it that `Use_When` belongs in the header. Add "header clauses (Use_When, …) go before the first step" to the message.
6. **Is `Produce note` enough on a Task_Agent?** `30:11: error missing_type: Produce note needs a type: note: <type>`. Perfect.
7. **`true_or_false` branches: `yes/no` or `true/false`?** Probe `yes -> review` / `no -> end`: three errors, `missing_branch ... has no branch for true and false` plus two `unknown_label: yes is not a value of assessment.receipt; its values are true and false`. Right answer, but one mistake produced three errors (the `missing_branch` is a consequence of the two). Collapse it.
8. **A `score` answer: do branches name labels or levels?** 2.4: "`score.value`: integer, the most probable level"; `cli-json.md`: a score answer is "the level's number (its position in the labels, from 0)". Probe `0 -> end` / `1 -> end` / `2 -> review`: `unknown_label: 0 is not a value of assessment.urgency; its values are low, medium and high` (plus a `missing_branch` for all three). Probe `low/medium/high`: compiles. **So a Route branches on the label while the documented `value` is an integer.** The spec must say which; today it says both.
9. **Can a Decide have no `Read` at all?** Probe deleting `Read claim`: compiles with no warning. 2.1 says "`Read` is what the model judges", so a Decide that judges nothing should at least be a warning.
10. Aliases (`next assess`, `Questions {`, `Task review`) all compile as promised. Good.
11. **Forgetting `Produce` on a Decide**: `10:1 missing_clause: Decide assess names no key; Produce <key> names the one key whose fields are its answers` — then three `unknown_key: nothing produces assessment` at every reader. One cause, four errors.
12. **Second producer of a key**: `Produce note: string, assessment: string` on the Task_Agent gave `duplicate_producer: assessment is already produced by assess on a path to review, and a key has one producer per path; put the second in a loop if it is a rewrite, or give it a different name` — excellent — followed by two `type_mismatch` with the garbled phrase **"the decision assess produces from assess"**.

What the spec should have said, in one place near the top: a 15-line "shape of a card" cheat sheet with the three clause orders and the allowed branch targets (`<step>`, `end`, `Continue`), the `.value`/`.confidence` Read rule, and the label-vs-level rule for `score`.

## Bugs (wrong behaviour, crashes, contradictions between docs and CLI)

1. **A bad answer kills the pause.** `docs/cli-json.md`: "An answer that does not fit its pause leaves the pause in place; answer it again." CLI (runs 10–12): after `invalid_output` the run is `status: failed` and the next answer is refused with `not_paused: run … is failed, not paused; an answer needs a pause (resume it with no answers to retry the failed step)`. You need a bare `aip resume <id>` first. Either the doc or the runtime is wrong; the doc's behaviour is the one an agent wants.
2. **"The first pass always runs" is false.** Spec 2.1 Loops and 2.3 both say it; the runtime tests `Until` at the head and skips the body: run 13 and the batched run's record `"step": "revise", "result": {"iterations": 0}, "exit": {"reason": "until", "where": "head", ...}`. The example depends on this skip (a reply that passes `check` must not go to `fix`). The spec sentence should be "the body runs at least once only when the answer is absent before the loop".
3. **`index` inside nested loops is the innermost loop's, even for a step that is not in that loop.** Spec: "Inside a body `index` names the pass." `check` sits in the `For` body, outside `revise`; reached by `Again check` from `fix`, it saw `index = 1` then `2` (run 21, `stdin.state.index`), the `revise` count, not the `For` pass (0). The frame in the failed cap run shows the leak: `"cursors": [{"state": {..., "index": 2, ...` for `each_ticket` pass 0. Either document that `index` is the innermost *active* loop's and that `Again` runs the target "inside" that loop, or restore the outer `index`.
4. **`iterations` is one key for all loops.** After the run, `state.iterations = 1` (the For's); `revise`'s `3` is only in the record (`"result": {"iterations": 3}`). Spec: "after the loop `iterations` says how many ran" — true only for the last loop that exited. A step after a `For` that wants the inner loop's count cannot get it.
5. **`loop_cap` on a `For` is `resumable: true` and the retry fails identically** (runs 15–16). `runtime.md` line 101 admits "a retry arrives at the head again and fails the same way". Then `resumable` should be `false`, as it is for `invalid_input`.
6. **`--progress` is blind until a batch completes.** Runs 5 and 6 printed one line (`start`) and then the pause; three model answers, three route decisions and a script run were invisible for ~14 s and only appeared, 16 lines at once, in run 7. Documented ("entries appear when its batch completes"), but it defeats the flag's purpose on exactly the runs where you want it.
7. **Version string**: `aip --version` → `aip 0.8.0 language 0.9`, `compile --json` → `"compiler_version": "0.8.0", "language_version": "0.9"`. The repo and spec call this "AIP 0.9". A newcomer reads 0.8.0 as the wrong install.
8. **`aip runs` with no server**: `aip: no server is configured…`, exit 0, although `$AIP_HOME/runs/` holds seven run files. The help says "with a run id, that run's record (this machine's run file when it has one)"; listing should fall back to the local files too.
9. **One cause, many errors** (items 7, 11, 12 above; break b4 below gave `missing_loop_exit` plus two `unreachable_step`). Not wrong, but a newcomer fixes the first and is surprised the rest vanish.

## Breaking ticket-triage (five diagnostics)

| Break | Diagnostic | Verdict |
|---|---|---|
| b1 delete `angry -> escalate` | `32:3 missing_branch: Route by_tone has no branch for angry; a route names every value classification.tone can take` | Right, points at the Route header (32) not the gap; a newcomer knows what to do. |
| b2 `draft` reads `passed` | `40:26 unavailable_key: passed is not available at draft on every path: check does not run before it on every path` | Right line and column (the key itself). Fine. "on every path" twice in one sentence. |
| b3 `classify` as a Task_Agent, keep `Confidence_Below` | `30:5 confidence_on_agent_answer: tone is the agent's answer (produced by classify), which has a value and no confidence, so Confidence_Below cannot apply to it; route on its value alone, or ask a decision model in a Decide` | Best message in the set: cause, rule, two fixes. |
| b4 delete the For's `Next_Step summarize` | `20:1 missing_loop_exit: For each_ticket does not say where the run goes when it exits; its block ends with Next_Step <step>` + `70:1 unreachable_step: nothing reaches Task_Agent summarize` + `76:1 unreachable_step: nothing reaches End` | Right; the two cascades are noise. Points at the `For` line, not its closing brace where the line is missing. |
| b5 `Answer_Quesions` | `24:5 syntax_error: expected a clause of Decide (Read, Answer_Questions, History, Produce, Next_Step, Continue, Again), got 'Answer_Quesions'` | Right line; the candidate list is what a newcomer needs. A "did you mean Answer_Questions?" would finish it. |

## Confusing (spec passages, wording, JSON shapes, error messages)

- **Two names for the same thing.** The summary example is `Decide classify … Produce classification`; the prose and tables use `Decide triage … Produce triage_decision` (2.1 table, 2.4, glossary). Reading 2.4 while looking at the example, I kept checking whether `triage_decision` was a third key.
- **2.1 "The one exception is `end` … and `Continue` as a route target"**: two exceptions introduced as one.
- **2.1 `Again`** ("re-enters the procedure at a step (or a loop) at the level of the enclosing loop, from which the flow reaches that loop again, and follows the flow from there; when the loop is reached the pass is over, as with Continue, and the loop keeps its count") took three reads. The record then attributes the re-run `check` to `passes: [each_ticket 2, revise 0]`, so the step "at the level of the enclosing loop" is recorded as inside the inner one. Say plainly: "`Again check` runs `check` as part of the current `revise` pass".
- **"`question_labels` when they are missing, or on a type that has none"** (2.1, in parentheses, mid-sentence) is a diagnostic code dropped into prose.
- **Glossary `Route`: "the runtime, from a value in the state"** vs 2.1/2.2 "from one answer". The whole design is that it is never a plain value.
- **`true_or_false` has the alias `noul`** (types table) — a model's field name as a type alias. Nobody will write it, and seeing it makes `noul` in the JSON look like a type.
- **Decision history in a spec row**: "Decisions need a model (2026-11-09)" explains `Agent_Fallback`, `reason: manual`, `reason: hand` — three things that no longer exist. Move to a changelog.
- **"`Produce` always needs a type, except on a decision"** sits in a paragraph that starts with `Read`; I missed it the first time and found it only via `missing_type`.
- **Header end rule**: "The header ends where the first step, loop or named string below it begins" — the example puts `classify_question = …` after `Requires`, so the header ended before I expected; fine, but the probe shows a header clause after that point is just a syntax error with no hint.
- **`Loop <name> <n> Times`** gets one sentence; nothing says whether it takes `Else_*`, what `Until` it has (none), or whether `Continue` is needed.
- **Score levels vs labels** (item 8 above). cli-json.md says a score answer is "the level's number"; the compiler says "its values are low, medium and high".
- **JSON shapes.** (a) The pause's `tasks[i].index` is the answer key, `tasks[i].pass` is a loop pass number; in a single-loop run they differ (index 0 is pass 1), which is right, but `index` is also the runtime's reserved state key, a third meaning of the word. (b) The run file calls the record `run.history`; the docs call it "the record" and `--progress` "record entries"; `History true` on a Decide is a fourth use of "history". (c) `"pass"` on a loop's own exit entry is the *enclosing* loop's pass (`"step": "revise", "pass": 1`), while on a step it is the innermost. (d) History entry 9 has `at: 19:40:45.020`, earlier than entry 8's `19:40:58.197`: entries are in pass order, not time order, which is documented but surprises anyone sorting by `at`. (e) The route's entry has `"result": {"to": "escalate"}` and also top-level `"to": "escalate"`, `"value"`, `"read"`, `"check"`: the same fact twice.
- **`aip: not recorded: no server is configured; run \`aip config --server URL\`…`** on stderr at every single `run`/`resume`. Once per session would do.
- **`type_mismatch` message**: "assessment is a string here and the decision assess produces from assess" — "produces from assess" is not a sentence.
- **Empty-list run**: `summarize` is asked to "Summarize the batch" with `"replies": []`. Not a bug, but a `For` with zero passes followed by a Task_Agent is a shape the spec could warn about.

## Good (what was clear; keep short)

- The card shape works: after the spec I wrote a 5-step procedure that compiled first time, and `aip info` read it back as I meant it.
- `compile --check` is instant and every diagnostic had the right line; `confidence_on_agent_answer`, `missing_type`, `duplicate_producer`, `missing_branch`, `unknown_label` say the rule and the fix.
- The paused JSON is self-sufficient: `prompt`, `state`, `answer_with`, `labels`, and `passes` told me exactly which ticket I was answering (`tasks[1].pass = 2` → the cancellation) without opening the run file.
- The run record answers the governance questions: per entry, which ticket (`input.ticket` on `classify`/`draft`/`escalate`; `passes` on `check`/`fix`), what the model said and how sure (`"tone": {"value": "angry", "confidence": 1.0, "probabilities": ...}`), what the route did (`"check": {"below": 0.6, "confidence": 1.0, "fired": false, "reason": null}`), what a script got on stdin, why a loop ended (`"exit": {"reason": "until", "where": "head", "resolution": {...}}`), and what the `For` collected (`"result": {"iterations": 3, "replies": [...]}`). The result is readable without the source.
- `fmt` is idempotent and `compile -o` → `export` reproduces the folder byte for byte with the same bundle id.
- Batching: three passes went to the model as one call and one pause carried both open tasks; keyed answers worked first time.

## Top 5 changes I would make, ranked

1. **Make a rejected answer leave the pause in place** (Bug 1), as `cli-json.md` already promises; or, if the failed-then-retry dance is intended, change the doc and make the `not_paused` message say "resume with no answers, then answer again".
2. **Fix the loop prose in the spec to match the runtime**: delete "the first pass always runs" (2.1, 2.3), define `index` and `iterations` under nesting (innermost active loop; the outer count is lost), and state what `Again` does to pass attribution. Then decide whether `check` seeing the inner `index` is the behaviour you want (Bugs 2–4).
3. **One name per concept across spec, example and JSON**: `classification` vs `triage_decision`; record vs `history`; label vs level for `score` (pick labels, since that is what compiles, and fix 2.4 and cli-json.md).
4. **Collapse cascaded diagnostics** so one mistake prints one error (missing `Produce` on a Decide → 4; wrong `true/false` labels → 3; missing loop exit → 3), and add "did you mean" to `syntax_error` for a keyword within edit distance 1–2.
5. **Make `--progress` stream inside a batch** (or print a one-line `batch` event with the passes' `classify`/`by_tone` results as each completes), and drop the per-command "not recorded" stderr line to once per run. Smaller: `aip runs` should list `$AIP_HOME/runs` when no server is configured, and `loop_cap` on a `For` should be `resumable: false`.
