---
name: aip-runtime
description: Run published AIP procedures (runbooks, step-by-step workflows) from an AIP server with the `aip` command. Use when a task might match a known procedure, runbook, or workflow, when the user mentions aip or AIP, or when AIP_SERVER is set; search the catalog first, then run the match and answer its pauses instead of doing the steps by hand.
license: Apache-2.0
metadata:
  aip-version: "0.8"
---

# Running AIP procedures

An AIP procedure is a graph of typed steps that `aip` and its server run: a start step holding
the input, scripts, decisions, routers, and tasks it hands back to you. You find the procedure,
give it its start input, and answer when it pauses. You never execute its steps yourself.

## Check once

```
aip --help          # the client is installed
aip config          # prints `server: <url>` (else set AIP_SERVER=http://host:port) and `decision model: <endpoint>  key: set` or `none`
```

No server and no `aip`: this skill does not apply; do the task as you normally would.
A skill folder on disk (`aip run <folder>`) runs locally with the same loop below.

## The loop

1. **Search** whenever the task might match a known procedure. Use the task's own words.

   ```
   aip search "<a few words from the task>"      # name@revision  score  description
   ```

   Read the descriptions. Pick the one that says it is for this task, or none; a high
   score alone is not a match. `aip list` shows every published name.

2. **Inspect** the match. `info` is all you need to read; do not fetch its SKILL.md.

   ```
   aip info <name>                    # purpose, when to use, start input, steps, result
   aip info <name> --example-input    # a JSON object with every start key, example values
   ```

   Write the start input to a file, replacing the example values with the task's real
   ones. Keys and types must match the START INPUT table.

3. **Run** it.

   ```
   aip run <name> --input start.json
   ```

   It prints one JSON object. Exit 0 with `"done": true`: finished, `state` is the result.
   Exit 0 with `"paused"`: answer it (step 4). Exit 1 with `"error"`: see step 5.

4. **Answer** each pause by its `paused` kind: write the answer as a JSON object and run
   `aip resume <run_id> --input answer.json`. Repeat until `"done": true`.

   | `paused`      | what the pause carries                               | what you put in the answer file                                    |
   |---------------|------------------------------------------------------|--------------------------------------------------------------------|
   | `task`        | `tasks`, one per waiting pass, each with `prompt`: what to do; `state`; `references`; `answer_with`; `labels` | for every task at once, the work product under every key in `answer_with` and no other key, with those types; an answer-typed key is `true`/`false` or one of its `labels`, and nothing else |

   A decision (`Decide`) never pauses: the decision model on this machine answers it. There is no
   answering one yourself.

   `state` is only what this step needs. The run holds the rest (the server, for a published
   procedure) and your answer is merged over it, so send only the keys asked for. Load a `references` entry only if the
   task says you need it.

5. **On an error**, read `error`, `step` and `message`. `invalid_input` / `invalid_output`
   name the keys in `missing` and `invalid`: fix your input or answer and resume again (a
   bad answer leaves the pause in place, and names in `missing_tasks` a task you left out).
   `loop_cap` has `resumable` false: a loop ran out of passes, the run is over, report it. `script_failed` carries the script's `exit_code`
   and `stderr`; if `resumable` is true, `aip resume <run_id>` with no input retries that
   step once the cause is fixed. `requires_unmet` lists in `missing` what the machine running
   the scripts lacks; install it if you may, then retry the same way. `no_decision_model`: this
   machine has no decision model configured, and `decision_model_failed`: the one configured
   (`model`, `endpoint`, `cause`) did not answer. Do not answer the decision yourself; report it
   (once the model is configured or reachable, a bare `aip resume <run_id>` asks it). Otherwise report the error.

## Rules

- **Do not do the steps by hand** when the procedure can run them. The scripts, routing,
  and validation are the procedure; your job is the pauses and the final result.
- **Scripts run here, on this machine,** for a published procedure too: `aip` fetches them
  from the server and runs them itself. Files they read and write are relative to the run's
  working directory, the directory `aip run` started in (or `--workdir`), kept for `resume`.
- **Decisions are resolved here too.** `aip` asks the decision model configured on this machine
  (an endpoint with the TypeSafe API shape: `aip config --decision-model-key KEY`, and
  `--decision-model URL` for an endpoint other than TypeSafe's; `AIP_DECISION_MODEL_KEY` and
  `AIP_DECISION_MODEL` override), which answers with its confidence, and a router checks that
  confidence where the author says. Without one, a decision stops the run with `no_decision_model`;
  you never answer a decision yourself. The history records which model answered and at which
  endpoint (`answered_by`). Do not set a key unless asked.
- **One run, one run id.** Every outcome prints `run_id`; `aip resume <run_id>` finds the
  run file (`run_file`, under `~/.aip/runs/`) from any directory and rewrites it. Do not edit it. Do not start a second run of the same task.
- **Report the result** from `state` (the end step's declared keys) in the task's terms,
  and say which procedure ran, by name. What each step produced is in the run's history:
  on the server for a published procedure (`GET /runs/<run_id>`), in the run file's
  `history` for a folder. If the run stops with an error you cannot fix, report the
  error; do not improvise the remaining steps.
- **Do not publish, pin, or retire** anything unless asked; those change the catalog for
  everyone.

## Example

Task: "A customer wrote: I was charged twice! Handle it."

```
$ aip search "customer charged twice billing"
billing-support@124d4a7b6208abed  0.812  Triage an inbound billing message ...
$ aip info billing-support --example-input > start.json       # edit: real message
$ aip run billing-support-agent --input start.json
{ "paused": "task", "step": "triage",
  "tasks": [ { "index": 0, "prompt": "Read the customer's message and classify it. ...",
               "state": { "message": "I was charged twice!" }, "references": [],
               "answer_with": { "billing": "true_or_false", "tone": "choice" }, "labels": { "tone": ["angry", "calm"] } } ],
  "run_id": "4f1c9a2e7b3d5068", "run_file": "~/.aip/runs/4f1c9a2e7b3d5068.json" }
$ echo '{"billing": true, "tone": "angry"}' > answer.json
$ aip resume 4f1c9a2e7b3d5068 --input answer.json
{ "done": true, "run_id": "4f1c9a2e7b3d5068", "state": { "message": "I was charged twice!" }, "run_file": "..." }
```

The angry branch ran the procedure's script here and opened the ticket (its `ticket_id` is in
the run's history); you answered one pause, a task that asked you to classify the message under
its `labels`, and the router branched on your answer. In `billing-support`, the same procedure
with a `Decide`, the decision model classifies instead and the router checks its confidence in
the tone before it branches, escalating an unsure one; with no model configured that run stops
with `no_decision_model`. A calm message pauses with a `task` asking you to draft the reply, and
your `{"reply": "..."}` ends the run.
