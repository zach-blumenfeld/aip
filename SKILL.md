---
name: aip
description: Compile human-authored docs into AIP Instructions (validated, structured skill folders). Use when the user wants to make a skill, build a deliberation/runbook/spec/decision-log Instruction from existing material, or author/refine an AIP schema.
---

# AIP — Agent Instruction Protocol

This skill helps the user produce an **Instruction**: a folder that
conforms to the [Agent Skills spec](https://agentskills.io/specification)
and adds AIP-required `schema/` and `source/` directories plus a
schema-validated YAML body in `SKILL.md`.

The full protocol is specified in `spec.md` in this skill's folder.
Read it when you need format details — don't guess at format
mechanics.

> **Note on this file:** this `SKILL.md` is itself a regular Agent
> Skill (markdown body), not an AIP Instruction. AIP Instructions
> have a fenced-YAML body per `spec.md` §SKILL.md format. Don't be
> confused by the difference — this skill is the *tool* that
> produces Instructions; it isn't one.

## When to use this skill

Activate when the user asks to:

- "Create / make / compile a skill" (with or without source material)
- "Turn this doc into an AIP Instruction"
- "Build a deliberation / runbook / spec / decision log as an
  Instruction"
- "Author / draft / refine an AIP schema"
- "Update this AIP Instruction" (you'll need to read `spec.md` to do
  this correctly, especially if the existing Instruction was authored
  against an earlier spec — check its `metadata.aip.spec` URL)

## When NOT to use

- One-off scripts or ad-hoc shell helpers → regular Agent Skill, not
  an AIP Instruction.
- Free prose with no structural payoff (FAQs, casual notes) →
  regular Agent Skill or just markdown.
- Content the user reads but no agent consumes → markdown in a wiki.

If unsure: AIP Instructions earn their structure when an autonomous
agent will consume the content repeatedly. If a human will read it
once, plain markdown is fine.

## Selective typing

The single highest-leverage authoring decision is which sections to
*type* (list-of-objects, structured records) vs leave as freeform
text under a `|`-block. Get this right and an Instruction compresses
40–60% below its markdown source while staying agent-queryable. Get
it wrong — type everything — and the Instruction can compile
*larger* than its source, while being harder to read.

**Heuristic:** would the agent ever `for` over this section, or
filter / look up by one of its sub-fields? If yes, type it. If no,
leave it as text.

Worked example (from a real compile —
`discussions/learning-search-first/`, Attempt 3):

- **Typed** — `steps` (id / do / parallel? / one_of?), `decisions`
  (when / then pairs), `examples` (need / found / action). An agent
  iterates over steps, looks up the right decision by condition,
  scans examples for a matching need. Structure earns its keep.
- **Freeform `|`-block** — `shortcuts` (categorised reference list),
  `modes.quick` / `modes.full` (terse prose blocks), `integrations`
  (one-line strings per partner). The agent reads these once for
  context; decomposing into records inflates size without enabling
  any new query.

**Corollary — don't fight tight source.** Markdown tables and ASCII
workflow diagrams in the source are already structured. Drop them
into `|`-block strings without apology; don't re-encode every row
as a typed record just because you can. Tight source resists
compression — that's a feature, not a failing to correct.

## The three usage scenarios

Every session falls into one of three shapes. Detect which from the
user's opening:

### Scenario 1 — No schema specified (most common)

User has a doc (or describes one). They don't know or care about
JSON Schema; that's your job.

**You own schema selection and reuse. The user is not expected to
understand JSON Schema or open schema files. Your bias is to reuse
existing schemas over drafting new ones, and — when no bundled
candidate fits — to draft a permissive schema (required-minimum
core, freeform-text leaves where structure isn't earning) rather
than a heavily-typed one. See [Selective typing](#selective-typing).**

Flow: [walkthrough entry](#entry-sequence) → [schema discovery](#schema-discovery)
→ [walkthrough middle](#depth-adapted-middle) →
[checkpoints](#always-confirm-checkpoints) → [install](#install-procedure).

### Scenario 2 — Schema specified

User provides both source material and a schema reference (path or
name).

Differences from Scenario 1:

1. Before the walkthrough entry, run
   `uv run scripts/validate_schema.py <schema-path>` to confirm
   AIP compliance. If it fails, surface to the user.
2. Skip schema discovery (you have the schema).
3. Do a brief semantic fit-check: does the schema actually fit the
   user's content? Flag obvious mismatches (e.g., a historical wiki
   doc paired with a workflow schema).
4. Always-confirm checkpoint #1 (chosen schema) becomes "I'll use
   the schema you gave me; here's why it fits / here's a concern I
   have with the fit. OK?"

### Scenario 3 — Author or iterate on a schema (rare, advanced)

User wants to create or refine a JSON Schema. Conversational —
there's no fixed step sequence.

See [Scenario 3 details](#scenario-3-details) below.

## The walkthrough

For Scenarios 1 and 2, follow this structured walkthrough. The
walkthrough is specified in `spec.md` §The AIP skill → Walkthrough UX
— this section is the operational implementation of it.

### Entry sequence

At the start of every new Instruction:

1. **Confirm intent.** Acknowledge what the user wants to make.
   Surface ambiguity in plain language.
   - *Good:* "You want to turn `decision-notes.md` into a
     deliberation Instruction — correct?"
   - *Bad:* jumping straight into compilation without confirming.

2. **Ask depth.** Single question, three options. Phrase it
   naturally; the levels are:
   - **Quick** (~2 min) — you make most decisions, show the result
     for review
   - **Balanced** (~5–10 min) — you ask about the 3–5 most important
     structural choices
   - **Thorough** (~20+ min) — field-by-field collaboration

3. **Determine source materials path.** Three valid starting points:
   - User pastes/describes inline → use what they wrote
   - User points to an existing markdown file → read it
   - User describes verbally with no file → **draft
     `source/README.md` first** as the canonical source, get user
     approval, then compile

   Ask only when the answer isn't obvious from context. If the user
   has already supplied a doc inline or as a file path, don't ask.

### Depth-adapted middle

The middle covers schema selection, body compilation, and
refinement. It adapts to the chosen depth:

- **Quick:** pick the most likely schema match (see
  [Schema discovery](#schema-discovery)), draft the body, present
  the result. Ask only the always-confirm checkpoints.
- **Balanced:** surface 3–5 key structural choices for user input.
  Examples:
  - "Deliberation schema vs. spec schema?"
  - "One Instruction or two?"
  - "What's the primary axis of organization — chronological, by
    topic, by decision-point?"
  - "For each significant section: freeform text or queryable
    structure?" (see [Selective typing](#selective-typing))
- **Thorough:** walk through each significant field with the user
  before validating and presenting.

### Validation failures — tiered recovery

When `validate.py` or `validate_schema.py` fails:

- **Trivial** (typos, obviously missing required field, formatting
  drift): silently retry with the fix. Don't bother the user.
- **Substantive** (semantic mismatch, schema doesn't fit content,
  structural conflict): surface the error in plain language plus
  your proposed fix and ask the user to confirm before retrying.

Rule of thumb: if the user's judgment would change the fix, surface
it. If the fix is obvious and mechanical, just do it.

### Always-confirm checkpoints

Four points where you **always** confirm with the user, regardless
of depth setting. Skip none of these.

1. **Chosen schema before compiling body.**
   *"I'll use the deliberation schema (from
   `references/examples/deliberation/`) — it fits because [reason].
   OK to proceed?"*

   Prevents wasted body-drafting effort if the user disagrees.

   When the schema leaves room for either typed records or freeform
   text in significant sections, fold a sub-question into this
   checkpoint: *"For these sections — `<list>` — I'm planning typed
   records; for these — `<list>` — freeform text. Sound right?"*
   The user often has a clearer sense than you do of which sections
   will be queried. See [Selective typing](#selective-typing).

2. **`description` field text.** Show the proposed description
   before finalizing.

   `description` is the *only* signal Claude Code uses to decide
   whether to activate the Instruction at session startup (see
   `spec.md` §SKILL.md format → Discovery considerations). The user
   knows their phrasing preferences better than you do.

3. **Final Instruction preview before install.** Show the rendered
   `SKILL.md` (or a clean structured summary of it) so the user
   sees exactly what's about to land on disk.

4. **Install location.** Ask:
   - User-global (`~/.claude/skills/`) — available in every Claude
     Code session
   - Project-local (`./.claude/skills/`) — available only when
     Claude Code runs from this project

   Default suggestion: project-local if CWD is inside a git repo,
   user-global otherwise. The user can override.

## Schema discovery

Used in Scenario 1 (no schema specified). Search three sources for
candidate schemas. For each candidate, read `$id`, `title`,
`description`, and `aip.tag` (all required per `spec.md` §AIP schema
conventions) and rank against the user's intent.

| Source                 | Where                                                                                  | Include only if…                                                          |
|------------------------|----------------------------------------------------------------------------------------|---------------------------------------------------------------------------|
| Bundled examples       | `references/examples/*/` (in this skill's folder)                                      | Always include (trusted source).                                          |
| Project-local schemas  | `*.schema.json` under CWD (max depth 4, respect `.gitignore`)                          | Schema has a top-level `aip:` object.                                     |
| Installed Instructions | `~/.claude/skills/*/schema/*.schema.json` and `./.claude/skills/*/schema/*.schema.json` | Containing skill's `SKILL.md` has `metadata.aip.spec` in frontmatter.     |

**Dedup precedence** when the same `$id` appears in multiple
sources: **bundled > project-local > installed**.

**Why the filters matter:** they prevent false positives from random
`*.schema.json` files (AJV fixtures, JSON Schema store, npm package
schemas) and from non-AIP installed skills. Don't recommend
non-AIP schemas — they won't validate, and they won't have the
metadata an agent expects.

**If no candidate fits well:** offer to draft a custom schema
(Scenario 3). But try discovery first — schema reuse is the
preference, especially for v0.1 when the bundled corpus is still
small.

See `spec.md` §Schema discovery for the full convention.

## Validation scripts

The skill bundles two Python scripts under `scripts/`. Both use
[PEP 723](https://peps.python.org/pep-0723/) inline dependencies and
run via `uv run` — no install step needed, no virtualenv to manage.

```bash
# Validate an Instruction (frontmatter + fenced YAML body) against
# the schema referenced by metadata.aip.schemaId
uv run scripts/validate.py path/to/instruction/

# Validate a JSON Schema against AIP conventions (required metadata
# keywords, AIP namespace presence, reserved property names,
# strict-core / open-extensions pattern)
uv run scripts/validate_schema.py path/to/schema.json
```

When to invoke:

- **Scenario 1:** run `validate.py` on the compiled Instruction as
  the final smoke check before install.
- **Scenario 2:** run `validate_schema.py` on the user-provided
  schema *before* compiling; run `validate.py` on the result before
  install.
- **Scenario 3:** run `validate_schema.py` on each draft iteration.

Apply the [tiered recovery](#validation-failures--tiered-recovery)
rule to any failure.

## Install procedure

After all always-confirm checkpoints pass:

1. **Confirm install location** (per checkpoint #4 above).
2. **Create the Instruction folder** at `<location>/<name>/`. The
   folder name must equal the `name` field in the SKILL.md
   frontmatter (Agent Skills spec requirement).
3. **Write the contents:**
   - `SKILL.md` — frontmatter (including required
     `metadata.aip.spec` and `metadata.aip.schemaId`) and body
     (exactly one fenced YAML code block, no surrounding prose).
     See `spec.md` §SKILL.md format.
   - `schema/<schema-name>.schema.json` — copy of the chosen schema,
     whether bundled, project-local, installed, or freshly authored.
     Optional `schema/README.md` for schema documentation.
   - `source/README.md` — the canonical human-readable source
     (either the user's original doc or your drafted version, per
     the entry sequence). Plus any additional source files the user
     provided.
4. **Run `uv run scripts/validate.py <new-instruction-path>/`** as
   a final smoke check. Apply tiered recovery on failure.
5. **Tell the user where it landed** and any next steps. For
   project-local installs, note that they may need to open a new
   Claude Code session in this directory for the skill to activate.

### Compiling into an existing skill folder

If a folder already exists at the chosen install location:

- **If it's a hand-authored skill** (no `metadata.aip.spec` in its
  `SKILL.md` frontmatter): ask the user before overwriting. Don't
  silently clobber non-AIP content.
- **If it's a previously-compiled AIP Instruction** (has
  `metadata.aip.spec`): preserve any existing `scripts/`, `assets/`,
  and additional top-level files. Overwrite only `SKILL.md`,
  `schema/`, and `source/`.

If the user is *updating* an existing Instruction (not creating a
new one), check the existing `metadata.aip.spec` URL — they may
have been authored against an earlier spec version. Read the
relevant spec section before making structural changes.

## Scenario 3 details

Schema authoring is conversational. There's no fixed step sequence.
General approach:

1. **Understand the domain.** Ask what kind of content the schema
   will validate. Pull in reference material: other schemas, user's
   examples, the user's mental model, web sources if relevant.

2. **Identify the core structure.** What are the main fields? Which
   are required vs optional? What's the strict-core / open-extensions
   split (see `spec.md` §AIP schema conventions → Required structural
   conventions)?

3. **Draft and validate.** Write a JSON Schema draft with the
   required AIP metadata at the root:
   - `$schema` (JSON Schema dialect)
   - `$id` (UUID URN — generate one with `uuid` library or
     `uuidgen`)
   - `title` (short display name)
   - `description` (one or two sentences)
   - `aip:` namespace object (with at least the version/tag fields
     if relevant)

   Run `uv run scripts/validate_schema.py <draft.schema.json>` to
   confirm AIP compliance.

4. **Iterate.** Show the draft to the user, gather feedback, refine.
   Re-validate after each round. Watch for:
   - Use of reserved property names (`id`, `schemaId`, `key`,
     `idx`, `_source`) — not allowed
   - DB-specific keywords (`x-graph-*`, `x-neo4j-*`) — not allowed
     per spec.md Principle 1
   - Strict-core pattern violations

5. **Settle.** When the user is satisfied and the validator passes,
   the schema is ready. The user can use it immediately to compile
   an Instruction (Scenario 2), or you can offer to install it as
   a bundled reference at `references/examples/<name>/`.

The depth selector applies here too:
- **Quick:** "Give me a draft based on what we've discussed; I'll
  review."
- **Balanced:** "Let's settle the main fields together, then you
  draft and I'll review."
- **Thorough:** "Walk me through every decision before writing the
  schema."

## Source/README.md content

Whatever scenario you're in, the Instruction's `source/README.md`
must be the canonical human-readable source. Guidance:

- **If the user provided a doc:** copy it (lightly cleaned up if
  needed, but preserve the user's voice and structure).
- **If you drafted source from a verbal description:** the draft
  *is* the source going forward. Get explicit user approval before
  writing.
- **What to include:** enough information that a future human
  reader can understand why the Instruction exists and what it
  encodes. Not a rewrite of the compiled body; the source explains,
  the body executes.

Additional source files (deliberation drafts, prior conversation
logs, diagrams, related notes) can go alongside `README.md` in
`source/` — AIP preserves the Agent Skills "open extension"
property there (see `spec.md` §Instruction format → Open extensions).

## Format reference

The authoritative format is in `spec.md`. Key sections:

| You need to know about… | Read… |
|---|---|
| Folder layout of an Instruction | §Instruction format |
| `SKILL.md` frontmatter and body rules | §SKILL.md format |
| What a valid AIP schema looks like | §AIP schema conventions |
| Schema discovery filters and rationale | §Schema discovery |
| The walkthrough this skill implements | §The AIP skill → Walkthrough UX |
| Why AIP exists, what problem it solves | §Value Proposition, §What this is |

**When in doubt, read `spec.md` before guessing.** Format errors
get caught by the validators, but earlier-is-better — a wrong
assumption that propagates through compilation wastes the user's
attention.

## Examples

Bundled example schemas live at `references/examples/<name>/`. In
v0.1 this folder may be empty; the canonical AIP examples are still
being curated. The `workflow/schemas/` folder in this repo contains
prototype schemas (`deliberation.schema.json`, `generic.schema.json`)
that predate the session 5 metadata requirements — useful as
structural reference, but they'll need a metadata refresh before
being promoted to `references/examples/`.

## Anti-patterns to avoid

- **Don't make the user choose between JSON Schema files by hand.**
  Schema selection is your job (Scenarios 1 and 2). The user picks
  by name/intent; you handle the schema mechanics.
- **Don't skip the always-confirm checkpoints**, even in Quick
  mode. They're load-bearing — `description` and install location
  are hard to fix after the fact.
- **Don't invent metadata keywords.** AIP-specific frontmatter and
  schema metadata must go under the `aip:` namespace, not bare at
  the root. See `spec.md` for the exact contract.
- **Don't write the source from scratch when the user gave you a
  doc.** Preserve their content; the compiled body is the
  derivative artifact.
- **Don't compile and install in one breath.** The preview
  checkpoint exists so the user catches issues *before* the folder
  lands on disk. Always show, then install.
- **Don't over-decompose tight source.** Freeform-reference
  sections (shortcuts by category, integration notes, mode prose)
  default to `|`-block strings, not typed record lists. Tables and
  ASCII workflow diagrams from the source can go in as `|`-blocks
  too. Type only what the agent would iterate or filter by — see
  [Selective typing](#selective-typing).
- **Don't promise compression for tight, already-structured
  source.** `spec.md` §Value Proposition's 40–60% reduction assumes
  prose-heavy source AND selective-typing discipline. Tight markdown
  + rigid full-typed schema can compress *negatively* (a real
  compile saw +4.2%). Set expectations honestly when the source is
  already terse.
