---
name: meeting-notes
description: Summarize a meeting transcript and list its action items.
metadata:
  aip-version: "0.8"
---

# AIP runtime — format 0.8

You are executing an Agent Instruction Protocol (AIP) procedure: the fenced YAML block in this skill's `SKILL.md`. AIP is a protocol for cheaply, quickly, and accurately executing multi-step tasks as a graph of typed steps. You drive the run and execute every step yourself, following the semantics below.

Critical terminology:

- **Client**: you, the agent running this procedure; the `client_task` step kind is named for it. You supply the start step's input, run each script, answer questions by your own judgment where the step allows it, perform each task, follow each router, and make the final call at every step.
- **State**: the one JSON object a run carries. Each step declares the keys it reads as `inputs`; `execution` and `client_task` steps declare the keys they add as `outputs`, and a `decision` adds one key per question, plus a `<question>_confidence` number for each question its `confidence` list names.
- **Step kinds**: `start` holds the procedure's inputs, `execution` runs a script, `decision` asks typed questions about the state, `client_task` hands work to you, `router` branches on a value in the state, `end` declares the procedure's result.

## Execution

The state starts as the `start` step's `inputs`, which you supply, and flows along `inputs_to`; each step adds its outputs to it. Keys accumulate, and a later step may overwrite one. A step runs only if the state holds every key it declares in `inputs`, with the declared types; check that before each step. A step sees only those keys: give it its declared `inputs` and nothing else from the state. You have the final say at every step.

- **`start`**: the state begins as this step's `inputs`, with the declared types. Continue at `inputs_to`.
- **`execution`**: before the first one, check that this machine has everything `requires` names (the interpreter at its minimum version, the packages, the tools); if anything is missing, stop and name all of it. Run `script` from its folder, launched with the step's `command` when it has one and `python <script>` otherwise, with one JSON object on stdin, `{"state": <the step's inputs>, "assets": {<file stem>: <content>}, "expects": <the next step's inputs>}`. The script writes one JSON object to stdout holding exactly the step's `outputs`; add them to the state. A non-zero exit, or output missing a declared key, fails the step: stop there and report it rather than doing the step by hand.
- **`decision`**: answer each question from the step's inputs, and from the run so far only when the step sets `history: true`. Each answer collapses to one value under its question name and is added to the state: a noul to `true`/`false`, a choice to its label, a score to its level number. For each question the step's `confidence` list names, a decision model also adds `<question>_confidence`, the probability it put on its answer, in `[0, 1]`; an answer given by your own judgment adds no confidence key. You may answer by your own judgment only when the step sets `fallback: true`; otherwise the step needs a decision model, and without one you stop there and say so.
- **`client_task`**: render `template` with `{key}` from the step's inputs, `{assets[stem]}` for its assets, and `{meta.name}` for the skill name. Perform the task, loading `references` if their descriptions apply, and produce the step's `outputs`; add them to the state.
- **`router`**: when the step has a `confidence` check, read the state's `confidence.key` first: if it is absent, null, or below `confidence.below`, continue at `confidence.to`. Otherwise read the state's `branch_on` key and continue at `branches[value]`. A value with no branch is an error.
- **`end`**: the state must hold `end`'s `inputs`. Those keys are the procedure's result.

```yaml
purpose: ""

trigger_when:
  - A meeting transcript needs a summary and action items.

steps:
  - name: start
    kind: start
    inputs:
      - name: transcript
        type: string
    inputs_to: clean

  - name: clean
    kind: execution
    description: Strip timestamps and filler words from the transcript.
    inputs:
      - name: transcript
        type: string
    script: scripts/clean.py
    inputs_to: summarize

  - name: summarize
    kind: client_task
    description: Write the summary and pull out the action items.
    inputs:
      - name: clean_transcript
        type: string
    template: assets/summarize.md
    outputs:
      - name: summary
        type: string
      - name: action_items
        type: list[*]
    inputs_to: end

  - name: end
    kind: end
    inputs:
      - name: summary
        type: string
      - name: action_items
        type: list[*]
```
