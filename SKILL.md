---
name: aip
description: Create skills as governance-ready AIP Instructions — schema-validated structure that gates quality at write time, catches silent drift, and makes a skill corpus queryable for governance and analytics. Use whenever authoring a skill an autonomous agent will consume, including net-new skills, compiling existing material (runbooks, deliberations, specs, decision logs, post-mortems), and drafting/refining the JSON Schemas skills validate against. Default to using this any time the consumer is an autonomous agent — the structural constraint is what makes a skill production-grade.
---

# AIP — Agent Instruction Protocol

Produces an **Instruction**: an Agent-Skills-compatible folder with a
schema-validated YAML body in `SKILL.md`, plus `schema/` and `source/`
directories. Structure earns its keep when an autonomous agent
consumes the content repeatedly — validation catches drift, the
schema makes a corpus queryable, and the discipline forces clarity
plain markdown skills can avoid.

> **Note:** this `SKILL.md` is a regular Agent Skill (markdown body),
> not an AIP Instruction. It's the tool that produces Instructions.

## When to use

- Authoring any skill an autonomous or long-running agent will consume
- "Create / make / compile a skill" (with or without source material)
- "Turn this doc into an AIP Instruction"
- "Build a deliberation / runbook / spec / decision log / post-mortem
  as an Instruction"
- "Author / draft / refine an AIP schema"
- "Update this AIP Instruction" — check the existing
  `metadata.aip.schemaId` before changing structure

Default to using this any time the eventual consumer is an
autonomous agent. The harder it is to inspect the agent's behavior
in real time (long-running, multi-step, production), the more the
structural validation earns its keep.

## When NOT to use

- Content no agent will consume (human-only wikis, FAQs, casual notes)
- One-off shell helpers where no schema family applies
- Free prose with no structural payoff and no plan for cross-doc query

## Audience awareness

AIP authors range from senior engineers to domain experts with no
JSON Schema background. Calibrate language: explain terms like "JSON
Schema," "validator," "fenced YAML" on first use unless the user
signals familiarity. The user is **never** expected to read or pick
schemas by hand — schema selection is your job.

**Default to summaries, not raw artifacts.** Before dumping a JSON
Schema, a fenced YAML body, or validator output to the chat, ask if
the user wants to see it — most will say no. Lead with a natural-
language description ("the schema has fields X, Y, Z; the body
validates"). The artifacts are on disk; the chat is for the human.

## The three usage scenarios

Detect which one applies from the user's opening:

### Scenario 1 — No schema specified (most common)

User has a doc (or describes one). They don't know or care about
JSON Schema; that's your job.

Bias to schema reuse over drafting new ones. When no bundled
candidate fits, draft a *permissive* schema (required-minimum core,
freeform-text leaves where structure isn't earning) rather than a
heavily-typed one — see [Selective typing](#selective-typing).
**Scope the schema to the category of work, not the specific skill.**
If the skill is "search-first before writing code," the schema is
`runbook` — not `search-first`. The category is what future skills
reuse.

When you draft a new schema mid-Scenario-1, you've entered Scenario 3
for that artifact — run `validate_schema.py` on it *before* compiling
the body (see [Validation scripts](#validation-scripts)).

### Scenario 2 — Schema specified

User provides both source material and a schema reference.

Differences from Scenario 1:

1. Run `uv run scripts/validate_schema.py <schema>` first to confirm
   AIP compliance.
2. Skip schema discovery.
3. Brief semantic fit-check: does the schema actually fit the user's
   content? Flag obvious mismatches.
4. Checkpoint #1 becomes: *"I'll use the schema you gave me; here's
   why it fits / a concern with the fit. OK?"*

### Scenario 3 — Author or iterate on a schema (rare, advanced)

Conversational — no fixed step sequence. See
[Scenario 3 details](#scenario-3-details).

## The walkthrough (Scenarios 1 and 2)

### Entry sequence

1. **Capture intent.** Harvest from the conversation already in
   progress *first* — the doc the user's been working on, the
   workflow they just walked you through, corrections they made.
   The user often expects you to have noticed. Confirm what you
   extracted; only ask about pieces that aren't visible. *"You want
   to turn `decision-notes.md` into a deliberation Instruction —
   correct?"* — don't ask the user to restate what they just told you.

2. **Ask depth.** Single question, three options:
   - **Quick** (~2 min) — you make most decisions, show the result
     for review
   - **Balanced** (~5–10 min) — you ask about the 3–5 most important
     structural choices
   - **Thorough** (~20+ min) — field-by-field collaboration

3. **Determine source materials.** Three valid starts: inline paste
   → use what they wrote; existing markdown file → read it; verbal
   description with no file → **draft `source/README.md` first** as
   the canonical source, get approval, then compile. Only ask when
   the answer isn't obvious from context.

### Depth-adapted middle

- **Quick:** pick the most likely schema match, draft the body,
  present. Ask only the always-confirm checkpoints.
- **Balanced:** surface 3–5 key structural choices for user input:
  - "Schema A vs schema B?"
  - "One Instruction or two?"
  - "Primary axis of organization — chronological, by topic, by
    decision-point?"
  - "For each significant section: freeform text or queryable
    structure?" (see [Selective typing](#selective-typing))
- **Thorough:** walk through each significant field with the user
  before validating and presenting.

### Validation failures — tiered recovery

On `validate.py` / `validate_schema.py` failure: if **trivial**
(typo, missing required field, formatting drift), silently retry.
If **substantive** (semantic mismatch, schema doesn't fit, structural
conflict), surface the error in plain language with your proposed
fix and ask for confirmation. Rule: if the user's judgment would
change the fix, surface it.

### Always-confirm checkpoints

Four points to **always** confirm, regardless of depth.

1. **Chosen schema before compiling.** *"I'll use the deliberation
   schema — it fits because [reason]. OK?"* If sections could go
   either typed or freeform, fold in: *"Typed for `<list>`, freeform
   text for `<list>` — sound right?"* Offer (don't auto-show) the
   schema's structure: *"Want me to show the schema, or just go on
   the description?"* Most users will say go on.

2. **`description` field text.** Show before finalizing — this is
   the only signal the host agent reads at session startup to decide
   whether to activate the Instruction. Two rules:
   - **What + when, slightly pushy.** Skills under-trigger by
     default; descriptions need to actively recruit. Name the
     contexts an agent should reach for it in, including phrasings
     the user might not use.
   - **Mention the schema's domain** (e.g., "Deliberation for…")
     so AIP-aware discovery recognizes it as a candidate.

3. **Final preview before install.** Show a clean structured summary
   (what it does, the body's top-level fields, the schema's role).
   Offer to dump the full rendered `SKILL.md` if the user wants —
   default to the summary; most won't.

4. **Install location.** Ask user-global (the host agent's
   user-wide skills directory — e.g., `~/.claude/skills/` for
   Claude Code) vs project-local (`./.claude/skills/` or equivalent
   for the host agent). Default: project-local if CWD is in a git
   repo, user-global otherwise.

## Schema discovery

Used in Scenario 1. Search three sources (bundled examples,
project-local schemas, installed Instructions), rank candidates
against the user's intent, prefer reuse. If nothing fits, offer to
draft a custom schema (Scenario 3).

Read **[references/schema-discovery.md](references/schema-discovery.md)**
for the source table, filters, dedup precedence, and rationale.

## Selective typing

The highest-leverage authoring decision is which sections to *type*
(list-of-objects, structured records) vs leave as freeform text
under a `|`-block. Get this right and an Instruction compresses
40–60% below its markdown source while staying agent-queryable. Get
it wrong — type everything — and the Instruction can compile
*larger* than its source while being harder to read.

**Heuristic:** would the agent ever `for` over this section, or
filter / look up by one of its sub-fields? If yes, type it. If no,
leave it as text.

Worked example (from `discussions/learning-search-first/`, Attempt 3):

- **Typed** — `steps` (id / do / parallel? / one_of?), `decisions`
  (when / then pairs), `examples` (need / found / action). The agent
  iterates over them.
- **Freeform `|`-block** — `shortcuts` (categorised reference list),
  `modes.quick` / `modes.full` (terse prose blocks), `integrations`
  (one-line strings). The agent reads these once for context;
  decomposing inflates size without enabling any new query.

**Don't fight tight source.** Markdown tables and ASCII workflow
diagrams in the source are already structured. Drop them into
`|`-block strings; don't re-encode every row as a typed record.

## Body drafting style

- **Imperative form.** "Search npm before writing a utility" beats
  "the user should consider searching npm."
- **Explain the *why*, sparingly.** A short line of reasoning beats
  a paragraph of all-caps MUSTs. LLMs reason from intent.
- **Keep the prompt lean.** Skill bodies that feel padded waste
  tokens on every invocation.
- **No surprises.** Body contents should match what `description`
  promises.

## Validation scripts

Two Python scripts under `scripts/`, run via `uv run` (PEP 723
inline deps — no install, no virtualenv):

```bash
uv run scripts/validate.py path/to/instruction/   # Instruction
uv run scripts/validate_schema.py path/to/schema.json   # Schema
```

When to invoke — keyed on the write, not the scenario:

**Run a validator after any write to a schema or Instruction.**
Initial compile, schema authoring, post-install edits, renaming a
field across two files — all of them.

- Wrote/edited a schema file → `validate_schema.py <file>`
- Wrote/edited a `SKILL.md` or an Instruction folder →
  `validate.py <folder>`
- Both changed in the same turn → run both
- Scenario-1 reuse failed and you drafted a new schema → you've
  entered Scenario 3 for that artifact. Run `validate_schema.py` on
  the new schema *before* compiling the body against it. `validate.py`
  on the Instruction does not catch schema-side AIP-compliance bugs;
  the body can fit a non-compliant schema silently.

Don't substitute manual review. The validators take ~1 second; an
eyeball check is not equivalent and routinely misses AIP-namespace
and required-metadata bugs.

Apply [tiered recovery](#validation-failures--tiered-recovery) on
failure.

## Format essentials

Enough format detail to draft a valid Instruction without guessing.
The validators catch the rest.

### Instruction folder layout

```
<instruction-name>/
├── SKILL.md                       # frontmatter + fenced YAML body
├── schema/
│   ├── <schema-name>.schema.json  # AIP-compliant JSON Schema
│   └── README.md                  # optional schema docs
├── source/
│   ├── README.md                  # canonical human source
│   └── ...                        # additional source files
├── scripts/                       # optional
├── assets/                        # optional
├── references/                    # optional
└── ...                            # any additional dirs
```

`<instruction-name>` must equal the `name` in SKILL.md frontmatter
(Agent Skills spec requirement).

### SKILL.md frontmatter — required fields

| Field                   | Source       | Notes                                                                                       |
|-------------------------|--------------|---------------------------------------------------------------------------------------------|
| `name`                  | Agent Skills | 1–64 chars; lowercase `a–z`/`0–9`/`-`; matches parent directory                             |
| `description`           | Agent Skills | 1–1024 chars; what + when; see Checkpoint #2                                                |
| `metadata.aip.spec`     | AIP          | `https://raw.githubusercontent.com/zach-blumenfeld/aip/main/spec.md` (current placeholder)  |
| `metadata.aip.schemaId` | AIP          | UUID URN matching the `$id` of the schema in `schema/`                                      |

Optional: `license`, `compatibility`, `metadata.*` (free-form),
`allowed-tools`.

### SKILL.md body — rules

Exactly one fenced YAML code block (tag `yaml` or `yml`), no
surrounding prose, no second code block. The body validates against
the schema referenced by `metadata.aip.schemaId`. The body does
*not* repeat `schemaId` — frontmatter is the single source of truth.

````markdown
---
name: my-instruction
description: ...
metadata:
  aip:
    spec: https://raw.githubusercontent.com/zach-blumenfeld/aip/main/spec.md
    schemaId: urn:uuid:...
---

```yaml
# body fields per schema...
```
````

### Body size — keep it lean

Target `SKILL.md` under ~500 lines / ~5000 tokens. Skills load in
three levels: metadata (name + description) is always in context;
the body loads when the skill triggers; `references/`, `scripts/`,
`assets/` load on demand. Body bloat costs tokens on every
invocation. If the body would overflow, split into multiple smaller
Instructions before pushing content into `references/`.

Schema-authoring details (required root metadata, structural rules,
reserved names) live in
[references/scenario-3-schema-authoring.md](references/scenario-3-schema-authoring.md)
— relevant only when drafting a new schema (Scenario 3).

## Draft and install

Always draft into a temp folder first — never write directly into
the host agent's live skills directory (e.g., `.claude/skills/`)
until the user has confirmed both the artifact and the destination.

1. **Create temp draft** at a tempdir like `/tmp/aip-draft-<name>/`.
2. **Write contents:** `SKILL.md`, `schema/<schema-name>.schema.json`,
   `source/README.md`.
3. **Run `uv run scripts/validate.py /tmp/aip-draft-<name>/`** as
   the smoke check. Apply tiered recovery on failure.
4. **Preview to the user** (Checkpoint #3) — summary first, full
   artifact on request.
5. **Confirm install location** (Checkpoint #4). Don't move anything
   until the user has chosen.
6. **Move `/tmp/aip-draft-<name>/` → `<location>/<name>/`** (folder
   name must equal `name` in frontmatter).
7. **Tell the user where it landed.** For project-local installs,
   a fresh agent session in this directory may be needed for the
   skill to activate.

If the user declines to install or wants to revise, leave the temp
folder in place and iterate there.

### Existing folders and source content

If a folder already exists at the install location: for hand-authored
skills (no `metadata.aip.spec`), ask before overwriting. For
previously-compiled Instructions, preserve `scripts/`, `assets/`,
and other top-level files; overwrite only `SKILL.md`, `schema/`, and
`source/`. When updating, check the existing `metadata.aip.spec` URL
— it may target an earlier spec version.

`source/README.md` is the canonical human-readable source. If the
user provided a doc, copy it (lightly cleaned, preserving voice).
If you drafted from a verbal description, the draft *is* the source
going forward — get explicit approval before writing. Include enough
that a future reader understands why the Instruction exists; the
source explains, the body executes. Additional source files (drafts,
prior logs, diagrams) go alongside `README.md` in `source/`.

## Scenario 3 details

Schema authoring is conversational — no fixed step sequence. Scope
new schemas to the **category of work** (runbook, document-template,
reference, post-mortem), not to the specific skill instance.

Read **[references/scenario-3-schema-authoring.md](references/scenario-3-schema-authoring.md)**
for the full procedure, depth-selector phrasing, scoping guidance,
and the required-root-metadata reference.

## After install

Installed Instructions are regular Agent Skills with extra structure
— compatible with Anthropic's `skill-creator` for iterative
refinement. Run the Instruction through skill-creator's eval loop
to measure and tune; AIP's structural guarantees and skill-creator's
iteration loop are complementary, not overlapping.

## Anti-patterns

- **Don't make the user pick JSON Schemas by hand.** That's your job.
- **Don't skip always-confirm checkpoints**, even in Quick mode —
  `description` and install location are hard to fix later.
- **Don't invent metadata keywords.** AIP-specific frontmatter and
  schema metadata go under the `aip:` namespace, not bare at the root.
- **Don't write source from scratch when the user gave you a doc.**
  Preserve their content; the compiled body is derivative.
- **Don't compile and install in one breath.** Draft in temp,
  preview, confirm location, then move. The user has to catch issues
  *before* the folder lands in a live skill path.
- **Don't dump JSON Schemas or YAML bodies into chat without asking.**
  Default to a natural-language summary; offer the raw artifact.
  Most users will pass.
- **Don't over-decompose tight source.** Freeform-reference sections
  default to `|`-block strings. Type only what the agent would iterate
  or filter by — see [Selective typing](#selective-typing).
- **Don't promise compression for tight, already-structured source.**
  40–60% reduction assumes prose-heavy source AND selective-typing.
  Tight markdown + rigid full-typed schema can compress *negatively*.
- **Don't treat the bundled validators as out-of-scope under user
  scope restrictions.** When the user says "do it without X" or
  restricts external resources, the validators in this skill's
  `scripts/` are part of the skill's contract — not third-party
  resources. Run them anyway, and surface that you're doing so.
- **Don't pile on all-caps MUSTs.** Explain why once; LLMs reason
  from intent.
