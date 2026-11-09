# Upgrading

## 0.6a1 to 0.8

Format `0.8` (release 0.8.0, 2026-11-03) is breaking: a skill written for `0.6a1` no longer
loads. Upgrade the install first, then each skill with one command.

```bash
curl -sSfL https://raw.githubusercontent.com/zach-blumenfeld/aip/main/install.sh | bash   # or: uv tool install --force aip-spec agent-instruction-protocol
aip --version                                           # aip 0.8.0 format 0.8
aip upgrade ./billing-support                           # or: aip-spec upgrade ./billing-support
```

Four things changed in the format; the first three are mechanical and `aip upgrade` does them,
the fourth is a decision only the author can take.

1. **The start step is explicit.** A step of `kind: start` holds the procedure's `inputs` and
   points at the first runnable step. Before, the first step was the start and its `inputs` were
   the procedure's. The upgrade inserts a `start` step before the old first step, carrying its
   inputs and pointing at it; the old step keeps its `inputs`, now consumed from the state.
2. **`thresholds` are gone.** A decision no longer flags an uncertain answer for review, and the
   `review` pause is gone with it. Instead a decision can list questions under `confidence`, and a
   model's answer then writes `<question>_confidence` into the state (`[0, 1]`); a router can check
   that key before it branches, `confidence: {key, below, to}`, and send a low or absent one where
   the author wants it. The upgrade drops every `thresholds` block. It does not add the list and
   the check: where the skill relied on review, add them by hand, and `aip-spec validate` then
   says whether the route is measured.
3. **Decisions opt in to being answered by hand.** `fallback: true` on a decision lets a client
   with no decision model answer the questions itself; the default is `false`, and a run with no
   model then stops at the decision with `no_decision_model`. A 0.6a1 run could always be answered
   by hand, so the upgrade sets `fallback: true` on every decision and keeps that behaviour. Set
   it back to `false` wherever a decision model is required: a decision answered by hand writes no
   confidence, and a router fed by it is an unmeasured route, which the validator warns about.
4. **Keys may be overwritten.** The one-producer rule is gone: a later step may produce a key an
   earlier one produced, or a start input, and the value is overwritten. Nothing in a 0.6a1 skill
   needs to change for this; the validator now says `duplicate_producer` as information, and a
   script that echoed a start input is no longer an error.

The runtime block is replaced and `metadata.aip-version` set to `"0.8"`. The rewrite is line
edits, so comments and layout survive. The command prints each change and what it left by
hand, writes the skill, and validates it: exit 0 when valid, 1 when the validator still names
something, 2 (nothing written) on a layout the edits cannot follow. `--check` reports and writes
nothing. On the 0.6a1 `billing-support`:

```
$ aip upgrade billing-support
billing-support/SKILL.md: 0.6a1 -> 0.8
  replaced the 0.6a1 runtime block with the 0.8 block
  set `metadata.aip-version` to "0.8"
  inserted a `start` step named `start` before `triage`, carrying its 1 input and pointing at it
  `triage`: dropped `thresholds` (billing: 0.15, tone: 0.6)
  `triage`: set `fallback: true`
by hand:
  `triage` reviewed its answers below those thresholds; if the skill relied on that, add `confidence: [billing, tone]` to the decision and a `confidence: {key: <question>_confidence, below: <bound>, to: <step>}` check to the router that branches on its answer
  every decision now says `fallback: true`, as a run in the earlier format could always be answered by hand; set `fallback: false` where a decision model is required
wrote billing-support/SKILL.md; VALID (name: billing-support) (1 warning(s) — see stderr)
```

The warning on stderr is `unmeasured_route`: `by-tone` branches on `tone`, which a client may
have chosen by hand. The diff the upgrade wrote, with the runtime block elided:

```diff
--- a/billing-support/SKILL.md   (0.6a1)
+++ b/billing-support/SKILL.md   (0.8)
 metadata:
-  aip-version: "0.6a1"
+  aip-version: "0.8"
 ---
-# AIP runtime — format 0.6a1
+# AIP runtime — format 0.8
 ... (the rest of the block, regenerated)

 steps:
+  - name: start
+    kind: start
+    inputs:
+      - name: message
+        type: string
+        description: The customer's message, verbatim.
+    inputs_to: triage
+
   - name: triage
     kind: decision
     ...
-    thresholds:
-      billing: 0.15
-      tone: 0.6
+    fallback: true
     inputs_to: by-tone
```

The shipped example goes one step further by hand, which is what step 2 above asks for: `triage`
names `tone` in a `confidence` list and `by-tone` checks it, `confidence: {key: tone_confidence,
below: 0.6, to: escalate}`, so a message the model is unsure about is escalated rather than
replied to. It keeps `fallback: true` so the quickstart runs without a TypeSafe key, and says in a
comment that a production skill turns it off; the validator therefore warns
`confidence_on_unmeasured_source` on it, and a run answered by hand is escalated whatever tone was
given, because a manual answer writes no confidence.

A skill that was never upgraded past `0.5a1` or `0.6a0` takes the same command; for `0.5a1` it
also names the `outputs` and `requires` to add by hand (the next sections).

What else changed for people running skills, visible after upgrading the runtime
(`CHANGELOG.md` has the detail): the `review` pause no longer exists, so a client with a key is
never asked to confirm an answer; a decision pause carries `confidence` and `fallback` where it
carried `thresholds`; a run with no key stops with `no_decision_model` at a decision that does not
allow `fallback`; a router's history entry says whether its check fired and why (`low`, `absent`);
the `overridden-decisions` governance query is replaced by `confidence-fired` and
`unmeasured-routes`; and the console's `0.8.0` follows the same changes (it needs `aip` 0.8.0).

## 0.6a1 to 0.7.0

In 0.7.0 the packages come from PyPI instead of git, and the authoring skill is named `aip-compile`
instead of `aip`; the format stays `0.6a1`, so a skill that validates today validates unchanged.
Re-run the one-line installer, which does everything below, or do it by hand:

```bash
curl -sSfL https://raw.githubusercontent.com/zach-blumenfeld/aip/main/install.sh | bash
```

```bash
uv tool uninstall aip                                  # the pre-0.7.0 install, if present
uv tool install --force aip-spec agent-instruction-protocol
aip skill install                                      # refreshes aip-runtime, adds aip-compile
aip skill prune                                        # removes the old `aip` skill folder
```

The first line removes the git-installed `aip` tool (the distribution is `agent-instruction-protocol` now; the command is still `aip`); the second installs both packages from PyPI; `aip skill install` writes `aip-compile` and `aip-runtime` into every agent it detects, refreshing `aip-runtime` in place; `aip skill prune` removes only retired skill names (today the authoring skill's old `aip/` folder), so `aip-runtime` is refreshed by `install`, never removed by `prune`. Both are safe to re-run. `aip skill list` shows the result per agent. Authored skills need no change in 0.7.0.
Afterwards `aip --version` prints `aip 0.7.0 format 0.6a1`.

If you pinned a git URL yourself, in a `pyproject.toml`, a requirements file, or a `uv tool
install` line, change it to the PyPI names. The format package was its own repository,
[zach-blumenfeld/aip-spec](https://github.com/zach-blumenfeld/aip-spec), now archived; it lives at
`packages/aip-spec/` in this one, and the runtime's distribution is `agent-instruction-protocol`
(the module and command are still `aip`):

```text
aip-spec @ git+https://github.com/zach-blumenfeld/aip-spec.git@v0.6a1     ->  aip-spec==0.7.0
aip[server] @ git+https://github.com/zach-blumenfeld/aip.git@v0.6a1        ->  agent-instruction-protocol[server]==0.7.0
```

## 0.5a1 to 0.6a0

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
