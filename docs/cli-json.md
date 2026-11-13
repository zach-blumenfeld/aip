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

**Recording.** When a server is configured the run is posted there at every stop and the object
carries `"recorded": true` (or `false` when the server did not take it, with the reason on
stderr; the next stop tries again). `aip config server local`, which the installer sets, records
on this machine with nothing to start: the first command that needs the server starts one
(`http://127.0.0.1:8247`, its store one file under the user data directory), later commands
reuse it, and it stops when idle (`docs/server-design.md`, The local server). `aip config server
URL --token T` records on a server elsewhere, `aip config server none` nowhere, and `AIP_SERVER`
overrides the file with any of the three. A folder or file run is recorded as a run of a *draft*
bundle, unless the server already holds that very bundle as a published revision: then it is a
run of that revision. With no server the object has no `recorded` key, the run works, and `aip
run` ends with one line on stderr, once for the run: its resumes do not repeat it, and a command
that changed nothing (a refused answer) prints no line about recording at all; its object says
`"recorded": false` where a server is configured, since nothing was sent.

```text
aip: not recorded: no server is configured; run `aip config server local` to record runs on this machine, or `aip config server URL` for a server elsewhere
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

`aip agent` prints the object `aip run` prints for the run of `assist` it drove
(`docs/agent.md`), done (its `result.note` is the answer, or the question for the person),
paused (its model's answer would not hold after four tries: exit 1, and `aip agent: gave up at
<step> after 4 answers: <reason>` on stderr) or the error object below (the model's endpoint
failing is one, kind `server`, with `aip agent: the model's endpoint failed: <why>` on stderr),
with `session` added. The
runs themselves are ordinary runs, recorded as agent `agent`: `aip runs
--session <session>` lists them, and their pauses and errors are the objects of this page.

`aip resume --work JSON` adds what the answering agent says it spent to the task's history
entry, marked `work: "reported"` (below); it changes nothing else in the object printed. A
`--work` that does not fit (a key other than `model`, `tool_calls`, `tokens`, `seconds`, a value
of the wrong kind) is refused as `invalid_input`, resumable, and the pause stands.

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
| `invalid_input` | the inputs do not fit `Start`; a step's `Read` key is missing or mistyped; a target, run id or JSON argument cannot be used (then `kind` says which: `not_found`, `retired`, `no_server`, `compile_error`, `not_a_bundle`, `bundle_tampered`, …). A published name the server does not have reads the same from every command: `no procedure 'billing-support'; did you mean `billing_support`?` (the hint when the name with `_` for `-` is published), `no revision 7 of billing_support`, `billing_support has no live revision`. `retired` is `aip run name@revision` on a retired revision, which `--force` runs anyway | `missing`, `invalid` |
| `invalid_output` | a result does not match the step's `Produce` keys: a script's (then `script` is set), or an answer to a pause; a key the step does not produce, an answer's value outside the key's labels, or anything on an agent's answer but its value, counts | `missing`, `invalid` (key names); for an answer to a pause also `missing_tasks` (task indexes left unanswered) and `invalid_tasks` (indexes the pause does not have), each present when it names something |
| `no_branch` | a route read a value none of its branch lines names | `key`, `value`, `branches` |
| `script_failed` | a script exited non-zero, or did not print one JSON object (then `exit_code` is 0) | `script`, `exit_code`, `stderr` |
| `timeout` | a script ran past the cap on one script, `aip config --script-timeout` (`AIP_SCRIPT_TIMEOUT`, 300 seconds by default); the message names the knob, and a retry runs the script again | `script`, `seconds` |
| `script_not_run` | a run that executes no script (the SDK's `run(..., scripts=False)`, a trial) reached an `Execute`; it stops there, before the script starts, and is over: never resumable, and not recorded | `script` |
| `requires_unmet` | the machine lacks what the procedure's `Requires` names, checked before the first script runs | `missing` |
| `no_decision_model` | a `Decide` step and this client has no decision model configured | |
| `decision_model_failed` | the decision model failed on a `Decide` step (unreachable, refused the key, a bad reply) | `model`, `endpoint`, `cause` |
| `loop_cap` | a `For` (or fold) given more items than `At_Most`, or an `Until` loop at its cap with `Else_Fail`; `step` is `null` and `loop` names the loop; never resumable | `loop`, `cap` (the most passes, or items, allowed), `count` (the passes run, or the items given) |
| `not_paused` | `resume` with answers for a run that is not paused (a failed run is retried with none), or with none for a run that is done or that failed in a way a retry would only repeat (`loop_cap`, `script_not_run`) | |
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
  "run_file": "/home/you/.aip/runs/4f1c9a2e7b3d5068.json",
  "warning": "no decision model is configured, and this procedure asks one at triage: a run that reaches it fails there with no_decision_model until one is set (run `aip config --decision-model-key KEY`, and `aip config --decision-model URL` for an endpoint other than TypeSafe's)"
}
```

**The warning.** `aip run` does not wait for the `Decide` to say so. When the procedure has one
and no model is configured, it prints `aip: warning: <the sentence>` on stderr before the first
step runs, and the object that call prints, whichever of the three it is, carries the sentence
as `warning`. It is a warning and not an error because the run may never reach the step: a
route may go another way. `aip info` shows the same sentence (`warning` in its `--json`). To run
one command with no model whatever the config file holds, set `AIP_DECISION_MODEL_KEY=` to
nothing (and `AIP_DECISION_MODEL=` too, when the file names an endpoint).

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

`aip agent --progress` prints the step lines of the run of `assist` it drives
(`{"event": "step", ...}`, the fields above) and nothing of its own. `aip agent --answer RUN
--progress` (one pause of any run, answered by the model and resumed; `docs/agent.md`) prints a
line per model call (`{"event": "answer", "step", "run_id", "tokens", "seconds"}`),
`{"event": "refused", "step", "run_id", "reason"}` when an answer did not hold and went back to
the model, or `{"event": "gave_up", "step", "run_id", "reason"}` when none would or the endpoint
failed, among the run's step lines, then the object `aip resume` prints; when the model gave up,
the run's paused object as it was, with `"gave_up": "<reason>"`, exit 1.

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

`aip runs` lists runs, the most recently started first (a run resumed later keeps its place):
the server's when one is configured, else this machine's run files, so a run id is never lost.
`--name`, `--status`, `--agent`, `--session`, `--user`, `--draft` or `--published`, and
`--limit` filter either list, and `--json` prints it as JSON. A `--name` that is no procedure's
answers `no runs of `x`; names are `aip list`'s` (the published name of the folder
`billing-support` is `billing_support`).

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
A script's or an agent's row names what it produced, with the value of an answer-typed key, so
a check that failed reads `scripts/policy_check.py -> passed=false`. A paused run ends with the
step it waits at and since when, a failed one with the error and whether a retry can help. A
run paused inside a `For` lists the passes it has made so far, one row per entry as for a
finished loop; only the loop's own exit row waits for the loop to end.

## `aip audit` and `aip export runs`

`aip audit` lists the server's audit queries, one per line with what it answers, and `aip audit
<query>` prints one query's rows as a JSON list (`docs/server-design.md`, Audit, has each
query's rows). The flags are the queries' parameters: `--name`, `--agent`, `--session`, `--user`,
`--draft` or `--published` (which runs), `--window N` (how many recent runs), `--limit N`,
`--repeats N` (`repeated-cycles`), `--key K` (`lineage`). `aip audit --save NAME --cypher
'MATCH ...'` (or `@file`) keeps a query of your own on the server, listed with `(stored)` and
run by its name; `--delete NAME` removes it. A query is refused when it is stored if it writes
or does not parse, and its rows are whatever it returns: a node comes back as `{"labels",
"properties"}`, a relationship as `{"type", "properties"}`. With `--name x`, when nothing
matches because there is no run of `x` and no procedure of that name, the rows are `[]` and
stderr says `no runs of `x`; names are `aip list`'s`.

```text
$ aip audit confidence-fired --agent claude
[
  {"name": "billing_support", "route": "by_tone", "reason": "below", "fired": 1, "run_ids": ["4f1c9a2e7b3d5068"]}
]
```

`aip export runs [name] [--since DATE] [--agent A] [--session S] [--user U] [--draft |
--published] -o audit.rl` writes the server's runs that match, and the procedures they ran, as
one Relate file: each run's record beside the graph of the bundle it ran, which the engine's
own tools open with no server and the queries of `docs/language/queries.md` answer on. It prints
`wrote 7 run(s) of 1 procedure(s) (3 bundles: each revision and each draft is one) to
audit.rl`, naming the bundles only when there are more of them than procedures, and refuses a
file that exists without `--force`.

## The run file

`~/.aip/runs/<run_id>.json` is the run, whole; `aip runs <run_id> --json` prints it flat (with
the history as the record shows it, below). At the
top: `run_id`, `bundle_id` (once, here; the bundle is in the cache under that id), `name`,
`target` and `origin` (what `aip run` was given: a `folder`, a `file` or a `name`), `revision`
(the one a name resolved to, or the one the server said the bundle is published as; a run with
none is a draft's),
`workdir` (the run's working directory; `aip runs <run_id> --json` prints it, and the server's
record keeps it), `server` and `recorded` (where it is recorded, and whether the last stop got
there), `scripts` (false for a trial, which executes no script and is not recorded), `created` and
`updated` (the file's own times), and `run`, which holds:

| key | what |
|---|---|
| `status` | `paused`, `done` or `failed` |
| `position` | the node about to run, `step:<name>` or `loop:<name>`: the step a paused run waits at or a failed one stopped at; `null` once done |
| `started`, `finished` | when the run began, and when it last reached `done` or `failed` (`null` while paused) |
| `identity` | `agent`, `session`, `user`: who started it; and `agent_version` when the agent gave one (`aip mcp` records the MCP client's own version). Runs are filtered by `agent` alone |
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
entries are in pass order, not time order. While a run is paused (or failed) inside a `For`,
the entries its passes have written are held with those passes under `frames`, and join
`history` when the batch completes; `aip runs <run_id>`, its `--json` and the server's record
show them in place already, so a paused loop's work is always in the record. Per kind:

| kind | also |
|---|---|
| `Decide` | `answered_by` (`{"model": "jev-1", "endpoint": "https://api.typesafe.ai"}`: the model the reply named and the endpoint asked); `model_seconds`, the call alone; `history_sent`, whether the earlier entries went to the model (`History true`); and when the decision went out with other `For` passes in one call, `batched: true` and `batch_size`, with `model_seconds` the one call's on each of them. `result` is the answer objects whole |
| `Route` | `read` (the dotted key it routed on, for lineage; `input` has the answer under its short name), `check` (`null` without a `Confidence_Below`; else `below`, `confidence`, `fired`, and when it fired `reason`: `below`, or `absent` for a script's answer with no confidence), `value` (the branch word taken, `null` when the check fired) and `to`. Its `result` is empty: a route produces nothing |
| `Aggregate` | `resolutions`: per aggregation, each answer's `source`, `value`, `holds`, `probability` (the probability the answer put on the condition, the number a `With Confidence_Above` bar reads; `null` for an answer that has none) and `barred` |
| `Execute` | `script` and `stdin` |
| `Task_Agent` | `prompt` and `references` as handed over; `answered_by` (`{"agent", "session"}`: who resumed with the answer; `aip agent`'s answers are `{"agent": "agent", "session", "model": ID}`, `ID` being the model the endpoint said answered); `waited_seconds`, from the pause to the answer. The entry is written when the answer is accepted. What answering took, when it is known, is marked `work: "reported"`: an answer given with `aip resume --work` (or by `aip agent`, which reports its model's tokens and seconds) has what the agent said: `model` in `answered_by`, `tool_calls` (a count, or a list as above), `tokens` (at least `total`) and `work_seconds` |
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
