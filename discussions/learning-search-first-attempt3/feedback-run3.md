# AIP feedback — run 3

## Issue: validators were not run

In this session I compiled `productivity-skill.md` into a `search-first` AIP
Instruction, then iterated on the schema (renamed `id` → `name` in `steps`).
I did **not** run the AIP validators in either pass. The user had to ask
"did you run the validator?" before I executed them.

When I finally ran them:

- `validate.py` on the Instruction: **VALID** (no real issue)
- `validate_schema.py` on the schema: **INVALID** — `missing_aip_namespace`.
  I had nested the AIP marker under `metadata.aip` instead of putting `aip`
  at the schema root. A real bug, caught only because the user prompted.

### Two instances, same root cause

1. **Initial compile.** The user said "do not discover resources outside
   this folder. We are testing how we do without it." I interpreted that
   broadly to include the validators bundled inside `.claude/skills/aip/`,
   even though those live *inside* the folder. I substituted a manual eyeball
   check ("required fields present, single fenced YAML block") and declared
   the draft safe. The schema bug slipped through.

2. **Schema edit.** No scope restriction was in play here — I simply
   forgot. After renaming `id` → `name` in two files, I reported "two-file
   change, kept in sync" and stopped. Re-validation never entered the plan.

The first case is a *scope-interpretation* failure; the second is a
*habit* failure. Both result in the same thing: shipping unvalidated
artifacts.

## What the aip skill currently says

From `SKILL.md`:

> **Scenario 1:** `validate.py` on the compiled Instruction before install.
> **Scenario 2:** `validate_schema.py` on the user's schema first; `validate.py` on the result before install.
> **Scenario 3:** `validate_schema.py` on each draft iteration.

And in "Draft and install":

> 3. Run `uv run scripts/validate.py /tmp/aip-draft-<name>/` as the smoke check.

Gaps that allowed me to skip:

- **Scenario 1 says nothing about validating a freshly-drafted schema.**
  When schema reuse fails and I draft a new one (as I did here), the
  skill only prescribes `validate.py` on the *Instruction*. But
  `validate.py` validates the body against the schema, not the schema
  against AIP spec — so a non-compliant schema passes silently if the
  body happens to fit it. Scenario 3 covers schema validation, but I was
  in a Scenario-1 flow that drifted into schema authoring without
  picking up Scenario 3's rules.
- **No "after every edit" rule.** Validation language is scoped to the
  initial compile ("before install", "smoke check"). Once a skill is
  installed, edits like my `id` → `name` rename have no prescribed
  validation step.
- **No carve-out for bundled tooling under scope restrictions.** When a
  user restricts scope, the skill doesn't tell the agent that its own
  validators are still in-scope.

## Recommended fix to the aip skill

Three small edits to `.claude/skills/aip/SKILL.md`:

### 1. Make validation non-optional after every write

Replace the conditional "When to invoke" list with a rule keyed on the
write, not the scenario:

> **Run the validator after any write to a draft or installed
> Instruction or schema** — initial compile, schema authoring, post-
> install edits, all of them.
>
> - After writing/editing a schema file → `validate_schema.py <file>`.
> - After writing/editing a `SKILL.md` or an Instruction folder →
>   `validate.py <folder>`.
> - If both changed in the same turn, run both.
>
> Don't substitute manual review. The validators take ~1 second; an
> eyeball check is not equivalent and routinely misses
> AIP-namespace and required-metadata bugs.

### 2. Cover the Scenario-1-becomes-Scenario-3 case

Add to Scenario 1:

> If schema reuse fails and you draft a new schema, you've entered
> Scenario 3 for that artifact. Run `validate_schema.py` on the new
> schema before compiling the body against it — `validate.py` on the
> compiled Instruction does not catch schema-side AIP-compliance bugs.

### 3. Scope-restriction carve-out

Add to the anti-patterns list:

> **Don't treat the bundled validators as out-of-scope under user
> scope restrictions.** When the user restricts external resources or
> says "do it without X," the AIP validators in this skill's `scripts/`
> are part of the skill's contract, not third-party resources. Run them
> anyway, and surface to the user that you are doing so.

---

## Issue 2: selective-typing guidance is under-specified for plural fields

While iterating on the schema, the user proposed: *"any property with a
plural name should be a list, with items as block text."* I initially
flagged the issue that anonymous block-text items lose their labels
(`## Quick mode` etc. become parse-only). We landed on a refined rule
that the aip skill should adopt.

### What I'd originally done

In the first compile, I left `modes`, `search_shortcuts`, and
`integrations` as single freeform `|`-blocks. The selective-typing
heuristic in the aip skill ("would the agent ever `for` over this
section?") said leave them as strings — which is *defensible*, but
ignores a separate axis: plural-named fields read more naturally as
lists, even when each item's body stays as prose.

### The refined convention

> **Plural fields are lists.** If items have a natural label, give them
> a thin `{label, body}` envelope; if items are already single-line
> strings (e.g., `integrations`, `anti_patterns`, `triggers`), they're
> a list of strings.

Applied to this skill:

| Field | Before | After |
|---|---|---|
| `modes` | `\|`-block prose | `[{name, body}, ...]` — labels: `quick`, `full` |
| `search_shortcuts` | `\|`-block prose | `[{category, body}, ...]` — labels: `Development Tooling`, `AI / LLM Integration`, etc. |
| `integrations` | `\|`-block prose | `[string, ...]` — items already one-liners |

The bodies stay as `\|`-block prose inside the envelope. No re-encoding
of tight markdown into typed records.

### Token impact

Measured with `tiktoken` (`cl100k_base`):

| Version | Tokens | Δ from source | Δ from prev |
|---|---:|---:|---:|
| `productivity-skill.md` (source) | 1,671 | — | — |
| `SKILL.md` after initial compile | 1,370 | −18% | baseline |
| `SKILL.md` after `id` → `name` rename | 1,370 | −18% | 0 |
| `SKILL.md` after list envelopes | 1,389 | −17% | +19 |
| `SKILL.md` after completeness restoration (Issue 4) | 1,563 | −6.5% | +174 |
| `SKILL.md` after collapsing to `trigger_when` | 1,563 | −6.5% | 0 |

The `{name, body}` and `{category, body}` envelopes added ~19 tokens
(~1.4%) over the single-`\|`-block version. The completeness
restoration (Issue 4) added ~174 tokens by reinstating `search`/
`result` example fields, full `integrations` sub-bullets (planner's 3,
architect's 3, iterative-retrieval's `Cycle 1/2/3`), and the
broader-context items absorbed into `trigger_when`. The honest
end-state sits ~6.5% under the markdown source.

Generalising: each `{label, body}` envelope adds roughly 8–12 tokens
of YAML scaffolding per item. For collections of 2–10 items the cost
is in the noise; for collections of 50+ items it starts to matter —
at that scale, prefer a flat `[string]` (with the label embedded as a
prefix) or split into multiple skills.

### The honest compression number

The aip skill's `SKILL.md` currently advertises that a well-authored
Instruction "compresses 40–60% below its markdown source while staying
agent-queryable." For this skill, the realised number is **~6.5%**.
The first compile *looked* like ~18%, but ~12 of those points came
from silently dropped source content — not from structural
compression. Once Issue 4's completeness restoration brought the
dropped content back, the compression ratio settled at ~6.5%.

This isn't a problem — 6.5% smaller than the source, while gaining
schema validation, queryable structure, and governance metadata, is a
clear win. But it suggests the aip skill's 40–60% claim is calibrated
on a different kind of source: prose-heavy material with significant
redundancy, narrative framing, or "telling" the reader things the
schema makes implicit. For *tight, already-structured* source
(markdown tables, ASCII workflow diagrams, terse bulleted lists like
`productivity-skill.md`), 5–15% is a more realistic expectation.

**Recommended addition to the aip skill's anti-patterns list:**

> **Don't quote the 40–60% compression range to authors of tight,
> already-structured source.** That figure assumes prose-heavy material
> where selective typing has room to eliminate redundancy. For source
> that's already dense (markdown tables, terse bulleted lists, ASCII
> diagrams), realistic compression is 5–15% — and if it looks bigger,
> first check for silently dropped content via the completeness
> checkpoint. The structural-fidelity floor for tight source is roughly
> "source size + envelope scaffolding − redundant prose."

### Why this beats both extremes

- **vs. single `\|`-block:** preserves the label as a queryable field
  (an agent or governance tool can ask "list all categories" or "pull
  the quick mode body") instead of forcing it into a markdown heading.
- **vs. fully typed records:** doesn't re-encode prose-shaped content
  (numbered checklists, categorised bullets) as YAML records. Avoids
  the negative-compression failure mode the aip skill already warns
  about.
- **vs. anonymous list of block-text items:** keeps the label
  accessible without re-parsing the body's markdown.

### Recommended addition to the aip skill

Append to the [Selective typing](#selective-typing) section of
`.claude/skills/aip/SKILL.md`:

> **Plural-named fields default to lists, not single `\|`-blocks.**
> The "would the agent iterate?" heuristic decides whether to *type*
> the body of each item; the plural name decides whether the field
> itself is a list. They're independent questions.
>
> - Items with a natural label → list of `{label, body}` thin envelopes
>   (`modes: [{name, body}]`, `search_shortcuts: [{category, body}]`).
>   Keeps the label queryable without re-encoding the body.
> - Items already single-line strings → list of strings
>   (`integrations`, `triggers`, `anti_patterns`).
> - Items the agent would `for`-over by sub-fields → full typed records
>   (`steps`, `decisions`, `examples`).
>
> Avoid: single `\|`-block for a plural-named field where items have a
> natural label. The label gets buried in markdown and stops being
> queryable for governance or cross-skill analysis.

### YAML caveat worth documenting

Block scalars inside a sequence are more indentation-sensitive than a
top-level `\|`-block. Items containing code fences or already-indented
content trip authors up. A one-line note in the aip skill's "Body
drafting style" section would save future authors the debugging.

---

## Issue 3: JSON Schema reserved-keyword collision on property names

The user's IDE linter flagged `properties.examples` in the runbook
schema with *"Incompatible Types: Required: array, Actual: object."*
The AIP validators (`validate_schema.py`, `validate.py`) both passed,
so the schema is spec-legal — the linter was generating a false
positive against the JSON Schema meta-schema.

### Why it happens

`examples` is a reserved annotation keyword in JSON Schema (Draft 7+).
The meta-schema types it as `{"type": "array"}`. Naive linters apply
this rule path-blind — any key named `examples` is expected to have an
array value, regardless of whether it appears at a schema-keyword
position (where it would be an annotation) or under `properties.*`
(where it's just a data-property name and the value is correctly a
sub-schema object).

Spec-compliant validators track JSON pointers and apply the array
constraint only to `examples` at schema-keyword position. That's why
the AIP validators don't flag it.

### Spec-compliance and runtime risk

For this schema, leaving `examples` as a property name carries no
fatal-error risk in any actual validation path AIP relies on:

| Path | Risk |
|---|---|
| AIP validators | None — already passing |
| Spec-compliant JSON Schema validators (`jsonschema`, `ajv` default mode) | None — `properties.examples` is valid syntax |
| Agent at runtime reading SKILL.md body | None — YAML parsing is name-agnostic |
| `$ref` resolution from other skills | None — standard $ref doesn't apply meta-schema strict mode |
| IDE linters (VS Code, JetBrains JSON Schema extensions) | False-positive squiggle, non-blocking |
| `ajv` with `strict: true` + meta-schema strict mode | Possible warning, generally not fatal |

Decision in this run: **leave the schema as-is.** The cost (every
future author seeing a squiggle when opening the file) is real but
cosmetic; the rename churn (schema + body + any downstream consumers)
isn't justified for one skill in isolation. The right place to fix this
is in the aip skill's authoring guidance, so the next schema avoids
the collision in the first place.

### Other collision-prone keywords

The full list of JSON Schema annotation keywords whose meta-schema
type is a non-object — and which therefore trigger the same linter
false-positive if used as data-property names:

| Reserved keyword | Meta-schema type | Suggested alternatives |
|---|---|---|
| `examples` | array | `worked_examples`, `cases`, `scenarios` |
| `enum` | array | `options`, `choices`, `valid_values` |
| `required` | array | `required_fields`, `mandatory` |
| `format` | string | `format_type`, `style` |
| `const` | (specific behavior) | `fixed_value`, `literal` |
| `default` | (annotation, special-cased) | `default_value`, `initial` |

Keywords like `title`, `description`, `type` are also reserved but
their meta-schema types are strings, which doesn't conflict with the
usual sub-schema object — they typically don't trigger the linter, but
they're confusing and best avoided as data-property names too.

### Recommended additions to the aip skill

**1. Anti-pattern in the main `.claude/skills/aip/SKILL.md`** (compact,
high-visibility):

> **Don't use JSON Schema reserved annotation keywords as data-property
> names.** Names like `examples`, `enum`, `required`, `format`, `const`
> trigger false-positive linter errors in IDEs (VS Code, JetBrains)
> validating against the meta-schema, even though the schema is
> spec-legal. Pick a synonym: `worked_examples`, `options`,
> `required_fields`, `format_type`, `fixed_value`. The AIP validators
> won't catch this — the cost is silent author friction every time
> someone opens the schema.

**2. Full table in `references/scenario-3-schema-authoring.md`** — the
reserved-keyword table above, with alternatives, for use during schema
drafting.

**3. Optional: soft warning in `validate_schema.py`.** Non-fatal,
output to stderr:
>
> `warning: property name 'examples' may collide with the JSON Schema
> annotation keyword and trigger linter false-positives in
> JSON-Schema-aware IDEs. Consider renaming to 'worked_examples' or
> 'cases'.`

This makes the guidance actionable at write time. Keep it as a warning,
not an error — `properties.examples` is spec-legal and may be the right
choice in some cases (e.g., if the schema is consumed only by tools
known to handle JSON pointers correctly).

---

## Issue 4: body compilation can silently drop source content

A line-by-line review of `productivity-skill.md` against the compiled
`SKILL.md` (run 3, late session) surfaced three categories of content
drop. The Instruction validates, the schema validates, the body fits
the schema — but distinct information from the source is gone with no
record of the loss.

### What got dropped

**#1 — `examples` lost two fields per example.** Schema had
`need / found / action`; source had `Need / Search / Found / Action /
Result`. Across all 3 examples:

- `Search:` (the literal query string that worked — reusable IP, the
  actual recipe) → dropped.
- `Result:` (the outcome / value pitch) → dropped.

**#2 — "When to Use This Skill" section had no schema representation.**
Source had two condition lists: "Trigger" (action-oriented invocation
conditions) and "When to Use This Skill" (broader applicability
contexts). The first mapped to `triggers`; the second's unique items
("When evaluating technology choices", "Planning architecture
decisions") had nowhere to live and were dropped.

**#3 — `integrations` flattened sub-structure.** Source had `Cycle 1 /
Cycle 2 / Cycle 3` for the iterative-retrieval integration and 3
sub-bullets each for the planner and architect integrations. I
condensed each integration into a single sentence, losing the cycle
labels and the `(npm, PyPI, MCP)` parenthetical that specified what
"broad search" meant.

### Root cause

I imposed a *generic mental model* of what AIP-shaped data should look
like, rather than reading the source's structure carefully:

- For `examples`, three fields (`need / found / action`) felt clean.
  The source had five. I designed the schema before reading the
  examples carefully, then forced the data into it.
- For `integrations`, I had a generic "one sentence per partner" shape
  in my head and condensed the sub-bullets to fit.

The shared failure mode: reading source for *category* ("this is an
example") and missing the *information density within each item*. The
aip skill's selective-typing rule told me how to *type* fields, but
had no checkpoint for "are you actually preserving source content?"

### Recommended additions to the aip skill

#### 1. Mandatory completeness check, **after** body compilation

Add to `.claude/skills/aip/SKILL.md`:

> **Completeness check (after body compilation, before final preview).**
> Walk the source line-by-line against the compiled body. Classify
> every distinct piece of source content as one of:
>
> 1. **Mapped** — appears in the body, faithfully captured.
> 2. **Schema gap** — body can't represent this because the schema
>    lacks a field. Fix: create a new schema file with the field, point
>    the skill's `schemaId` at it, re-compile.
> 3. **Body drop** — schema has the capacity but the author
>    under-captured. Fix: re-author the body to include it.
> 4. **Deliberate drop** — source content is redundant or genuinely
>    doesn't belong. Fix: record in `source/README.md` with rationale.
>
> The existing "final preview" checkpoint becomes this check: the
> preview shifts from "show what landed" to "prove nothing got
> dropped."

**Why after, not before.** A before-compile check only catches schema
gaps and requires the author to mentally simulate the body — which is
exactly the failure mode that caused this issue. After-compile compares
compiled body to source directly, catching schema gaps *and* body
authoring gaps. The downside (a schema gap means re-compiling) is
bounded; see schema versioning below.

#### 2. One required field in every AIP schema: `trigger_when`

> **Original draft of this recommendation** proposed two required
> fields, `trigger__use_this_skill_when` (action-oriented invocation
> conditions) and `when_to_use` (broader applicability contexts), to
> force authors to capture both kinds of situations. Revised after
> checking standard practice — see below.

Every AIP schema must include a single required field:

- **`trigger_when`** — list of strings, `minItems: 1`. Conditions
  under which the agent should consider this skill. **Mixed
  granularity is expected**: immediate triggers (*"user asks 'add X
  functionality'"*) and broader applicability contexts (*"evaluating
  technology choices"*) belong in the same list.

##### Why one field, not two

The two-field design was over-engineering, for three reasons surfaced
by a web search of standard practice:

1. **No major framework splits these.** Anthropic Agent Skills, MCP
   tool definitions, and OpenAI function calling all use a single
   `description` (or equivalent) field that combines "what + when."
   The Anthropic skill-creator guidance is explicit: *"All 'when to
   use' info goes [in the description], not in the body"* and *"make
   descriptions a little bit 'pushy'"* to combat under-triggering.
2. **The two-field split produced near-duplicates in practice.** In
   the search-first skill, 3 of 5 items in `when_to_use` were verbatim
   duplicates of items in `trigger__use_this_skill_when`. Only items
   4–5 (*"evaluating technology choices"*, *"planning architecture
   decisions"*) were genuinely distinct — and those fit naturally
   alongside the immediate triggers in a single mixed-granularity
   list.
3. **The structural-validation benefit is preserved.** AIP's
   queryability win over Anthropic's freeform `description` comes
   from the field being an *array of strings*, not from there being
   two arrays. A single required `trigger_when: [string]` is still
   queryable across a skill corpus.

The "never silently drop activation conditions" requirement that
motivated the two-field design is fully satisfied by a single
required `trigger_when` with `minItems: 1`. Authors are forced to
enumerate; mixed granularity lets them include broader contexts
without inventing artificial distinctions.

##### Sources

- [Anthropic — Equipping agents for the real world with Agent Skills](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills)
- [anthropics/skills — skill-creator SKILL.md](https://github.com/anthropics/skills/blob/main/skills/skill-creator/SKILL.md)
- [Model Context Protocol — Tools specification](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)
- [6 Principles from Anthropic's Official Skills Guide — Christian Dussol, Medium (April 2026)](https://medium.com/@christian.dussol/6-principles-from-anthropics-official-skills-guide-applied-to-a-real-skill-d59424e38ff3)

#### 3. Schema versioning: edit-in-place when you own it, new file when others depend

The rule is about *consumers*, not about change magnitude:

> **A schema with no other dependents can be edited in place.** Change
> the filename, `$id`, `version`, fields, required list — whatever's
> needed. The skill that owns it is the only consumer; updating both
> in the same commit keeps them in sync.
>
> **A schema with other dependents must not be mutated.** Create a new
> schema file (e.g., `runbook-v2.schema.json`) with a fresh UUID `$id`.
> Update only the skill that needs the new shape; existing skills
> pinned to the old schema keep working unchanged.

For this run: only `search-first` uses the runbook schema, so editing
`runbook.schema.json` in place — bumping `version` to `2.0.0`, renaming
`triggers` to `trigger_when`, adding fields — is the right move. No
second file needed.

The redraft cost is now genuinely a non-issue: most edits during the
v0 phase are in-place (the corpus is small, most schemas have one
dependent). The "new file" branch kicks in only once a schema accretes
external users, which is itself a good signal that the schema is
mature enough to deserve careful versioning.

As the corpus matures and schemas accumulate fields and edge cases,
completeness drops become rarer regardless of which branch is in play.

### What this would have caught in this run

- **#1** — surfaces at the completeness check. `Search:` and `Result:`
  appear in source examples but not the compiled body. Action: new
  runbook schema version adds optional `search` and `result` fields to
  the example object.
- **#2** — impossible to drop with `trigger_when` required and
  expected to be mixed-granularity. The author is forced to enumerate
  conditions, and broader applicability contexts (*"evaluating
  technology choices"*, *"planning architecture decisions"*) fit
  naturally alongside immediate triggers in the same list.
- **#3** — surfaces at the completeness check. Cycle labels and the
  `(npm, PyPI, MCP)` parenthetical appear in source but not the body.
  Action: either restore them in the body (if `integrations` is
  retyped to allow nested structure) or record the deliberate drop
  with rationale.

---

## Issue 5: schema discovery is over-engineered for v0

The aip skill currently treats schema selection as a discovery problem:
search bundled examples, project-local schemas, installed Instructions;
apply dedup precedence rules; rank candidates; fall back to authoring
a new schema in-line (Scenario 3). Scenario 1, Scenario 2, and
Scenario 3 each carry their own depth-selector, checkpoint sequence,
and validation rules in the main `SKILL.md`.

For a v0 corpus, this is overkill. Most authors will pick from a small
canonical set; a few will bring their own; almost no one needs to
author a schema inline as part of compiling a skill.

### Proposed simplification

**Curate, don't discover.** All canonical AIP schemas live in one
directory:

```
.claude/skills/aip/references/schema_examples/
  ├── runbook.schema.json
  ├── deliberation.schema.json
  ├── post-mortem.schema.json
  └── ...
```

(`references/` over `assets/` because schemas are reference material
the agent loads when picking, not data the workflow processes blindly.
The existing `references/` pattern already houses
`schema-discovery.md` and `scenario-3-schema-authoring.md`.)

**Two paths, presented up front:**

1. **Pick from the curated list.** The agent reads
   `references/schema_examples/`, shows the user a short list (file
   name + each schema's `description` field), and recommends the best
   fit based on the source material. User confirms or picks a
   different one.
2. **Bring your own.** User types a path to a schema file they
   authored elsewhere. The agent loads it, runs `validate_schema.py`
   on it, and proceeds.

That's the entire selection flow. No source ranking, no dedup
precedence, no inline authoring path.

### Where schema authoring goes

Schema authoring guidance — the full Scenario 3 walkthrough, required
root metadata, structural rules, depth-selector phrasing — moves
entirely to a separate references file (e.g.,
`references/authoring-custom-schemas.md`). The main `SKILL.md` body
references it but doesn't walk users through it inline. Authoring a
schema becomes an *opt-in, separate activity* — read the reference
file, draft the schema, then come back and use the "bring your own"
path.

### What collapses

- **Scenarios 1 + 2 merge** into a single binary checkpoint ("pick
  from list, or BYO").
- **Scenario 3 disappears from the main flow**, becoming a
  references-only path.
- **The "schema discovery" section** in `SKILL.md` shrinks to one
  paragraph: *"List `references/schema_examples/`, recommend the best
  fit, ask the user."*
- **Most of the always-confirm checkpoint sequence simplifies.**
  Checkpoint #1 ("chosen schema before compiling") becomes a one-line
  confirmation rather than a multi-decision deliberation.

### What's lost (and why it's acceptable for v0)

- **Extend/Wrap path loses a smooth on-ramp.** Current flow can offer
  "this schema is close — should we wrap it?" Under the new model,
  the user either picks the closest fit and lives with the gap, or
  authors a new schema. For v0, that's the right trade: most
  near-misses indicate the curated set needs a new addition (a
  deliberate corpus-evolution activity), not an ad-hoc wrapper.
- **No discovery across installed Instructions.** If someone has a
  great schema in another skill's `schema/` directory, the aip
  skill won't find it. That's fine — schemas worth reusing should
  be promoted into `references/schema_examples/` deliberately,
  which is the same "curate" principle applied at corpus level.

### Implications for the existing recommendations in this feedback

- **Issue 1 (run validators)**: unchanged — validators still run on
  whichever schema path is chosen.
- **Issue 4 §2 (`trigger_when` required)**: unchanged — this is a
  schema-content rule, not a discovery rule. Every curated schema in
  `references/schema_examples/` must include `trigger_when` in its
  `required` array.
- **Issue 4 §3 (schema versioning)**: simplified further. "Edit in
  place when you own it" applies cleanly to curated schemas in the
  references directory — the maintainer of the curated set is the
  only consumer until a skill pins to a schema. For BYO schemas,
  versioning is the user's problem.

### Estimated impact

The current aip `SKILL.md` is ~500 lines. This simplification should
remove ~100–150 lines of schema-discovery walkthrough, scenario
branching, and dedup precedence, while keeping the actual compile
logic intact. That's a 20–30% reduction in skill body size — paid for
once, every author invocation cheaper thereafter.

---

## Minor observations

Smaller items surfaced during the session that don't warrant their own
numbered issue, but are worth recording.

### Completeness check needs a tool, not just a rule

Issue 4 recommends a line-by-line source-vs-compiled comparison after
body compilation. This session I did it manually by reading both files
end-to-end. A small script — `compare.py source.md SKILL.md` outputting
unmapped source content — would make the checkpoint reliable rather
than dependent on author memory. Same automation pattern as
`validate.py` and `validate_schema.py`: turn the rule into a script
the workflow always runs.

### Token impact should be a built-in command

Every author benefits from knowing the realistic compression number
after compile. This session I generated it via ad-hoc
`uv run --with tiktoken` calls. Baking that into a `scripts/measure.py`
(tokens, chars, lines, ratio to source) makes it cheap to surface at
every preview checkpoint — and would naturally catch silent drops
early: *"your compile shrank 30%? check for unmapped source content
before previewing."*

### Checkpoint #2 should flag description rewrites explicitly

The aip skill's Checkpoint #2 says to show the `description` field
before finalizing. In this session, my compiled description was a
*rewrite* of the source's description (the source had its own,
shorter one). I showed the new description, but didn't flag that it
*differed* from the source's. The user approved without seeing the
comparison. Refinement: when the compiled `description` differs
materially from the source's, show both side-by-side at Checkpoint #2
and ask which to keep.

### Codify "describe before apply" for non-trivial changes

Several times during the session, the user asked *"what would the
change be?"* before *"apply it."* That's a healthier pattern than
jumping straight to applying. The aip skill could make this an
explicit decision step: *"For non-trivial schema or body changes,
describe the diff first; apply only on confirmation."* Adjacent to
but distinct from the always-confirm checkpoints — the difference is
that this applies to *every* substantive change, not just install-time
gates.

### Validation should be tied to named checkpoints, not author memory

Issue 1 captured the rule *"run validators after every write."* The
stronger framing: validators run *automatically* at named workflow
checkpoints (after every schema write, before every preview, before
install). Less *"remember to run them,"* more *"these checkpoints
include validation."* The aip skill's current language ("when to
invoke") still puts the burden on the author to remember which
scenario applies. Naming the checkpoints — and making validation part
of the checkpoint definition — removes the failure mode that produced
Issue 1 in the first place.

---

## Severity

Medium. The Instruction validator passed in this run, so no broken
artifact landed in the user's skills directory — but only because the
body and schema happened to be mutually consistent. A coordinated bug
where the schema is non-compliant *and* the body doesn't surface it via
`validate.py` would ship silently under the current guidance.
