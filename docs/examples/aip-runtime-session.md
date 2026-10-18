# A fresh agent runs `billing-support` through `aip-runtime`

The fresh-agent check for the `aip-runtime` skill, re-recorded for the 0.6a0 release (milestone C1), where the
server holds the run and the client runs its scripts and resolves its decisions. It doubles as step 5 of the
README's walkthrough: the server is the walkthrough's, `aip server` over a local Neo4j with `billing-support`
published, and `aip` is the one `install.sh` put in `~/.local/bin`. A Claude Code session was started with
`claude -p` from an empty directory whose only skill was `aip-runtime` (written by `aip runtime --skill --out
.claude/skills`; `--setting-sources project` kept the user's own skills out). The server URL came from `aip
config`, not `AIP_SERVER`, and no decision-model key was configured, so the triage decision paused for the agent
to answer. The agent was given the README's first prompt and nothing else: no procedure, no SKILL.md, no mention
of AIP.

The transcript below is the session's stream-json output rendered as text; tool outputs are verbatim except that
the session's temporary directory is shown as `/tmp/session/`, the home directory as `~/`, and the machine's
name as `laptop.local` (`AIP_HOME` pointed at `/tmp/session/aiphome`, so the run file is there). The agent
completed the procedure through `search` → `info` → `run` → `resume`: it answered the decision pause itself
(billing, angry), the router sent the run to the escalation script, which `aip` ran on this machine, and the
agent read the ticket from the run's history on the server. It never fetched the procedure's SKILL.md.

One caveat from the same setup: the first attempt with the identical prompt did not load the skill at all. The
agent looked for billing tools, found none, and drafted a reply to the customer by hand (2 turns). The run below
is the second attempt. Whether a host agent picks up `aip-runtime` for a task that does not name AIP is up to
the agent; the skill's description is what it has to go on.

## Setup

```
$ aip server &                                   # ~/.config/aip/server.toml: the Neo4j backend
$ aip config --server http://localhost:8000
$ aip-spec example billing-support --out .
wrote billing-support
$ aip publish billing-support
billing-support@261db90f642343eb
$ mkdir -p /tmp/session/fresh && cd /tmp/session/fresh
$ aip runtime --skill --out .claude/skills
wrote .claude/skills/aip-runtime/SKILL.md
$ claude -p 'A customer wrote: "I was charged twice! Refund me today or I'"'"'m gone." Handle it.' \
    --setting-sources project --allowedTools Bash,Read,Write,Edit,Skill --output-format stream-json --verbose
```

## Transcript

**init** — model `claude-fable-5-1`, skills available: `aip-runtime` (plus Claude Code's built-in slash commands), cwd `fresh`

**assistant:**

I'll check the working directory for any customer or billing context first, then handle the complaint.

**tool: Bash** — List working directory and memory folder contents

```bash
ls -la /tmp/session/fresh 2>/dev/null; ls -la ~/.claude/projects/-tmp-session-fresh/memory/ 2>/dev/null
```

```
total 0
drwxr-xr-x@ 3 zach  wheel   96 Oct 18 13:38 .
drwxr-xr-x@ 6 zach  wheel  192 Oct 18 13:38 ..
drwxr-xr-x@ 3 zach  wheel   96 Oct 18 13:38 .claude
total 0
drwxr-xr-x@ 2 zach  staff   64 Oct 18 13:38 .
drwxr-xr-x@ 5 zach  staff  160 Oct 18 13:38 ..
```

**tool: Bash** — Show files in the project .claude folder and their contents

```bash
find /tmp/session/fresh/.claude -type f | head -50; echo "---"; find /tmp/session/fresh/.claude -type f -exec sh -c 'echo "== $1"; cat "$1"' _ {} \; 2>/dev/null | head -200
```

```
/tmp/session/fresh/.claude/skills/aip-runtime/SKILL.md
---
== /tmp/session/fresh/.claude/skills/aip-runtime/SKILL.md
---
name: aip-runtime
description: Run published AIP procedures (runbooks, step-by-step workflows) from an AIP server with the `aip` command. Use when a task might match a known procedure, runbook, or workflow, when the user mentions aip or AIP, or when AIP_SERVER is set; search the catalog first, then run the match and answer its pauses instead of doing the steps by hand.
license: Apache-2.0
metadata:
  aip-version: "0.6a0"
---

# Running AIP procedures

An AIP procedure is a graph of typed steps that `aip` and its server run: scripts, decisions,
routers, and tasks it hands back to you. You find the procedure, give it its start input,
and answer when it pauses. You never execute its steps yourself.

## Check once

```
aip --help          # the client is installed
aip config          # prints `server: <url>`; else set AIP_SERVER=http://host:port
                    # and `decision model: TypeSafe` or `none`
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
   | `decision`    | `questions` (`type`, `instructions`, `criteria`) and `state`: no decision model here | one key per question: `true`/`false` for `noul`, a `criteria` label for `choice`, the level number (list position from 0) for `score`; judge from `state` |
   | `review`      | `proposed_answers` from this machine's decision model, and `review`: the ones under their confidence threshold | only the keys you override, e.g. `{"tone": "calm"}`; `{}` accepts every proposed answer |
   | `client_task` | `task`: what to do; `state`; `references`; `answer_with` | the work product under every key in `answer_with`, with those types |

   `state` is only what this step needs. The run holds the rest (the server, for a published
   procedure) and your answer is merged over it, so send only the keys asked for. Load a `references` entry only if the
   task says you need it.

5. **On an error**, read `error`, `step` and `message`. `invalid_input` / `invalid_output`
   name the keys in `missing` and `invalid`: fix your input or answer and resume again (a
   bad answer leaves the pause in place). `script_failed` carries the script's `exit_code`
   and `stderr`; if `resumable` is true, `aip resume <run_id>` with no input retries that
   step once the cause is fixed. `requires_unmet` lists in `missing` what the machine running
   the scripts lacks; install it if you may, then retry the same way. Otherwise report the error.

## Rules

- **Do not do the steps by hand** when the procedure can run them. The scripts, routing,
  and validation are the procedure; your job is the pauses and the final result.
- **Scripts run here, on this machine,** for a published procedure too: `aip` fetches them
  from the server and runs them itself. Files they read and write are relative to the run's
  working directory, the directory `aip run` started in (or `--workdir`), kept for `resume`.
- **Decisions are resolved here too.** With a TypeSafe key on this machine (`TYPESAFE_API_KEY`,
  or `aip config --decision-model KEY`) `aip` asks the model and pauses only for a `review`;
  without one every decision pauses as `decision` for you to answer. Either way the run's
  history records who answered (`resolver`: `typesafe` or `manual`). Do not set a key unless asked.
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
$ aip run billing-support --input start.json
{ "paused": "decision", "step": "triage",
  "questions": { "billing": {"type": "noul", ...}, "tone": {"type": "choice", "criteria": {"angry": ..., "calm": ...}} },
  "state": { "message": "I was charged twice!" },
  "run_id": "4f1c9a2e7b3d5068", "run_file": "~/.aip/runs/4f1c9a2e7b3d5068.json" }
$ echo '{"billing": true, "tone": "angry"}' > answer.json
$ aip resume 4f1c9a2e7b3d5068 --input answer.json
{ "done": true, "run_id": "4f1c9a2e7b3d5068", "state": { "message": "I was charged twice!" }, "run_file": "..." }
```

The angry branch ran the procedure's script here and opened the ticket (its `ticket_id` is in
the run's history); you answered one pause. The calm branch would instead pause with
`client_task` asking you to draft the reply, and your `{"reply": "..."}` would end the run.
```

**assistant:**

This task matches the project's AIP runtime skill, which has a billing procedure for exactly this case. Loading it and checking the client.

**tool: Skill**

```json
{
  "skill": "aip-runtime"
}
```

```
Launching skill: aip-runtime
```

**tool: Bash** — Check that the aip client is installed and configured

```bash
which aip && aip --help 2>&1 | head -20; echo "--- config"; aip config 2>&1; echo "--- env"; echo "AIP_SERVER=$AIP_SERVER"
```

```
~/.local/bin/aip
usage: aip <command> [args]
       aip --version

commands:
  validate
  schema
  runtime
  skill
  info
  run
  resume
  search
  list
  publish
  get
  pin
  retire
  runs
  governance
  config
--- config
server: http://localhost:8000  (from ~/.config/aip/config.json)
token:  none
decision model: none; every decision pauses for you to answer (`aip config --decision-model KEY`)
--- env
AIP_SERVER=
```

**tool: Bash** — Search the AIP catalog for a billing procedure

```bash
aip search "customer charged twice billing refund" 2>&1; echo "--- list"; aip list 2>&1
```

```
billing-support@261db90f642343eb  1.536  Triage an inbound billing message with a structured decision model, escalate angry customers to tier 2 by script, and draft a policy-grounded reply for everyone else. Use when handling customer billing messages, refund requests, or duplicate charge complaints.
--- list
billing-support  261db90f642343eb  1 revision(s)  Triage an inbound billing message with a structured decision model, escalate angry customers to tier 2 by script, and draft a policy-grounded reply for everyone else. Use when handling customer billing messages, refund requests, or duplicate charge complaints.
```

**assistant:**

The catalog has a matching procedure, billing-support. Inspecting it and its example input together.

**tool: Bash** — Show the billing-support procedure's purpose, inputs, and steps

```bash
aip info billing-support 2>&1
```

```
billing-support  (AIP 0.6a0)

Triage an inbound billing message with a structured decision model, escalate angry customers to tier 2 by script, and draft a policy-grounded reply for everyone else. Use when handling customer billing messages, refund requests, or duplicate charge complaints.

PURPOSE
  Turn an inbound billing message into either a tier-2 ticket or a drafted reply. A structured decision classifies the message; a script opens the ticket; the agent drafts the reply against the refund policy.

TRIGGER WHEN
  - A customer message about a charge, invoice, refund, or subscription arrives.
  - Support asks to triage a billing complaint.
DO NOT USE WHEN
  - The message is about product bugs or feature requests rather than billing.

START INPUT  (step `triage`, decision)
  message  string    The customer's message, verbatim.

  example start.json:
  {"message": "<string>"}

  run:  aip run billing-support --input start.json

STEPS
  triage  [decision]  -> by-tone
      Classify whether the message is about billing and how upset the customer is.
      ? billing [noul]  (threshold 0.15): Is this message about a charge, invoice, refund, or subscription payment?
      ? tone [choice]  (threshold 0.6): How upset is the customer? Angry means explicit frustration, threats to cancel, or demands.
  by-tone  [router on `tone`]  angry -> escalate, calm -> reply
      Angry customers go to a human queue; calm ones get a drafted reply.
  escalate  [execution]  -> end
      Open a tier-2 ticket for the message.
      script: scripts/escalate.py  assets: assets/config.json
  reply  [client_task]  -> end
      Draft a calm reply grounded in the refund policy.
      template: assets/reply.md  assets: assets/policy.md
      reference: references/help.md  (Escalation contacts and plan matrix. Only for plan changes, currency issues, or charges older than 30 days.)
  end  [end]
      The original message plus either a ticket or a drafted reply.

RESULT  (end state)
  message  string

ANTI-PATTERNS
  - Replying to an angry customer with a templated answer instead of escalating.
  - Promising a refund the policy does not cover.
```

**tool: Bash** — Save the procedure's example start input to a working folder

```bash
mkdir -p /tmp/session/fresh/aip-work && cd /tmp/session/fresh/aip-work && aip info billing-support --example-input 2>&1 | tee start.json
```

```
{
  "message": "<string>"
}
```

**tool: Write**

```json
{
  "file_path": "/tmp/session/fresh/aip-work/start.json",
  "content": "{\n  \"message\": \"I was charged twice! Refund me today or I'm gone.\"\n}\n"
}
```

```
The file /tmp/session/fresh/aip-work/start.json has been updated successfully. (file state is current in your context — no need to Read it back)
```

**tool: Bash** — Start the billing-support procedure with the customer's message

```bash
aip run billing-support --input start.json 2>&1
```

```
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
    "message": "I was charged twice! Refund me today or I'm gone."
  },
  "run_id": "20d9b68010614e71",
  "run_file": "/tmp/session/aiphome/runs/20d9b68010614e71.json"
}
```

**assistant:**

The run paused at triage. The message is clearly about a charge and refund, and it demands same-day action with a threat to leave, so it is billing and angry.

**tool: Write**

```json
{
  "file_path": "/tmp/session/fresh/aip-work/answer.json",
  "content": "{\n  \"billing\": true,\n  \"tone\": \"angry\"\n}\n"
}
```

```
File created successfully at: /tmp/session/fresh/aip-work/answer.json (file state is current in your context — no need to Read it back)
```

**tool: Bash** — Resume the run with the triage answers

```bash
aip resume 20d9b68010614e71 --input answer.json 2>&1
```

```
{
  "done": true,
  "run_id": "20d9b68010614e71",
  "state": {
    "message": "I was charged twice! Refund me today or I'm gone."
  },
  "run_file": "/tmp/session/aiphome/runs/20d9b68010614e71.json"
}
```

**assistant:**

The run finished on the escalation branch. Pulling the run history from the server to get the ticket ID.

**tool: Bash** — Fetch the run's history from the AIP server

```bash
curl -s http://localhost:8000/runs/20d9b68010614e71 2>&1 | head -c 4000
```

```
{"run_id":"20d9b68010614e71","name":"billing-support","revision":"261db90f642343eb","status":"done","started_at":"2026-10-18T20:39:22.594637Z","updated_at":"2026-10-18T20:39:26.604563Z","version":5,"after":"end","pause":{"kind":"done","state":{"message":"I was charged twice! Refund me today or I'm gone."}},"state":{"message":"I was charged twice! Refund me today or I'm gone."},"history":[{"attribution":{"confidence":null,"model":null,"resolver":"manual","reviewed":false},"input":{"message":"I was charged twice! Refund me today or I'm gone."},"kind":"decision","result":{"answers":{"billing":true,"tone":"angry"}},"step":"triage"},{"input":{"tone":"angry"},"kind":"router","result":{"to":"escalate"},"step":"by-tone"},{"host":"laptop.local","input":{"message":"I was charged twice! Refund me today or I'm gone.","tone":"angry"},"kind":"execution","result":{"queue":"tier2","ticket_id":19084},"seconds":0.013,"step":"escalate"},{"input":{"message":"I was charged twice! Refund me today or I'm gone."},"kind":"end","result":{"message":"I was charged twice! Refund me today or I'm gone."},"step":"end"}]}
```

**tool: Bash** — Show the run's recorded history via the aip client

```bash
aip runs 20d9b68010614e71 2>&1 | head -80 || aip runs 2>&1 | head -40
```

```
{
  "run_id": "20d9b68010614e71",
  "name": "billing-support",
  "revision": "261db90f642343eb",
  "status": "done",
  "started_at": "2026-10-18T20:39:22.594637Z",
  "updated_at": "2026-10-18T20:39:26.604563Z",
  "version": 5,
  "after": "end",
  "pause": {
    "kind": "done",
    "state": {
      "message": "I was charged twice! Refund me today or I'm gone."
    }
  },
  "state": {
    "message": "I was charged twice! Refund me today or I'm gone."
  },
  "history": [
    {
      "attribution": {
        "confidence": null,
        "model": null,
        "resolver": "manual",
        "reviewed": false
      },
      "input": {
        "message": "I was charged twice! Refund me today or I'm gone."
      },
      "kind": "decision",
      "result": {
        "answers": {
          "billing": true,
          "tone": "angry"
        }
      },
      "step": "triage"
    },
    {
      "input": {
        "tone": "angry"
      },
      "kind": "router",
      "result": {
        "to": "escalate"
      },
      "step": "by-tone"
    },
    {
      "host": "laptop.local",
      "input": {
        "message": "I was charged twice! Refund me today or I'm gone.",
        "tone": "angry"
      },
      "kind": "execution",
      "result": {
        "queue": "tier2",
        "ticket_id": 19084
      },
      "seconds": 0.013,
      "step": "escalate"
    },
    {
      "input": {
        "message": "I was charged twice! Refund me today or I'm gone."
      },
      "kind": "end",
      "result": {
        "message": "I was charged twice! Refund me today or I'm gone."
      },
      "step": "end"
    }
  ]
}
```

**assistant:**

The complaint has been escalated to the tier 2 human queue. I ran the catalog's billing-support procedure rather than replying by hand, and it routed the message to escalation.

**What happened**

- The procedure's triage step paused and asked me to classify the message. I answered that it is a billing matter and that the tone is angry, since the customer demands a same-day refund and threatens to leave.
- The router sent the angry branch to the escalation script, which opened a ticket. No reply was drafted. The procedure explicitly treats sending a templated answer to an angry customer as an anti-pattern.

| Item | Value |
|---|---|
| Procedure | billing-support, revision 261db90f642343eb |
| Run ID | 20d9b68010614e71 |
| Queue | tier2 |
| Ticket ID | 19084 |

**What's next**

The customer has not been answered yet. A tier 2 agent needs to pick up ticket 19084, verify the duplicate charge, and issue the refund. Given the "today" demand, that ticket should be worked promptly. If you want me to also send a short holding note to the customer acknowledging the escalation, I can draft one, but Gmail is not authorized in this session, so sending it would need to go through your connector settings first.

**result** — success, 15 turns, 49s
