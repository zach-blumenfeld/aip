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
| start (`kind: start`) | inputs `s` | the client's start input | | `{s}` |
| A (execution) | in `s`, out `A_x` | `{s}` | `{A_x}` | `{s, A_x}` |
| B (execution) | in `A_x`, out `B_x` | `{A_x}` | `{B_x}` | `{s, A_x, B_x}` |
| C (decision) | in `s, B_x`, question `q1` | `{s, B_x}` | its answers `{q1}` | `{s, A_x, B_x, q1}` |
| D (client task) | in `q1`, out `D_x` | `{q1}` | the client's answer `{D_x}` | `{s, A_x, B_x, q1, D_x}` |
| end | inputs `s, D_x` | | | the result: `{s, D_x}` |

The validator proves at write time that every key a step reads has a producer on every path to
it (the start step counts as the producer of its inputs) and that every declaration of a key
agrees on its type. A key may have more than one producer: keys accumulate, and where a run
passes through two producers the later one overwrites the value, which the validator reports as
information (`duplicate_producer`), not as a fault. The run's result is the state projected to
the end step's `inputs`; everything else stays in the history.

Separately from the state, the run history records every step's input and result. The state is
the working object; the history is the ledger.

## What each step kind adds

- **start**: holds the procedure's `inputs`, which the client supplies. The runtime checks the
  start input against their types, writes the first history entry (`"kind": "start"`), and hands
  the state to `inputs_to`. It runs nothing and adds nothing beyond the input.
- **execution**: runs a script. The script gets `{"state": <its declared inputs>, "assets": ...,
  "expects": ...}` on stdin (`currentState` carries the same object for one more version) and must
  print a JSON object holding exactly its declared `outputs`. A missing, mistyped, or undeclared
  key fails the step, naming the key, and nothing is merged. It runs on the client, for a served
  run too, launched from its folder with the step's `command`, or `python <script>`, with
  `AIP_WORKDIR` set to the run's working directory, where it reads and writes files; before the
  first script runs, the client's machine is checked against the skill's `requires` (interpreter
  and minimum version, packages, tools), and a `requires_unmet` error names everything missing.
  On a served run the server sends the rendered stdin and the client posts the output back.
- **decision**: asks typed questions about its declared inputs. The run stops at every decision
  and the client resolves it: with a decision model configured on the client (`TYPESAFE_API_KEY`
  or `aip config --decision-model`), the model receives `{"state": <declared inputs>}`, plus
  `history` only when the step sets `history: true`; without one, the agent answers, but only
  where the step sets `fallback: true` (the default is `false`, and the run then stops with
  `no_decision_model` until a model is configured). The answers (one key per question, typed:
  noul boolean, choice label, score level) are the result, posted with their attribution,
  `{"resolver": "typesafe"|"manual", "model", "confidence"}`, which the history records. For each
  question the step names in its `confidence` list, a model's answer also adds
  `<question>_confidence`, a float in `[0, 1]`: the probability the model put on the answer it
  gave (`|2p - 1|` for a noul, its own confidence for a choice or score), the same number the
  attribution records. A manual answer adds no confidence key. Nothing else is added, which is
  why a client cannot slip extra keys in at a decision. The server never calls a model.
- **client_task**: hands work to the client. The task template renders from the declared inputs
  only. The client's answer must contain the step's declared `outputs` with their types; the
  pause's `answer_with` lists them.
- **router**: reads one key and picks the next step. With a `confidence` check it first reads
  the check's key: below the bound, or absent, or null, the run goes to the check's `to`; a key
  answered by hand is not checked (`reason: manual`). The history entry records
  `"confidence": {"fired", "reason"}` beside the branch taken. Adds nothing.
- **end**: stops. The state projected to its `inputs` is the run's output.

## Typed inputs, typed outputs

Each step declares `inputs`: a list of key names with types. When the state reaches a step, the
runtime checks that every declared key is present with the right type and rejects the run if
not ("input to step build is invalid: script_path is a required property"), then hands the step
those keys and nothing else. Keys the step did not declare stay in the full state, out of its
sight. The run history records each step's input as the projected keys.

Execution and client_task steps declare `outputs` the same way, and a decision's outputs are its
question names plus the `<question>_confidence` keys its `confidence` list names (written by a
model, not by a manual answer). The step's result is checked against them before it is merged
into the full state. The full state has one home: the run file for a local run, the server's run record for
a served one, where the client's run file holds only the run id and the pending pause.

## Where keys come from

A key in the state got there in exactly one of three ways:

1. the client put it in the start input, which the `start` step declares;
2. a script, decision, or client-task answer returned it;
3. (nowhere else).

If a step needs a key that no earlier step returns, the only place it can come from is the start
input, and the start step must declare it so the client knows to supply it. A key may arrive
more than once: a later producer overwrites the earlier value, and the history keeps both.

## What the client sees at a pause

A pause happens at a client task, or at a decision the client has no model for when the step
allows a manual answer (`fallback: true`; otherwise the run stops with `no_decision_model`).
`aip run` / `aip resume` print one JSON object, and the whole of it
lands in the agent's context, so it carries only what the paused step needs: `state` is the
step's declared inputs, never the run's whole state. At a client task it also has `task` (the
template rendered from those inputs, nothing prepended), `references` (names and descriptions;
contents only on request, the one lazy part) and `answer_with` (the step's `outputs` with their
types, what the answer must contain). The shapes for every pause kind, done, and error are in
[`cli-json.md`](cli-json.md) and are tested against the CLI.

The answer is merged over the state the run holds (the run file locally, the server for a served
run), so it carries only the keys asked for.

## Files

State is JSON. Scripts that read or write files do so on the client's disk, under the run's
working directory (`AIP_WORKDIR`), and put paths or summaries in the state, not contents. The
state object should stay small.

## Known gaps

The gaps 0.5a1 had (no declared outputs, the whole state at every pause and to every step,
silent overwrites, the `suggested` name) are closed in 0.6a0. The gap 0.6a0 left, no deliberate
re-computation (a key had one producer, so a second draft of `reply` had to be `reply_v2`), is
closed in 0.8: a later step may produce a key again and overwrite it, and the validator says so
as information. What remains:

1. **Nothing bounds the state's size.** Files belong under `AIP_WORKDIR` with paths in the
   state, but that is convention; a script can still return a large blob, which every later
   step that declares it receives and the server stores.
2. **Left-overs kept for one version.** Scripts still get `currentState` beside `state`, the
   format still accepts a client task's `framing` flag (ignored), and the server still answers
   the deprecated `/procedures/{ref}/step|answer`, where the client carries the state itself.
3. **The runtime block does not mention `AIP_WORKDIR`.** An agent running a skill by hand from
   the block alone does not know where a script expects the run's files.

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
  "run_file": "/home/you/.aip/runs/4f1c9a2e7b3d5068.json"
}
```

Dropped in A3: `suggested` (replaced by `state`, filtered to the declared keys, the same name at
every pause kind and the name TypeSafe uses; structured values belong here, prose belongs in
`task`), the `resume` command string (the skill knows it), and the framing paragraph prepended to
every task (it described `currentState` and `history`, which the pause does not carry, and
repeated the skill; the format's `framing` flag on client tasks is now ignored). `answer_with` is
`expects` renamed; it stays because it is generated from the graph per step, which SKILL.md
cannot do, and it is what the answer is validated against.

## Pause shape (decision)

What goes to the decision model, which the client calls with its own key: `questions` as printed, and `state` built as
`{"state": <the step's declared inputs>}`, with `"history": <every prior step's input and result>`
added only when the step sets `history: true`. History grows with the run and is billed on every
decision, so it is off by default.

Decision, no model configured on the client and `fallback: true` on the step (the agent stands in for the model, so it gets the same two things):

```json
{
  "paused": "decision",
  "step": "triage",
  "questions": { "billing": { "type": "noul", "instructions": "..." },
                 "tone": { "type": "choice", "instructions": "...", "criteria": { "angry": "...", "calm": "..." } } },
  "state": { "message": "..." },
  "confidence": [ "tone" ],
  "fallback": true,
  "run_id": "4f1c9a2e7b3d5068",
  "run_file": "/home/you/.aip/runs/4f1c9a2e7b3d5068.json"
}
```

Answer: one key per question, `{"billing": true, "tone": "calm"}`. No `answer_with`: the
questions block already defines the answer shape. Recorded as `"resolver": "manual"` with no
confidence, and `tone_confidence` is not written: `confidence` names the keys a model's answer
would have added. A router that checks `tone_confidence` skips the check for it (`reason: manual`)
and takes the branch you chose; a manual answer never gets a number invented for it. With a model, nothing pauses here: it answers,
the keys are written, and the router's check decides what a low confidence means.

## Three ways a run stops

Each is one JSON object on stdout ([`cli-json.md`](cli-json.md)):

- **paused** (exit 0): the agent must answer (client task, or a decision with no model on the client where the step allows it).
- **done** (exit 0): the end step was reached; `state` is the end step's inputs.
- **error** (exit 1): a step failed (`script_failed`, `timeout`, `invalid_input`, `invalid_output`,
  `requires_unmet`, `no_decision_model`, or `server`), with the step and the detail: the script's
  exit code and stderr, or the `missing` and `invalid` keys. No traceback unless `--debug`. The
  run file keeps the state before the failing step, and `aip resume <run_id>` with no input
  retries it. Nothing to answer, something to fix: `no_decision_model` means a decision with
  `fallback: false` and no key on this client, and the retry asks the model once one is set. A
  bad answer to a pause is an error too, but it leaves the pause in place to be answered again.

## Try it: five commands, no server

The aip-spec package ships a tiny example, `billing-support`: a start step holding the message,
a decision (is it billing, how upset) that emits `tone_confidence`, a router on tone that first
checks that confidence, then either a script that opens a ticket (angry, or unsure) or a client
task that drafts a reply (calm). Its decision sets `fallback: true`, so with no decision model
configured it pauses to you, which is exactly what an agent sees; your answer carries no
confidence, and the router does not check one for it, so the tone you give picks the branch. With
a key (`aip config --decision-model KEY`) the model answers and the router checks its confidence.

```sh
cd "$(mktemp -d)"
aip-spec example billing-support --out .       # the example, as ./billing-support
EX=./billing-support

# 1. start: the state is just your start input, checked against the start step's inputs;
#    the run pauses at the decision. Note `confidence: ["tone"]` and `fallback: true` on the pause.
echo '{"message":"This is the THIRD time you have double charged me. Fix it today or I cancel."}' > start.json
aip run "$EX" --input start.json --run-file run.json

# 2. answer both questions; your answer writes no `tone_confidence`, and the router does not check
#    one for it (`reason: manual`): `angry` sends the run to the script, which runs with no pause; done.
#    `state` is the end step's inputs (just `message` here); run.json's `history` is the ledger:
#    the start entry, the decision with `"resolver": "manual"`, the router with
#    `"confidence": {"fired": false, "reason": "manual"}`, and the ticket on the `escalate` entry.
echo '{"billing": true, "tone": "angry"}' > answer1.json
aip resume run.json --input answer1.json --progress   # a line per step, then done

# 3. answering "calm" by hand takes the calm branch, unchecked: the run pauses at the client task.
#    Note `state`: only the step's inputs (message, tone; not billing), `answer_with`: the step's
#    outputs ({"reply": "string"}), and `task`: the template rendered from the step's declared
#    inputs. Answer it with those outputs and the run ends.
echo '{"message":"Hi, I think I was charged twice for March. Could you check?"}' > start2.json
aip run "$EX" --input start2.json --run-file run2.json
echo '{"billing": true, "tone": "calm"}' > answer2.json
aip resume run2.json --input answer2.json
echo '{"reply":"Thanks for flagging this; duplicate charges are refunded in full within 5 business days."}' > answer3.json
aip resume run2.json --input answer3.json

# 4. with a TypeSafe key (aip config --decision-model KEY) the decision does not pause: the model
#    answers and writes tone_confidence, and the router checks it; a confident "calm" reaches the
#    client task as above, an unsure one is escalated.
aip run "$EX" --input start2.json --run-file run3.json
```

Things to notice: `--input` takes a file, not inline JSON. Answering only one of two questions
is an `invalid_output` error naming the missing one (`"missing": ["tone"]`), and the pause stays
put for a second try. At the client-task pause, `answer_with` lists the step's declared outputs,
which is what your answer must contain.
