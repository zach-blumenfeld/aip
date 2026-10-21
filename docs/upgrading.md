# Upgrading a 0.5a1 skill to 0.6a0

Format 0.6a1 (2026-10-19) is 0.6a0 with one more validator rule, `type_mismatch` (a consumed key carries its
producer's type), and a new heading on the runtime block. A 0.6a0 skill validates under 0.6a1 with one
`runtime_block_outdated` warning; to clear it, replace the runtime block with `aip-spec runtime` and set
`metadata.aip-version` to `"0.6a1"`. Nothing else changes. The rest of this page is the 0.5a1 to 0.6a0 upgrade.

Format 0.6a0 is breaking: the validator accepts 0.6a0 skills only, and a 0.5a1 skill fails with
one message that says what to change, ahead of the errors that name the steps:

```
$ aip-spec validate ./billing-support
{"kind": "runtime_block_outdated", "message": "0.5a1 skill: add outputs to each execution and client_task step, a requires block, and regenerate the runtime block (`aip-spec runtime` prints the 0.6a0 block; set `metadata.aip-version` to \"0.6a0\"). Format 0.6a0 does not accept 0.5a1 skills; any `missing_outputs` and `missing_requires` errors below name the steps to edit", ...}
{"kind": "missing_outputs", "message": "client_task `reply` declares no `outputs`; ...", "location": "body:$.steps[3]"}
{"kind": "missing_requires", "message": "the procedure runs scripts (`escalate`) but declares no `requires`; ...", "location": "body:$.requires"}
INVALID: 3 error(s) — see stderr
```

Nothing is wrong with the skill; it is written for the previous format. Three edits upgrade it.
The example throughout is `billing-support`, whose whole diff from 0.5a1 to 0.6a0 is below.

## 1. Declare `outputs` on each execution and client_task step

Every key a step adds to the state is now declared, like `inputs` (name, type, description).
Decisions need nothing: their outputs are their question names. Routers and the end step add no
keys; the end step's `inputs` are the procedure's result, the keys handed back at done.

The validator then checks the data flow, which 0.5a1 could not: every key a step reads is
produced on every path to it or declared on the start step (`unproduced_input`), and each key is
produced by exactly one step and is never a start input (`duplicate_producer`). Two follow-ons
in the step's files:

- **Scripts print exactly their `outputs`.** A 0.5a1 script often echoed keys it was given, so
  they passed through; now an undeclared key fails the step, and echoing a start input is a
  second producer. Scripts read `payload["state"]`, which holds only the step's declared
  `inputs` (`currentState`, with the same contents, is still sent for one more version).
- **Client-task templates ask for exactly the `outputs`.** The answer is checked against them.

## 2. Add a `requires` block if the skill has scripts

A top-level `requires` names what the machine running the scripts needs: the interpreter and its
minimum version, pip packages (optionally `name>=version`), and tools on the PATH. Scripts run on
the client now, next to the data, and the client checks this block before the first one runs,
stopping with `requires_unmet` and every missing item. A step may also set `command`, the
argument list that launches its script from the script's folder (default `python <script>`);
its first item must be the interpreter or a declared tool.

## 3. Regenerate the runtime block

Replace the body's runtime block with the output of `aip-spec runtime`, verbatim, and set
`metadata.aip-version` to `"0.6a0"`. The new block tells an agent running the skill by hand that
each step sees only its declared inputs and adds its declared outputs.

## The billing-support diff

The runtime block's text is elided; it is whatever `aip-spec runtime` prints.

```diff
--- a/billing-support/SKILL.md   (0.5a1)
+++ b/billing-support/SKILL.md   (0.6a0)
 metadata:
-  aip-version: "0.5a1"
+  aip-version: "0.6a0"
 ---
-# AIP runtime — format 0.5a1
+# AIP runtime — format 0.6a0
 ... (the rest of the block, regenerated)

 do_not_use_when:
   - The message is about product bugs or feature requests rather than billing.

+requires:
+  interpreter:
+    name: python
+    version: "3.10"
+
 steps:
   ...
   - name: escalate
     kind: execution
     ...
     script: scripts/escalate.py
     assets:
       - assets/config.json
+    outputs:
+      - name: ticket_id
+        type: integer
+        description: The tier-2 ticket opened for the message.
+      - name: queue
+        type: string
+        description: The queue the ticket was routed to.
     inputs_to: end

   - name: reply
     kind: client_task
     ...
     references:
       - path: references/help.md
         description: Escalation contacts and plan matrix. Only for plan changes, currency issues, or charges older than 30 days.
+    outputs:
+      - name: reply
+        type: string
+        description: The drafted reply to send the customer.
     inputs_to: end
```

```diff
--- a/billing-support/scripts/escalate.py
+++ b/billing-support/scripts/escalate.py
-stdin:  {"currentState": {"message": str, "tone": str, ...}, "assets": {"config": str}, "expects": {...}}
-stdout: {"message": str, "ticket_id": int, "queue": str}
+stdin:  {"state": {"message": str, "tone": str}, "assets": {"config": str}, "expects": {...}}
+stdout: {"ticket_id": int, "queue": str}
 ...
-state = payload["currentState"]
+state = payload["state"]
 ...
-json.dump({"message": state["message"], "ticket_id": ticket_id, "queue": config["queue"]}, sys.stdout)
+json.dump({"ticket_id": ticket_id, "queue": config["queue"]}, sys.stdout)
```

```diff
--- a/billing-support/assets/reply.md
+++ b/billing-support/assets/reply.md
-Return JSON with `message` (the original customer message) and `reply` (your reply text).
+Return JSON with `reply` (your reply text).
```

`message` stays in the result without either step returning it: it is a start input, the state
only grows, and `end` declares it. Then `aip-spec validate ./billing-support` passes, and
`aip run ./billing-support` runs it.

## What else changed for people running skills

Not edits to a skill, but visible after upgrading the runtime (`CHANGELOG.md` has the detail):

- `aip run` and `aip resume` print one JSON object per outcome, paused, done or error
  ([`cli-json.md`](cli-json.md)); a pause carries only the paused step's declared inputs.
- Run files live in `~/.aip/runs/<run-id>.json`; `aip resume <run-id>` works from any directory.
- On a served run the server holds the run's state and history and never runs a script or calls a
  decision model: the client runs every script and resolves every decision, and reports each with
  attribution ([`run-modes.md`](run-modes.md)). The server's `[decision_model]` table, the
  per-name threshold overrides, and `aip server --inspector` are gone; the decision-model key is
  `aip config --decision-model` on the client, and the UI is `npx aip-console`.
