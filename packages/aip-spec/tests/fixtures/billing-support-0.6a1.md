---
name: billing-support
description: Triage an inbound billing message with a structured decision model, escalate angry customers to tier 2 by script, and draft a policy-grounded reply for everyone else. Use when handling customer billing messages, refund requests, or duplicate charge complaints.
metadata:
  aip-version: "0.6a1"
---

# AIP runtime — format 0.6a1

You are executing an Agent Instruction Protocol (AIP) procedure: the fenced YAML block in this skill's `SKILL.md`. AIP is a protocol for cheaply, quickly, and accurately executing multi-step tasks as a graph of typed steps. You drive the run and execute every step yourself, following the semantics below.

Critical terminology:

- **Client**: you, the agent running this procedure; the `client_task` step kind is named for it. You supply each step's input, run its script, answer its questions by your own judgment, perform its task, follow its router, and make the final call at every step.
- **State**: the one JSON object a run carries. Each step declares the keys it reads as `inputs`; `execution` and `client_task` steps declare the keys they add as `outputs`, and a `decision` adds one key per question.
- **Step kinds**: `execution` runs a script, `decision` asks typed questions about the state, `client_task` hands work to you, `router` branches on a value in the state, `end` declares the procedure's result.

## Execution

The state starts as the start step's `inputs` and flows along `inputs_to`; each step adds its outputs to it. Every key is produced by exactly one step, so keys accumulate and nothing is overwritten. A step runs only if the state holds every key it declares in `inputs`, with the declared types; check that before each step. A step sees only those keys: give it its declared `inputs` and nothing else from the state. You have the final say at every step.

- **`execution`**: before the first one, check that this machine has everything `requires` names (the interpreter at its minimum version, the packages, the tools); if anything is missing, stop and name all of it. Run `script` from its folder, launched with the step's `command` when it has one and `python <script>` otherwise, with one JSON object on stdin, `{"state": <the step's inputs>, "assets": {<file stem>: <content>}, "expects": <the next step's inputs>}`. The script writes one JSON object to stdout holding exactly the step's `outputs`; add them to the state. A non-zero exit, or output missing a declared key, fails the step: stop there and report it rather than doing the step by hand.
- **`decision`**: answer each question from the step's inputs, and from the run so far only when the step sets `history: true`. Each answer collapses to one value under its question name and is added to the state: a noul to `true`/`false`, a choice to its label, a score to its level number. `thresholds` name the questions where an uncertain answer matters most; when your answer to one is a close call, reconsider it before continuing.
- **`client_task`**: render `template` with `{key}` from the step's inputs, `{assets[stem]}` for its assets, and `{meta.name}` for the skill name. Perform the task, loading `references` if their descriptions apply, and produce the step's `outputs`; add them to the state.
- **`router`**: read the state's `branch_on` key and continue at `branches[value]`. A value with no branch is an error.
- **`end`**: the state must hold `end`'s `inputs`. Those keys are the procedure's result.

```yaml
purpose: >
  Turn an inbound billing message into either a tier-2 ticket or a drafted reply.
  A structured decision classifies the message; a script opens the ticket; the agent
  drafts the reply against the refund policy.

trigger_when:
  - A customer message about a charge, invoice, refund, or subscription arrives.
  - Support asks to triage a billing complaint.

do_not_use_when:
  - The message is about product bugs or feature requests rather than billing.

requires:
  interpreter:
    name: python
    version: "3.10"

steps:
  - name: triage
    kind: decision
    description: Classify whether the message is about billing and how upset the customer is.
    inputs:
      - name: message
        type: string
        description: The customer's message, verbatim.
    questions:
      billing:
        type: noul
        instructions: Is this message about a charge, invoice, refund, or subscription payment?
      tone:
        type: choice
        instructions: How upset is the customer? Angry means explicit frustration, threats to cancel, or demands.
        criteria:
          angry: Frustrated, demanding, or threatening to leave.
          calm: Neutral or polite, asking a question.
    thresholds:
      billing: 0.15
      tone: 0.6
    inputs_to: by-tone

  - name: by-tone
    kind: router
    description: Angry customers go to a human queue; calm ones get a drafted reply.
    branch_on: tone
    branches:
      angry: escalate
      calm: reply

  - name: escalate
    kind: execution
    description: Open a tier-2 ticket for the message.
    inputs:
      - name: message
        type: string
      - name: tone
        type: string
    script: scripts/escalate.py
    assets:
      - assets/config.json
    outputs:
      - name: ticket_id
        type: integer
        description: The tier-2 ticket opened for the message.
      - name: queue
        type: string
        description: The queue the ticket was routed to.
    inputs_to: end

  - name: reply
    kind: client_task
    description: Draft a calm reply grounded in the refund policy.
    inputs:
      - name: message
        type: string
      - name: tone
        type: string
    template: assets/reply.md
    assets:
      - assets/policy.md
    references:
      - path: references/help.md
        description: Escalation contacts and plan matrix. Only for plan changes, currency issues, or charges older than 30 days.
    outputs:
      - name: reply
        type: string
        description: The drafted reply to send the customer.
    inputs_to: end

  - name: end
    kind: end
    description: The original message plus either a ticket or a drafted reply.
    inputs:
      - name: message
        type: string

anti_patterns:
  - Replying to an angry customer with a templated answer instead of escalating.
  - Promising a refund the policy does not cover.
```
