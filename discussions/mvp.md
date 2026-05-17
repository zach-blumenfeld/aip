# MVP — what AIP v0.1 ships

> **Status: deliberation.** Scope doc for the v0.1 release. Some
> pieces decided, some open. The four (or three-and-a-half) pieces
> are listed below; each has its own open questions surfaced
> inline rather than rolled up at the end.

## What triggered this

[`spec.md`](../spec.md) is settling, the [`aip` skill](../SKILL.md)
is mostly drafted, and a real end-to-end compile
([`learning-search-first`](learning-search-first/)) just produced
an honest signal: the format works when the schema is selectively
typed, and the worst-case authoring UX (markdown with a fenced YAML
body) is the part most likely to gate adoption.

That makes this the right moment to lock the v0.1 scope: what we
actually ship, what we deliberately leave out, and what order.

## Goal

Make AIP usable end-to-end by a non-AIP-expert author **on day
one**, and demonstrate the corpus-scale payoff **on day two**.

Concretely, "day one" means: an author with a doc and an editor
can produce a validated Instruction without learning JSON Schema.
"Day two" means: a small corpus of validated Instructions can be
loaded into a database, queried across, and round-tripped back to
disk without loss.

If we ship the pieces below and a warehouse manager (or a junior
engineer, or a domain expert in any field) can author a useful
skill without understanding the spec, v0.1 succeeded. If we ship
them and only AIP authors can use them, we missed.

## The pieces

### 1. The AIP skill

**What it is.** [`SKILL.md`](../SKILL.md) in this repo. A
Claude-Code-installable skill that walks a user through producing
an AIP Instruction from source material — schema selection
(reuse-first), body compilation, validation, install.

**Current state.** Mostly done. Recent
[selective-typing learning](learning-search-first/) prompted edits
to surface the typed-vs-text decision in the walkthrough and add
anti-patterns against over-decomposing tight source.

**Scope for MVP.**

- Three scenarios as currently spec'd: no schema specified, schema
  specified, schema authoring.
- The depth selector (Quick / Balanced / Thorough).
- Bundled validators (`validate.py`, `validate_schema.py`).
- Bundled example schemas (see piece 3).

**Open questions.**

- The walkthrough as written assumes the user starts in Claude
  Code. Once the extension exists (piece 2), a non-trivial share
  of compilation might happen *in the editor* with the skill
  invoked as a side-channel. Worth re-examining the walkthrough
  shape after the extension lands.
- Does the skill ever produce non-Instruction artifacts (a
  hand-authored markdown skill that the user *doesn't* want
  compiled)? Currently it assumes the answer is yes (the "When
  NOT to use" section), but doesn't help in that case.

**NOT in MVP.** Multi-user collaborative authoring, schema
authoring beyond the conversational Scenario 3, integration with
external authoring tools.

### 2. The VS Code editor extension

**What it is.** A VS Code extension that gives SKILL.md files full
JSON-Schema-driven YAML LSP features (validation, autocomplete,
hover docs, error squiggles) — inside the fenced YAML body, while
keeping the SKILL.md on disk format unchanged. Mechanism: virtual
document containing just the body, attached to the YAML LSP, with
position translation back to the real file. (MDX, Vue SFC, and
Astro use the same pattern.)

**Current state.** Not started.

**Scope for MVP.**

- Detect SKILL.md files; virtual-doc the fenced YAML body to the
  YAML LSP.
- Bundle the v0.1 core schemas (piece 3) so users don't need to
  fetch them.
- Wire `metadata.aip.schemaId` (in the markdown frontmatter) to
  the schema the body validates against.
- Validate the frontmatter too (Agent Skills spec compliance) —
  nearly free once the virtual-doc plumbing exists.

**Open questions.**

- Schema distribution: bundle inside the extension (simple, but
  updates ship with extension releases) or fetch by `$id` from a
  registry (flexible, but adds offline-failure modes)? Probably
  bundle for v0.1 and revisit.
- Snippets, templates, and commands (new-Instruction, run-validator,
  preview) — which earn their place in v0.1 vs v0.2? Lean toward
  shipping just the LSP first; commands are accretive.
- Cursor compatibility: VS Code extensions generally work in
  Cursor without modification. Worth confirming once we have
  something runnable.

**NOT in MVP.** Other editors (JetBrains, Vim, Emacs, Sublime),
multi-file Instruction workflows, GitHub Actions / CI integration.

**Why this may be the highest-leverage piece.** The skill's
audience ceiling is "people who could plausibly run Claude Code."
The extension's downstream reach is anyone using an agent that
consumes Instructions — they never have to touch AIP authoring at
all, because the skill author did, and the editor made that easy.
A warehouse manager won't run the AIP skill, but a developer
building tools for warehouse workers will — and that developer is
who the extension is for. The skill creates one Instruction at a
time; the extension makes the format viable for sustained
authoring across a team.

This has a sequencing implication: extension might want to ship
*in parallel* with the skill, not after. See
[Sequencing](#sequencing--dependencies) below.

### 3. Core example schemas

**What they are.** A small set of permissive, generic JSON Schemas
that cover the bulk of plausible AIP use cases. The schemas are
*structural*; the skills built on top of them carry the domain
expertise.

**Proposed split — two schemas for v0.1**, categorized by **who is
consuming the artifact the skill produces or acts on**:

| Schema | Question it answers | Who reads the artifact | Examples of skills built on it |
|---|---|---|---|
| **Runbook** | "what should I do?" | Agent (and acts) | search-first; deploy-check; incident-response |
| **Document Template** | "help me make a thing" | Human (the produced output) | deliberation; spec draft; PRD; shift handoff note; damage/discrepancy report; safety incident write-up; message to manager; onboarding cheatsheet for a new hire |

The "who reads it" axis matters because the same surface artifact
can land in different categories depending on consumer. An
onboarding cheatsheet *for a new human hire* is a Document
Template (a skill helps the manager produce it). The same content
*given to an agent newly assigned to a domain* would belong to a
third category — Reference / Domain Expertise — where the agent
loads it as context. We're explicitly **deferring Reference to
v0.2** (see the *NOT in MVP* block below for this piece); two
schemas is enough surface to validate the format and demonstrate
the corpus payoff, and Reference was already flagged as the
category most likely to come out as a near-empty wrapper around
markdown.

The warehouse-worker examples above are deliberate: the schemas
have to work for non-technical domains, or the corpus-scale
payoff stays theoretical.

**Current state.** Runbook has a prototype shape from
[`learning-search-first` Attempt 3](learning-search-first/attempt-3-runbook-skill.md)
— that needs to be promoted to a real schema file rather than only
an instance. Document Template and Reference have not been drafted.

**Scope for MVP.**

- Two permissive schemas: Runbook, Document Template.
- Each follows the selective-typing discipline: required-minimum
  core, freeform-text leaves where structure isn't earning.
- Each ships as a `references/examples/<name>/` directory in the
  AIP skill, with a sample instance.

**Open questions.**

- **Document Template is the highest-stakes design.** Two
  interaction shapes need to fit: transformation ("turn my mumbled
  3 bullets into a clean handoff note") and guided elicitation
  ("ask me the right questions for a damage report"). Schema
  probably needs slot definitions with optional prompt text per
  slot.
- **What does a Document Template Instruction validate?** Two
  readings, possibly both:
  - *Template-as-Instruction*: the YAML body defines the slots and
    prompts; the filled output goes elsewhere (a Slack message,
    paper form, email). One Instruction per template kind.
  - *Filled-doc-as-Instruction*: each filled deliberation / spec /
    decision-log is its own Instruction in a corpus, queryable
    across (matches §Value Proposition's "every option rejected
    for speculative reasons across all deliberations").
  - The deliberation/spec case wants the latter; the warehouse
    handoff case wants the former. The schema may need to support
    both modes, or we may need two related schemas. Settling this
    blocks the schema draft.
- **Do we ship a generic catch-all schema** (everything optional,
  any leaf string-or-structured) for cases that don't fit
  Runbook / Document Template? Lean: no — opinionated schemas
  earn their keep; a catch-all invites lazy authoring. Authors
  whose use case doesn't fit either schema fall back to a regular
  Agent Skill (a category SKILL.md already names) until v0.2
  introduces Reference or another schema.

**NOT in MVP.**

- **Reference / Domain Expertise schema** — deferred to v0.2.
  Most likely to come out as a thin wrapper around markdown; not
  worth the design cost in v0.1, and dropping it keeps the
  authoring surface to two well-distinguished shapes.
- Schemas for fine-grained doc types (deliberation-specific,
  spec-specific, decision-log-specific) — those live in the skills
  built on top of Document Template, not as standalone schemas.
- Schemas for cross-doc linkage / refs beyond what `spec.md`
  already covers.

### 4. The Neo4j connector

**What it is.** A reference connector that reads validated AIP
Instructions and projects them into Neo4j as a graph, per the
mapping rules in [`spec.md` §Mapping rules](../spec.md). Supports
round-trip — load to graph, edit in graph (or not), serialize back
to disk as a valid Instruction.

**Current state.** Not started.

**Scope for MVP.**

- Implements the connector interface sketched in `spec.md` §1
  (`setup_schema`, `ingest`, `read_back`, `validate_round_trip`,
  `delete`).
- Idempotent schema setup (constraints / indexes derived from the
  JSON Schema).
- Round-trip lossless for v0.1 schemas (Runbook, Document
  Template).
- One demo query per §Value Proposition bullet — at minimum
  "decision archaeology across all deliberations" and "every
  spec with unresolved open questions."

**Open questions.**

- **Edge-name preservation strategy** is still open in `spec.md`
  §2. Lean: store the source YAML property name on the edge
  always. Worth settling before the connector lands.
- **Transactionality contract.** Spec leans yes-with-an-escape-hatch
  for huge ingests. Probably fine to start strict-only for MVP;
  add the escape hatch when someone needs it.
- **How do `|`-block freeform-text fields project into the
  graph?** Spec says: as a property on the parent node, searchable
  via fulltext if the connector indexes it. The Neo4j connector
  should *demonstrate* the fulltext-index path so the freeform-text
  branch isn't a black box.
- **Multi-tenancy / namespace.** If a user loads two corpora into
  the same Neo4j instance, do they collide? Probably want a
  `corpus` or `space` label per node — defer the exact mechanism
  but flag.

**NOT in MVP.** Other connectors (Postgres, Pinecone, DuckDB,
filesystem-only). Read-from-graph as a primary authoring mode
(round-trip support is required, but the canonical edit surface
stays the YAML body).

## Repo structure — one repo or several

Three obvious shapes:

1. **Monorepo.** `aip/` contains spec, skill, schemas, extension,
   connector. Simplest dependency story; everything versioned
   together. Cost: a Neo4j contributor has to navigate a TypeScript
   extension codebase, and an extension contributor has to navigate
   Python validators and Cypher.
2. **Spec + skill + schemas in one repo; extension and connector
   each in their own.** The current `aip/` repo stays the
   protocol+skill+schemas home. Extension lives at `aip-vscode` (or
   similar); connector at `aip-neo4j`. Cost: cross-repo coordination
   when the spec moves.
3. **Everything separate.** Five repos. Cost: overhead exceeds the
   coordination benefit at v0.1 scale.

Lean: **option 2.** The schemas and spec naturally co-evolve with
each other; the extension and connector are independent consumers
that should be free to release on their own cadence. The "version
pin" between them is just `metadata.aip.spec` in each Instruction
— the connector and extension both read it.

## Sequencing & dependencies

Strict ordering isn't necessary, but some things gate others:

```
spec (settled) ─────┬─→ schemas (drafted) ─┬─→ skill (final tweaks)
                    │                       │
                    │                       ├─→ extension (bundles schemas)
                    │                       │
                    └───────────────────────┴─→ connector (validates against schemas)
```

The interesting tension: **skill vs extension priority.** If the
"extension > skill in value" claim holds (see piece 2), the
extension should ship in parallel with — not after — the skill,
even though the skill is closer to done. The skill's last 20% of
polish can wait while the extension catches up.

Connector goes last because it consumes everything upstream. Demo
queries depend on having real Instances to query, which depend on
schemas being stable and the authoring tools (skill + extension)
producing them.

## Cross-cutting open questions

### §1 — How does the extension discover bundled schemas vs project-local schemas?

Mirrors the `aip` skill's schema discovery (bundled > project-local
> installed). The extension probably wants the same precedence,
implemented in TypeScript instead of Python. Worth specifying once,
not twice.

### §2 — Skill author audience vs end user audience

We've been mixing two audiences:

- **Skill authors** — people who build skills using AIP. These use
  the AIP skill and/or the extension to produce Instructions.
- **End users** — people whose agents *consume* the resulting
  skills. These never touch AIP authoring directly.

The pieces above target skill authors. End users are downstream
and benefit invisibly. But it's worth being explicit in any v0.1
marketing / docs that AIP is infrastructure, not a user-facing
product.

### §3 — What's the upgrade path when schemas evolve?

`metadata.aip.spec` versions the Instruction against a spec
release. Schemas have their own `$id` (UUID URN). When a schema
gains a new optional field, existing Instances still validate. When
a schema breaks compatibility, the old `$id` stays valid; a new
`$id` represents the new version. This is in the spec, but the
pragmatic story — "what do I do when my schema changed and I have
500 Instances in Neo4j?" — isn't documented anywhere. The
connector MVP probably needs at least a stub answer.

### §4 — Naming

`.inst` was floated and dropped (no separate file extension).
The artifact stays `SKILL.md` per Agent Skills spec. Worth a
sentence somewhere that "Instruction" is the conceptual unit and
"SKILL.md" is the file, just so the docs aren't confusing.

## What we're deliberately NOT shipping in v0.1

- Schemas for fine-grained doc types (deliberation-specific,
  spec-specific, etc.) — they live in skills, not schemas.
- Other connectors (Postgres, Pinecone, DuckDB).
- Other editors (JetBrains, Vim, Emacs).
- A web playground.
- A schema registry / marketplace.
- CI integrations (GitHub Actions, pre-commit hooks for
  validation).
- Multi-language extension support.
- A separate compiler CLI (the skill is the compiler; CLI follows
  if there's demand).

Each of these is plausible v0.2+ work, none of them block the
"author + corpus + connector" loop the v0.1 MVP is trying to
demonstrate.

## Decision summary

| Piece | Decided | Open |
|---|---|---|
| AIP skill | Ship as currently spec'd, with recent selective-typing edits | Walkthrough may want re-examining once extension exists |
| Extension | Build it; virtual-doc YAML inside SKILL.md; bundle schemas | MVP feature set vs v0.2; Cursor compat |
| Schemas | Two: Runbook, Document Template; permissive. Reference deferred to v0.2 | Document Template's two-mode question (template-as-Instruction vs filled-doc-as-Instruction) |
| Connector | Neo4j, round-trip, lossless, with demo queries | Edge-name strategy; freeform-text indexing; multi-tenancy |
| Repo structure | Lean: spec+skill+schemas in `aip/`; extension and connector each separate | — |
| Sequencing | Skill and extension in parallel; connector after | — |
