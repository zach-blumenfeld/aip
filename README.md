<table>
  <tr>
    <td width="140" align="center" valign="middle">
      <img src="img/aip.png" alt="aip logo" width="120" />
    </td>
    <td valign="middle">
      <h1>AIP — Agent Instruction Protocol</h1>
      <p><em>Compile Skills for Autonomous Agents to engineer and govern reliable AI workflows like code.</em></p>
    </td>
  </tr>
</table>

Your team's skills, prompts, deliberations, and runbooks are the
documents that drive your AI workflows. Today they live as ad-hoc
markdown — they drift between revisions, they fail silently when an
agent reads them, and the corpus can't be queried to see what's
actually happening. As those workflows become autonomous, that gap
between "human-readable" and "agent-executable" stops being a quality
issue and becomes a production-reliability one.

AIP closes the gap. A JSON Schema per document type declares the
shape; a small toolchain validates, compiles, ingests, and reads
back. Human prose stays canonical; the agent-readable companion is
a build artifact. The closest analogy is a compiler — source
language, target language, type system, multi-target backends,
preserved source. The case-gating is the same as any compile step:
**you compile for production; you validate for autonomy.**

AIP positions upstream of agent runtime / execution-graph
protocols (LangGraph, ADK, AgentOps). It's the protocol for the
*inputs* that drive agent behavior, not the runtime that executes
them.



## Benefits

1. **Reliability for autonomous workflows.** Schema validation catches
   structural drift at write time. Silent bugs in skills and prompts
   stop being silent. Evalautions can be associated to specific parts of structured skill and adrferssed in a targeted matter 
2. **Lower cost per AI interaction.** Compressed structured documents
   cut token usage 40–60% versus their human-prose sources. Savings
   compound across every long-running session and every sub-agent
   fan-out.
3. **Insights at corpus scale.** Once N documents share a structured
   shape, cross-doc queries become single-line operations. "Every
   option rejected for speculative reasons across all our
   deliberations" — one query, not a doc-trawling expedition.
4. **Vendor-neutral by design.** Schemas declare data shape only — no
   database-specific keywords. Per-database connectors let any storage
   system plug in. No lock-in.
5. **Continuous improvement.** A schema-validated corpus is
   high-quality structured training data for fine-tuning agents that
   mirror your team's reasoning patterns.
6. **Audit and governance.** Every agent decision lives in a queryable
   graph with provenance back to its source document. AI-driven
   workflows become inspectable, not opaque.
7. **Zero-friction entry point for skill authoring.** If you've never
   written a Claude Code skill before, using AIP is how you get your
   first one. The agent walks you through it conversationally and
   compiles the output into a correctly-structured skill folder you can
   inspect and learn from. No prior knowledge of the Skills spec
   required — the process teaches you the format by producing a working
   example of it.

---

## Get started

Install the AIP skill into your Claude Code personal skills directory:

```bash
git clone https://github.com/zach-blumenfeld/aip ~/.claude/skills/aip
```

That's it. Claude Code picks up the skill automatically at the next
session. Your agent will know how to compile, validate, and iterate
on AIP-compliant skills and documents.

**Requirements:** [uv](https://docs.astral.sh/uv/) for the bundled
validation scripts (`uv run scripts/validate.py`,
`uv run scripts/validate_schema.py`).

**Cross-platform:** The AIP skill follows the open
[Agent Skills](https://agentskills.io) standard and works anywhere
that standard is supported — Claude Code, Cursor, and others.

**Discoverable via community registries:**
[ClaudSkills](https://claudskills.com/) |
[SkillsMP](https://skillsmp.com/) |
[Skills.sh](https://skills.sh)

---

See [`spec.md`](spec.md) for the technical specification.


# TO ADD
The idea is to improve skill Performsnce & Governance. 

The Protocol is simple.  Instead of free-form markdown write skills as YAML that comply with a json schema

Still human readable- but validatablile to schema.  

So Why 

Performance
- They do better than free form markdown by default
- They provide a concrete method for tuning skills to perform better for specific models and run time (adjust the schema)

Governance
- skill compy with standard
- they are vlaidated
- they are easier to track and maintain in a database 

## Why is the AIP SKILL.MD not Written in AIP?

For the same reason that AI requires humans to build it.  Something had to exist before.  Eventually the AIP skill will be written in AIP, just as agents may eventually build agents, we just aren't there yet. 