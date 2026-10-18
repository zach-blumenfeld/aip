# The CLI's JSON output

`aip run` and `aip resume` print exactly one JSON object on stdout when they stop, and nothing
else unless asked: no prose, no traceback. A run stops one of three ways:

| outcome | first key | exit code |
|---|---|---|
| paused | `"paused": <kind>` | 0 |
| done | `"done": true` | 0 |
| error | `"error": <kind>` | 1 |

This is a contract: agents, the aip-runtime skill, and the console parse it. Every example on
this page is checked against the CLI's real output by `tests/test_cli_json.py` (a local run of
the `billing-support` example from aip-spec; the test reads `4f1c9a2e7b3d5068` as whatever id the run
was given).

Flags:

- `--progress`: before the final object, one line per completed step (below). The final object
  is then printed on one line too, so the whole output is JSON lines.
- `--debug`: on an error, the traceback goes to stderr. Stdout is unchanged.

Every outcome except an error before anything ran writes the run file named by `run_file`, by
default `~/.aip/runs/<run_id>.json` (`AIP_HOME` moves `~/.aip`; `aip run --run-file <path>`
picks an explicit path). `run_id` is the server's run id on a served run and a generated one on
a local run. `aip resume <run_id> --input <answer.json>` answers a pause, from any directory;
`aip resume <run_id>` with no input retries a failed step. A run file's path works in place of
the id. An answer is merged over the state the run holds (the run file of a local run; the
server, for a served run, whose run file holds only the run id, server, revision, working
directory and pause), so
it carries only the keys the pause asks for.

## Paused

Every pause has `paused` (the kind), `step`, `state`, `run_id` and `run_file`. `state` is the
paused step's declared inputs only, never the whole run's state.

### `decision`: answer the questions

No decision model is configured on this client (`TYPESAFE_API_KEY`, or `aip config
--decision-model KEY`), so the agent answers in its place. It gets what the model would have:
`questions` and `state`. The run's history records the answer with `"resolver": "manual"`.

<!-- cli-json: paused-decision -->
```json
{
  "paused": "decision",
  "step": "triage",
  "questions": {
    "billing": {
      "type": "noul",
      "instructions": "Is this message about a charge, invoice, refund, or subscription payment?"
    },
    "tone": {
      "type": "choice",
      "instructions": "How upset is the customer? Angry means explicit frustration, threats to cancel, or demands.",
      "criteria": {
        "angry": "Frustrated, demanding, or threatening to leave.",
        "calm": "Neutral or polite, asking a question."
      }
    }
  },
  "state": {
    "message": "I was charged twice for March. Could you check?"
  },
  "run_id": "4f1c9a2e7b3d5068",
  "run_file": "/home/you/.aip/runs/4f1c9a2e7b3d5068.json"
}
```

Answer: one key per question, `{"billing": true, "tone": "calm"}`. A `noul` is `true`/`false`, a
`choice` one of its `criteria` labels, a `score` the level number (its position in `criteria`,
from 0). The questions define the answer's shape, so there is no `answer_with`.

### `client_task`: do the step's work

<!-- cli-json: paused-client-task -->
```json
{
  "paused": "client_task",
  "step": "reply",
  "task": "# Draft a reply\n\nWrite a short, calm reply to the customer below. Apply the policy exactly; do not\npromise anything the policy does not cover.\n\nCustomer message:\nI was charged twice for March. Could you check?\n\nPolicy:\n# Refund policy\n\n- Duplicate charges are refunded in full within 5 business days.\n- Refunds for other reasons are honored within 30 days of purchase.\n\n\nReturn JSON with `reply` (your reply text).\n",
  "state": {
    "message": "I was charged twice for March. Could you check?",
    "tone": "calm"
  },
  "references": [
    {
      "uri": "billing-support/references/help.md",
      "description": "Escalation contacts and plan matrix. Only for plan changes, currency issues, or charges older than 30 days."
    }
  ],
  "answer_with": {
    "reply": "string"
  },
  "run_id": "4f1c9a2e7b3d5068",
  "run_file": "/home/you/.aip/runs/4f1c9a2e7b3d5068.json"
}
```

`task` is the step's template rendered from its declared inputs, with nothing prepended.
`references` are named, not loaded. `answer_with` is the step's declared `outputs` with their
types; the answer must hold every one of them: `{"reply": "..."}`.

### `review`: confirm or override the model

This client's decision model answered, but at least one question fell under its threshold (the
author's, from SKILL.md). Nothing is recorded yet: on a served run the server still waits at the
decision, and the review exists only in the run file. Once answered, the history records the
final answers with `"resolver": "typesafe"`, `"reviewed": true`, and the model's
`proposed` answers beside them.

<!-- cli-json: paused-review -->
```json
{
  "paused": "review",
  "step": "triage",
  "state": {
    "message": "I was charged twice for March. Could you check?"
  },
  "proposed_answers": {
    "billing": true,
    "tone": "angry"
  },
  "review": [
    {
      "question": "tone",
      "type": "choice",
      "confidence": 0.58,
      "probabilities": {
        "angry": 0.58,
        "calm": 0.42
      },
      "reason": "confidence below 0.6"
    }
  ],
  "run_id": "4f1c9a2e7b3d5068",
  "run_file": "/home/you/.aip/runs/4f1c9a2e7b3d5068.json"
}
```

Answer: only the overrides, `{"tone": "calm"}`, or `{}` to accept every proposed answer. A
`noul` review item carries `noul` (the probability of true) instead of `confidence` and
`probabilities`.

## Done

<!-- cli-json: done -->
```json
{
  "done": true,
  "run_id": "4f1c9a2e7b3d5068",
  "state": {
    "message": "I was charged twice for March. Could you check?"
  },
  "run_file": "/home/you/.aip/runs/4f1c9a2e7b3d5068.json"
}
```

`state` is the procedure's result: the state projected to the end step's `inputs`. What each
step produced along the way is in the run's history: the run file's `history` for a local run,
`GET /runs/{run_id}` for a served one.

## Error

Every error has `error` (the kind), `step` (the failing step; `null` when no step is to blame),
`message` (for a human), `run_id`, `resumable`, and `run_file` when `resumable` is true.

| kind | when | extra keys |
|---|---|---|
| `script_failed` | a script exited non-zero, or did not print one JSON object (then `exit_code` is 0) | `script`, `exit_code`, `stderr` |
| `timeout` | a script ran past the step's timeout | `script`, `seconds` |
| `invalid_input` | the state lacks a key the step declares, or holds it with the wrong type, or a router's key has no branch | `missing`, `invalid` |
| `invalid_output` | a result does not match the step's outputs: a script's (then `script` is set), or an answer to a pause | `missing`, `invalid` |
| `requires_unmet` | the machine lacks what the skill's `requires` block names, checked before the first script runs | `missing` |
| `server` | anything else: an unknown skill or folder, an unreachable server, a bug | `status` on a served run (the HTTP status) |

`missing` names keys that are absent; `invalid` names keys that are mistyped, undeclared, or
have no branch.

A step that failed while running leaves the run file at the state before it, so
`aip resume <run_id>` with no input retries it once the cause is fixed:

<!-- cli-json: error-script-failed -->
```json
{
  "error": "script_failed",
  "step": "escalate",
  "message": "Script scripts/escalate.py exited with 1:\nticket service unreachable",
  "script": "scripts/escalate.py",
  "exit_code": 1,
  "stderr": "ticket service unreachable",
  "run_id": "4f1c9a2e7b3d5068",
  "resumable": true,
  "run_file": "/home/you/.aip/runs/4f1c9a2e7b3d5068.json"
}
```

An answer that does not fit its pause leaves the pause in place; answer it again. Here the
decision pause above was answered with `{"billing": true}` only:

<!-- cli-json: error-invalid-output -->
```json
{
  "error": "invalid_output",
  "step": "triage",
  "message": "Output of step 'triage' is invalid: missing answers for ['tone']",
  "missing": [
    "tone"
  ],
  "invalid": [],
  "run_id": "4f1c9a2e7b3d5068",
  "resumable": true,
  "run_file": "/home/you/.aip/runs/4f1c9a2e7b3d5068.json"
}
```

A skill with scripts declares the environment they need in `requires`. Before the first script
runs, the machine is checked against it and every missing item is named at once, so nothing is
half done; the run waits before that step, and `aip resume <run_id>` retries once the items are
installed. Here the skill also asked for package `nosuchpkg` and tool `nosuchtool`:

<!-- cli-json: error-requires-unmet -->
```json
{
  "error": "requires_unmet",
  "step": "escalate",
  "message": "this machine lacks what the skill requires: package nosuchpkg; tool nosuchtool (not on PATH)",
  "missing": [
    "package nosuchpkg",
    "tool nosuchtool (not on PATH)"
  ],
  "run_id": "4f1c9a2e7b3d5068",
  "resumable": true,
  "run_file": "/home/you/.aip/runs/4f1c9a2e7b3d5068.json"
}
```

An error before any step ran (a start input missing a key, an unknown skill) is not resumable
and writes no run file; its `run_id` is `null` on a local run: fix the input and `aip run` again.

## `--progress`

One line per completed step, in order: `{"event": "step", "step", "kind"}` plus `to` for a
router (the branch taken), `resolver` for a decision (`typesafe` or `manual`), `seconds` for an
execution step (wall time; `<seconds>` below stands for a number). A client task's or a
reviewed decision's line is printed when its answer is accepted, by the `resume` that carries
it. The end step has no line: the final object follows.

The angry branch, resumed after the decision pause with `{"billing": true, "tone": "angry"}`:

<!-- cli-json: progress -->
```jsonl
{"event": "step", "step": "triage", "kind": "decision", "resolver": "manual"}
{"event": "step", "step": "by-tone", "kind": "router", "to": "escalate"}
{"event": "step", "step": "escalate", "kind": "execution", "seconds": "<seconds>"}
{"done": true, "run_id": "4f1c9a2e7b3d5068", "state": {"message": "This is the THIRD time you have double charged me. Fix it today or I cancel."}, "run_file": "/home/you/.aip/runs/4f1c9a2e7b3d5068.json"}
```

## `--version`

`aip --version` prints one line of plain text, `aip <version> format <format>`: the package
version (PEP 440) and the skill format the runtime accepts. The console (formerly inspector)
reads it at startup and refuses an `aip` below its minimum.

<!-- cli-version -->
```text
aip 0.6a0 format 0.6a0
```
