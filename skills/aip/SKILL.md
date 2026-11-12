---
name: aip
description: Run and write Agent Instruction Protocol (AIP) procedures with the `aip` command. A procedure is a runbook or workflow that aip runs step by step, pausing for you only where a step is yours. Use when a task might match a known procedure, runbook or workflow, when the user mentions aip or AIP, a `procedure.aip` file or an `.rl` bundle, or asks to build a procedure from a description (`make_procedure`); search the catalog first, then run the match and answer its pauses instead of doing the steps by hand.
license: Apache-2.0
metadata:
  aip-version: "0.9"
---

# AIP: running and writing procedures

An AIP procedure is a small graph of typed steps that the `aip` command runs: scripts it
executes, questions it puts to a decision model, routes and loops it follows, and tasks it hands
to you. You find the procedure, give it its inputs, and answer when it pauses. You never perform
its steps yourself, and you never decide where it goes next.

## Check once

```
aip --version       # aip 0.9.0 language 0.9; no `aip`: this skill does not apply
aip config          # where runs are recorded (server: local, a URL, or none) and whether a decision model is set
```

A procedure is named three ways, and every command takes any of them: a published name
(`billing_support`, `billing_support@2`), a program folder (the directory holding
`procedure.aip`), or a compiled bundle (`file.rl`).

## Run a procedure

1. **Find it.** Search with the task's own words and read the descriptions; a high score alone
   is not a match. `aip list` shows every published name.

   ```
   aip search "<a few words from the task>"      # name@revision  score N  description
   ```

2. **Read what it needs.**

   ```
   aip info <target>                     # what it does, when to use it, its inputs, steps and result
   aip info <target> --example-inputs    # a JSON object with every input, to fill with the real values
   ```

3. **Run it.** Give every input and nothing else.

   ```
   aip run <target> --inputs '{"message": "..."}'       # or --inputs @inputs.json
   ```

   It prints one JSON object. `"done": true`: finished, `result` is the outcome. `"paused":
   "task"`: answer it (step 4). `"error"`: step 5. Every object carries `run_id`, `run_file`
   (where the run is kept on this machine) and, when `aip config` names a server, `recorded`
   (whether this stop reached it).

4. **Answer the pause.** A pause has `step` and `tasks`. Each task has `prompt` (what to do),
   `state` (the data for it), `references` (files to load only if the prompt needs them),
   `answer_with` (the keys to answer, with their types) and `labels` (the allowed values of a
   `choice` or `score` key). Do what the prompt says, then:

   ```
   aip resume <run_id> --answers '{"reply": "..."}'     # or --answers @answers.json
   ```

   - **One task**: the answer is one object with every key of `answer_with` and no other key.
     A `true_or_false` key is `true` or `false`; a `choice` or `score` key is one of its `labels`.
   - **Several tasks** (a loop hands over a batch): answer all of them in one `resume`, keyed by
     each task's `index`: `{"0": {"reply": "..."}, "1": {"reply": "..."}}`. Each task stands on
     its own; do each from its own `prompt` and `state`. A task's `passes` says which pass of
     which loop it is (`[{"loop": "each_ticket", "pass": 1}]`); `pass` is the innermost one.
   - Inside a loop with a cap a task has `pass_of`, the cap, and `last_pass`: when it is true
     this is the last attempt the loop allows, so make it count.

   Repeat until `"done": true`. The pause's `hint` shows the shape of the answer. You may add
   `--work '{"model": "<your model id>", "tool_calls": 3, "tokens": 12000}'` to say what the
   answer took; the record keeps it as reported by you.

5. **On an error**, read `error`, `step`, `message` and `resumable`.
   - `invalid_input`: the inputs do not fit; `missing` and `invalid` name the keys. Fix them and
     `aip run` again.
   - `invalid_output` after a `resume`: your answer did not fit (`missing`, `invalid`,
     `missing_tasks`). Nothing was applied and the pause still waits: answer again, correctly.
   - `no_decision_model`, `decision_model_failed`: a `Decide` step needs the decision model
     configured on this machine. Do not answer the decision yourself and do not set a key unless
     asked; report it. Once it is fixed, `aip resume <run_id>` with no answers retries the step.
   - `script_failed`, `requires_unmet`, `timeout`: a script could not run; `stderr` or `missing`
     says why. Fix the cause if you may, then `aip resume <run_id>` with no answers.
   - `loop_cap`: a loop ran out of passes. The run is over (`resumable` is false); report it.
   - Anything else, or `resumable: false`: report the error. Do not improvise the remaining steps.

## Rules

- **Do not do the steps by hand** when the procedure can run them. The scripts, the decisions
  and the routing are the procedure; your part is the tasks it hands you and the final report.
- **Scripts and decisions run on this machine.** Scripts read and write files relative to the
  directory `aip run` started in (or `--workdir`).
- **One run, one run id.** `aip resume <run_id>` works from any directory. Do not edit run
  files and do not start a second run of the same task. `aip runs` lists runs and
  `aip runs <run_id>` shows one step by step.
- **Report the result** from `result`, in the task's terms, and say which procedure ran.
- **Do not publish, pin or retire** anything unless asked; those change the catalog for everyone.
- **A task no one procedure covers** can go to the orchestrator, when the user wants it run
  unattended: `aip runah assist -i '{"task": "...", "outcome": ""}'` runs the procedures that fit
  one after another, builds one with `build_procedure` when none does, and ends with the answer or
  a question for the person in `result.note`. It needs runah's model (`aip config runah`), and
  `--budget-tokens N` bounds what it spends; every run it starts is listed under it in
  `aip runs <run_id>`.

## Write a procedure

To build a procedure from a description, run the procedure that does it:

```
aip run make_procedure --inputs '{"name": "policy_draft", "description": "<what it should do: inputs, steps, who does each, result>", "materials": ""}'
```

`materials` is a path to a file or folder of source material, or an empty string. The run hands
you a task to write the program folder (the prompt carries the language on one page), compiles
what you wrote, and hands the compiler's diagnostics back until it compiles; its result is the
folder's path. It only checks: your files stay as you wrote them. If `make_procedure` is not in the catalog (`aip list`), write the folder directly
with the same reference, `references/language.md` beside this file, and check it yourself.

Then, or when editing an existing `procedure.aip`:

```
aip compile --check <folder>      # every mistake with its line; exit 0 when it compiles
aip fmt <folder>                  # the canonical form
aip run <folder> --inputs ...     # try it; a folder runs as a draft
aip publish <folder>              # only when asked: name@revision in the catalog
```

Read `references/language.md` before writing or changing a procedure: the step kinds, the rules
the compiler enforces, loops, and what a prompt and a script are given.

## Example

Task: "A customer wrote: I was charged twice! Handle it."

```
$ aip search "customer charged twice billing"
billing_support_agent@1  score 0.812  Turn an inbound billing message into either a tier-2 ticket or a drafted reply. ...
$ aip run billing_support_agent --inputs '{"message": "I was charged twice!"}'
{ "paused": "task", "step": "triage",
  "tasks": [ { "index": 0, "prompt": "Read the customer's message and classify it. ...",
               "state": { "message": "I was charged twice!" }, "references": [],
               "answer_with": { "billing": "true_or_false", "tone": "choice" },
               "labels": { "tone": ["angry", "calm"] } } ],
  "hint": "answer with {\"billing\": true | false, \"tone\": \"angry\" | \"calm\"}; ...",
  "run_id": "4f1c9a2e7b3d5068" }
$ aip resume 4f1c9a2e7b3d5068 --answers '{"billing": true, "tone": "calm"}'
{ "paused": "task", "step": "reply",
  "tasks": [ { "index": 0, "prompt": "# Draft a reply ...", "answer_with": { "reply": "string" }, ... } ],
  "run_id": "4f1c9a2e7b3d5068" }
$ aip resume 4f1c9a2e7b3d5068 --answers '{"reply": "Thanks for flagging this; duplicate charges are refunded in full within 5 business days."}'
{ "done": true, "result": { "message": "I was charged twice!", "reply": "Thanks for flagging this; ..." },
  "run_id": "4f1c9a2e7b3d5068" }
```

You answered two tasks: one that asked you to classify the message under its `labels`, and one
that asked for the reply. The route between them was the procedure's: on `angry` it would have
run its own script to open a ticket, and no task would have asked you for a reply.
