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
`billing-support`, `billing-support-agent` and `ticket-triage` examples under
`examples/language/`, run with no server configured; the test reads `4f1c9a2e7b3d5068` as
whatever id the run was given and shows `run_file` as its file name).

```
aip run <folder | bundle.rl | name[@rev]> --inputs '{"message": "..."}' [--batch N] [--agent A] [--session S] [--workdir DIR]
aip resume <run_id | run_file> --answers '{...}'
aip resume <run_id>                                     retry the step a failed run stopped at
```

`--inputs` and `--answers` take JSON inline, `@path` for a file, or `-` for stdin. Flags on both:

- `--progress`: before the final object, one line per record entry (below). The final object is
  then printed on one line too, so the whole output is JSON lines.
- `--debug`: when the command itself fails, the traceback goes to stderr. Stdout is unchanged.

Every run runs on this machine, from the bundle cache (`~/.aip/bundles/<bundle id>.rl`): a
folder is compiled and cached, an `.rl` verified and cached, a published name fetched (or
`aip pull` did it earlier). Every stop writes the run file named by `run_file`, by default
`~/.aip/runs/<run_id>.json` (`AIP_HOME` moves `~/.aip`), holding the whole run: the state, the
record, the loop frames, the pending pause or the error. `aip resume <run_id>` works from any
directory, and a run file's path works in place of the id. A resumed run is of the exact
bundle it started on, whatever happened to the folder since.

**Recording.** When a server is configured (`aip config --server URL`, or `AIP_SERVER`) the run
is posted there at every stop, a folder or file run as a run of a *draft* bundle, and the object
carries `"recorded": true` (or `false` when the server did not take it, with the reason on
stderr; the next stop tries again). With no server the object has no `recorded` key, the run
works, and the command ends with one line on stderr:

```text
aip: not recorded: no server is configured; run `aip config --server URL` to record runs on a server
```

## Paused

Every pause has `paused` (the kind, `task`: a `Task_Agent` step waits for the agent; a `Decide`
never pauses, it needs a decision model and fails the run without one, below), `step`, `tasks`,
`run_id` and `run_file`. `tasks` is a list with one entry per `For` pass waiting at the step,
and one entry outside a loop. Each task carries `index` (its position in the list, what the
answer is keyed by), `pass` (the innermost loop's pass number, `null` outside loops), `passes`
(every enclosing loop's name and pass number, outermost first), `prompt` (the step's `Prompt`
file or its description with `{key}` and `{assets[stem]}` filled in, nothing prepended), `state`
(the keys the step `Read`s, as it sees them), `references` (named, not loaded; read them when
the prompt calls for it), `answer_with` (what to answer: the keys and their types) and `labels`
(for each `choice` or `score` among them, the values it may take).

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
  "run_id": "4f1c9a2e7b3d5068",
  "run_file": "/home/you/.aip/runs/4f1c9a2e7b3d5068.json"
}
```

Answer with every key of `answer_with`: `{"billing": true, "tone": "calm"}`. An answer-typed
key takes the bare value, or `{"value": ...}`: a `true_or_false` is `true` or `false`, a
`choice` or a `score` one of its `labels`. The runtime stores it as `{"value": ...}` and nothing else: a value outside the labels, or
anything on the answer but its value (a `confidence`, say), is refused as `invalid_output` and
the pause stands. An agent's answer has no confidence, so the route `by_tone` that reads `tone`
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
  "run_id": "4f1c9a2e7b3d5068",
  "run_file": "/home/you/.aip/runs/4f1c9a2e7b3d5068.json"
}
```

Answer every task, keyed by its index: `{"0": {"reply": "..."}, "1": {"reply": "..."}}`. A list
in task order works too, and for a single task the one answer object on its own. An answer that
does not fit the step's keys is refused and nothing is applied (the `invalid_output` error
below); a task left unanswered fails its pass and the run, and a retry asks for it again.

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

`result` is the `End` step's `Read` keys that the path produced: here the reply, and on the angry path the ticket and its queue instead. What every step read and produced along the way is
the run's record: the run file's `run.history` (`aip runs <run_id>` prints the run), one entry
per step run with `step`, `kind`, `pass`, `passes`, `at`, `input` and `result`; a decision's
`answered_by` (`{"model": "jev-1", "endpoint": "https://api.typesafe.ai"}`, the model the reply
named and the endpoint asked) and the answer objects whole; a route's `read`, `check`
(`below`, `confidence`, `fired`, `reason`: `below`, or `absent` when a script's answer carried
no confidence), `value` and `to`;
an aggregation's `resolutions`; a script's `script`, `stdin` and `seconds`; a task's `prompt` and
`references`; a loop's `iterations`, collected list and `exit`. `docs/language/runtime.md`, The
record, is the definition.

## Error

Every error has `error` (the kind), `step` (the failing step; `null` when no step is to blame),
`message`, `pass` and `passes` (which loop pass failed), `run_id`, `resumable`, and `run_file`
when `resumable` is true.

| kind | when | extra keys |
|---|---|---|
| `invalid_input` | the inputs do not fit `Start`; a step's `Read` key is missing or mistyped; a target, run id or JSON argument cannot be used (then `kind` says which: `not_found`, `no_server`, `compile_error`, `not_a_bundle`, `bundle_tampered`, …) | `missing`, `invalid` |
| `invalid_output` | a result does not match the step's `Produce` keys: a script's (then `script` is set), or an answer to a pause; an answer's value outside the key's labels, or anything on an agent's answer but its value, counts | `missing`, `invalid` |
| `no_branch` | a route read a value none of its branch lines names | `key`, `value`, `branches` |
| `script_failed` | a script exited non-zero, or did not print one JSON object (then `exit_code` is 0) | `script`, `exit_code`, `stderr` |
| `timeout` | a script ran past the timeout | `script`, `seconds` |
| `requires_unmet` | the machine lacks what the procedure's `Requires` names, checked before the first script runs | `missing` |
| `no_decision_model` | a `Decide` step and this client has no decision model configured | |
| `decision_model_failed` | the decision model failed on a `Decide` step (unreachable, refused the key, a bad reply) | `model`, `endpoint`, `cause` |
| `loop_cap` | a `For` (or fold) given more items than `At_Most`, or an `Until` loop at its cap with `Else_Fail` | `loop`, `cap`, `count` |
| `not_paused` | `resume` with answers for a run that is not paused (a failed run is retried with none), or with none for a run that is done | |
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

An answer that does not fit its pause leaves the pause in place; answer it again. Here the
`triage` task of `billing-support-agent` above was answered with `{"billing": true}` only:

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

One line per record entry, in order, as the run writes them: `{"event": "step", "step",
"kind", "pass", "passes"}` plus `to` for a route, `answered_by` for a decision, `seconds` for a
script (wall time; `<seconds>` below stands for a number), and `exit` and `iterations` for a
loop. A `For` pass's entries appear when its batch completes, pass by pass in input order,
which is the order the record has them in at every batch size.

The angry branch of `billing-support`, with a decision model that read the message as angry:
no step paused, so one `run` printed the whole record and the final object.

<!-- cli-json: progress -->
```jsonl
{"event": "step", "step": "start", "kind": "Start", "pass": null, "passes": []}
{"event": "step", "step": "triage", "kind": "Decide", "pass": null, "passes": [], "answered_by": {"model": "jev-1", "endpoint": "https://api.typesafe.ai"}}
{"event": "step", "step": "by_tone", "kind": "Route", "pass": null, "passes": [], "to": "escalate"}
{"event": "step", "step": "escalate", "kind": "Execute", "pass": null, "passes": [], "seconds": "<seconds>"}
{"event": "step", "step": "end", "kind": "End", "pass": null, "passes": []}
{"done": true, "result": {"message": "This is the THIRD time you have double charged me. Fix it today or I cancel.", "ticket_id": 35566, "queue": "tier2"}, "run_id": "4f1c9a2e7b3d5068", "run_file": "/home/you/.aip/runs/4f1c9a2e7b3d5068.json"}
```

## `--version`

`aip --version` prints one line of plain text, `aip <version> language <language>`: the package
version (PEP 440) and the language version the compiler and runtime speak. The console reads
it at startup and refuses an `aip` below its minimum.

<!-- cli-version -->
```text
aip 0.9.0 language 0.9
```
