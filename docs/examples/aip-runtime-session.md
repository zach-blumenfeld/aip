# A fresh agent runs `billing-support` through `aip-runtime`

The M5 fresh-agent check (`docs/PLAN.md`). A Claude Code session was started with `claude -p` from an empty directory whose only skill was `aip-runtime` (written by `aip runtime --skill --out .claude/skills`; `--setting-sources project` kept the user's own skills out). `AIP_SERVER` pointed at a filesystem-backed `aip server` on port 8765 with `examples/billing-support` published. The agent was given the task in plain words and nothing else: no procedure, no SKILL.md, no mention of AIP.

The transcript below is the session's stream-json output rendered as text; tool outputs are verbatim. The agent completed the procedure through `search` → `info` → `run` → `resume` and never fetched or read the procedure's own SKILL.md: the only `/files/SKILL.md` request in the server log is `aip info` rendering its summary, and the agent's turns contain no `aip get`, no `curl`, and no file reads.

## Setup

```
$ aip server --backend filesystem --root ./root --port 8765 &
$ export AIP_SERVER=http://localhost:8765
$ aip publish examples/billing-support
billing-support@124d4a7b6208abed
$ mkdir fresh && cd fresh
$ aip runtime --skill --out .claude/skills
wrote .claude/skills/aip-runtime/SKILL.md
$ claude -p 'A customer wrote in: "I was charged twice!" Handle this billing message for me.' \
    --setting-sources project --allowedTools Bash,Read,Write,Edit,Skill --output-format stream-json --verbose
```

## Transcript

**init** — model `claude-opus-5-5`, skills available: `aip-runtime` (plus Claude Code's built-in slash commands), cwd `fresh`

**tool: Skill**

```json
{
  "skill": "aip-runtime",
  "args": "Customer billing message: \"I was charged twice!\" \u2014 find and run a matching procedure"
}
```

```
Launching skill: aip-runtime
```

**tool: Bash** — Check AIP server and search catalog

```bash
aip config && aip search "customer charged twice billing"
```

```
server: http://localhost:8765  (from AIP_SERVER)
token:  none
billing-support@124d4a7b6208abed  20.000  Triage an inbound billing message with a structured decision model, escalate angry customers to tier 2 by script, and draft a policy-grounded reply for everyone else. Use when handling customer billing messages, refund requests, or duplicate charge complaints.
```

**tool: Bash** — Inspect billing-support procedure

```bash
aip info billing-support && aip info billing-support --example-input
```

```
billing-support  (AIP 0.5a0)

Triage an inbound billing message with a structured decision model, escalate angry customers to tier 2 by script, and draft a policy-grounded reply for everyone else. Use when handling customer billing messages, refund requests, or duplicate charge complaints.

PURPOSE
  Turn an inbound billing message into either a tier-2 ticket or a drafted reply. A structured decision model classifies the message; the client confirms low-confidence calls; a script opens the ticket; the client drafts the reply against the refund policy.

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
{
  "message": "<string>"
}
```

**tool: Bash** — Run billing-support procedure

```bash
echo '{"message": "I was charged twice!"}' > start.json && aip run billing-support --input start.json; echo "exit=$?"
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
  "expects": {
    "message": "string"
  },
  "suggested": {
    "message": "I was charged twice!"
  },
  "resume": "aip resume .aip/runs/billing-support-1791094558.json --input <answer.json>",
  "run_file": ".aip/runs/billing-support-1791094558.json"
}
exit=3
```

**tool: Bash** — Answer triage pause and resume run

```bash
echo '{"billing": true, "tone": "angry"}' > answer.json && aip resume .aip/runs/billing-support-1791094558.json --input answer.json; echo "exit=$?"
```

```
{
  "done": true,
  "state": {
    "message": "I was charged twice!",
    "billing": true,
    "tone": "angry",
    "ticket_id": 68875,
    "queue": "tier2"
  },
  "history": [
    {
      "step": "triage",
      "kind": "decision",
      "input": {
        "message": "I was charged twice!"
      },
      "result": {
        "answers": {
          "billing": {
            "type": "noul",
            "manual": true
          },
          "tone": {
            "type": "choice",
            "manual": "angry"
          }
        }
      },
      "manual": true
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
        "billing": true,
        "tone": "angry"
      },
      "result": {
        "message": "I was charged twice!",
        "ticket_id": 68875,
        "queue": "tier2"
      }
    },
    {
      "step": "end",
      "kind": "end",
      "input": {
        "message": "I was charged twice!",
        "billing": true,
        "tone": "angry",
        "ticket_id": 68875,
        "queue": "tier2"
      },
      "result": {
        "message": "I was charged twice!",
        "billing": true,
        "tone": "angry",
        "ticket_id": 68875,
        "queue": "tier2"
      }
    }
  ]
}
exit=0
```

**assistant:**

I escalated the message to a human: it's now **ticket #68875 in the tier-2 queue**. I used the `billing-support` procedure from your AIP server.

The procedure asked me two questions about the message:
- **Is it about billing?** Yes, it's a duplicate charge.
- **Tone: angry or calm?** I picked **angry**, and that choice is what sent it to a person. The message is short and has no threats or demands, so it was a close call. But it's an exclamation-mark complaint about money, not a neutral question. The procedure also warns against sending a templated reply to an upset customer, so a human seemed safer.

If you'd rather treat it as calm, I can rerun it. That path drafts a reply to the customer based on the refund policy instead of opening a ticket. If you do, the ticket I already opened should be closed so the case isn't handled twice.

**result** — success, 7 turns, 27s
