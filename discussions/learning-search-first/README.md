# Learning: compiling the `search-first` runbook

> **Status: settled — next direction for AIP.** 2026-05-16.
>
> First end-to-end AIP compile of a hand-authored runbook-shape
> skill. The initial compile produced an artifact *larger* than the
> source and harder to use; the second attempt (selective typing —
> see Attempt 3) hit the spec's claimed 40–60% reduction and is
> sharper than the source for agent consumption. The unlock is
> **selective decomposition**, not heavier schema machinery.

## What triggered this

A real compile end-to-end: `scratch/productivity-skill.md`
([copied here as `source.md`](source.md)) — a hand-authored
"search-before-you-code" runbook — became the AIP Instruction at
`.claude/skills/search-first/` ([SKILL.md copied here as
`attempt-2-aip-skill.md`](attempt-2-aip-skill.md), schema as
[`attempt-2-aip-schema.json`](attempt-2-aip-schema.json)).

Both validators passed (after fixing the `schemaId` reserved-names
contradiction — commit `afe91bf`). But the result surprised:

1. The compiled `SKILL.md` was **larger** than the source.
   `spec.md` §Value Proposition predicts 40–60% reduction.
2. Asked which artifact was easier to use, an LLM consumer
   preferred the markdown. Heading navigation, the markdown
   decision-matrix table, and the ASCII workflow diagram were real
   cognitive aids the YAML form lost.

That prompted the deeper question: is AIP over-engineered for
runbook-shape skills, or is the schema design wrong?

## The three attempts

| Attempt | File | Chars | Δ vs source |
|---|---|---:|---:|
| 0 | [`source.md`](source.md) | 7,909 | — |
| 1 | [`attempt-1-naive-yaml.yml`](attempt-1-naive-yaml.yml) — headings → keys, tables/diagrams dropped in as `\|`-block text (body only, no skill wrapping) | 7,846 | −0.8% |
| 2 | [`attempt-2-aip-skill.md`](attempt-2-aip-skill.md) — full AIP compile in SKILL.md format (typed records everywhere, AIP frontmatter, body `schemaId`) | 8,241 | **+4.2%** |
| 3 | [`attempt-3-runbook-skill.md`](attempt-3-runbook-skill.md) — selective typing in SKILL.md format (light Agent-Skills frontmatter; typed where queryable/actionable, text elsewhere) | **4,824** | **−39%** |

Attempt 3 is the next direction. The body alone is 4,606 chars
(selective-typing YAML); wrapping it as a SKILL.md adds 218
chars of frontmatter — apples-to-apples with Attempt 2's 8,241. Attempt 1 is the floor: a deterministic markdown-to-YAML
conversion is essentially free in size and gives
key-addressability, but it's not a skill (no frontmatter, no
discovery). Attempt 2 is the cautionary tale: rigid full-typed
schema *increases* size for already-tight source.

## What we learned

### 1. The 40–60% compression claim is real — but only with selective typing

`spec.md` §Value Proposition needs qualification. Compression
depends on the source AND the schema design:

- Prose-heavy source + any reasonable schema → compression real.
- Tight, already-structured source + rigid full-typed schema →
  compression negative.
- Tight, already-structured source + selective typing → compression
  real (−42% in this test).

The factor the spec missed: schema-design discipline can swing the
compression ratio by 50+ points on the same source.

### 2. Selective decomposition is the discipline

The principle from Attempt 3: **decompose where decomposition adds
query or action value; leave text where structure isn't earning
its way.**

Where typing earned its keep in Attempt 3:

- **`steps`** — the ASCII workflow diagram was *gesturing* at
  structure (5 named phases with a parallel branch in step 2 and
  a `one_of` in step 4). As a list of `{id, do, parallel?,
  one_of?}` objects it's clearer than the ASCII *and* smaller.
- **`decisions`** — `{when, then}` pairs are barely longer than
  the markdown table row, and they're directly actionable by an
  agent without re-parsing prose.
- **`examples`** — `{need, found, action}` dropped the verbose
  `search:` and `result:` fields without losing meaning.

Where typing would have *cost* us — kept as `|`-block text:

- **`shortcuts`** — `Linting → eslint, ruff, ...` is denser as
  text than as `{need, candidates}` records. Honest read: this
  is freeform reference content, not workflow.
- **`modes.quick` / `modes.full`** — terse text blocks preserve
  the source's voice and are smaller than decomposed step lists.
- **`integrations`** — one-line strings per partner. Cheaper than
  a typed object with `with`/`howToCombine` keys.

The judgment call: would the agent ever `for` over this field, or
filter/query by one of its sub-fields? If yes, type it. If no,
leave it as text.

### 3. Other savings in Attempt 3

Not from schema; from honest editing:

- Dropped the duplicated "When to Use This Skill" section that
  overlapped `trigger`.
- Tightened `scope` from two paragraphs to one.
- Removed AIP frontmatter overhead (no `metadata.aip.spec`,
  no body `schemaId`).
- Compressed `modes` from sectioned prose to two text blocks.
- Compressed `integrations` from prose paragraphs to one-line
  strings.

A solid chunk of the 42% came from these. The schema discipline
*enabled* the editing — once the structure is explicit, redundant
prose is visible.

## Proposed runbook standard (the next thing we're building)

The skill is split between Agent-Skills frontmatter (for
discovery) and a fenced YAML body (the runbook):

```
Frontmatter (Agent Skills spec):
  Required: name, description
  Optional: license, compatibility, allowed-tools, metadata.*

Body (fenced YAML — the runbook):
  Required: trigger, steps
  Optional: scope, decisions, modes, shortcuts, integrations,
            examples, anti_patterns
```

`name` covers what the body's `title` would; `description`
covers what the body's `summary` would. Both jobs already in
frontmatter — no redundancy in the body.

**Type discipline:** lists-of-objects only where the agent would
`for`/filter by a sub-field (`steps`, `decisions`, `examples`).
Text under any leaf where structure isn't earning. Tables and
ASCII diagrams go into `|`-blocks without apology.

**Authoring discipline:** treat the YAML body as the agent-form.
The `source/README.md` (when present) stays canonical for humans.
Don't try to make the YAML readable as a doc — make it terse and
queryable.

This is a one-screen schema, easy to read, easy to validate. The
frontmatter is pure Agent Skills spec — no AIP-specific fields
required. AIP metadata (`metadata.aip.spec`,
`metadata.aip.schemaId`) only when a database consumer is
actually in play. Strictly additive to plain markdown skills.

## What this means for AIP next

1. **§Value Proposition needs qualification.** Add a paragraph:
   "Compression claims assume both prose-heavy source AND
   selective-typing schema discipline. Tight source + rigid
   typing can produce negative compression. See
   [learning-search-first](discussions/learning-search-first/)."

2. **The current `runbook.schema.json` (Attempt 2's schema) is
   over-engineered.** It types `shortcuts`, `modes` steps,
   `integrations`, and `examples` more heavily than pays off.
   Replace with a permissive runbook schema modeled on
   Attempt 3's shape.

3. **The Walkthrough UX in `spec.md` §The AIP skill needs a
   selective-typing prompt.** The current Balanced-depth
   walkthrough surfaces "deliberation vs spec schema?" — it
   should also surface "for each section: is this freeform text
   or queryable structure?" That's the high-leverage decision.

4. **Runbook-shape skills are IN scope.** The earlier instinct
   to push them out (see prior version of this doc) was
   premature — the problem was schema design, not the case fit.

## Open questions

### §1 — How to communicate the selective-typing judgment to authors

The AIP skill's Walkthrough UX needs a section-by-section prompt:
"text or typed?" with a heuristic ("would the agent iterate or
filter by a sub-field of this section? type it. otherwise: text").
A handful of worked examples in `spec.md` showing good vs bad
decomposition would help.

### §2 — Does this need a separate "runbook" schema, or one schema with more permissive typing?

Two options:

- **One schema per doc type, terse**: ship `runbook.schema.json`
  modeled on Attempt 3. Future doc types (deliberation, spec,
  post-mortem) get their own equally terse schemas. Schema is the
  type discipline; authors just use it.
- **One schema with optional everything**: ship a single
  permissive schema where almost every field is optional and any
  leaf can be string-or-structured. Authors decide field-by-field.

Lean: option 1. Schemas earn their keep by being opinionated.

### §3 — Compile a prose-heavy source next

This whole exercise was one runbook-shape source. Compile a real
deliberation or spec next — the other side of the compiler
analogy. Hypothesis: selective-typing schema will hit 50–70%
reduction there, since prose has more removable scaffolding.

### §4 — How does the connector see freeform text fields?

If `shortcuts:` is a `|`-block string in the body, the graph
projection treats it as a single property on the `:Document`
node. That's fine — searchable via fulltext if the connector
indexes it; not decomposable into typed records. The mapping
rules in `spec.md` §Mapping rules already cover this case
("Property with primitive type → Property on the parent node").
No spec change needed; just a doc note explaining the
text-vs-typed tradeoff at storage time.

## Artifacts

- [`source.md`](source.md) — hand-authored runbook source (the
  starting point)
- [`attempt-1-naive-yaml.yml`](attempt-1-naive-yaml.yml) —
  heading-to-key 1:1 translation; body only, no skill wrapping;
  ~same size as source
- [`attempt-2-aip-skill.md`](attempt-2-aip-skill.md) — full AIP
  compile per current spec; SKILL.md format; +4.2% over source
- [`attempt-2-aip-schema.json`](attempt-2-aip-schema.json) —
  the over-engineered runbook schema produced for Attempt 2
- [`attempt-3-runbook-skill.md`](attempt-3-runbook-skill.md) —
  selective-typing runbook shape in SKILL.md format (light
  Agent-Skills frontmatter + fenced YAML body); **−39% (the
  next direction we're building)**
