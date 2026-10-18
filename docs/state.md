# How state moves through a procedure

For readers who know agents and skills but not AIP's internals. Describes what the runtime does
today; the last section lists what is known to be awkward.

## One object, growing

A run carries a single flat JSON object called the state. It starts as the client's start input.
Every step reads the whole state, returns a result, and the result is merged over the state
(`{**state, **result}`). Nothing is ever removed, so the state only grows.

| step | receives | returns | state afterwards |
|---|---|---|---|
| start | `{s}` | | `{s}` |
| A (execution) | `{s}` | `{A_x}` | `{s, A_x}` |
| B (execution) | `{s, A_x}` | `{B_x}` | `{s, A_x, B_x}` |
| C (decision) | `{s, A_x, B_x}` | its answers `{q1}` | `{s, A_x, B_x, q1}` |
| D (client task) | `{s, A_x, B_x, q1}` | the client's answer `{D_x}` | `{s, A_x, B_x, q1, D_x}` |

A step may overwrite an existing key by returning it. Nothing warns about that today; this
probably needs a validator rule so a step cannot produce a key an earlier step produced (see
"Known gaps").

Separately from the state, the run history records every step's input and result. The state is
the working object; the history is the ledger.

## What each step kind adds

- **execution**: runs a script. The script gets the whole state on stdin as JSON and must print a
  JSON object on stdout. That object is the step's result.
- **decision**: asks typed questions about the state. The answers (one key per question) are the
  result. Nothing else is added, which is why a client cannot slip extra keys in at a decision.
- **client_task**: hands work to the client. The client's answer is the result; it must contain
  the keys the next step declares as inputs. Extra keys in the answer are kept.
- **router**: reads one key and picks the next step. Adds nothing.
- **end**: stops. The state at that point is the run's output.

## Typed inputs, untyped outputs

Each step declares `inputs`: a list of key names with types. When the state reaches a step, the
runtime checks that every declared key is present with the right type and rejects the run if
not ("input to step build is invalid: script_path is a required property"). Keys the step did
not declare ride along unchecked, and today the step still receives all of them.

Intended rule: a step reads only what it declares. Scripts get only their declared inputs on
stdin, client tasks see only theirs at a pause, decisions judge only theirs. The full state
lives on the server and the step's result is merged back into it there.

No step declares what it produces. So the validator cannot tell, at write time, whether the key a
step needs will exist by the time it runs; the runtime finds out one step at a time. See
"Known gaps".

## Where keys come from

A key in the state got there in exactly one of three ways:

1. the client put it in the start input;
2. a script, decision, or client-task answer returned it;
3. (nowhere else).

If a step needs a key that no earlier step returns, the only place it can come from is the start
input, and the start step must declare it so the client knows to supply it.

## What the client sees at a pause

A pause happens at a client task, or at a decision nothing could answer. The server returns:

- `task`: the step's text, with `{key}` placeholders filled from the state. The author chooses
  which keys appear here.
- `references`: names and descriptions of extra files; contents are fetched only on request.
- `expects`: the keys and types the next step needs, i.e. what the answer must contain.
- `suggested`: the whole current state. The answer is merged over it.

All of this is printed by `aip run` / `aip resume` and lands in the agent's context in full.
Only `references` is lazy.

`suggested` is named for decision and review pauses, where it holds the decision model's proposed
answers for the client to accept or correct. At a client-task pause it is simply the current
state, and the name is confusing there.

## Files

State is JSON. Scripts that read or write files do so on disk and put paths or summaries in the
state, not contents. The state object should stay small.

## Known gaps

1. **No declared outputs**, so missing keys are found at run time, not at validation. Fix: steps
   declare the keys they produce; the validator checks every consumed key has a producer or is in
   the start input.
2. **The whole state goes to the client at every pause**, whatever the step needs. Same fix as
   gap 5 below, applied at pauses.
3. **`suggested` is a misleading name.** It comes from an earlier design where the client could
   edit the server's proposed next input between steps. With append-only state and steps reading
   only their declared inputs, nothing is proposed any more: it is the state. Fix: call it
   `state` at every pause; at a review pause, put the decision model's proposed answers under
   their own key (e.g. `proposed_answers`) beside the state they were judged on.
4. **Silent overwrites** of existing keys, and collisions between steps that happen to use the
   same name. Fix: a validator rule that each key is produced by exactly one step (and is not in
   the start input), so the state is append-only by construction. Deliberate re-computation
   would need an explicit opt-in.
5. **Steps receive the whole state**, not just their declared inputs (scripts on stdin, client
   tasks at a pause). Fix: the runtime projects the state down to the step's declared inputs
   before handing it over; the server keeps the full state.

## Proposed pause shape (client task)

For an agent that has the aip-runtime skill, the pause should carry only what this step needs:

```json
{
  "paused": "client_task",
  "step": "reply",
  "task": "<rendered template: what to do for this step, never how to use aip>",
  "state": { "only the keys this step declared" },
  "references": [ { "uri": "...", "description": "..." } ],
  "answer_with": { "message": "string", "reply": "string" },
  "run_file": "run.json"
}
```

Dropped: `suggested` (replaced by `state`, filtered to the declared keys, the same name at every
pause kind and the name TypeSafe uses; structured values belong here, prose belongs in `task`), the `resume` command string (the skill knows it), and the
framing paragraph prepended to every task (it describes `currentState` and `history`, which the
pause does not carry, and repeats the skill). `answer_with` is `expects` renamed; it stays because
it is generated from the graph per step, which SKILL.md cannot do, and it is what the server
validates the answer against.

## Proposed pause shapes (decision and review)

What goes to the decision model today: `questions` as printed, and `state` built as
`{"currentState": <whole state>, "history": <every prior step's input and result>}`. Under the
read-only-your-inputs rule that becomes the step's declared keys only, with history included only
when the skill asks for it. History grows with the run and is billed on every decision.

Decision, no model configured (the agent stands in for the model, so it gets the same two things):

```json
{
  "paused": "decision",
  "step": "triage",
  "questions": { "billing": { "type": "noul", "instructions": "..." },
                 "tone": { "type": "choice", "instructions": "...", "criteria": { "angry": "...", "calm": "..." } } },
  "state": { "message": "..." },
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
  "run_file": "run.json"
}
```

Answer: only overrides, `{"tone": "calm"}`, or `{}` to accept. The questions are not repeated;
the model already answered them.

## Three ways a run stops

- **paused**: the client must answer (client task, decision with no resolver, or review).
- **done**: the end step was reached; the final state is printed.
- **error**: a step failed (script exit, invalid input or output, unmet requirement, timeout).
  Printed as one JSON object with the kind, the step, and the detail, exit code non-zero, no
  traceback unless `--debug`. The run keeps the state before the failing step, and
  `aip resume <run_id>` with no input retries it. Nothing to answer, something to fix.

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
#    Note `suggested`: the whole state so far (message, billing, tone), and `task`: the
#    template with only the keys the author chose rendered into it.
echo '{"billing": true, "tone": "calm"}' > answer1.json
aip resume run.json --input answer1.json

# 3. answer the client task; the run ends. `state` is the final merged object, `history` the ledger.
echo '{"message":"Hi, I think I was charged twice for March. Could you check?","reply":"Thanks for flagging this; duplicate charges are refunded in full within 5 business days."}' > answer2.json
aip resume run.json --input answer2.json

# 4. the other branch: an angry message routes to the script, which runs with no pause
echo '{"message":"This is the THIRD time you have double charged me. Fix it today or I cancel."}' > start2.json
aip run "$EX" --input start2.json --run-file run2.json
echo '{"billing": true, "tone": "angry"}' > answer3.json
aip resume run2.json --input answer3.json      # done: state now has ticket_id and queue
```

Things to notice: `--input` takes a file, not inline JSON. Answering only one of two questions
fails with a Python traceback rather than a message (a client bug). At the client-task pause,
`expects` lists the *next* step's inputs, which is what your answer must contain.
