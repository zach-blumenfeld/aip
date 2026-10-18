# How state moves through a procedure

For readers who know agents and skills but not AIP's internals. Describes what the runtime does
today; the last section lists what is known to be awkward.

## One object, growing

A run carries a single flat JSON object called the state. It starts as the client's start input.
Each step sees only the keys it declares as `inputs`, returns exactly the keys it declares as
`outputs`, and those are merged into the full state (`{**state, **outputs}`). Nothing is ever
removed, so the state only grows.

| step | declares | receives | returns | state afterwards |
|---|---|---|---|---|
| start | inputs `s` | | | `{s}` |
| A (execution) | in `s`, out `A_x` | `{s}` | `{A_x}` | `{s, A_x}` |
| B (execution) | in `A_x`, out `B_x` | `{A_x}` | `{B_x}` | `{s, A_x, B_x}` |
| C (decision) | in `s, B_x`, question `q1` | `{s, B_x}` | its answers `{q1}` | `{s, A_x, B_x, q1}` |
| D (client task) | in `q1`, out `D_x` | `{q1}` | the client's answer `{D_x}` | `{s, A_x, B_x, q1, D_x}` |
| end | inputs `s, D_x` | | | the result: `{s, D_x}` |

The validator (format 0.6a0) proves at write time that every key a step reads has a producer on
every path to it, and that each key has exactly one producer, so no step overwrites another's key.
The run's result is the state projected to the end step's `inputs`; everything else stays in the
history.

Separately from the state, the run history records every step's input and result. The state is
the working object; the history is the ledger.

## What each step kind adds

- **execution**: runs a script. The script gets `{"state": <its declared inputs>, "assets": ...,
  "expects": ...}` on stdin (`currentState` carries the same object for one more version) and must
  print a JSON object holding exactly its declared `outputs`. A missing, mistyped, or undeclared
  key fails the step, naming the key, and nothing is merged.
- **decision**: asks typed questions about its declared inputs; the decision model receives
  `{"state": <declared inputs>}`, plus `history` only when the step sets `history: true`. The
  answers (one key per question, typed: noul boolean, choice label, score level) are the result.
  Nothing else is added, which is why a client cannot slip extra keys in at a decision.
- **client_task**: hands work to the client. The task template renders from the declared inputs
  only. The client's answer must contain the step's declared `outputs` with their types; the
  pause's `answer_with` lists them.
- **router**: reads one key and picks the next step. Adds nothing.
- **end**: stops. The state projected to its `inputs` is the run's output.

## Typed inputs, typed outputs

Each step declares `inputs`: a list of key names with types. When the state reaches a step, the
runtime checks that every declared key is present with the right type and rejects the run if
not ("input to step build is invalid: script_path is a required property"), then hands the step
those keys and nothing else. Keys the step did not declare stay in the full state, out of its
sight. The run history records each step's input as the projected keys.

Execution and client_task steps declare `outputs` the same way, and a decision's outputs are its
question names. The step's result is checked against them before it is merged into the full
state. Today the client's run file carries the full state between calls; from B1 the server
holds it.

## Where keys come from

A key in the state got there in exactly one of three ways:

1. the client put it in the start input;
2. a script, decision, or client-task answer returned it;
3. (nowhere else).

If a step needs a key that no earlier step returns, the only place it can come from is the start
input, and the start step must declare it so the client knows to supply it.

## What the client sees at a pause

A pause happens at a client task, at a decision nothing could answer, or at a decision the model
answered under its threshold. `aip run` / `aip resume` print one JSON object, and the whole of it
lands in the agent's context, so it carries only what the paused step needs: `state` is the
step's declared inputs, never the run's whole state. At a client task it also has `task` (the
template rendered from those inputs, nothing prepended), `references` (names and descriptions;
contents only on request, the one lazy part) and `answer_with` (the step's `outputs` with their
types, what the answer must contain). The shapes for every pause kind, done, and error are in
[`cli-json.md`](cli-json.md) and are tested against the CLI.

The answer is merged over the state the run file holds, so it carries only the keys asked for.

## Files

State is JSON. Scripts that read or write files do so on disk and put paths or summaries in the
state, not contents. The state object should stay small.

## Known gaps

1. ~~**No declared outputs.**~~ Fixed in 0.6a0: steps declare `outputs` and the validator checks
   every consumed key has a producer on every path or is a start input.
2. ~~**The whole state goes to the client at every pause.**~~ Fixed (A3): a pause's `state` is
   the paused step's declared inputs; the rest stays in the run file.
3. ~~**`suggested` is a misleading name.**~~ Fixed (A3): every pause says `state`, and a review
   pause puts the model's answers under `proposed_answers` beside the state they were judged on.
4. ~~**Silent overwrites.**~~ Fixed in 0.6a0: each key is produced by exactly one step and is
   never a start input, so the state is append-only by construction. Deliberate re-computation
   would need an explicit opt-in.
5. ~~**Steps receive the whole state.**~~ Fixed: scripts, decisions, and client-task templates
   get only their declared inputs, and results are checked against declared outputs.

## Pause shape (client task)

The pause carries only what this step needs (the full example is in `cli-json.md`):

```json
{
  "paused": "client_task",
  "step": "reply",
  "task": "<rendered template: what to do for this step, never how to use aip>",
  "state": { "only the keys this step declared" },
  "references": [ { "uri": "...", "description": "..." } ],
  "answer_with": { "reply": "string" },
  "run_id": "4f1c9a2e7b3d5068",
  "run_file": "run.json"
}
```

Dropped in A3: `suggested` (replaced by `state`, filtered to the declared keys, the same name at
every pause kind and the name TypeSafe uses; structured values belong here, prose belongs in
`task`), the `resume` command string (the skill knows it), and the framing paragraph prepended to
every task (it described `currentState` and `history`, which the pause does not carry, and
repeated the skill; the format's `framing` flag on client tasks is now ignored). `answer_with` is
`expects` renamed; it stays because it is generated from the graph per step, which SKILL.md
cannot do, and it is what the answer is validated against.

## Pause shapes (decision and review)

What goes to the decision model: `questions` as printed, and `state` built as
`{"state": <the step's declared inputs>}`, with `"history": <every prior step's input and result>`
added only when the step sets `history: true`. History grows with the run and is billed on every
decision, so it is off by default.

Decision, no model configured (the agent stands in for the model, so it gets the same two things):

```json
{
  "paused": "decision",
  "step": "triage",
  "questions": { "billing": { "type": "noul", "instructions": "..." },
                 "tone": { "type": "choice", "instructions": "...", "criteria": { "angry": "...", "calm": "..." } } },
  "state": { "message": "..." },
  "run_id": "4f1c9a2e7b3d5068",
  "run_file": "run.json"
}
```

Answer: one key per question, `{"billing": true, "tone": "calm"}`. No `answer_with`: the
questions block already defines the answer shape.

Review, the model answered but one question fell under its threshold:

```json
{
  "paused": "review",
  "step": "triage",
  "state": { "message": "..." },
  "proposed_answers": { "billing": true, "tone": "angry" },
  "review": [ { "question": "tone", "confidence": 0.58, "probabilities": { "angry": 0.58, "calm": 0.42 }, "reason": "confidence below 0.7" } ],
  "run_id": "4f1c9a2e7b3d5068",
  "run_file": "run.json"
}
```

Answer: only overrides, `{"tone": "calm"}`, or `{}` to accept. The questions are not repeated;
the model already answered them.

## Three ways a run stops

Each is one JSON object on stdout ([`cli-json.md`](cli-json.md)):

- **paused** (exit 0): the client must answer (client task, decision with no resolver, or review).
- **done** (exit 0): the end step was reached; `state` is the end step's inputs.
- **error** (exit 1): a step failed (`script_failed`, `timeout`, `invalid_input`, `invalid_output`,
  `requires_unmet`, or `server`), with the step and the detail: the script's exit code and
  stderr, or the `missing` and `invalid` keys. No traceback unless `--debug`. The run file keeps
  the state before the failing step, and `aip resume <run_id>` with no input retries it. Nothing to answer, something to fix. A bad answer to a pause is an error too, but
  it leaves the pause in place to be answered again.

## Try it: five commands, no server

The aip-spec package ships a tiny example, `billing-support`: a decision (is it billing, how
upset), a router on tone, then either a script that opens a ticket (angry) or a client task that
drafts a reply (calm). With no decision model configured, every decision pauses to you, which is
exactly what an agent sees.

```sh
EX=$(python3 -c "import aip_spec, pathlib; print(pathlib.Path(aip_spec.__file__).parent.parent.parent / 'examples' / 'billing-support')" 2>/dev/null \
    || echo ~/dev/aip-skillbench/.claude/skills-src/aip-spec/examples/billing-support)
cd "$(mktemp -d)"

# 1. start: the state is just your start input; the run pauses at the decision
echo '{"message":"Hi, I think I was charged twice for March. Could you check?"}' > start.json
aip run "$EX" --input start.json --run-file run.json

# 2. answer both questions; the router picks "reply"; the run pauses at the client task.
#    Note `state`: only the step's inputs (message, tone; not billing), `answer_with`: the
#    step's outputs ({"reply": "string"}), and `task`: the template rendered from the
#    step's declared inputs.
echo '{"billing": true, "tone": "calm"}' > answer1.json
aip resume run.json --input answer1.json

# 3. answer the client task with its outputs; the run ends. `state` is the end step's inputs
#    (just `message` here); the run file's `history` is the ledger, where the reply is recorded.
echo '{"reply":"Thanks for flagging this; duplicate charges are refunded in full within 5 business days."}' > answer2.json
aip resume run.json --input answer2.json

# 4. the other branch: an angry message routes to the script, which runs with no pause
echo '{"message":"This is the THIRD time you have double charged me. Fix it today or I cancel."}' > start2.json
aip run "$EX" --input start2.json --run-file run2.json
echo '{"billing": true, "tone": "angry"}' > answer3.json
aip resume run2.json --input answer3.json --progress   # a line per step, then done; ticket_id is in run2.json's history
```

Things to notice: `--input` takes a file, not inline JSON. Answering only one of two questions
is an `invalid_output` error naming the missing one (`"missing": ["tone"]`), and the pause stays
put for a second try. At the client-task pause, `answer_with` lists the step's declared outputs,
which is what your answer must contain.
