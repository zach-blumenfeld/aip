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
| Build artifact           | Agent-readable companion file                          |
| Source preservation      | Human doc stays canonical (.c isn't deleted after .o)  |

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
- **An AIP-compiled document** (validated against its declared schema)
  accompanies each human-prose source. Same content, restructured for
  AI ingestibility. The human doc stays canonical for humans; the
  compiled document is the machine-readable face.
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

4. **Source documents are optional.** A producer can ingest an
   AIP-compiled YAML alone, or include the original markdown source
   as a linked Document. The DB carries no opinion either way.

5. **Strict-core, open-extensions schemas.** Every object in a schema
   has a closed key set, plus an optional `extensions:` map for
   doc-specific structure that doesn't fit. Predictability without
   brittleness.

6. **Lossy is the only ingest mode.** AIP-compiled files in lossless
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

**Required conventions:**

- Schemas must not define properties using AIP-reserved names: `id`,
  `schemaId`, `key`, `idx`, `_source`. These are injected by the
  connector at ingest time.
- The root schema must follow the strict-core / open-extensions
  pattern: a closed key set plus an optional `extensions:` map.
- `$defs` entries become node types in storage; each must have a
  clearly-named key (becomes the node label).

**The `examples/schemas/` directory** (`deliberation.schema.json`,
`generic.schema.json`) contains reference schemas that demonstrate
these conventions — they are not part of the AIP protocol itself.

## Components

### A. AIP-compiled documents

The output of the `compile` skill — a YAML document validated against
a team's AIP-compliant schema. This is what agents read and what
connectors ingest.

### B. Producer pipeline (human → AIP-compiled document)

Two paths:

- **Agent path (primary).** A human writes prose; the agent — guided
  by the AIP skill — compiles it into the AIP-compiled companion.
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
(e.g. as a final check before offering to install a compiled skill).
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
   │   AIP-compiled doc  │  ← validated against team's JSON Schema
   │   (schema-validated │     (deliberation / spec / runbook / …)
   │    YAML)            │
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
- `schemaId` — declares which schema this node belongs to
- `key` — for nodes reached via a map (preserves original YAML key)
- `idx` — for nodes reached via a list (preserves original YAML order)
- `_source` — optional path to the source markdown for the root doc

Schemas must not define properties with these names. (Add to the
strict-core schema validator as a future enforcement check.)

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
companion's `:Document` via an optional `[:DERIVED_FROM]` edge. The
markdown content lives on the source `:Document.content` property.
Round-trip writes the markdown back to the path stored in
`source._path`.

Source ingest is opt-in per producer invocation. Some YAMLs have no
sibling markdown (agent-authored) and that's fine — no source node,
no `[:DERIVED_FROM]` edge.

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
  companion via optional `[:DERIVED_FROM]`.

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
mapper.py --schema   <path-to-json-schema> \
          --rewrite  <path-to-ai-companion-yaml> \
          [--source <path-to-original-markdown>] \
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
AIP-compliant skills and documents. It encodes:

- What AIP is and when to use it
- The three usage scenarios (create skill without schema / with schema
  / author a schema) — see [cli-api.md § Usage scenarios](discussions/cli-api.md)
- Output format: SKILL.md folder structure, frontmatter requirements,
  `references/` and `meta.yml` conventions
- AIP schema conventions (reserved property names, strict-core /
  open-extensions pattern) — enough for the agent to validate a schema
  in context before running a script
- Pointers to example schemas in `references/examples/`
- Schema discovery hints: where to look for existing schemas in a
  user's project or installed skills
- How to invoke `scripts/validate.py` and `scripts/validate_schema.py`
  as a final check before offering to install

**`scripts/`** contains the validation logic the agent (and CI)
actually runs:

- `validate.py` — loads a document, reads its declared `schema:` field,
  fetches or resolves the schema, validates with `jsonschema`. Exits
  non-zero with structured error output on failure.
- `validate_schema.py` — validates a JSON Schema file against AIP
  conventions (reserved property names, strict-core pattern, `$defs`
  naming). Exits non-zero with structured error output on failure.

Both scripts use [PEP 723](https://peps.python.org/pep-0723/) inline
dependency declarations and are run via `uv run` — isolated
environment, no install step:

```bash
uv run scripts/validate.py path/to/doc.yml
uv run scripts/validate_schema.py path/to/schema.json
```

The compile, draft-schema, and install operations are things the
agent *does* as part of the conversational workflow — not sub-commands
of the skill.

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

### §8 — Schema discovery convention (open)

For the most common usage scenario (user wants to create a skill,
no schema specified), the agent must know what schemas already exist
and offer informed suggestions. Three sources need discovery
conventions:

1. **AIP example schemas** — bundled in `examples/schemas/` and
   exposed via the AIP skill. Solved by the skill itself.
2. **Project-local schemas** — agent scans for `*.schema.json` files
   in the current working directory tree. Convention not yet
   specified: depth limit? ignore paths? naming requirements?
3. **Schemas in installed skills** — a skill folder may embed a
   schema it was compiled against. Convention for where this lives
   inside the folder (e.g., `references/schema.json`?) is not yet
   defined.

Until this is resolved, the AIP skill cannot fully implement Scenario 1.
This likely needs its own discussion doc before the skill can be
written.

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

- **AIP-compiled document** — the YAML doc validated against a
  team's AIP-compliant schema, produced from a human-prose source by
  the `compile` skill.
- **AIP-compliant schema** — a JSON Schema that follows AIP
  conventions (no reserved property names, strict-core /
  open-extensions pattern). What teams produce with agent assistance;
  what `scripts/validate_schema.py` checks.
- **aip skill** — the reference implementation of AIP. A Claude Code
  skill (`~/.claude/skills/aip/`) containing SKILL.md (agent
  knowledge) and `scripts/` (validation scripts run via `uv run`).
  No separate binary installation required.
- **Connector** — a per-database adapter (separate package: `aip-neo4j`,
  `aip-postgres`, …) that implements the vendor-neutral mapping rules.
- **Mapping rules** — vendor-neutral conventions for projecting a
  schema-validated YAML into storage. Specified here; implemented per connector.
- **Producer** — the team / pipeline that authors and validates
  AIP-compiled documents using the `compile` skill.
- **Round-trip** — the cycle YAML → storage → YAML, where the
  reconstructed YAML re-parses to the same data structure.
- **Schema** — a JSON Schema declaring the shape of one doc type,
  authored by a team to follow AIP conventions.
- **Source markdown** — the original human-prose document; optional
  ingest target.

## Change log

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
