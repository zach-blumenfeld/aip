# The CLI's JSON output

`aip run` and `aip resume` print exactly one JSON object on stdout when they stop, and nothing
else there unless asked: no prose, no traceback. A run stops one of three ways:

| outcome | first key | exit code |
|---|---|---|
| paused | `"paused": <kind>` | 0 |
| done | `"done": true` | 0 |
| error | `"error": <kind>` | 1 |

This is a contract: agents, the `aip` skill, `aip mcp` and the console parse it. Every example
on this page is checked against the CLI's real output by `tests/test_cli_json.py` (the
`billing-support`, `billing-support-agent`, `ticket-triage` and `fixed-policy` examples under
`examples/language/`, run with no server configured; the test reads `4f1c9a2e7b3d5068` as
whatever id the run was given and shows `run_file` as its file name).

```
aip run <folder | bundle.rl | name[@rev]> --inputs '{"message": "..."}' [--batch N] [--agent A] [--session S] [--workdir DIR]
aip resume <run_id | run_file> --answers '{...}'
aip resume <run_id>                                     retry the step a failed run stopped at
```

`--inputs` and `--answers` take JSON inline, `@path` for a file, or `-` for stdin. Flags on both:

- `--progress`: one line per history entry as the run writes it (below), then the final object
  on one line too, so the whole output is JSON lines.
- `--debug`: when the command itself fails, the traceback goes to stderr. Stdout is unchanged.

Every run runs on this machine, from the bundle cache (`~/.aip/bundles/<bundle id>.rl`): a
folder is compiled and cached, an `.rl` verified and cached, a published name fetched (or
`aip pull` did it earlier). Every stop writes the run file named by `run_file`, by default
`~/.aip/runs/<run_id>.json` (`AIP_HOME` moves `~/.aip`), holding the whole run: the state, the
history, the loop frames, the pending pause or the error (The run file, below). `aip resume
<run_id>` works from any directory, and a run file's path works in place of the id. A resumed
run is of the exact bundle it started on, whatever happened to the folder since. `aip runs`
lists the runs and `aip runs <run_id>` prints one step by step (below).

**Recording.** When a server is configured (`aip config --server URL`, or `AIP_SERVER`) the run
is posted there at every stop, a folder or file run as a run of a *draft* bundle, and the object
carries `"recorded": true` (or `false` when the server did not take it, with the reason on
stderr; the next stop tries again). With no server the object has no `recorded` key, the run
works, and `aip run` ends with one line on stderr, once for the run: its resumes do not repeat
it, and a command that changed nothing (a refused answer) prints no line about recording at all.

```text
aip: not recorded: no server is configured; run `aip config --server URL` to record runs on a server
```

## Paused

Every pause has `paused` (the kind, `task`: a `Task_Agent` step waits for the agent; a `Decide`
never pauses, it needs a decision model and fails the run without one, below), `step`, `tasks`,
`hint`, `run_id` and `run_file`. `tasks` is a list with one entry per `For` pass waiting at the
step, and one entry outside a loop. Each task carries `index` (its position in the list, what
the answer is keyed by), `pass` (the innermost loop's pass number, `null` outside loops),
`passes` (every enclosing loop's name and pass number, outermost first), `prompt` (the step's
`Prompt` file or its description with `{key}` and `{assets[stem]}` filled in, nothing
prepended), `state` (the keys the step `Read`s, as it sees them), `references` (named, not
loaded; read them when the prompt calls for it), `answer_with` (what to answer: the keys and
their types) and `labels` (for each `choice` or `score` among them, the values it may take).
`hint` is one line on the shape of an answer to this pause.

A task whose innermost loop is a `Loop` with a cap (`At_Most` on an `Until` loop, the count of
a `Times` loop) also carries `pass_of`, the cap, and `last_pass`: `true` when this pass is the
last the cap allows. In `fixed-policy` (`Loop revise Until check_summary.all_hold, At_Most 3,
Else_Fail`, whose body checks the work and then asks for a fix) the three `fix` tasks carry
`"pass": 0, "last_pass": false, "pass_of": 3`, then `1`, then `"pass": 2, "last_pass": true`:
the agent asked for the third fix can see that no pass follows it, so nothing will check that
fix and the run then fails at the cap (`loop_cap`, below).

### A task that decides

`billing-support-agent` has the agent classify the message: its `triage` is a `Task_Agent`
producing `billing: true_or_false` and `tone: choice [angry, calm]`, so the procedure runs with
no decision model at all.

<!-- cli-json: paused-task-labels -->
```json
{
  "paused": "task",
  "step": "triage",
  "tasks": [
    {
      "index": 0,
      "pass": null,
      "passes": [],
      "prompt": "Read the customer's message and classify it.\n\nCustomer message:\nI was charged twice for March. Could you check?\n\nAnswer `billing` with true when the message is about a charge, invoice, refund, or\nsubscription payment, and `tone` with `angry` for explicit frustration, threats to cancel,\nor demands, else `calm`.",
      "state": {
        "message": "I was charged twice for March. Could you check?"
      },
      "references": [],
      "answer_with": {
        "billing": "true_or_false",
        "tone": "choice"
      },
      "labels": {
        "tone": [
          "angry",
          "calm"
        ]
      }
    }
  ],
  "hint": "answer with {\"billing\": true | false, \"tone\": \"angry\" | \"calm\"}; the bare value is enough for a true_or_false, choice or score key ({\"value\": ...} is the same answer)",
  "run_id": "4f1c9a2e7b3d5068",
  "run_file": "/home/you/.aip/runs/4f1c9a2e7b3d5068.json"
}
```

Answer with every key of `answer_with` and nothing else. An answer-typed key (a `true_or_false`,
a `choice`, a `score`) has two spellings that mean the same: the bare value, or an object with
`value`:

```json
{"billing": true, "tone": "calm"}
{"billing": {"value": true}, "tone": {"value": "calm"}}
```

A `true_or_false` is `true` or `false`, a `choice` or a `score` one of its `labels`. The runtime
stores either spelling as `{"value": ...}`, which is how a later task's `state` shows it.
Answers are as strict as inputs: a key missing, a key the pause did not ask for, a value outside
the labels, or anything on an answer but its value (a `confidence`, say) is refused as
`invalid_output` naming it, nothing is applied, and the pause stands with the same tasks:
answer again. An agent's answer has no confidence, so the route `by_tone` that reads `tone`
branches on its value and has no `Confidence_Below` (the compiler refuses one on an agent's
answer). A model's answer, below, carries its confidence and a route may check it; so may a
script's, when the script wrote `confidence` and `probabilities` beside its `value`.

### A task that does the step's work

Here `billing-support` was run with a decision model: its `triage` is a `Decide`, the model
answered `calm` at 0.9, the route's `Confidence_Below 0.9` did not fire, and the run waits at
`reply` for the agent to draft the reply.

<!-- cli-json: paused-task -->
```json
{
  "paused": "task",
  "step": "reply",
  "tasks": [
    {
      "index": 0,
      "pass": null,
      "passes": [],
      "prompt": "# Draft a reply\n\nWrite a short, calm reply to the customer below. Apply the policy exactly; do not\npromise anything the policy does not cover.\n\nCustomer message:\nI was charged twice for March. Could you check?\n\nPolicy:\n# Refund policy\n\n- Duplicate charges are refunded in full within 5 business days.\n- Refunds for other reasons are honored within 30 days of purchase.\n\n\nReturn JSON with `reply` (your reply text).\n",
      "state": {
        "message": "I was charged twice for March. Could you check?",
        "tone": {
          "value": "calm",
          "confidence": 0.9,
          "probabilities": {
            "angry": 0.1,
            "calm": 0.9
          }
        }
      },
      "references": [
        {
          "path": "references/help.md",
          "description": "Escalation contacts and plan matrix. Only for plan changes, currency issues, or charges older than 30 days."
        }
      ],
      "answer_with": {
        "reply": "string"
      },
      "labels": {}
    }
  ],
  "hint": "answer with {\"reply\": <string>}",
  "run_id": "4f1c9a2e7b3d5068",
  "run_file": "/home/you/.aip/runs/4f1c9a2e7b3d5068.json"
}
```

`state` holds the `Read` keys: `triage_decision.tone` arrives as `tone`, the model's whole
answer object. Answer with every key of `answer_with`: `{"reply": "..."}`.

### Several tasks at once

Inside a `For` loop the passes run in batches, and every pass waiting at the same step goes
out as one pause. Here `ticket-triage` was run on three tickets with a model: the angry one was
escalated by a script and finished its pass; the two calm ones wait at `draft`, so the pause
carries two tasks, for passes 0 and 2.

<!-- cli-json: paused-tasks -->
```json
{
  "paused": "task",
  "step": "draft",
  "tasks": [
    {
      "index": 0,
      "pass": 0,
      "passes": [
        {
          "loop": "each_ticket",
          "pass": 0
        }
      ],
      "prompt": "Write a reply that follows the policy.",
      "state": {
        "ticket": "Can I get a copy of my March invoice?",
        "policy": "Duplicate charges are refunded in full within 5 business days. Plan changes take effect next cycle."
      },
      "references": [],
      "answer_with": {
        "reply": "string"
      },
      "labels": {}
    },
    {
      "index": 1,
      "pass": 2,
      "passes": [
        {
          "loop": "each_ticket",
          "pass": 2
        }
      ],
      "prompt": "Write a reply that follows the policy.",
      "state": {
        "ticket": "How do I move to the annual plan?",
        "policy": "Duplicate charges are refunded in full within 5 business days. Plan changes take effect next cycle."
      },
      "references": [],
      "answer_with": {
        "reply": "string"
      },
      "labels": {}
    }
  ],
  "hint": "answer all 2 tasks at once, by index: {\"0\": {\"reply\": <string>}, \"1\": ...}",
  "run_id": "4f1c9a2e7b3d5068",
  "run_file": "/home/you/.aip/runs/4f1c9a2e7b3d5068.json"
}
```

Answer every task in one `resume`, keyed by its index: `{"0": {"reply": "..."}, "1": {"reply":
"..."}}`. A list in task order works too, and for a single task the one answer object on its
own. The answers are taken whole or not at all: if one does not fit its step's keys, a task is
left out, or there is an answer for a task the pause does not have, the `invalid_output` error
below names every such key and task, nothing is applied, and the same tasks wait.

## Done

<!-- cli-json: done -->
```json
{
  "done": true,
  "result": {
    "message": "I was charged twice for March. Could you check?",
    "reply": "Thanks for flagging this; duplicate charges are refunded in full within 5 business days."
  },
  "run_id": "4f1c9a2e7b3d5068",
  "run_file": "/home/you/.aip/runs/4f1c9a2e7b3d5068.json"
}
```

`result` is the `End` step's `Read` keys that the path produced: here the reply, and on the
angry path the ticket and its queue instead. What every step read and produced along the way is
the run's `history`, in the run file (below); `aip runs <run_id>` prints it as a table.

## Error

Every error has `error` (the kind), `step` (the failing step; `null` when no step is to blame),
`message`, `pass` and `passes` (which loop pass failed), `run_id`, `resumable` (whether `aip
resume <run_id>` can still move the run: a retry once the cause is fixed, or another answer),
and `run_file` when `resumable` is true.

| kind | when | extra keys |
|---|---|---|
| `invalid_input` | the inputs do not fit `Start`; a step's `Read` key is missing or mistyped; a target, run id or JSON argument cannot be used (then `kind` says which: `not_found`, `no_server`, `compile_error`, `not_a_bundle`, `bundle_tampered`, …) | `missing`, `invalid` |
| `invalid_output` | a result does not match the step's `Produce` keys: a script's (then `script` is set), or an answer to a pause; a key the step does not produce, an answer's value outside the key's labels, or anything on an agent's answer but its value, counts | `missing`, `invalid` (key names); for an answer to a pause also `missing_tasks` (task indexes left unanswered) and `invalid_tasks` (indexes the pause does not have), each present when it names something |
| `no_branch` | a route read a value none of its branch lines names | `key`, `value`, `branches` |
| `script_failed` | a script exited non-zero, or did not print one JSON object (then `exit_code` is 0) | `script`, `exit_code`, `stderr` |
| `timeout` | a script ran past the timeout | `script`, `seconds` |
| `requires_unmet` | the machine lacks what the procedure's `Requires` names, checked before the first script runs | `missing` |
| `no_decision_model` | a `Decide` step and this client has no decision model configured | |
| `decision_model_failed` | the decision model failed on a `Decide` step (unreachable, refused the key, a bad reply) | `model`, `endpoint`, `cause` |
| `loop_cap` | a `For` (or fold) given more items than `At_Most`, or an `Until` loop at its cap with `Else_Fail`; `step` is `null` and `loop` names the loop; never resumable | `loop`, `cap` (the most passes, or items, allowed), `count` (the passes run, or the items given) |
| `not_paused` | `resume` with answers for a run that is not paused (a failed run is retried with none), or with none for a run that is done or that failed in a way a retry would only repeat (`loop_cap`) | |
| `server` | anything else: a bug, an unreachable server | |

A step that failed while running leaves the run at the state before it, so
`aip resume <run_id>` with no answers retries it once the cause is fixed. The retry runs the
same bundle: what changes between two tries is the world the script sees, not the procedure.
Here the ticket service was unreachable:

<!-- cli-json: error-script-failed -->
```json
{
  "error": "script_failed",
  "step": "escalate",
  "message": "the script scripts/escalate.py exited with 1:\nticket service unreachable",
  "script": "scripts/escalate.py",
  "exit_code": 1,
  "stderr": "ticket service unreachable",
  "pass": null,
  "passes": [],
  "run_id": "4f1c9a2e7b3d5068",
  "resumable": true,
  "run_file": "/home/you/.aip/runs/4f1c9a2e7b3d5068.json"
}
```

An answer that does not fit its pause leaves the pause in place: the run is still `paused` with
the same tasks, and the next `aip resume <run_id> --answers ...` answers it. Here the `triage`
task of `billing-support-agent` above was answered with `{"billing": true}` only:

<!-- cli-json: error-invalid-output -->
```json
{
  "error": "invalid_output",
  "step": "triage",
  "message": "the output of 'triage': tone is missing",
  "missing": [
    "tone"
  ],
  "invalid": [],
  "pass": null,
  "passes": [],
  "run_id": "4f1c9a2e7b3d5068",
  "resumable": true,
  "run_file": "/home/you/.aip/runs/4f1c9a2e7b3d5068.json"
}
```

And here with `{"billing": true, "tone": "calm", "confidence": 0.9}`, a key the pause did not
ask for. `invalid` names it; a list with more answers than the pause has tasks is refused the
same way, with `"invalid_tasks": [1]`, and a task left out with `"missing_tasks": [0]`:

<!-- cli-json: error-extra-key -->
```json
{
  "error": "invalid_output",
  "step": "triage",
  "message": "the output of 'triage': confidence is not a Produce key of triage; its keys are ['billing', 'tone']",
  "missing": [],
  "invalid": [
    "confidence"
  ],
  "pass": null,
  "passes": [],
  "run_id": "4f1c9a2e7b3d5068",
  "resumable": true,
  "run_file": "/home/you/.aip/runs/4f1c9a2e7b3d5068.json"
}
```

A loop at its cap is the one failure of a run under way that is not resumable, because a retry
would fail the same way. Here `fixed-policy` ran its three `revise` passes with a model that
never found the policies held, and the agent's third fix (the task that said `"last_pass":
true`) was followed by the cap. The error names the loop as `loop` (it is not a step), the
`cap` and the `count` of passes run, and no pass, since none was under way; the loop's exit
entry in the history says `"exit": {"reason": "cap", ...}`; `aip resume` on this run answers
`not_paused`. Run the procedure again, on other inputs or with a higher `At_Most`.

<!-- cli-json: error-loop-cap -->
```json
{
  "error": "loop_cap",
  "step": null,
  "message": "revise ran 3 passes without its condition holding (At_Most 3, Else_Fail)",
  "loop": "revise",
  "cap": 3,
  "count": 3,
  "pass": null,
  "passes": [],
  "run_id": "4f1c9a2e7b3d5068",
  "resumable": false
}
```

A `Decide` needs a decision model; there is no answering it by hand (a procedure that wants the
agent to decide uses a `Task_Agent`, as `billing-support-agent` does). The model is an endpoint
with the TypeSafe API shape: `aip config --decision-model-key KEY` sets the key, and
`aip config --decision-model URL` moves the endpoint off TypeSafe's (`AIP_DECISION_MODEL_KEY`
and `AIP_DECISION_MODEL` override the file); `aip config` prints the endpoint and whether a key
is set, never the key. With neither configured the run fails at the decision, resumable:
configure the model, then `aip resume <run_id>` with no answers asks it. Here `billing-support`
was run on a client with no model:

<!-- cli-json: error-no-decision-model -->
```json
{
  "error": "no_decision_model",
  "step": "triage",
  "message": "triage is a decision and no decision model is configured; a Decide is always answered by a decision model, so configure one: run `aip config --decision-model-key KEY`, and `aip config --decision-model URL` for an endpoint other than TypeSafe's; then `aip resume <run_id>` asks it",
  "pass": null,
  "passes": [],
  "run_id": "4f1c9a2e7b3d5068",
  "resumable": true,
  "run_file": "/home/you/.aip/runs/4f1c9a2e7b3d5068.json"
}
```

A model that fails (nothing answers at the endpoint, the key is refused, the reply is not an
answer) fails the decision the same way, as `decision_model_failed` with `model`, `endpoint`
and `cause`; fix the endpoint or the key and `aip resume <run_id>` asks again.

An error before any step ran is not resumable and writes no run file: fix the inputs (or the
target) and `aip run` again. Here the inputs named `msg` instead of `message`:

<!-- cli-json: error-invalid-input -->
```json
{
  "error": "invalid_input",
  "step": "start",
  "message": "the input to 'start': message is missing; msg is not an input of this procedure; the inputs are ['message']",
  "missing": [
    "message"
  ],
  "invalid": [
    "msg"
  ],
  "pass": null,
  "passes": [],
  "run_id": null,
  "resumable": false
}
```

## `--progress`

One line per history entry, the moment the run writes it: `{"event": "step", "step", "kind",
"pass", "passes"}`, what happened there, and `seconds`, the step's own wall time (`<seconds>`
below stands for a number). What happened is, per kind: for a `Decide`, `answered_by` and
`answers` (each question's `value` and `confidence`); for a `Route`, `to` and, when the route
has a `Confidence_Below` check, `fired`; for an `Aggregate`, `result` (each aggregation's
value); for a `Task_Agent`, `answered_by` (the agent and session that answered); for a loop's
exit, `exit` (`until`, `items`, `times` or `cap`), `where` (`head`, or the step that produced
the `Until` answer) and `iterations`. A loop's line has no `seconds`.

The lines of a `For` appear as its passes run, so a batch reports while it works: the
classifications, the routes, a script, before the pause that follows. That is the order things
happened in. The history holds the same entries pass by pass in input order, the same at every
batch size, so inside a `For` the two orders can differ.

The angry branch of `billing-support`, with a decision model that read the message as angry:
no step paused, so one `run` printed the whole record and the final object.

<!-- cli-json: progress -->
```jsonl
{"event": "step", "step": "start", "kind": "Start", "pass": null, "passes": [], "seconds": "<seconds>"}
{"event": "step", "step": "triage", "kind": "Decide", "pass": null, "passes": [], "answered_by": {"model": "jev-1", "endpoint": "https://api.typesafe.ai"}, "answers": {"billing": {"value": true, "confidence": 0.94}, "tone": {"value": "angry", "confidence": 0.9}}, "seconds": "<seconds>"}
{"event": "step", "step": "by_tone", "kind": "Route", "pass": null, "passes": [], "to": "escalate", "fired": false, "seconds": "<seconds>"}
{"event": "step", "step": "escalate", "kind": "Execute", "pass": null, "passes": [], "seconds": "<seconds>"}
{"event": "step", "step": "end", "kind": "End", "pass": null, "passes": [], "seconds": "<seconds>"}
{"done": true, "result": {"message": "This is the THIRD time you have double charged me. Fix it today or I cancel.", "ticket_id": 35566, "queue": "tier2"}, "run_id": "4f1c9a2e7b3d5068", "run_file": "/home/you/.aip/runs/4f1c9a2e7b3d5068.json"}
```

## `aip runs`

`aip runs` lists runs, newest first: the server's when one is configured, else this machine's
run files, so a run id is never lost. `--name`, `--status`, `--agent`, `--session` and `--limit`
filter either list, and `--json` prints it as JSON.

```text
RUN               NAME                           STATUS  AGENT  STARTED                        UPDATED
7ca2fee28b8b46c7  billing_support_agent (draft)  paused  cli    2026-11-09T21:22:57.803+00:00  2026-11-09T21:22:57.830+00:00
1d5a6e3abcfd46db  billing_support (draft)        done    cli    2026-11-09T21:22:57.641+00:00  2026-11-09T21:22:57.671+00:00
```

`aip runs <run_id>` prints one run step by step, from this machine's run file when it has one
and from the server otherwise: a row per history entry with the step, its kind, its pass (every
enclosing loop and pass number), when the entry was written, `+MS` (the step's own time in
milliseconds, its `seconds`; a loop's exit row has none), and who answered or where it went and
why. `aip runs <run_id> --json` prints the whole record instead. An id no run has answers `aip:
no run <id> on this machine` and exit 1. This is the progress example's run (the times are one
run's; the test checks the columns and the rows):

```text
run 1d5a6e3abcfd46db  billing_support  draft  done
  bundle    d263181349669ead0530b8be158d5f96d3c4a386017e77085fa0c8d9170ddda7
  target    /home/you/aip/examples/language/billing-support
  agent     cli   session -   user -
  started   2026-11-09T21:22:57.641+00:00   finished 2026-11-09T21:22:57.671+00:00

STEP      KIND     PASS  WHEN          +MS  WHAT
start     Start    -     21:22:57.641    1  message
triage    Decide   -     21:22:57.642    0  billing=true 0.94, tone=angry 0.9  (by jev-1)
by_tone   Route    -     21:22:57.642    0  -> escalate  (triage_decision.tone is angry; confidence 0.9 not below 0.9)
escalate  Execute  -     21:22:57.670   28  scripts/escalate.py -> ticket_id, queue
end       End      -     21:22:57.671    0  message, ticket_id, queue

result: {"message": "This is the THIRD time you have double charged me. Fix it today or I cancel.", "ticket_id": 35566, "queue": "tier2"}
```

A decision's row shows each answer's value and confidence and the model; a route's where it
went and on what (the value, or `check fired` with the confidence and the bound); a task's who
answered and after how long a wait; a loop's why and where it exited and after how many passes.
A paused run ends with the step it waits at and since when, a failed one with the error and
whether a retry can help.

## The run file

`~/.aip/runs/<run_id>.json` is the run, whole; `aip runs <run_id> --json` prints it flat. At the
top: `run_id`, `bundle_id` (once, here; the bundle is in the cache under that id), `name`,
`target` and `origin` (what `aip run` was given: a `folder`, a `file` or a `name`), `revision`,
`workdir`, `server` and `recorded` (where it is recorded, and whether the last stop got there),
`created` and `updated` (the file's own times), and `run`, which holds:

| key | what |
|---|---|
| `status` | `paused`, `done` or `failed` |
| `position` | the node about to run, `step:<name>` or `loop:<name>`: the step a paused run waits at or a failed one stopped at; `null` once done |
| `started`, `finished` | when the run began, and when it last reached `done` or `failed` (`null` while paused) |
| `identity` | `agent`, `session`, `user`: who started it |
| `state` | the procedure's keys as they stand |
| `loops` | the runtime's loop keys while the run is under way (`index`, `iterations` and each loop's own key, `docs/language/spec.md` 2.6). They are never in `state`, and a run that is over (done, or failed at a cap) has none |
| `history` | one entry per step run, below |
| `pause` | the pending pause (`kind`, `step`, `tasks`, and `since`, when it began), or `null` |
| `error` | the error object of a failed run, or `null` |
| `result` | the `End` step's keys once done |
| `frames`, `passes` | the engine's bookkeeping for the loops under way, which is what lets a paused run resume mid-loop: one frame per loop entered and not yet left, with its `count` (passes completed), the list it runs over, for a `For` the passes in flight, and for a `Loop` `written` (the keys its body has produced, for the `Until` rule), `head` (set when the run stopped at the loop's head) and `until` (the head's test, until an entry carries it). Not a contract: read `history`, not these. Empty once the run is over |
| `requires_checked` | whether the procedure's `Requires` has been checked on this machine in this run |
| `batch` | how many `For` passes run at once in this run |

**The history.** One entry per step run, appended and never rewritten, every pass of a loop
included. "Record" means the whole run; its entries are the history. Every entry has `step`,
`kind`, `pass` and `passes` (as in a task), `at` (when it was written, UTC), `input` (the keys
the step read, each under the name the step reads it by: `tone`, not `triage_decision.tone`) and
`result` (what it produced). A step's entry has `seconds`, the step's own wall time; the time
between two entries' `at` also holds whatever waiting came between them. Inside a `For` the
entries are in pass order, not time order. Per kind:

| kind | also |
|---|---|
| `Decide` | `answered_by` (`{"model": "jev-1", "endpoint": "https://api.typesafe.ai"}`: the model the reply named and the endpoint asked); `model_seconds`, the call alone; `history_sent`, whether the earlier entries went to the model (`History true`); and when the decision went out with other `For` passes in one call, `batched: true` and `batch_size`, with `model_seconds` the one call's on each of them. `result` is the answer objects whole |
| `Route` | `read` (the dotted key it routed on, for lineage; `input` has the answer under its short name), `check` (`null` without a `Confidence_Below`; else `below`, `confidence`, `fired`, and when it fired `reason`: `below`, or `absent` for a script's answer with no confidence), `value` (the branch word taken, `null` when the check fired) and `to`. Its `result` is empty: a route produces nothing |
| `Aggregate` | `resolutions`: per aggregation, each answer's `source`, `value`, `holds`, `probability` (the probability the answer put on the condition, the number a `With Confidence_Above` bar reads; `null` for an answer that has none) and `barred` |
| `Execute` | `script` and `stdin` |
| `Task_Agent` | `prompt` and `references` as handed over; `answered_by` (`{"agent", "session"}`: who resumed with the answer); `waited_seconds`, from the pause to the answer. The entry is written when the answer is accepted |
| `For`, `Loop` | written when the loop exits: `result` holds `iterations` and a `For`'s collected list; `exit` has `reason` (`until`, `items`, `times`, `cap`), `where` (`head`, or the step or loop that produced the `Until` answer) and that answer's `resolution`. A loop that fails the run at its cap writes it too, with `reason: cap`. No `seconds` |

The first entry a `Loop Until` pass writes at the loop's own level also carries `until`, the test
at the head that let the pass run: `{"where": "head", "holds": false, "resolution": {...}}`, the
resolution `null` when the answer was not in the state yet (a `For` in the body writes its
passes' entries first, so there it is on the `For`'s own entry). `docs/language/runtime.md`, The
record, is the definition.

## `--version`

`aip --version` prints one line of plain text, `aip <version> language <language>`: the package
version (PEP 440) and the language version the compiler and runtime speak. The console reads
it at startup and refuses an `aip` below its minimum.

<!-- cli-version -->
```text
aip 0.9.0 language 0.9
```
