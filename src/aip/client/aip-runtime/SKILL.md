---
name: aip-runtime
description: Run published AIP procedures (runbooks, step-by-step workflows) from an AIP server with the `aip` command. Use when a task might match a known procedure, runbook, or workflow, when the user mentions aip or AIP, or when AIP_SERVER is set; search the catalog first, then run the match and answer its pauses instead of doing the steps by hand.
license: Apache-2.0
metadata:
  aip-version: "0.5a1"
---

# Running AIP procedures

An AIP procedure is a graph of typed steps that a server executes: scripts, decisions,
routers, and tasks it hands back to you. You are the client. You find the procedure,
give it its start input, and answer when it pauses. You never execute its steps yourself.

## Check once

```
aip --help          # the client is installed
aip config          # prints `server: <url>`; else set AIP_SERVER=http://host:port
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

   Exit 0: done, the JSON has `"done": true` and `state` is the result. Exit 3: a pause,
   printed as JSON with `paused`, `step`, and a `resume` command. Exit 1: an error on
   stderr; fix the input or report it.

4. **Answer** each pause by `paused` kind, write the answer as a JSON object, and run the
   printed `resume` command with `--input <answer.json>`. Repeat until `"done": true`.

   | `paused`      | what the block carries                              | what you put in the answer file                                    |
   |---------------|-----------------------------------------------------|--------------------------------------------------------------------|
   | `decision`    | `questions`: name, `type`, `instructions`, `criteria` | one key per question: `true`/`false` for `noul`, a `criteria` label for `choice`, the level number (list position from 0) for `score`; judge from `suggested` |
   | `review`      | `review`: answers under their confidence threshold   | only the keys you override, e.g. `{"tone": "calm"}`; `{}` accepts the model's answers |
   | `client_task` | `task`: the rendered instructions; `references`; `expects` | the work product under the keys in `expects`; extra keys pass through to the state |

   Your answer is merged over `suggested`, so you need not repeat what is already there.
   Load a `references` entry only if the task text says you need it.

## Rules

- **Do not do the steps by hand** when the server can run them. The scripts, routing,
  and validation are the procedure; your job is the pauses and the final result.
- **Scripts run on the server.** File paths in the start input must be reachable there,
  not just here. Output the server produced is in `state`, not on your disk.
- **One run, one run file.** The pause names it (`run_file`); `resume` reads and rewrites
  it. Do not edit it. Do not start a second run of the same task.
- **Report the result** from `state` in the task's terms, and say which procedure ran,
  by name. If the procedure stops with an error, report the error; do not improvise the
  remaining steps.
- **Do not publish, pin, or retire** anything unless asked; those change the catalog for
  everyone.

## Example

Task: "A customer wrote: I was charged twice! Handle it."

```
$ aip search "customer charged twice billing"
billing-support@124d4a7b6208abed  0.812  Triage an inbound billing message ...
$ aip info billing-support --example-input > start.json       # edit: real message
$ aip run billing-support --input start.json
{ "paused": "decision", "step": "triage",
  "questions": { "billing": {"type": "noul", ...}, "tone": {"type": "choice", "criteria": {"angry": ..., "calm": ...}} },
  "suggested": { "message": "I was charged twice!" },
  "resume": "aip resume .aip/runs/billing-support-....json --input <answer.json>", ... }
$ echo '{"billing": true, "tone": "angry"}' > answer.json
$ aip resume .aip/runs/billing-support-....json --input answer.json
{ "done": true, "state": { "message": "...", "billing": true, "tone": "angry", "ticket_id": 45067, "queue": "tier2" }, ... }
```

The angry branch ran a script on the server and opened the ticket; you answered one
pause. The calm branch would instead pause with `client_task` asking you to draft the
reply, and your `{"reply": "..."}` would end the run.
