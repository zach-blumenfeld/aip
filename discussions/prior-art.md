# Discussion: prior art & landscape survey

> **Status: research, not deliberation.** Documents a web search
> conducted 2026-05-16 to verify that AIP is not reinventing
> something that already exists. Records every source visited,
> what it does, and how it differs from AIP. One open concern
> surfaced: the name "AIP" has significant existing use as an
> acronym — flagged at the end.

## What triggered this

Before investing further in the spec and tooling, we wanted to
sanity-check the landscape. The question: **does a tool or protocol
already exist that does what AIP does?** If so, we should understand
it deeply rather than duplicate it.

## What AIP does (reference frame for comparison)

For comparison purposes, AIP's core value proposition is:

1. A team writes human-prose documents (skills, runbooks,
   deliberations, specs).
2. An AI agent — guided by the **AIP skill** (a Claude Code skill)
   — compiles each document into a schema-validated YAML companion.
3. The schema is team-authored JSON Schema that follows
   [AIP conventions](../spec.md#aip-schema-conventions). AIP's
   underlying type system is standard [JSON Schema](https://json-schema.org/).
4. The validated YAML is directly agent-readable and optionally
   ingestable into a graph or relational database via connector
   packages (`aip-neo4j`, `aip-postgres`, …).
5. The AIP skill includes Python validation scripts (`scripts/`)
   run via `uv run` — no separate binary installation.

AIP is positioned **upstream of agent runtime / execution-graph
protocols** (LangGraph, ADK, AgentOps). It defines the *inputs*
that drive agent behavior; it does not control the runtime.

See [`spec.md`](../spec.md) and
[`discussions/cli-api.md`](cli-api.md) for full detail.

## Search angles covered

1. "agent instruction protocol" — name collision check
2. Structured document formats for AI agent consumption
3. Prompt / skill management tools using JSON Schema validation
4. Claude Code skill authoring tools or frameworks
5. "AI runbook" / "AI skill specification" existing standards
6. Document-as-code for AI workflows (OpenAPI analogue for agents)
7. Tools that compile human documentation into structured agent-readable formats

## Findings

### 1. The name "AIP" — collision concern

> **This is the most actionable finding. See [§Naming concern](#naming-concern).**

The acronym "AIP" is already occupied by at least four distinct
initiatives, all in the AI-agent space:

| Name | Source | What it is |
|------|--------|------------|
| Agent Identity Protocol | [IETF draft-singla](https://www.ietf.org/archive/id/draft-singla-agent-identity-protocol-00.html) | Identity/authentication for AI agents at runtime |
| Agent Identity Protocol | [IETF draft-prakash](https://www.ietf.org/archive/id/draft-prakash-aip-00.html) | Competing IETF draft for the same concept |
| Agentic Interaction Protocol | [AXONIC-AIP on GitHub](https://github.com/AXONIC-AIP/AIP) | Deterministic governance and safety standard for agent interactions |
| Agent Internet Protocol | [IETF datatracker](https://datatracker.ietf.org/doc/draft-song-anp-aip/) | Internet-layer routing protocol for AI agents |

None of these touch what our AIP does — they are all
runtime/execution/identity protocols operating at a different layer.
Semantic collision is minimal. But two IETF drafts using the same
acronym in the same general domain is not nothing.

### 2. Anthropic Agent Skills / SKILL.md

**Source:** [Anthropic Agent Skills overview](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)
| [Ylang Labs writeup](https://ylanglabs.com/blogs/agent-skills)

The most structurally adjacent thing found. SKILL.md is an open
standard (released late 2025) for packaging AI agent skills as a
directory: `SKILL.md` (markdown + YAML frontmatter) plus optional
`scripts/`, `references/`, and `assets/` subdirs. Now supported
across Claude Code, Cursor, and Gemini CLI.

**How it differs from AIP:**
- SKILL.md has no schema validation layer — skill authors write
  freeform markdown prose. No type system.
- No concept of compiling prose into a validated structured companion.
- No pluggable JSON Schema family per document type.
- No graph/DB ingest connectors.

**Relationship to AIP:** AIP wraps SKILL.md as its delivery
mechanism — the AIP skill's `SKILL.md` is our compile output, not
our authoring model (per
[cli-api.md § Foundational research](cli-api.md)). AIP's
toolchain is additive and novel on top of the Skills format.

### 3. Knows / KnowsRecord

**Source:** [arxiv 2604.17309](https://arxiv.org/html/2604.17309)
| [knows.academy](https://knows.academy/)

A YAML sidecar format for academic research papers — schema-validated
and designed to be agent-consumable. Structurally the closest thing
to AIP's "validated YAML companion" concept. The paper describes
using JSON Schema 2020-12 to validate structured metadata alongside
human-readable documents.

**How it differs from AIP:**
- Scoped entirely to academic publications — not a general-purpose
  protocol for any document type.
- No AI-guided compilation step (no equivalent of the AIP skill's
  conversational authoring workflow).
- No connector layer for DB ingest.
- No team-definable schema family — the schema is fixed by the
  Knows spec itself.

**Verdict:** Closest structural neighbor. Validates that the
"validated YAML companion alongside human prose" pattern has
independent motivation. Worth monitoring; their schema-validation
approach may offer useful reference.

### 4. Agent Format (AGF) / agentformat.org

**Source:** [Snap Engineering blog](https://eng.snap.com/agent-format)
| [agentformat.org](https://agentformat.org/)

A declarative `.agf.yaml` standard for defining what an agent *is*
— identity, action space, safety constraints, approval gates.
Described as "Kubernetes for AI agents." Governance-focused.

**How it differs from AIP:**
- Describes agent *configuration at runtime*, not the instruction
  documents fed into an agent.
- No document compilation step.
- No schema family per document type.
- AIP is upstream of what AGF describes — AIP defines the inputs;
  AGF defines the agent that consumes them.

### 5. Open Agent Spec

**Source:** [openagentspec.dev](https://www.openagentspec.dev/)

A YAML-based declarative standard for defining agents across LLM
engines — similar intent to Agent Format. Describes the agent, not
the documents the agent reads.

**How it differs from AIP:** Same as §4 above. Runtime
configuration layer, not document compilation layer.

### 6. Policy Cards

**Source:** [arxiv 2510.24383](https://arxiv.org/abs/2510.24383)
(October 2025)

Machine-readable JSON Schema (2020-12) governance documents encoding
what an agent is allowed or denied at runtime. Closest to AIP in
its use of JSON Schema as a type system for agent-facing documents.

**How it differs from AIP:**
- Purpose is runtime compliance enforcement, not upstream document
  compilation.
- The compilation step — prose → validated structured artifact — does
  not exist here.
- Schemas are fixed governance constructs, not team-definable per
  document type.

### 7. Prompt management tools

**Sources:**
- [PromptLayer on JSON Schema](https://blog.promptlayer.com/how-json-schema-works-for-structured-outputs-and-tool-integration/)
- LangSmith (langsmith.com)
- Humanloop (humanloop.com)

These tools manage and version prompt *strings*, with some JSON
Schema awareness for structured LLM *outputs*. They operate on the
prompt → response cycle, not on the document → structured companion
compilation pipeline.

**How they differ from AIP:**
- No per-document-type schema family.
- No AI-guided compilation of prose documents.
- No graph/DB ingest connectors.
- They manage prompts; AIP compiles documents that contain the
  instructions those prompts would otherwise carry ad-hoc.

### 8. Specification-first agentic development (methodology)

**Source:** [dev.to — Holger Leichsenring](https://dev.to/holgerleichsenring/specification-first-agentic-development-a-methodology-for-structured-traceable-ai-assisted-la)

A growing workflow philosophy: write specs before agentic coding,
use structured documents to keep AI output traceable. Directionally
aligned with AIP's motivation but is a methodology, not a toolchain.
No validation, no compilation, no schema conventions.

**Relationship to AIP:** AIP is the toolchain that makes this
methodology mechanically enforceable rather than just aspirational.

## Summary table

| Tool / project | Layer | Schema validation | Compilation step | DB ingest | Verdict |
|----------------|-------|-------------------|-----------------|-----------|---------|
| Knows ([knows.academy](https://knows.academy/)) | Document sidecar | Yes (JSON Schema 2020-12) | No | No | Closest neighbor; scoped to academic papers only |
| SKILL.md ([Anthropic](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)) | Skill packaging | No | No | No | Format AIP wraps; additive relationship |
| Agent Format ([agentformat.org](https://agentformat.org/)) | Runtime config | No | No | No | Different layer entirely |
| Open Agent Spec ([openagentspec.dev](https://www.openagentspec.dev/)) | Runtime config | No | No | No | Different layer entirely |
| Policy Cards ([arxiv](https://arxiv.org/abs/2510.24383)) | Runtime compliance | Yes (JSON Schema) | No | No | Different purpose (governance at runtime) |
| PromptLayer / LangSmith / Humanloop | Prompt management | Partial | No | No | Different object (prompts, not documents) |
| Spec-first methodology ([dev.to](https://dev.to/holgerleichsenring/specification-first-agentic-development-a-methodology-for-structured-traceable-ai-assisted-la)) | Workflow philosophy | No | No | No | AIP is the mechanical implementation of this idea |

**No tool found does the combination AIP targets:** AI-guided
compilation of multi-type human-prose documents → schema-validated
YAML → optional DB ingest, with team-definable schemas constrained
by a protocol convention.

## Naming concern

The acronym **AIP** is in active use in the IETF for agent-related
protocols. Two competing drafts for "Agent Identity Protocol"
([draft-singla](https://www.ietf.org/archive/id/draft-singla-agent-identity-protocol-00.html),
[draft-prakash](https://www.ietf.org/archive/id/draft-prakash-aip-00.html))
plus an "Agent Internet Protocol"
([IETF datatracker](https://datatracker.ietf.org/doc/draft-song-anp-aip/))
mean that anyone searching "AIP protocol" in an AI-agent context
will hit those results before ours.

**Semantic collision is minimal** — all existing AIPs operate at
the runtime/identity layer, which is explicitly not our scope
(per [discussions/identity-and-naming.md](identity-and-naming.md)).
But **brand confusion is real**, especially given the IETF filings.

The naming deliberation is in
[discussions/identity-and-naming.md](identity-and-naming.md).
The relevant open question is §3 (domain / repo / package naming).
This finding should inform that discussion before any public launch.

**Options (not deliberated here — belongs in identity-and-naming.md):**

- Keep AIP, accept the collision — the semantic distinction is clear
  enough that practitioners will differentiate.
- Qualify it — "AIP — Agent Instruction Protocol" as the full form
  is distinct enough from "Agent Identity Protocol" that explicit
  use of the full name avoids confusion.
- Revisit the acronym — if the IETF drafts progress to RFCs, the
  collision risk grows.

## What to watch

- **Knows ([knows.academy](https://knows.academy/))** — most
  structurally adjacent. If they expand beyond academic papers or
  add a compilation toolchain, they become a direct neighbor.
- **SKILL.md adoption** — already cross-platform (Claude Code,
  Cursor, Gemini CLI). AIP's value is additive, but monitoring
  whether Anthropic adds native schema validation to the Skills spec
  is worthwhile.
- **IETF AIP drafts** — if either Agent Identity Protocol draft
  progresses toward RFC status, the naming collision risk increases
  significantly.
