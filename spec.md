# AIP — Agent Instruction Protocol — spec (draft v0.1)

> **Status: draft.** Captures decisions made through 2026-05-15.
> Several sections are settled; several open-question subsections
> remain and may be promoted to standalone discussion docs.

> **Protocol name: AIP — Agent Instruction Protocol** (committed per
> [identity-and-naming.md](discussions/identity-and-naming.md)).
> Positioned upstream of agent runtime / execution-graph protocols
> (LangGraph, ADK). Reference implementation: the **`aip` skill**
> (bundled in this repo), which includes validation scripts in
> `scripts/`. No separate binary installation required. The point: a
> thin format + storage protocol for the documents that drive
> autonomous agent behavior.


## Value Proposition

### One-sentence claim

Compiles human-authored documents into validated, queryable,
round-trippable agent-readable counterparts — keeping the human
source canonical and producing the agent form as a build artifact.

### When the benefit is large vs small

Two scaling factors govern when this matters:

- **How autonomously the consuming agent operates.** Constant
  human oversight (e.g. chat assistants) catches structural
  confusion in real time — value is modest. Long-running,
  unsupervised, multi-step agents have no safety net — value is
  large. Every token saved compounds over a long session; every
  silent structural bug becomes a wrong answer nobody catches;
  every cross-doc dependency that isn't queryable becomes a
  hand-coordination cost.
- **How many documents are in scope.** Per-document benefits
  start at doc #1. Per-corpus benefits compound with N.

If you're shipping autonomous AI workflows to production, this is
the difference between "works in a demo" and "works in production."

### Per-document benefits (the format alone)

Available the moment a doc validates against a schema; no DB
required.

- **Optimized for autonomous execution.** Compressed YAML cuts
  tokens (often 40–60% vs the human-prose source) and parses
  faster (native-parse formats cost less attention than markdown's
  loose structure). Predictable shape means agents code against
  the schema, not per-file examples. Removes narrative scaffolding
  that's signal for humans but noise for agents.

  *Caveat — when compression is real.* The 40–60% figure assumes
  prose-heavy source AND selective-typing schema discipline (type
  sections an agent will iterate or filter by; leave the rest as
  freeform text). Tight, already-structured source compiled against
  a rigid full-typed schema can compress *negatively* (a real
  compile in this project saw +4.2% — see
  [discussions/learning-search-first/](discussions/learning-search-first/)).
  Selective typing is covered in the reference `aip` skill's
  `SKILL.md`; schema-side guidance lives in
  [§AIP schema conventions](#aip-schema-conventions).
- **Forces clarity at write time.** Vague skills, prompts, and
  specs can't validate against a strict schema. The validator is
  a quality gate that catches under-specified structure before
  consumers see it.
- **Catches silent bugs in skills and prompts.** Schema validation
  surfaces structural drift before downstream consumers see wrong
  output. (Real example from this project: seven misparsed list
  items in one of our rewrites — invisible until validation
  surfaced them.)
- **Constrains agent drift.** Same agent on different days
  produces the same shape. No field-name spaghetti across runs.
- **Enables tooling.** CI validation, IDE autocomplete (YAML LSPs
  respect `$schema` refs), schema-driven search and extraction. A
  10-second validator one-liner catches structural bugs at commit
  time.
- **Improves security.** Structured form is harder to exploit than
  free prose; prompt-injection attempts that don't conform to the
  schema fail validation. Structural rigidity makes malicious
  alteration easier to detect.

### Per-corpus benefits (the storage layer)

Compound as you accumulate validated documents; require a
connector to a database.

- **Cross-doc analytics & insights.** "Every option rejected for
  speculative reasons across all deliberations," "every spec with
  unresolved open questions" — single query, not doc-trawling.
- **Decision archaeology.** Six months later, "why did we reject
  X?" is a structured lookup, not a re-read of 400 lines of prose.
- **Discoverability.** Schema + DB search makes documents findable
  by both humans and agents — without browsing.
- **Self-documentation & governance.** Schemas are themselves the
  spec for "what should a deliberation contain?" Ops metrics like
  "stale items by author" or "doc count by schema" become
  queryable.
- **Cross-doc reasoning as a graph.** `refs:` between docs become
  first-class edges; eventual cross-schema links (deliberation →
  spec → release → incident) make the dev lifecycle queryable.
- **Schema-to-schema translation.** Agents can derive draft specs
  from settled deliberations by mapping fields. Stage handoffs
  become mechanical instead of judgment-laden.
- **Continuous learning / training data.** A validated corpus is
  high-quality structured input for fine-tuning team-specific
  reasoning agents — far more useful than freeform markdown.

### The two layers compose but don't depend on each other

Authoring without storage works — per-document benefits available
on day one. Storage without authoring works — consume YAMLs
produced by another team. Either layer is useful alone; together
they compound.

### Mental model: it's a compiler

For programmers and technically-literate readers, the cleanest
analogy: this is a compiler from human-authored prose to
agent-executable structure.

| Compiler                 | AIP                                                    |
|--------------------------|--------------------------------------------------------|
| Source language          | Human-prose markdown                                   |
| Target language          | Schema-validated YAML                                  |
| Type system              | JSON Schema (https://json-schema.org/)                 |
| Static checks            | Schema validation                                      |
| Intermediate rep (IR)    | The validated YAML (consumed directly OR projected)    |
| Backends                 | Per-database connectors (Neo4j, Postgres, …)           |
| Build artifact           | Instruction (agent-readable folder; see §Instruction format) |
| Source preservation      | Source kept inside the Instruction (`source/`)         |

The analogy also explains the case-gating: **you don't compile
code you'll run once and discard. You compile code that runs in
production, repeatedly, where reliability and efficiency matter.
Autonomous agents are that production environment.** That's both
why use this and why build this — for the case where AI workflows
have to keep working without continuous human inspection.


## What this is

A discipline (and minimal toolchain) for capturing the kinds of
documents teams already write — deliberations, specs, runbooks,
post-mortems, design notes — in a format that is **simultaneously
readable by humans, agents, and databases**, without requiring any of
them to compromise.

Concretely:

- **Teams author JSON Schemas** — one per doc type — declaring the
  structured shape of that doc (a `deliberation` looks like X, a `spec`
  looks like Y). These schemas are not part of the AIP protocol; they
  are what teams *produce using* AIP. AIP defines the conventions a
  schema must follow to be AIP-compliant (see
  [§AIP schema conventions](#aip-schema-conventions)). The underlying
  type system is standard [JSON Schema](https://json-schema.org/).
- **An Instruction** (see [§Instruction format](#instruction-format))
  bundles the human-prose source, the schema, and the validated
  YAML-compliant `SKILL.md` body that agents read. The source stays
  canonical for humans (inside `source/`); the **Instruction body** —
  the validated content of `SKILL.md` — is the machine-readable face.
- **A vendor-neutral mapping rule set** describes how schema-validated
  YAML projects into a graph (or any other storage shape).
- **Connectors** are per-database adapters that implement the mapping.
  Each connector is a separate package (`aip-neo4j`, `aip-postgres`,
  …). Anyone can write a compliant connector by implementing the
  connector interface.

## What this is NOT

- Not a knowledge management system (Notion, Obsidian, Confluence).
  It's a format + protocol; storage is delegated.
- Not a CMS. No publishing, no rendering, no versioning UI.
- Not a wiki. Documents reference each other by path, not by hyperlink.
- Not a replacement for human judgment in producing the docs. The
  format is opinionated; the *content* is the team's.

## Non-negotiable principles

1. **Database-agnostic schemas.** JSON Schema files contain only
   data-shape declarations. No DB-specific keywords (no `x-graph-*`,
   no `x-neo4j-*`, no node/edge hints). Any DB vendor plugs in via a
   connector. This is the anti-lock-in guarantee.

2. **Two-way mapping (structural losslessness).** A producer can
   ingest YAML into the DB, read it back via the connector, and
   reconstruct YAML that re-parses to the same data structure.
   Comments and whitespace are not preserved (acceptable loss);
   structure, ordering, and values are.

3. **Convention-based mapping.** Mapping rules are derived from the
   schema's structure (`$defs`, `properties`, `additionalProperties`)
   — not from author-provided graph hints. Schemas are written
   without knowing or caring how they'll be stored.

4. **Source markdown ingest is optional.** A producer can ingest an
   Instruction body alone, or also ingest the Instruction's source
   markdown as a linked Document. The DB carries no opinion either way.

5. **Strict-core, open-extensions schemas.** Every object in a schema
   has a closed key set, plus an optional `extensions:` map for
   doc-specific structure that doesn't fit. Predictability without
   brittleness.

6. **Lossy is the only ingest mode.** Instruction bodies in lossless
   mode (with a `context:` TAIL preserving original phrasing) are not
   ingested into the DB. The lossless mode targets a different
   consumer (an agent reconstructing original tone). If lossless
   storage matters later, it gets its own schema and connector.

## AIP schema conventions

AIP does not define a fixed schema family. Teams create their own
JSON Schemas for their doc types. AIP defines the conventions a
schema must follow to be considered AIP-compliant. The
`scripts/validate_schema.py` script bundled in the `aip` skill
enforces these (see [§The AIP skill](#the-aip-skill)).

AIP-compliance has two layers: **required metadata** (root-level
annotation keywords that identify and describe the schema) and
**required structural conventions** (rules about how schemas declare
shape).

### Required metadata

Schemas declare identity and discovery metadata at the root using
standard JSON Schema meta-data annotation keywords, plus an AIP-
namespaced object for AIP-specific fields:

| Keyword         | Required? | Standard?          | Notes                                                                                                                   |
|-----------------|-----------|--------------------|-------------------------------------------------------------------------------------------------------------------------|
| `$schema`       | Required  | Yes                | Declares JSON Schema dialect, e.g. `https://json-schema.org/draft/2020-12/schema`.                                      |
| `$id`           | Required  | Yes                | Global identifier. Use a UUID URN (`urn:uuid:...`) for guaranteed uniqueness without requiring an HTTP host.            |
| `title`         | Required  | Yes                | Short human-readable display name.                                                                                      |
| `description`   | Required  | Yes                | Short human-readable description (one or two sentences). Keep it short — README is for prose.                           |
| `aip.version`   | Optional  | No (AIP namespace) | Version string if multiple versions exist. Schema versioning itself is out of scope for v0.1 (Open Q §6).               |
| `aip.tag`       | Optional  | No (AIP namespace) | Search tag for schema discovery (Open Q §8).                                                                            |

AIP-specific metadata lives under a top-level `aip:` object to avoid
colliding with future JSON Schema keywords:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:uuid:550e8400-e29b-41d4-a716-446655440000",
  "title": "Deliberation",
  "description": "Structured deliberation: items, options, lean, decision.",
  "aip": {
    "version": "0.1",
    "tag": "decision-process"
  },
  "type": "object",
  "properties": { ... }
}
```

`$id` is a JSON Schema URI. A UUID URN form (`urn:uuid:...`) is
intentionally non-dereferenceable, which matches the goal of
"schemas authored anywhere, globally unique without coordination."
This `$id` is what `metadata.aip.schemaId` in an Instruction's
`SKILL.md` frontmatter (see [§SKILL.md format](#skillmd-format)) and
`schemaId` on storage nodes (see [§Mapping rules](#mapping-rules))
reference. The connector derives the storage-node `schemaId` from
the Instruction's `metadata.aip.schemaId` (or equivalently from the
schema's own `$id`) at ingest time.

### Required structural conventions

- Schemas must not define properties using AIP-reserved names: `id`,
  `schemaId`, `key`, `idx`, `_source`. These are all injected by the
  connector at ingest time and may not be declared in any schema —
  not at the schema root, not inside `$defs`, not anywhere.
- The root schema must follow the strict-core / open-extensions
  pattern: a closed key set plus an optional `extensions:` map for
  doc-specific structure that doesn't fit.
- `$defs` entries become node types in storage; each must have a
  clearly-named key (becomes the node label).

### Optional README.md

A schema directory may include a `README.md` alongside the schema
file: prose explanation of what the schema is, when to use it, when
not to use it. Required for AIP-published reference schemas;
optional for team-local schemas. A schema with a clear `title` and
`description` doesn't necessarily need separate prose — the README
is for context that doesn't fit a one-sentence description.

**The `examples/schemas/` directory** (`deliberation.schema.json`,
`generic.schema.json`) contains reference schemas that demonstrate
these conventions — they are not part of the AIP protocol itself.

## Instruction format

The deliverable AIP produces is an **Instruction** — a skill folder
that conforms to the [Agent Skills spec](https://agentskills.io/specification)
and adds AIP-specific requirements on top. An Instruction is loadable
by any Agent Skills-compatible runtime; the AIP-specific structure
gives the team the schema, source, and validation guarantees that
distinguish an AIP Instruction from an ad-hoc skill.

### Terminology

- **Instruction** — the artifact AIP produces. A type of
  [Agent Skill](https://agentskills.io). The Instruction format is an
  extension of the Agent Skills spec — conforming to it and adding the
  requirements below.
- **schema** — the AIP-compliant JSON Schema that governs the
  Instruction's `SKILL.md` body.
- **source** — the canonical human-readable materials used to produce
  the Instruction. The `source → build artifact` analogy is loose: the
  source need not be proprietary, and is not guaranteed to contain
  enough information to deterministically reproduce the Instruction.
  What it does provide is a canonical, human-readable record of the
  information and reasoning behind the Instruction.

### Directory structure

```shell
instruction-name/
├── SKILL.md                       # Required: metadata + YAML-compliant instructions
├── schema/                        # Required: AIP schema
│   ├── schema-name.schema.json    # Required: schema spec
│   └── README.md                  # Optional: additional schema documentation
├── source/                        # Required: canonical human-readable source
│   ├── README.md                  # Required: main source doc
│   ├── SOURCE_SKILL.md            # Optional: Agent Skill (non-AIP) used as source
│   └── ...                        # Any additional files or directories
├── scripts/                       # Optional: executable code
├── assets/                        # Optional: templates, resources
├── references/                    # Optional: documentation
└── ...                            # Any additional files or directories
```

**AIP-specific requirements (in addition to `SKILL.md` from the Agent
Skills spec):**

- `schema/` containing one `*.schema.json` — the AIP-compliant schema
  the `SKILL.md` body validates against. Optional `README.md` for
  schema documentation.
- `source/` containing at minimum a `README.md` — the canonical
  human-readable source the Instruction was produced from. Optional
  `SOURCE_SKILL.md` when the Instruction was derived from a non-AIP
  Agent Skill.

**Open extensions.** AIP preserves the Agent Skills spec's "any
additional files or directories" property at two levels:

- **At the Instruction root** — teams may add directories beyond the
  Agent Skills well-known set (`scripts/`, `references/`, `assets/`)
  and the AIP-required set (`schema/`, `source/`).
- **Inside `source/`** — teams freely store deliberation drafts, prior
  conversation logs, diagrams, or related notes alongside the
  canonical `README.md`.

This keeps AIP a true extension of the Agent Skills spec rather than a
stricter dialect.

### Why these directories are top-level (not nested)

`schema/` and `source/` sit at the Instruction root rather than under
`references/` or a dedicated `aip/` namespace directory:

- The Agent Skills spec's directory diagram explicitly permits
  *"Any additional files or directories"* at the root.
- Neither is documentation. The Agent Skills spec defines `references/`
  as *"additional documentation that agents can read when needed."* A
  schema is a validation contract; the source is the canonical
  human-readable origin. Neither role fits `references/`.
- The Agent Skills spec advises *"Keep file references one level deep
  from `SKILL.md`."* `schema/foo.schema.json` is one level;
  `references/schema/foo.schema.json` is two.

## SKILL.md format

`SKILL.md` is the Instruction's main file. The YAML frontmatter
declares Agent Skills metadata plus AIP linkage; the body is the
schema-validated Instruction body that agents read and connectors
ingest.

### Frontmatter

Conforms to the
[Agent Skills spec frontmatter fields](https://agentskills.io/specification#frontmatter),
with two AIP-specific additions nested under `metadata.aip:`.

| Field                   | Required? | Source            | Notes                                                                                                                                              |
|-------------------------|-----------|-------------------|----------------------------------------------------------------------------------------------------------------------------------------------------|
| `name`                  | Required  | Agent Skills spec | 1–64 chars; lowercase `a–z`/`0–9`/`-`; no leading/trailing/consecutive hyphens; **must match the Instruction's parent directory name**.            |
| `description`           | Required  | Agent Skills spec | 1–1024 chars. Describes *what* the Instruction encodes and *when* to use it. See §Discovery considerations below.                                  |
| `metadata.aip.spec`     | Required  | AIP               | URL to the AIP spec this Instruction conforms to. Current placeholder: `https://raw.githubusercontent.com/zach-blumenfeld/aip/main/spec.md`. Makes the Instruction self-describing — see §Self-description below. |
| `metadata.aip.schemaId` | Required  | AIP               | UUID URN matching the `$id` of the schema in the Instruction's `schema/` directory.                                                                |
| `license`               | Optional  | Agent Skills spec | Pass-through.                                                                                                                                      |
| `compatibility`         | Optional  | Agent Skills spec | Pass-through. 1–500 chars.                                                                                                                         |
| Other `metadata.*` keys | Optional  | Agent Skills spec | Arbitrary string→string mapping for additional team-specific metadata.                                                                             |
| `allowed-tools`         | Optional  | Agent Skills spec | Pass-through (experimental in Agent Skills).                                                                                                       |

The Agent Skills spec recommends putting client-specific properties
under `metadata` (with reasonably unique key names) to avoid collision
with future spec additions. Nesting under `metadata.aip:` keeps
AIP-specific frontmatter cleanly namespaced.

### Body — the Instruction body

The content following the frontmatter is the **Instruction body**:
exactly one fenced YAML code block (language tag `yaml` or `yml`),
preceded and followed only by optional whitespace. No surrounding
prose, no second code block. The fence contents validate against the
schema referenced by `metadata.aip.schemaId`.

````markdown
---
name: launch-decision
description: Deliberation for v0.1 launch sequencing.
metadata:
  aip:
    spec: https://raw.githubusercontent.com/zach-blumenfeld/aip/main/spec.md
    schemaId: urn:uuid:550e8400-e29b-41d4-a716-446655440000
---

```yaml
title: Launch sequencing
items:
  - id: 1a
    description: ...
options:
  - id: A
    description: ...
lean:
  pick: 1a-A
  rationale: ...
```
````

The body does **not** repeat `schemaId` — the frontmatter's
`metadata.aip.schemaId` is the single source of truth for schema
linkage. Consumers that extract the body alone (e.g., a connector
ingesting into a database) must read frontmatter for schema context;
the body is not designed to be self-describing without it. This
keeps authoring non-redundant.

### Discovery considerations

Per the Agent Skills spec's progressive disclosure model, only `name`
and `description` load at startup for every installed skill. For AIP
Instructions, that makes `description` the *only* signal available
before the agent decides to activate the Instruction. Two
recommendations:

1. **Reference the schema's domain in `description`.** Beyond the
   Agent Skills convention of "what + when," include enough domain
   context for AIP-aware discovery to recognize the Instruction as a
   candidate match. *"Deliberation for v0.1 launch sequencing"* tells
   discovery both the schema family (deliberation) and the subject.
2. **Keep `description` short when possible.** The hard limit is
   1024 chars, but every installed skill's description loads at
   startup — shorter descriptions across the corpus mean less startup
   cost.

### Self-description for AIP-unaware agents

The required `metadata.aip.spec` field makes every Instruction
self-describing. An agent encountering an unfamiliar Instruction sees
the `metadata.aip.*` block, recognizes that an extension is in use,
and can fetch the spec URL to learn the format from first principles
before interpreting the rest of the file.

This mirrors the pattern used by JSON Schema's `$schema` keyword
(declare the dialect with a fetchable URL) and HTTP's `Content-Type`
header (declare the format inline with the payload).

**Current placeholder URL:**
`https://raw.githubusercontent.com/zach-blumenfeld/aip/main/spec.md`.
Raw markdown directly from the repo — agent-fetchable today, no
website infrastructure required. Tracks `main`, so it isn't pinned to
a version; that's an acceptable trade for v0.1, and gets replaced with
versioned URLs (e.g., `https://aip.dev/spec/v0.1`) once the AIP
website exists.

### Body size

The Agent Skills spec recommends keeping `SKILL.md` under 500 lines /
~5000 tokens (the body loads in full when the Instruction activates).
For AIP Instructions this is usually easy: the compiled YAML body is
typically 40–60% smaller than the markdown source.

If the body would exceed the budget, the team should consider
splitting the underlying domain into multiple smaller Instructions
rather than spilling content into `references/`. References load on
demand and don't shape behavior — they're for documentation an agent
might consult, not the instructions themselves.

## Schema discovery

When the agent helps a user produce an Instruction without a
pre-specified schema (Scenario 1 — see
[§The AIP skill](#the-aip-skill)), it must recommend candidate
schemas. The schema discovery convention defines where the agent
looks and how it filters candidates.

> Resolves [Open Q §8](#8--schema-discovery-convention-resolved).

### Three sources

| Source                 | Location                                                                                  | Filter                                                                                                              |
|------------------------|-------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------|
| Bundled examples       | `~/.claude/skills/aip/references/examples/*/`                                             | All subfolders (trusted source).                                                                                    |
| Project-local          | `*.schema.json` under CWD (max depth 4, respect `.gitignore`)                             | Schema has a top-level `aip:` object (AIP-compliant per [§AIP schema conventions](#aip-schema-conventions)).        |
| Installed Instructions | `~/.claude/skills/*/schema/*.schema.json` and `./.claude/skills/*/schema/*.schema.json`   | Containing skill's `SKILL.md` has `metadata.aip.spec` in frontmatter.                                               |

For each candidate, the agent reads `$id`, `title`, `description`,
and `aip.tag` (all required per
[§AIP schema conventions](#aip-schema-conventions)) and ranks against
the user's intent.

### Dedup precedence

When the same `$id` appears in multiple sources, prefer
**bundled > project-local > installed**. Closest-to-user wins for
trust and predictability.

### Why the filters work

The schema metadata requirements double as discovery filters:

- `metadata.aip.spec` in a `SKILL.md` is the "is this installed skill
  an AIP Instruction?" signal.
- A top-level `aip:` object in a `*.schema.json` is the "is this
  schema AIP-compliant?" signal.

These filters prevent false positives from random `*.schema.json`
files (AJV fixtures, JSON Schema store, npm package schemas) and
from non-AIP installed skills. No additional naming conventions or
registries are needed.

### Project-local scan parameters

- Maximum depth: 4 levels from CWD.
- Respect `.gitignore` (excludes `node_modules/` and similar by
  default).
- Most schema files in a real project live within 2–3 levels of CWD,
  so depth 4 covers the realistic cases without pathological
  recursion on large monorepos.

### What's deferred

For v0.1, AIP does not specify:

- Cross-corpus discovery ("find schemas similar to this one across
  all installed Instructions").
- A registry, marketplace, or remote schema fetching.
- Schema indexing or caching strategies.

The agent can always fall back to drafting custom (Scenario 3) when
bundled and discovered schemas don't fit. Discovery is a
recommendation surface, not a hard requirement.

## Components

### A. Instructions

The deliverable AIP produces (see [§Instruction format](#instruction-format)).
The **Instruction body** — the YAML-compliant content of `SKILL.md`,
validated against the Instruction's schema — is what agents read and
what connectors ingest.

### B. Producer pipeline (human → Instruction)

Two paths:

- **Agent path (primary).** A human writes prose; the agent — guided
  by the AIP skill — compiles it into an Instruction.
- **Schema authoring path.** The agent — guided by the AIP skill —
  helps a team draft a new AIP-compliant JSON Schema from a
  description, validating each iteration with `scripts/validate_schema.py`.

### C. Vendor-neutral mapping rules

A general rule set that derives a graph (or any storage shape) from a
schema's structure. Database-agnostic. Documented in
[§Mapping rules](#mapping-rules).

### D. Connectors (separate packages)

Per-database adapters that implement the connector interface (see
[Open Questions §1](#open-questions)). Each connector is its own
package:

- **`aip-neo4j`** — reference connector (see [§Reference connector](#reference-connector-neo4j-aip-neo4j))
- `aip-postgres`, `aip-duckdb`, … — future connectors

Connectors do not live in this repo. The connector interface contract
(what methods every connector must implement) is specified here and
enforced by the reference connector.

### E. The AIP skill (in this repo)

The `aip` skill is the canonical producer-side deliverable. It lives
in this repo and is coupled to this spec — when AIP conventions
change, the skill updates in lockstep. No separate binary or package
installation is required.

**Skill folder layout:**

```
~/.claude/skills/aip/
  SKILL.md                    ← agent knowledge (see §The AIP skill)
  scripts/
    validate.py               ← validates a doc against its declared schema
    validate_schema.py        ← validates a schema against AIP conventions
  references/
    examples/                 ← example schemas the agent can reference
      deliberation.schema.json
      generic.schema.json
```

**Scripts** are self-contained Python using [PEP 723](https://peps.python.org/pep-0723/)
inline dependency declarations, run via `uv run`:

```bash
uv run scripts/validate.py path/to/doc.yml
uv run scripts/validate_schema.py path/to/schema.json
```

The agent invokes these as part of the conversational workflow
(e.g. as a final check before offering to install an Instruction).
For CI pipelines and pre-commit hooks without an agent, the same
scripts run directly — no separate install step, because `uv run`
handles the isolated environment.

## Architecture

```
   ┌─────────────────────┐
   │  human-prose source │  (optional; some docs are agent-authored)
   │  e.g. discussion.md │
   └──────────┬──────────┘
              │
              ▼
   ┌─────────────────────┐
   │   producer pipeline │
   │   (agent + AIP      │  ← agent guided by AIP skill; scripts/
   │    skill + scripts) │     validate.py as final check
   └──────────┬──────────┘
              │
              ▼
   ┌─────────────────────┐
   │     Instruction     │  ← folder; SKILL.md body validated against
   │  (SKILL.md body +   │     team's JSON Schema (deliberation /
   │   schema/ + source/)│     spec / runbook / …)
   └──────────┬──────────┘
              │
              │   ─── stop here if no DB needed ───
              │
              ▼
   ┌─────────────────────┐
   │   connector         │  ← aip-neo4j (reference) | aip-postgres | …
   │   - validates       │
   │   - applies schema  │     (constraints/indexes if not exist)
   │   - ingests         │
   │   - reads back      │     (round-trip to YAML)
   └──────────┬──────────┘
              │
              ▼
   ┌─────────────────────┐
   │    storage          │  ← analysis, governance, cross-doc
   │  (Neo4j / SQL / …)  │     reasoning, training data
   └─────────────────────┘
```

The two arrows OUT of the connector matter equally: ingest (YAML →
DB) and read-back (DB → YAML). Neither is privileged. The
round-trip requirement (Principle 2) makes the connector a
bidirectional adapter, not a one-way ETL.

## Mapping rules

Vendor-neutral. The connector implements them; the schema doesn't
declare them.

### Rule set

| What's in the schema                                              | Becomes in storage                                                            |
|-------------------------------------------------------------------|-------------------------------------------------------------------------------|
| Each entry in top-level `$defs`                                   | A node type, label = `$def` name (e.g. `$defs.item` → `:Item`)                |
| The root schema itself                                            | A `:Document` node (single label, regardless of schema)                       |
| Property whose value is a `$ref` to a `$def`                      | Edge from parent → child node; default edge name = `HAS_<UPPERCASE_PROPERTY>` |
| Property whose value is `additionalProperties: {$ref: ...}` (map) | Edge per map entry; map key stored as `key:` property on child                |
| Property whose value is a list of `$ref`s                         | Edge per list item; index stored as `idx:` property on child                  |
| Property with primitive type (string/number/bool)                 | Property on the parent node                                                   |
| Property with list of primitives                                  | List property on the parent node                                              |
| Property with inline object (no `$ref`, no nested `$defs`)        | Property on parent, JSON-serialized                                           |
| Property with `oneOf` of mixed shapes                             | Property on parent, JSON-serialized                                           |
| Property with `additionalProperties: {type: 'string'}`            | Property on parent, JSON-serialized                                           |

### Reserved property names (mapper-injected)

These names are reserved on every node and must be preserved
round-trip:

- `id` — canonical node id (path-derived stable string)
- `schemaId` — declares which schema this node belongs to.
  Connector-derived from the Instruction's `metadata.aip.schemaId`
  (or, equivalently, from the resolved schema's own `$id`) — never
  declared in the schema or written into the body.
- `key` — for nodes reached via a map (preserves original YAML key)
- `idx` — for nodes reached via a list (preserves original YAML order)
- `_source` — optional path to the source markdown for the root doc

Schemas must not define properties with these names anywhere.
Enforced by `scripts/validate_schema.py`.

### Edge naming

Default: `HAS_<UPPERCASE_SINGULAR_PROPERTY_NAME>`. Pluralization is
naive — drop trailing `s` if present and not `ss`. Examples:

- `properties.items` → `[:HAS_ITEM]`
- `properties.options` → `[:HAS_OPTION]`
- `properties.lean` → `[:HAS_LEAN]`
- `properties.glossary` → `[:HAS_GLOSSARY]` (no de-pluralization;
  acceptable imperfection)

The literal-vs-de-pluralized choice is a connector decision, not a
schema decision. Different connectors may choose differently; the
round-trip mechanism must record which was used so the reverse
mapper can invert it. (See [Round-trip §Edge name preservation](#round-trip-mechanics).)

### Cross-doc references

A property whose value is a path-string to another markdown source
becomes a cross-doc edge if-and-only-if the connector can detect this.
Today, the only schema-recognized cross-doc reference shape is the
top-level `refs:` map (slug → path). The connector creates
`[:REFERENCES {slug}]` edges to `:Document` nodes (creating stub
Documents for not-yet-ingested targets, upgrading them in place when
those targets are later ingested).

Intra-doc references (e.g., `lean.pick: "1a"` referring to a sibling
option key) are NOT mapped to edges by the convention-based rules.
The string stays as a property; consumers join in the query layer if
needed. This is the price of zero schema annotations.

## Round-trip mechanics

Two-way mapping is the second non-negotiable principle. The
connector must support both directions; the read-back must produce
YAML that re-parses to the same data structure as the original ingest.

### What's preserved

- All values (strings, numbers, booleans, nulls)
- All map keys (via `key:` property on child nodes)
- All list orderings (via `idx:` property on child nodes)
- All nested structure (via either node-children or JSON-serialized
  blob properties)
- Schema declaration (`schema:` field on root)

### What's NOT preserved

- Comments
- Whitespace / indentation choices
- Block-scalar vs flow-scalar string formatting
- YAML anchor/alias references (resolved at parse time)

These are acceptable losses. If byte-equality matters for a use case,
keep the original YAML on disk (linked via `_source` property).

### Edge name preservation

To round-trip `properties.items` ↔ `[:HAS_ITEM]`, the connector must
record which property name produced which edge name. Two options:

- **Option A: derive both directions from the same rule.** If
  `HAS_ITEM` is always derived from `items` by a deterministic
  transform, the reverse just inverts the transform. Risk: ambiguous
  (does `HAS_DATA` come from `data` or `datas`?).
- **Option B: store the source property name on the edge.** Each
  edge carries an `_yaml_property: items` property. Reverse mapper
  uses it directly. Cost: edge bloat.

→ See [Open Questions §2](#open-questions). Both options are
implementable; pick one before connector v1.

### List-vs-map disambiguation

A child reached via a list has `idx:` (no `key:`). A child reached
via a map has `key:` (no `idx:`). Reverse mapper uses the presence
of one or the other to reconstruct the right YAML container.

Edge case: a property that's a single object (not a list, not a map)
produces a child with neither `idx:` nor `key:`. Reverse mapper
recognizes this as a singleton property.

### Source markdown round-trip

The source markdown is its own `:Document` node, with
`schemaId: 'source-markdown'` (or similar — TBD). Linked from the
Instruction's `:Document` via an optional `[:DERIVED_FROM]` edge. The
markdown content lives on the source `:Document.content` property.
Round-trip writes the markdown back to the path stored in
`source._path`.

Source ingest is opt-in per producer invocation. (Every Instruction
has a `source/` directory per §Instruction format, but the connector
may choose to ingest the Instruction body alone — no source node,
no `[:DERIVED_FROM]` edge.)

## Reference connector: Neo4j (`aip-neo4j`)

> This connector lives in the `aip-neo4j` package, not in this repo.
> Its design is specified here as the reference implementation of the
> connector interface.

### Graph shape

- **Root node**: single `:Document` label. Properties: `id`,
  `schemaId`, `status`, `title`, `_source` (path), `indexed_at`,
  plus all primitive root-level YAML fields.
- **Child nodes**: per-`$def` labels (`:Item`, `:Option`, `:Lean`, …)
  with `schemaId` property (to disambiguate cross-schema label
  collisions). Properties: `id`, `schemaId`, `key` or `idx` as
  applicable, plus all primitive fields from the corresponding
  schema object.
- **Edges**: derived from property names per
  [§Edge naming](#edge-naming).
- **Cross-doc edges**: `[:REFERENCES {slug}]` from the root
  `:Document` to other `:Document` nodes (one per `refs:` entry).
- **Source markdown**: a `:Document {schemaId: 'source-markdown'}`
  node with full content under a fulltext index, linked from the
  Instruction via optional `[:DERIVED_FROM]`.

### Constraints (auto-generated from schema family)

The connector emits `CREATE CONSTRAINT … IF NOT EXISTS` for:

- `:Document.id` UNIQUE
- For each `$def` label: `id` UNIQUE
- Index on `:Document.schemaId`
- Index on `:Document.status`
- Fulltext on `:Document.content` (when `schemaId='source-markdown'`)

The mapper runs these once per ingest invocation; `IF NOT EXISTS`
makes them idempotent across runs.

### Mapper invocation (target shape)

```bash
mapper.py --schema       <path-to-json-schema> \
          --instruction  <path-to-instruction-skill-md> \
          [--source      <path-to-source-readme>] \
          [--connector neo4j] \
          [--neo4j-uri bolt://localhost --user … --password …] \
          [--emit-only]
```

Default behavior: connect to Neo4j, ensure constraints, validate
YAML, ingest. `--emit-only` produces Cypher to stdout instead of
applying. `--source` is optional.

(Today's mapper does emit-only; runtime apply is on the v0.1
roadmap.)

### Reverse mapper invocation (target shape)

```bash
mapper.py --reverse \
          --connector neo4j \
          --neo4j-uri bolt://localhost \
          --doc-id <document-id> \
          [--out <path>]
```

Reads the graph starting from the named `:Document`, walks all
descendant nodes, reconstructs the YAML, validates against the
schema (must round-trip), writes to stdout or `--out`. The reverse
mapper is part of v0.1 — it's how Principle 2 gets verified.

## The AIP skill

One skill lives in this repo: `aip`. It is coupled to `spec.md` —
when AIP conventions change, the skill updates in lockstep.

**SKILL.md** is agent-loaded knowledge, not an invocable command.
The agent reads it to understand how to help a user produce
Instructions. It encodes:

- What AIP is and when to use it
- The three usage scenarios (create Instruction without schema / with
  schema / author a schema) — see
  [cli-api.md § Usage scenarios](discussions/cli-api.md)
- Instruction folder structure — see
  [§Instruction format](#instruction-format)
- SKILL.md frontmatter and body conventions — see
  [§SKILL.md format](#skillmd-format)
- AIP schema conventions: required metadata keywords (`$schema`,
  `$id`, `title`, `description`, AIP namespace), reserved property
  names, and the strict-core / open-extensions pattern — enough for
  the agent to validate a schema in context before running a script.
  See [§AIP schema conventions](#aip-schema-conventions).
- Pointers to example schemas in `references/examples/`
- Schema discovery hints: where to look for existing schemas in a
  user's project or installed skills
- How to invoke `scripts/validate.py` and `scripts/validate_schema.py`
  as a final check before offering to install

**`scripts/`** contains the validation logic the agent (and CI)
actually runs:

- `validate.py` — loads an Instruction, reads `metadata.aip.schemaId`
  from frontmatter, resolves the schema in `schema/`, extracts the
  body's fenced YAML block, and validates it with `jsonschema`. Exits
  non-zero with structured error output on failure.
- `validate_schema.py` — validates a JSON Schema file against AIP
  conventions: required metadata keywords (`$schema`, `$id`, `title`,
  `description`), AIP namespace presence, reserved property names,
  strict-core pattern, and `$defs` naming. Exits non-zero with
  structured error output on failure.

Both scripts use [PEP 723](https://peps.python.org/pep-0723/) inline
dependency declarations and are run via `uv run` — isolated
environment, no install step:

```bash
uv run scripts/validate.py path/to/instruction/
uv run scripts/validate_schema.py path/to/schema.json
```

The compile, draft-schema, and install operations are things the
agent *does* as part of the conversational workflow — not sub-commands
of the skill.

### Walkthrough UX

`SKILL.md` instructs the agent to run a structured walkthrough when
helping a user produce an Instruction. The walkthrough has a fixed
entry, a depth-adapted middle, and a small set of always-confirm
checkpoints regardless of depth.

This UX is specific to the reference `aip` skill — it is not a
protocol-level constraint. Other AIP skill implementations may
choose different walkthrough shapes.

#### Entry sequence

At the start of every new Instruction:

1. **Confirm intent.** Agent acknowledges what the user wants to
   make and surfaces any ambiguity in plain language.
2. **Ask depth.** Single question, three options:
   - **Quick** (~2 min) — agent makes most decisions, shows result
     for review
   - **Balanced** (~5–10 min) — agent asks about the 3–5 most
     important structural choices
   - **Thorough** (~20+ min) — field-by-field collaboration
3. **Determine source materials path.** Three valid starting points:
   - User pastes/describes a doc inline
   - User points to an existing markdown file
   - User describes verbally → agent drafts `source/README.md` first
     as the canonical source

   Agent asks only when the answer isn't obvious from context.

#### Depth-adapted middle

The middle (schema discovery, body compilation, refinement) adapts
to the chosen depth:

- **Quick** — agent picks the most likely schema match, drafts the
  body, presents the result. Asks only the always-confirm
  checkpoints (below).
- **Balanced** — agent surfaces 3–5 key structural choices for user
  input (e.g., "deliberation vs. spec schema?", "should this be one
  Instruction or two?", "what's the primary axis of organization?",
  "for each significant section: freeform text or queryable
  structure?"). The last question — selective typing — is high
  leverage; it's the difference between an Instruction that
  compresses 40–60% below source and one that compiles larger than
  its source. See [§Value Proposition](#value-proposition) and the
  reference `aip` skill's `SKILL.md` for the heuristic.
- **Thorough** — agent walks through each significant field with the
  user before validating and presenting.

#### Validation failures: tiered recovery

When `validate.py` or `validate_schema.py` fails:

- **Trivial** (typos, obviously missing required field, formatting):
  agent silently retries with the fix.
- **Substantive** (semantic mismatch, schema doesn't fit content,
  structural conflict): agent surfaces the error in plain language
  plus its proposed fix and asks for confirmation before retrying.

Keeps signal-to-noise high — the user is interrupted only when their
judgment is actually needed.

#### Always-confirm checkpoints

Four points where the agent always confirms with the user,
regardless of depth setting:

1. **Chosen schema before compiling body.** Prevents wasted
   body-drafting effort if the user disagrees.
2. **`description` field text.** Show and confirm before finalizing
   — `description` is the only signal at skill discovery time (see
   [§SKILL.md format](#skillmd-format)), and the user knows their
   phrasing preferences better than the agent.
3. **Final Instruction preview before install.** Show the rendered
   `SKILL.md` (or a clean summary) so the user sees exactly what's
   about to land on disk.
4. **Install location.** Ask user-global (`~/.claude/skills/`) vs
   project-local (`./.claude/skills/`), with a default suggestion
   based on whether CWD is in a git repo (project-local when in a
   repo, user-global when not).

## Open Questions

### §1 — Connector interface contract

Every connector implements an interface. What's in it? Minimum sketch:

```
connector.setup_schema(json_schema) -> applies constraints/indexes
connector.ingest(json_schema, yaml_doc, [source_md_path]) -> writes
connector.read_back(doc_id) -> yaml_doc
connector.validate_round_trip(doc_id) -> bool
connector.delete(doc_id) -> bool
```

Open:

- Should setup be schema-driven (idempotent re-apply on every ingest)
  or one-time (separate command)? My lean: schema-driven and
  idempotent — fewer setup steps for end users.
- What's the error contract? Exception types? Result objects?
  Probably depends on host language; spec the abstract behaviors,
  not the concrete signatures.
- Does the interface mandate transactionality (all-or-nothing
  ingest)? Probably yes, but with an `--allow-partial` escape hatch
  for huge ingests. Pending.

This may end up as its own discussion doc.

### §2 — Edge name preservation strategy

Round-trip needs to recover the original YAML property name from the
edge. Options:

- **Deterministic transform** (`items ↔ HAS_ITEM` via a fixed rule).
  Risk: ambiguous (`data ↔ HAS_DATA`, but `datas ↔ HAS_DATA` too).
- **Store source property on edge** (`[:HAS_ITEM {_yaml_property:
  'items'}]`). Unambiguous, slight bloat.
- **Hybrid** (use deterministic transform for unambiguous cases;
  store override only when the inverse is ambiguous).

My weak lean: store on edge always. Bloat is small; ambiguity
prevention is reliable. But this is design-shaped enough that it
deserves its own discussion.

### §3 — Skill model: resolved

**Resolved 2026-05-16.** One skill: `aip` — agent-loaded knowledge,
not an invocable command. Compile, draft-schema, and install are
agent behaviors guided by this skill. See [§The AIP skill](#the-aip-skill).

### §8 — Schema discovery convention: resolved

**Resolved 2026-05-16.** Three-source discovery model: bundled
examples (`references/examples/`), project-local schemas
(`*.schema.json` under CWD, max depth 4, respect `.gitignore`,
filtered to those with a top-level `aip:` object), and installed AIP
Instructions (filtered to skills whose `SKILL.md` has
`metadata.aip.spec`). Dedup precedence: bundled > project-local >
installed. See [§Schema discovery](#schema-discovery).

### §4 — Source markdown schema

The source markdown becomes a `:Document` with what `schemaId`?
Options: `'source-markdown'`, `'raw-markdown'`, `'source'`,
`'human-prose'`. Pick a value and lock it; consumers will key on it.

Also: should the source markdown have a real JSON Schema (loose,
just `doc`/`schemaId`/`content`/`source_path`), or is it
schema-less? Probably the former for consistency — every Document
node should validate against some schema, even a minimal one.

### §5 — Repo extraction: resolved

**Resolved 2026-05-15.** Extracted. This repo (`aip`) is the canonical
AIP protocol resource. Reference compiler package: **aip**.
Connector packages (`aip-neo4j`, `aip-postgres`, …) are separate repos.

### §6 — Schema versioning

How does a schema version itself, and what happens when a schema
changes mid-corpus? Two approaches:

- Bake version into `schemaId` (`deliberation/v1`, `deliberation/v2`)
  — incompatible versions get separate label spaces.
- Separate `schemaVersion` field, mappers reject mismatches.

Out of scope for v0.1; flagging for v0.2.

### §7 — Two-way validation as a CI check

If a producer ingests, then reads back, then diffs against the
original YAML, any structural mismatch is a connector bug. Should
this round-trip diff be a default mapper check (slow but safe) or
an opt-in (`--verify-roundtrip`)? Lean: opt-in for performance, but
required in CI.

## Out of scope for v0.1

- Schema versioning / migration tooling (Open Q §6)
- Cross-schema reference declarations (e.g. `spec.derived_from →
  deliberation`) — placeholder reserved in schema design, mapper
  doesn't act on it yet
- Real-time graph subscriptions / incremental ingest
- A second connector (Postgres, DuckDB) — needed to validate the
  vendor-neutral claim, but v0.1 ships with Neo4j only
- Lossless-mode storage (the `context:` TAIL has no graph
  representation)
- Authoring UI / web tooling
- Multi-tenant / access control

## Future direction

- **Schema family expansion.** Spec, release, runbook, ADR,
  post-mortem, incident schemas — each gets a standalone schema
  file, validates the same way, ingests via the same connector.
- **Cross-schema edges.** Once two schemas exist that conceptually
  reference each other (`spec.derived_from → deliberation`), the
  connector can recognize the field and create a typed edge.
  Requires a small extension to the convention rules — a designated
  property name (e.g., `_ref:` or `derived_from:`) that the connector
  treats as a reference, even though the schema declares it as a
  string.
- **Additional connectors.** Postgres, DuckDB, DynamoDB, in-memory.
  Reference impl validates the interface; alt-impls stress-test it.
- **Process meta-analysis.** Once a corpus exists with full
  schema-family coverage, queries like "did deliberations whose
  lean was followed ship faster than ones overridden mid-flight"
  become real. This is the long-term payoff.
- **Schema marketplace.** Teams publish their schemas; other teams
  fork or adopt. Cross-org learning. Requires the vendor-neutral
  guarantee to actually deliver.

## Glossary

- **Instruction** — the deliverable AIP produces. A folder conforming
  to the [Agent Skills spec](https://agentskills.io/specification),
  extended with AIP-required `schema/` and `source/` directories. See
  [§Instruction format](#instruction-format). Produced from
  human-prose source by the AIP skill.
- **Instruction body** — the YAML-compliant content of an
  Instruction's `SKILL.md`, contained in a single fenced YAML code
  block in the body. What the schema validates and what connectors
  ingest. See [§SKILL.md format](#skillmd-format).
- **`metadata.aip.spec`** — required `SKILL.md` frontmatter field. URL
  to the AIP spec version the Instruction conforms to. Makes the
  Instruction self-describing to AIP-unaware agents. See
  [§SKILL.md format](#skillmd-format).
- **`metadata.aip.schemaId`** — required `SKILL.md` frontmatter field.
  UUID URN matching the `$id` of the schema in the Instruction's
  `schema/` directory. The body itself does not repeat `schemaId`;
  consumers extracting the body alone must read the frontmatter for
  schema linkage. See [§SKILL.md format](#skillmd-format).
- **AIP-compliant schema** — a JSON Schema that follows AIP
  conventions: required root-level metadata keywords (`$schema`,
  `$id`, `title`, `description`, plus an `aip:` namespace for
  AIP-specific metadata), no reserved property names, strict-core /
  open-extensions pattern. What teams produce with agent assistance;
  what `scripts/validate_schema.py` checks. See
  [§AIP schema conventions](#aip-schema-conventions).
- **aip skill** — the reference implementation of AIP. A Claude Code
  skill (`~/.claude/skills/aip/`) containing SKILL.md (agent
  knowledge) and `scripts/` (validation scripts run via `uv run`).
  No separate binary installation required.
- **Connector** — a per-database adapter (separate package: `aip-neo4j`,
  `aip-postgres`, …) that implements the vendor-neutral mapping rules.
- **Mapping rules** — vendor-neutral conventions for projecting a
  schema-validated YAML into storage. Specified here; implemented per connector.
- **Producer** — the team / pipeline that authors and validates
  Instructions using the AIP skill.
- **Round-trip** — the cycle YAML → storage → YAML, where the
  reconstructed YAML re-parses to the same data structure.
- **Schema** — a JSON Schema declaring the shape of one doc type,
  authored by a team to follow AIP conventions.
- **Source markdown** — the original human-prose document; optional
  ingest target.

## Change log

- **2026-05-17** — Dropped the body-root `schemaId` requirement.
  Frontmatter `metadata.aip.schemaId` is now the single source of
  truth; the body no longer repeats it. Schemas may not declare
  `schemaId` anywhere (the previous root-properties exception is
  removed). Connector derives storage-node `schemaId` from
  frontmatter at ingest time. Reduces authoring redundancy at the
  cost of body-alone self-description — consumers extracting the
  YAML body without the surrounding SKILL.md must read frontmatter
  for schema linkage. Updated §SKILL.md format → Body section,
  §AIP schema conventions → required structural conventions,
  §Mapping rules → reserved property names, and the glossary entry
  for `metadata.aip.schemaId`. Validators (`validate.py`,
  `validate_schema.py`) updated to match.

- **2026-05-16 (session 6)** — Added §Schema discovery (new
  top-level section): three-source model — bundled examples,
  project-local schemas, and installed AIP Instructions — with
  filters that reuse session 5 metadata requirements (`metadata.aip.spec`
  on `SKILL.md` and the top-level `aip:` object on schemas both
  serve as "is this AIP?" filters). Dedup precedence
  bundled > project-local > installed; project-local scan depth
  capped at 4. Marks Open Q §8 resolved. Added §The AIP skill →
  ### Walkthrough UX subsection: fixed entry (confirm intent →
  depth selector → source materials path), depth-adapted middle
  (Quick / Balanced / Thorough), tiered validation recovery, and
  four always-confirm checkpoints regardless of depth (chosen
  schema, `description` text, final preview, install location).
  This UX is explicitly scoped to the reference `aip` skill, not the
  protocol.
- **2026-05-16 (session 5)** — Expanded §AIP schema conventions with
  a §Required metadata subsection (required root-level annotation
  keywords `$schema`, `$id`, `title`, `description`; AIP-specific
  metadata namespaced under a top-level `aip:` object; optional
  `aip.version` and `aip.tag`). Promoted existing rules to
  §Required structural conventions and added §Optional README.md
  guidance. Added new top-level §SKILL.md format section:
  frontmatter table including two new required AIP fields
  (`metadata.aip.spec` and `metadata.aip.schemaId`); body spec'd as
  exactly one fenced YAML code block; discovery and self-description
  considerations including the placeholder spec URL
  (`https://raw.githubusercontent.com/zach-blumenfeld/aip/main/spec.md`).
  Fixed §The AIP skill: removed stale `meta.yml` reference, pointed
  bullets to the new sections, updated validator descriptions to
  reflect the new Instruction folder layout and frontmatter fields.
  Synced directory diagram ordering (required dirs first). Added
  glossary entries for `metadata.aip.spec` and
  `metadata.aip.schemaId`; updated `AIP-compliant schema` and
  `Instruction body` entries.
- **2026-05-16 (session 4)** — Added §Instruction format: settled
  terminology (Instruction / schema / source), directory structure for
  an AIP Instruction (extension of the Agent Skills spec), AIP-specific
  required dirs (`schema/`, `source/`), and the open-extension property
  preserved at the root and inside `source/`. Reconciled terminology
  across the rest of the spec: "AIP-compiled document" → **Instruction**
  (the folder) and **Instruction body** (the validated YAML content of
  `SKILL.md`). Updated §What this is, §Non-negotiable principles 4 & 6,
  the compiler-analogy table, §Components A/B, the architecture
  diagram, §Source markdown round-trip, the Neo4j graph shape, the
  mapper invocation example, §The AIP skill, and the glossary
  (Instruction + Instruction body now two distinct entries).
- **2026-05-16 (session 3)** — Updated to reflect: (1) no separate
  CLI binary — validation is `scripts/validate.py` and
  `scripts/validate_schema.py` bundled inside the `aip` skill, run
  via `uv run`; (2) skill model: one `aip` skill (SKILL.md = agent
  knowledge, `scripts/` = validation tooling); (3) compile,
  draft-schema, and install are agent behaviors guided by the skill,
  not separate commands; (4) three usage scenarios documented in
  `cli-api.md`; (5) schema discovery added as open question §8.
- **2026-05-15 (session 2)** — Updated to reflect: (1) CLI name
  `aip`; (2) schemas in `examples/` are team-produced AIP-compliant
  examples, not the protocol itself — AIP uses standard JSON Schema;
  (3) connectors are separate packages (`aip-neo4j`, …); (4) closed
  open questions §3 and §5.
- **2026-05-15 (session 1)** — Initial draft. Captured: two-purpose
  framing, six non-negotiable principles, mapping rule set, Neo4j
  reference connector spec, seven open questions.
