# AIP 0.9 first-run report: billing-support and billing-support-agent

Binary `aip 0.8.0 language 0.9`, `AIP_HOME` pointed at a scratch dir (nothing landed in `~/.aip`). 5 decision-model runs, 6 agent-side runs. The storage engine is referred to only as ".rl bundle" below; two CLI messages and spec section 3 name it and are redacted here.

## What I ran (in order)

| # | Command | Outcome |
|---|---|---|
| 1 | `aip compile --check examples/language/billing-support` (and `-agent`) | `ok billing_support: 6 steps, 5 files, bundle a041de256ece` / `43c062fef8e7` |
| 2 | `aip compile --check --json billing-support` | ok; full graph with source spans (nodes, edges, `source: measured` on the route's read edge) |
| 3 | `aip compile billing-support -o bs.rl`, then again to `bs2.rl` | same id both times; `cmp` says the files differ in 398 bytes |
| 4 | `aip compile billing-support-agent` (no `-o`) | writes `billing_support_agent.rl` in cwd, as help says |
| 5 | `aip info <folder>`, `--json`, `--example-inputs`, `aip info bs.rl` | all fine; human summary is good |
| 6 | `aip export bs.rl --out bs-export`; `diff -r` against source | `IDENTICAL` for both examples; recompiled export gives same id; mode preserved; second export into same dir refused (`pass --force`) |
| 7 | `aip fmt --check` on both shipped examples | `would reformat ...procedure.aip` for both; exit 1 |
| 8 | `aip run billing-support --progress` angry | done in 0.45 s; `"to": "escalate"`, result `ticket_id 35566, queue tier2` |
| 9 | `aip run billing-support` calm | paused at `reply`; `tone.confidence 1.0` |
| 10 | `aip resume 696842d410c2470f --answers '{"reply": "..."}'` | done; result `message` + `reply` |
| 11 | `aip run billing-support` ambiguous x3 ("Hm. Saw two March charges... a bit annoyed but maybe I misread", "Charged twice again. Whatever...", "Refund. Now. Please and thank you :)") | calm 0.82 / angry 1.0 / angry 0.82. Never below 0.6; `check.fired: false` every time |
| 12 | `aip run billing-support-agent` calm msg -> pause at `triage` | `answer_with {billing: true_or_false, tone: choice}`, `labels {tone: [angry, calm]}` |
| 13 | `aip resume <A> --answers '{"billing": true, "tone": "furious"}'` | `invalid_output`: `tone: 'furious' is not one of the labels ['angry', 'calm']` |
| 14 | `... --answers '{"billing": true}'` | `invalid_output`: `tone is missing` |
| 15 | `... --answers '{"billing": true, "tone": "calm", "confidence": 0.9}'` | **accepted**, run moved to `reply`; the extra key silently dropped |
| 16 | `... --answers '{"billing": true, "tone": {"value": "calm", "confidence": 0.9}}'` (fresh run) | `invalid_output`: `tone: an agent's answer is its value and nothing else, not confidence` |
| 17 | `... --answers '{"billing": "yes", "tone": "calm"}'` | `invalid_output`: `billing: a true_or_false answer is an object with a value, not a string` |
| 18 | `... --answers '[{...}, {...}]'` (two answers, one task) | **accepted**; second silently dropped |
| 19 | `aip resume <paused>` with no answers | `invalid_input`: `is paused at reply: give the answers to its 1 task(s); only a failed run is retried without any` |
| 20 | `aip resume <B> --answers '{"billing": {"value": true}, "tone": {"value": "angry"}}'` | done via `escalate`, same ticket id as model run (deterministic script) |
| 21 | `aip resume <A> --answers '[{"reply": "..."}]'` (list form) | done |
| 22 | `aip resume deadbeef00000000 --answers ...` | `invalid_input`: `no run 'deadbeef00000000' on this machine (looked for .../runs/deadbeef00000000.json)` |
| 23 | `aip resume <done> --answers ...` / no answers / by file path | `not_paused`: `is done, not paused; an answer needs a pause` / `is done; there is nothing to resume` |
| 24 | `aip run ... --inputs '{}'`, no `--inputs`, extra key, `{"message": 5}`, `'["hi"]'` | `invalid_input` each; `message is missing` / `priority is not an input of this procedure; the inputs are ['message']` / `message: expected a string, got an integer` / `the inputs are a JSON object, got list` |
| 25 | `aip run /nonexistent/folder`; `aip run billing_support` (name, no server) | `kind: not_found` / `kind: no_server` with a clear hint |
| 26 | syntax error copy (`angry -> escalate ->`): `compile --check`, `--json`, `aip run` | `50:21: error syntax_error: expected a clause of Route (Read, Confidence_Below, <value> -> <step>), got '->'`; run gives `kind: compile_error` |
| 27 | semantic copies: `Next_Step by_tonee` + dropped `calm` branch; `Confidence_Below` on agent answer | 5 errors (1 `unknown_step` + 4 `unreachable_step`); `confidence_on_agent_answer` with a good message |
| 28 | hand-edited bundle bytes (`tier-2` -> `tier-9` at both offsets); truncated file; text file | edited bundle **runs, exports and infos as if untouched**; truncated/text -> `kind: not_a_bundle` |
| 29 | `aip run bsa.rl`; `--inputs @file`; `--inputs -`; `--inputs '{bad'`; `@/nonexistent.json` | all behave; parse errors say `give JSON inline, @path for a file, or - for stdin` |
| 30 | `aip runs`, `aip runs --json`, `aip runs --status done`, `aip runs zzz` | all: `aip: no server is configured; run \`aip config --server URL\`...` exit 1, with 12 run files on disk |
| 31 | `aip runs 60a24a92b7cc4b2b` and `--json` | both print the same JSON record; works without a server |
| 32 | `aip --help`, every subcommand `--help` | all fine except `aip server --help` (below) |
| 33 | `aip run --show` (named in `docs/language/end-to-end.md`) | `usage: ...` exit 2; flag does not exist |

## Bugs

1. **`aip server --help` crashes with a traceback.** `ImportError: cannot import name 'config_path' from 'aip.client.server' (src/aip/client/server.py)` from `src/aip/server/config.py:106`. Every other `--help` works.
2. **An extra top-level key in an answer is silently accepted.** `aip resume <id> --answers '{"billing": true, "tone": "calm", "confidence": 0.9}'` moved the run to `reply`. `docs/cli-json.md`, Paused: "An answer that does not fit the step's keys is refused and nothing is applied." Start inputs are strict (`priority is not an input of this procedure`), answers are not. Same for a list with two answers for a one-task pause (#18): accepted, second dropped.
3. **`aip runs` refuses to list local runs.** With 12 run files under `$AIP_HOME/runs`, `aip runs` prints `aip: no server is configured; run \`aip config --server URL\` to record runs on a server` and exits 1, while `aip runs <id>` happily reads the local file. Help says "The server's runs ... with a run id, that run's record (this machine's run file when it has one)", so it is as documented, but the asymmetry is a trap: there is no way to find a run id you lost except `ls $AIP_HOME/runs`.
4. **`aip runs <bad id>` gives the wrong error.** `aip runs zzz` -> `no server is configured`. `aip resume zzz` -> `no run 'zzz' on this machine (looked for ...)`. The second is right; the first hides the real cause.
5. **Shipped examples are not in canonical form.** `aip fmt --check examples/language/billing-support` -> `would reformat`, exit 1. The diff is alignment only (`tone_question  =`, `tone:    choice`, de-aligning `queue:` under `ticket_id:`), but a new user running `fmt --check` in CI on the examples fails, and the formatter changes the bundle id (`a041de256ece` -> `1610573b462a`) since the id hashes source bytes.
6. **Hand-edited bundle bytes are not detected.** Changing `tier-2 ticket` to `tier-9 ticket` at both offsets inside `bsa.rl` and running it: paused normally, `aip export` reproduced the untouched source, `aip info` showed `tier-2`. So the bytes I changed are dead copies inside the file, not the live record, and no integrity check covers the file as a whole. Spec 3 promises `bundle_tampered` for "any difference"; in practice a bundle can carry arbitrary foreign bytes and still verify. Related: the bundle is 69 KB for 4 KB of source, and two compiles of the same folder differ in 398 bytes while sharing an id, which means two "identical" bundles are not `cmp`-equal and the file cannot be checksummed as a release artifact.
7. **`not_a_bundle` messages leak internal storage names.** The messages for a truncated and a text `.rl` quote the engine's internal format name, magic string and page vocabulary (redacted here). A user-facing error should say "not an .rl bundle" and stop.
8. **One typo yields five errors.** `Next_Step by_tonee` produces `unknown_step` and then `unreachable_step` for `by_tone`, `escalate`, `reply`, `End`. The four cascades are consequences, not errors.
9. **Docs name a flag that does not exist.** `docs/language/end-to-end.md:49`: "`aip runs` and `aip run --show`". `aip run --show` -> usage error exit 2.

## Confusing

- **`run.at` means two things.** In every history entry `at` is a timestamp (`"at": "2026-11-09T19:40:40.378+00:00"`); at the run level `"at": null` for a done run and `"at": "step:reply"` for a paused one, a cursor. I read `at: null` as "no timestamp recorded" until the paused file showed otherwise.
- **The route's `input` key is spelled differently from everyone else's.** `by_tone` records `"input": {"triage_decision.tone": {...}}` (dotted) and also `"read": "triage_decision.tone"`, while `escalate`, which reads the same thing, records `"input": {"tone": {...}}` and the paused task's `state` has `tone`. Three spellings of one value in one file.
- **Who answered a `Task_Agent` is not in its record.** `triage` (agent) has `prompt`, `references`, `result` and no `answered_by`; `Decide` has `answered_by: {model, endpoint}`. `identity.agent: "cli"` sits once at run level. For governance ("which routes an agent steers") the per-step record is where I looked first.
- **Pause duration is invisible.** The `reply` entry's `at` is the resume time (`19:41:15.085`); the previous entry is `19:40:51.571`. Nothing says "paused at X". I had to subtract and infer that 24 s was my typing, not the runtime.
- **Only scripts get `seconds`.** The decision took ~295 ms (from `at` deltas); nothing records it. `--progress` shows `seconds` for `Execute` only.
- **`history_sent: false` on a decision** is not in `docs/cli-json.md`'s list of record keys; it is explained only in `docs/language/runtime.md` ("whether the history was sent"). Two more undocumented top-level run keys: `requires_checked`, `frames`.
- **`check.reason: null` when `fired: false`.** `cli-json.md` lists `reason: below | absent`; `null` is the third value and not named.
- **`bundle_id` repeated on every history entry** (64 hex chars x 5 steps) makes `cat run.json` 40% id. `aip runs <id>` prints the same JSON with no human layout, so there is no readable "what happened" view at all in the CLI; `aip info` gets a nice summary, a run does not.
- **"not recorded" line prints before the output, every time.** `aip: not recorded: no server is configured; run \`aip config --server URL\`...` on stderr for every run and resume, including the ones that fail with `invalid_output`. First-time read: I thought the run file had not been written.
- **`invalid_output` on a wrong-step answer does not say what was wrong.** Answering the `reply` pause with `{"billing": true, "tone": "calm"}` gives `the output of 'reply': reply is missing`, `invalid: []`. Start inputs name the stray keys (`priority is not an input of this procedure; the inputs are [...]`); answers should too.
- **Two spellings for the same value: `"tone": "calm"` and `"tone": {"value": "calm"}`.** Both work (#12, #20). Fine once known, but `answer_with: {"tone": "choice"}` does not say which; a first-timer tries `{"tone": {"value": "calm"}}` because that is how `state` shows it.
- **`info` for the agent example prints the whole prompt as the step description**, with `{message}` unfilled: `triage  Task_Agent  Read the customer's message and classify it. Customer message: {message} Answer ...`. The spec says "the description is the prompt" (open item 2); the table layout breaks on it.
- **Three ids, three lengths.** `compile` prints 12 hex (`a041de256ece`), `--json` 64, run ids 16. Fine, but `aip info` shows `a041de256ece…` with an ellipsis and no way to get the full id short of `--json`.
- **Spec vs. example comment.** `billing-support/procedure.aip` line 3 says "written in the language of docs/spec.md, section 2.1"; the file is `docs/language/spec.md`. Line 7 says `aip config --decision-model`; the key is set with `--decision-model-key`.
- **Confidence branch is hard to reach.** `Confidence_Below 0.6` needs `|p_angry - p_calm|` small; the model gave 1.0 for three of five messages and 0.82 for the two I built to be mixed (`probabilities: {angry: 0.91, calm: 0.09}` for "Refund. Now. Please and thank you :)"). I could not fire it. The record did say so plainly: `"check": {"below": 0.6, "confidence": 0.82, "fired": false, "reason": null}`. For a tutorial example, 0.6 is a branch nobody will see; 0.9 would demonstrate it.
- **`aip --help` lists command names only.** No one-liner per command; `aip db --help` still says "Load skills into Neo4j", a 0.8 concept, and `aip config --help` is the only place that says a `Decide` fails without a model.

## Good

- `aip compile` output is one line, says steps, files, id. Diagnostics are `file:line:col: severity code: message` and `--json` has the same shape with spans; `syntax_error` says what was expected.
- `confidence_on_agent_answer` message is a model for the rest: names the key, the producer, why, and two fixes.
- `aip info` human summary, with the ready-to-paste `run:` line, is the best onboarding surface here.
- Export is byte-for-byte and the id survives a round trip; refusing a non-empty `--out` is right.
- The JSON contract holds: every stop was one object, exit 0/1 as `cli-json.md` says, `--progress` lines are clean JSONL, stderr never leaked into stdout.
- Answer validation messages (#13, #16, #17) are specific and quote the labels.
- `aip resume` by id from any cwd, or by file path, both work; `not_paused` messages are exact about why.
- Speed: a full model-backed run in 0.45 s wall.

## Top 5 changes, ranked

1. **Make answers as strict as inputs.** Refuse unknown top-level keys and surplus list entries in `--answers` with `invalid: [...]` naming them, as `start` already does (`is not an input of this procedure; the inputs are [...]`). Bug #2 is a silent-success class of error and contradicts `cli-json.md`.
2. **Give `aip runs` a local mode and a human view.** `aip runs` with no server lists `$AIP_HOME/runs` (id, name, status, created); `aip runs <id>` prints a step table (step, kind, at, +duration, to/answered_by/fired) with `--json` for the record; `aip runs <bad id>` says "no run on this machine". Fixes bugs #3 and #4 and the biggest interpretability gap.
3. **One name, one meaning in the record.** Rename run-level `at` (cursor) to `position`; record `paused_at`/`resumed_at` (or `waited_seconds`) on a task entry and `seconds` on a decision; add `answered_by: {agent: "cli", session}` to `Task_Agent` entries; use one spelling for a read key in `input` (`tone` everywhere, with `read: "triage_decision.tone"` kept for lineage); document `history_sent`, `requires_checked`, `frames`, `reason: null` in `cli-json.md`.
4. **Fix `aip server --help`, run `aip fmt` on the shipped examples, and gate on `fmt --check` in CI.** Both are five-minute fixes and both are what a new user hits in the first ten minutes.
5. **Bundle integrity and error hygiene.** Either verify the whole file (a trailing checksum over the live bytes, or a canonical write so two compiles of one id are `cmp`-equal and dead pages cannot exist) or soften spec 3's "any difference is `bundle_tampered`" to what is actually checked. Strip engine-internal vocabulary from `not_a_bundle`. Collapse `unreachable_step` cascades behind the `unknown_step` that caused them.
