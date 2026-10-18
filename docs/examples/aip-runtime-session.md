# A fresh agent runs `billing-support` through `aip-runtime`

The fresh-agent check for the `aip-runtime` skill, re-recorded for format 0.6a0 (milestone A3), whose pauses carry only the paused step's declared inputs and whose outcomes are the JSON objects in [`docs/cli-json.md`](../cli-json.md). A Claude Code session was started with `claude -p` from an empty directory whose only skill was `aip-runtime` (written by `aip runtime --skill --out .claude/skills`; `--setting-sources project` kept the user's own skills out). `AIP_SERVER` pointed at a filesystem-backed `aip server` on port 8765 with the `billing-support` example from aip-spec published; the server read a TypeSafe key from its config, so the triage decision was answered by the model. The agent was given the task in plain words and nothing else: no procedure, no SKILL.md, no mention of AIP.

The transcript below is the session's stream-json output rendered as text; tool outputs are verbatim except that the session's temporary directory is shown as `/tmp/session/` and the home directory as `~/`. The agent completed the procedure through `search` → `info` → `run` → `resume`: the model's `tone` answer fell under its threshold, so the run paused for `review`, the agent accepted the proposed answers with `{}`, and the angry branch's script opened the ticket, which the agent read from the run file's `history`. It never fetched the procedure's own SKILL.md: the only `/files/SKILL.md` request in the server log is `aip info` rendering its summary.

## Setup

```
$ aip server --backend filesystem --root ./root --port 8765 &
$ export AIP_SERVER=http://localhost:8765
$ aip-spec example billing-support --out .
wrote billing-support
$ aip publish billing-support
billing-support@b22b55b4afd37eb1
$ mkdir fresh && cd fresh
$ aip runtime --skill --out .claude/skills
wrote .claude/skills/aip-runtime/SKILL.md
$ claude -p 'A customer wrote in: "I was charged twice!" Handle this billing message for me.' \
    --setting-sources project --allowedTools Bash,Read,Write,Edit,Skill --output-format stream-json --verbose
```

## Transcript

**init** — model `claude-fable-5-1`, skills available: `aip-runtime` (plus Claude Code's built-in slash commands), cwd `fresh`

**assistant:**

I'll check the working directory for any billing tooling or customer context before drafting a response.

**tool: Bash** — List files in working directory

```bash
ls -la /tmp/session/fresh
```

```
total 0
drwxr-xr-x@ 3 zach  wheel   96 Oct 18 12:01 .
drwx------@ 8 zach  wheel  256 Oct 18 12:01 ..
drwxr-xr-x@ 3 zach  wheel   96 Oct 18 12:01 .claude
```

**tool: Bash** — List and preview files under the .claude directory

```bash
find /tmp/session/fresh/.claude -type f | head -50; echo "---"; find /tmp/session/fresh/.claude -type f -name "*.md" -exec sh -c 'echo "== $1"; head -40 "$1"' _ {} \;
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

**assistant:**

The project has an AIP runbook skill, and a double-charge complaint is a classic procedure. I'll load the skill and check whether an AIP server is reachable.

**tool: Skill**

```json
{
  "skill": "aip-runtime"
}
```

```
Launching skill: aip-runtime
```

**tool: Bash** — Check whether the aip client and server are configured

```bash
which aip && aip config; echo "AIP_SERVER=$AIP_SERVER"
```

```
~/dev/aip/.venv/bin/aip
server: http://localhost:8765  (from AIP_SERVER)
token:  none
AIP_SERVER=http://localhost:8765
```

**tool: Bash** — Search the AIP catalog for a billing procedure

```bash
aip search "customer charged twice billing"
```

```
billing-support@b22b55b4afd37eb1  7.552  Triage an inbound billing message with a structured decision model, escalate angry customers to tier 2 by script, and draft a policy-grounded reply for everyone else. Use when handling customer billing messages, refund requests, or duplicate charge complaints.
```

**tool: Bash** — Inspect the billing-support procedure and its example input

```bash
aip info billing-support && echo "=== EXAMPLE INPUT ===" && aip info billing-support --example-input
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
=== EXAMPLE INPUT ===
{
  "message": "<string>"
}
```

**assistant:**

The billing-support procedure matches exactly. I'll start the run with the customer's message verbatim.

**tool: Bash** — Start the billing-support procedure with the customer's message

```bash
mkdir -p /tmp/session/aip-work && printf '%s' '{"message": "I was charged twice!"}' > /tmp/session/aip-work/start.json && aip run billing-support --input /tmp/session/aip-work/start.json
```

```
{
  "paused": "review",
  "step": "triage",
  "state": {
    "message": "I was charged twice!"
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
        "angry": 0.79,
        "calm": 0.21
      },
      "reason": "confidence below 0.6"
    }
  ],
  "run_id": "4c39c99ffbd94c76",
  "run_file": ".aip/runs/billing-support-1792350105.json"
}
```

**tool: Bash** — Accept the proposed triage answers and resume the run

```bash
printf '%s' '{}' > /tmp/session/aip-work/answer.json && aip resume .aip/runs/billing-support-1792350105.json --input /tmp/session/aip-work/answer.json
```

```
{
  "done": true,
  "run_id": "4c39c99ffbd94c76",
  "state": {
    "message": "I was charged twice!"
  },
  "run_file": ".aip/runs/billing-support-1792350105.json"
}
```

**tool: Bash** — Read the run history to find the ticket details

```bash
python3 -I -c "
import json
r = json.load(open('.aip/runs/billing-support-1792350105.json'))
print(json.dumps(r.get('history', r), indent=2))
"
```

```
[
  {
    "step": "triage",
    "kind": "decision",
    "input": {
      "message": "I was charged twice!"
    },
    "result": {
      "model": "jev-1.13.0",
      "usage": {
        "input_tokens": 376,
        "output_tokens": 50
      },
      "answers": {
        "billing": {
          "type": "noul",
          "noul": 0.98
        },
        "tone": {
          "type": "choice",
          "choice": "angry",
          "confidence": 0.58,
          "probabilities": {
            "angry": 0.79,
            "calm": 0.21
          }
        }
      }
    }
  },
  {
    "step": "by-tone",
    "kind": "router",
    "input": {
      "tone": "angry"
    },
    "result": {
      "to": "escalate"
    }
  },
  {
    "step": "escalate",
    "kind": "execution",
    "input": {
      "message": "I was charged twice!",
      "tone": "angry"
    },
    "result": {
      "ticket_id": 82237,
      "queue": "tier2"
    },
    "seconds": 0.016
  },
  {
    "step": "end",
    "kind": "end",
    "input": {
      "message": "I was charged twice!"
    },
    "result": {
      "message": "I was charged twice!"
    }
  }
]
```

**assistant:**

The message has been handled: the billing-support procedure escalated it to a tier-2 human ticket.

Ticket 82237, queue tier2

**What happened.** I ran the published `billing-support` AIP procedure with the customer's message verbatim. Its triage step classified the message as billing-related and leaned toward an angry tone, but flagged the tone call for review because confidence fell just under the threshold. The procedure's criteria count explicit frustration as angry, and a double-charge complaint with an exclamation fits that. I accepted the classification, and the procedure routed the message to its escalation script, which opened the ticket above.

**Why escalation rather than a drafted reply.** The procedure's own rule is that angry customers go to a human queue instead of getting a templated answer. That is also the safer outcome here, since I have no access to the billing ledger and could not have verified whether a duplicate charge actually occurred.

**What to do next.** A tier-2 agent should pull the customer's recent charges, confirm whether two captures posted, and reverse the duplicate if so. No reply has been sent to the customer yet. If you would rather I draft one now, tell me and I will write it against the refund policy.

**result** — success, 11 turns, 34s

