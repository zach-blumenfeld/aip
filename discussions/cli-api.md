# Discussion: CLI / API surface (v0.1 candidate)

> **Status: deliberation, not spec.** Captures the open design
> questions around the AIP skill and its bundled validation scripts.
> Defers all DB-publishing concerns to a later discussion. Key
> resolution (2026-05-16): no separate CLI binary — validation lives
> in `scripts/` inside the `aip` skill, run via `uv run`.

## What triggered this

Drafting the [README](../README.md) and [spec](../spec.md) for
Structured Documents surfaced a real design question we hadn't
deliberated yet: **what does the surface look like that a producer
team actually touches?** We've sketched the data shape (JSON
Schema, validated YAML, graph projection) but not the verbs (how do
I produce one? validate one? find one? throw one away?).

A first-pass CLI sketch landed in the README; pulling it here and
expanding into the open questions it raised.

## Usage scenarios

These three scenarios define the actual usage surface and drove the
key design decisions below. They should be consulted whenever a new
CLI command or skill capability is proposed.

Two roles appear in every scenario:
- **The agent** — an AI agent (e.g. Claude Code in the terminal)
- **The user** — the person directing the agent

### Scenario 1 — Create a skill, no schema specified (most common)

The user has a document describing a process, workflow, skill, or
cheat sheet — or describes what they want in the prompt. They ask the
agent to create a skill from it.

1. Agent reads the document (or takes the description from context),
   surfaces any structural gaps or concerns to the user.
2. Agent prompts the user to pick a schema — **not by exposing JSON
   Schema internals**, but by offering:
   - A short list of existing schemas that match the context (drawn
     from AIP example schemas, user's project schemas, and schemas in
     the user's installed skills directory)
   - An offer to draft a schema automatically based on the doc and
     session context
   - An option to discuss alternatives
3. Agent compiles the skill: produces the full SKILL.md folder with
   frontmatter, compiled body, source preserved in `references/`,
   metadata in `meta.yml`.
4. Agent asks whether to **install** the skill (move to
   `~/.claude/skills/` or `.claude/skills/`) or save it elsewhere
   for review first.

**Key implication:** The agent owns schema selection and reuse. The
user is not expected to understand JSON Schema or open schema files.
The agent's bias is to reuse existing schemas over drafting new ones.

### Scenario 2 — Create a skill with a specified schema

The user provides both a document path and a schema reference (path
or name).

1. Agent reads and validates the document.
2. Agent validates the schema is AIP-compliant (`uv run scripts/validate_schema.py`).
3. Agent checks schema–document fit semantically — flags mismatches
   (e.g. a historical wiki doc paired with a workflow schema).
4. Agent compiles the skill.
5. Agent asks whether to install or save for review.

### Scenario 3 — Author or iterate on a schema (rare, advanced)

The user wants to create or refine a schema. Inputs may include
reference docs, web sources, examples from the session, or prior
schemas. This is a conversational process — the agent assists in
thinking through structure, drafts schema iterations, runs
`uv run scripts/validate_schema.py` on each draft, and iterates until the user
is satisfied. There is no fixed command sequence.

### Design implications of these scenarios

These scenarios settle several open questions that had been framed as
CLI design questions:

- **`compile` and `draft-schema` are not scripts or CLI commands.**
  They are what the agent *does*, guided by SKILL.md knowledge. The
  agent writes files using what it knows from the AIP skill — no
  script invocation needed for compilation.
- **There is no separate CLI binary.** Validation is
  `scripts/validate.py` and `scripts/validate_schema.py` in the `aip`
  skill, run via `uv run`. The same commands work for the agent
  (inline during the workflow) and for CI (directly, no agent needed).
- **Schema discovery is a first-class concern.** For Scenario 1 to
  work, the agent must know what schemas already exist: AIP example
  schemas (in `references/examples/` of the skill), project-local
  schemas, and schemas embedded in other installed skills. The
  convention for discovering these is an open question
  (see [§Open questions §7](#open-questions)).
- **"Install" is a directory move.** Moving the compiled skill folder
  to `~/.claude/skills/` is a directory operation the agent performs
  directly — no script needed for v0.1.

## Foundational research (Anthropic Skills spec)

Before designing our own surface, we need to know what's already
constrained by the Anthropic Agent Skills open standard
([agentskills.io](https://agentskills.io/specification),
[Claude Code skills docs](https://code.claude.com/docs/en/skills)),
since "skills" is one of our primary doc types and we want
in-place integration with existing agent workflows.

**Hard constraints from the Anthropic spec:**

- **A skill is a directory, not a file.** `skill-name/SKILL.md`
  plus optional `scripts/`, `references/`, `assets/` subdirs.
- **The filename `SKILL.md` is mandated.** Not `skill.yml`, not
  `skill.md`. The extension is `.md` literally.
- **YAML frontmatter is required at the top of SKILL.md.** Two
  required fields: `name` (must match parent directory name) and
  `description`.
- **Optional frontmatter fields**: `license`, `compatibility`,
  `allowed_tools` (experimental), `metadata` (catch-all key-value
  map — the spec's escape hatch for author/version/etc.).
- **Storage locations are conventional:**
  - Personal: `~/.claude/skills/`
  - Project: `.claude/skills/`
  - Claude Code scans both at session startup, loads only
    frontmatter for triggering ("progressive disclosure").

**Design implication for us:** The agent reads SKILL.md directly.
Therefore **SKILL.md must be the compile *output*, not a sidecar.**
If the agent reads anything other than our compiled artifact, we've
defeated the value prop — the agent is consuming uncompiled content
and we've added a build step that produces something nobody loads.

So `aip compile` produces the **whole skill folder**: SKILL.md is
the primary output (with structured content + frontmatter that
Claude Code can read), and the skill folder is the build output
directory. The original human-prose source becomes another artifact
inside the folder (`references/source.md` or similar), preserved
for traceability but no longer the live source of truth after
compile. Metadata is also an artifact — either in SKILL.md
frontmatter under `metadata:`, or as a separate file in the folder.

**This is a deliberate hack of Anthropic's framework.** Their spec
treats SKILL.md as the canonical hand-authored skill definition;
we treat it as a compile target. The hack is necessary because the
alternative (SKILL.md as source, our YAML downstream) means agents
read the uncompiled form — defeating the entire compile-step value
prop. Worth being explicit about: we use Anthropic's framework as
our delivery mechanism, not as our authoring model.

## Validation surface — v0.1

There is no separate CLI binary. Validation is provided by Python
scripts bundled inside the `aip` skill's `scripts/` folder, run via
`uv run` (which handles isolated environments and inline dependencies
with no install step):

```bash
# Run by the agent as a final check, or directly in CI / pre-commit
uv run scripts/validate.py <skill-folder|doc.yml>   # doc against its declared schema
uv run scripts/validate_schema.py <schema.json>     # schema against AIP conventions
```

The Anthropic Skills spec ([agentskills.io/skill-creation/using-scripts](https://agentskills.io/skill-creation/using-scripts))
explicitly supports this pattern: scripts in `scripts/` are
referenced by relative path from the skill root, invoked by the
agent via bash, and their stdout/stderr feed directly into the
agent's context. For CI without an agent, the same commands run
directly — same scripts, same `uv run`, no extra installation.

**Why scripts-in-skill, not a standalone CLI:**

- No install step for users — the skill installs the validation
  tooling along with the knowledge.
- The agent can invoke them inline during the conversational workflow
  (e.g. Scenario 2: validate the user-supplied schema before
  compiling; Scenario 3: validate each schema draft as it's iterated).
- CI use is identical: `uv run scripts/validate.py doc.yml` works
  directly from the skill folder path.
- A standalone binary would require a separate package, separate
  versioning, and a separate install step — complexity with no
  benefit at v0.1 scale.

**What is NOT a script (and why):**

- `compile` — agent behavior guided by SKILL.md knowledge, not a
  script. The agent writes files; no script is needed.
- `draft-schema` — conversational agent activity (Scenario 3). The
  agent iterates and calls `validate_schema.py` on each draft.
- `install` — directory move the agent performs directly.

**DB publishing (deferred):**

```bash
# Future — not in this repo at v0.1
aip publish <skill-folder>             # → DB (aip-neo4j, aip-postgres, …)
aip get <skill-name> --out <path>      # ← DB
aip list --schema [name]               # inventory
aip archive|deprecate|rm <skill-name>  # delete from DB
```

All hard governance problems (provenance, idempotency, sharing,
versioning, deprecation, schema migration) live here. Separate
discussion when ready.

## Items to deliberate

### Item 1 — What does `aip compile` produce?

#### Problem

The agent reads SKILL.md directly (per Anthropic spec). For the
compile step to actually compile *for the agent*, SKILL.md must be
our output. The compile step therefore produces the whole skill
folder — not a YAML sidecar next to a human-authored SKILL.md.

But the original human-prose source has value too: traceability,
re-compilation if we change the schema, debugging when the
compiled form drifts from authorial intent. So the source isn't
discarded; it's preserved as another artifact in the build output.

Question: where exactly does each piece land in the skill folder?

#### Options

##### Option 1a — SKILL.md primary, source in references/

```
~/.claude/skills/my-skill/
  SKILL.md                  # ← compile output (frontmatter + structured body)
  references/
    source.md               # ← original human prose, preserved
  assets/                   # ← per Anthropic spec, optional
  scripts/                  # ← per Anthropic spec, optional
```

`aip compile <source.md> --name my-skill` creates the folder, writes
SKILL.md, copies the source into `references/`. Re-compiling
overwrites SKILL.md but preserves the source.

**Pros**
- Maximally Anthropic-spec-compatible. `references/` is a
  documented subdir; using it for source preservation is on-pattern.
- Source is preserved for traceability and re-compile.
- SKILL.md is the agent's input, fully under our control.

**Cons**
- Two copies of related content live in the same folder (compiled +
  source). Storage cost is small but conceptually overlapping.
- Re-compile semantics need spec'ing: do we always overwrite
  SKILL.md? What if someone hand-edited it after compile?

##### Option 1b — SKILL.md primary, source in assets/

Same as 1a but source lives in `assets/source.md` instead of
`references/`.

**Pros**
- `assets/` per Anthropic spec is for "files that the skill copies
  or embeds in its output" — arguably less semantically right than
  `references/` for our use.

**Cons**
- Less conventional. `references/` reads as "background context for
  the agent" which is a better fit for "original prose."

→ Reject in favor of 1a.

##### Option 1c — SKILL.md only, source discarded

`aip compile` reads source, writes SKILL.md, doesn't preserve the
source. User keeps source elsewhere (in a `drafts/` folder, in
git, wherever) by their own convention.

**Pros**
- Clean output — only the artifact lives in the skill folder.
- No "two sources of truth" risk.

**Cons**
- Loses the in-folder traceability. If you receive someone's skill
  folder, you can't see what it was compiled from.
- Re-compile requires the user to remember where they put the
  source.

##### Option 1d — Source not preserved by `aip`; `aip` records source path

Source stays where the user put it; `aip compile` writes the source
path into SKILL.md frontmatter (`metadata: { source_path: ... }`)
or into a sidecar `meta.yml`. No source-copy in the skill folder.

**Pros**
- Single source of truth; no duplication.
- Path-traceable (you know where the source lives).

**Cons**
- Brittle: source path can move/break; receiver of the skill folder
  has no source unless they get the source repo too.
- Cross-machine sharing breaks (path is local).

#### Tentative lean

**Option 1a (SKILL.md primary, source in `references/`).** The
`references/` slot is already the documented Anthropic convention
for "files the agent can load when it needs deeper context."
Putting the original prose there is on-pattern AND useful: agents
can fall back to the original phrasing for context, and humans can
inspect what the artifact was compiled from.

The "two copies" concern is small — disk is cheap, and the source
copy is guaranteed-available wherever the skill folder lives.

Re-compile semantics for v0.1: **always overwrite SKILL.md, warn
if the SKILL.md was hand-edited after the recorded compile time
(by hash diff).** Hand-editing the compiled artifact is allowed but
tracked; re-compile is destructive of those hand-edits.

### Item 2 — Where does metadata live?

#### Problem

The compile step needs to record metadata that doesn't belong in
either the human-prose source or the agent-facing structured body:
- Source path / source hash (for re-compile detection)
- Compile timestamp / compile version
- Schema name + schema version compiled against
- Author / created_by (for governance later)
- Deliberation links (cross-doc provenance)
- Description (already in SKILL.md frontmatter for skills)
- Version (recommended in `metadata:` per Anthropic spec)

In the new framing (SKILL.md is output, not source), metadata is
also an output artifact. Question: where does it live in the skill
folder?

#### Options

##### Option 2a — In SKILL.md frontmatter `metadata:` field

Per Anthropic spec, `metadata:` is the catch-all key-value map.
Put everything there.

**Pros**
- Anthropic-spec compatible without inventing a new file.
- Single file (SKILL.md) carries the whole artifact.
- Loaded into context with the rest of frontmatter (~100 tokens).

**Cons**
- Frontmatter loaded for *triggering* — bloating it with
  bookkeeping noise (compile timestamps, source hashes) wastes
  trigger-context tokens that should be reserved for `description`.
- Anthropic spec says frontmatter is `~100 tokens`. Heavy metadata
  blows that budget.
- Mixes agent-facing metadata (version, license) with tooling
  metadata (compile timestamp, source hash) — different audiences.

##### Option 2b — Separate file in skill folder

`<skill-folder>/meta.yml` (or `.aip.yml` if we want to namespace)
carries all tooling metadata. SKILL.md frontmatter holds only what
Anthropic spec requires (`name`, `description`) plus optional
agent-facing extras (`license`, `version`).

**Pros**
- Keeps SKILL.md frontmatter lean — only triggering-relevant
  content.
- Clean split: SKILL.md is for the agent; `meta.yml` is for our
  tooling.
- Easy to extend (add new metadata fields to `meta.yml` without
  touching SKILL.md).

**Cons**
- Extra file in the skill folder (small cost; it's not in any of
  Anthropic's named subdirs but the spec allows arbitrary files).
- Two-file pattern means receiver of the folder needs both.

##### Option 2c — Hybrid: agent-facing in frontmatter, tooling in sidecar

Split metadata by audience:
- SKILL.md frontmatter `metadata:` holds **agent-facing** fields
  (version, author, license, deliberation_links — anything the
  agent might surface).
- `<skill-folder>/meta.yml` holds **tooling-facing** fields
  (compile timestamp, source hash, schema version, source path,
  internal review status).

**Pros**
- Each piece of metadata lives where its consumer is.
- Frontmatter stays lean of bookkeeping noise.
- `meta.yml` becomes the audit/governance file.
- Maps cleanly to consumer expectations: agents see what they need;
  tooling sees what it needs.

**Cons**
- Two places to look for "what's the metadata?"
- Requires a clear rule for which field goes where (which becomes
  schema-authored, ideally).

#### Tentative lean

**Option 2c (hybrid).** The split is real — agent-facing metadata
and tooling-facing metadata have different consumers, different
update cadences, and different sensitivity to bloat. Putting them
together would force one consumer to deal with the other's noise.

Concretely:
- SKILL.md frontmatter: `name`, `description`, optional `version`,
  optional `license`, optional `metadata: { author, deliberation_links }`
- `meta.yml` (or `<sidecar-name>.yml`): everything else —
  `source_path`, `source_sha256`, `compile_timestamp`,
  `compile_version`, `schema_name`, `schema_version`, `source_hand_edited`

For non-skill docs (Item 3 below), the same pattern: a primary
artifact + a sidecar metadata file in the same folder (or sibling
file if the doc is single-file).

### Item 3 — Skills vs. general documents — what's the output shape?

#### Problem

Skills have Anthropic's folder shape to plug into (`<name>/SKILL.md`
+ optional subdirs). General docs (deliberations, specs, runbooks,
post-mortems) have no such constraint. What's the output shape for
those?

Two patterns to choose from:

##### Option 3a — Folder pattern for everything

Every compiled doc gets a folder, mirroring the skill convention:

```
my-deliberation/
  DOC.md                # primary artifact (could keep `SKILL.md` for uniformity?)
  references/source.md  # original prose
  meta.yml              # tooling metadata
```

**Pros**
- Uniform output shape across all doc types.
- Same `aip compile` semantics for everything.
- Sidecar metadata + source preservation work the same way.

**Cons**
- For docs that are read by humans (not agents), the folder pattern
  feels heavy — a single discussion doc becomes 3 files in a
  directory.
- Doesn't slot into any external tool's expectations the way the
  skill folder slots into Anthropic's.

##### Option 3b — Folder for skills, single-file for docs

Skills compile to folders (per Anthropic spec). General docs
compile to a single file with sidecar metadata in `.aip/`:

```
~/.claude/skills/my-skill/
  SKILL.md
  references/source.md
  meta.yml

docs/v0_4_0/
  ai-discussion.md      # the compiled doc (YAML head, prose body if useful)
  .aip/
    source.md           # original prose
    meta.yml
```

**Pros**
- Each doc type gets the shape native to its environment.
- Skills slot into Claude Code; docs slot into typical repo
  conventions (single files in a docs dir).
- Avoids heavy folder structures for what could be a single file.

**Cons**
- Two output patterns to understand and document.
- Cross-doc consistency is weaker (skill metadata in `meta.yml` at
  folder root; doc metadata in `.aip/meta.yml` at doc dir).

##### Option 3c — Schema-driven (the schema itself declares output shape)

Each schema declares its preferred output shape: `output: folder`
or `output: file`. `aip compile` dispatches based on the schema's
declaration.

**Pros**
- Maximum flexibility — schemas pick the shape that fits their use
  case.
- Easy to add new output shapes (e.g., `output: bundle` for a
  zip-archived doc).

**Cons**
- Adds a per-schema decision that has to be made up front.
- Spreads the output-shape logic across N schemas instead of one
  CLI rule.

#### Tentative lean

**Option 3b (folder for skills, single-file for docs).** Pragmatic.
Skills need to plug into Anthropic's folder convention because
that's how Claude Code finds them. Other docs don't have that
constraint, so the folder pattern adds weight without adding value.
Single-file with `.aip/` sidecar covers the metadata and source
preservation for non-skill docs.

This means we have two output patterns. Document them clearly:

| Doc type           | Output shape                                                 |
|--------------------|--------------------------------------------------------------|
| Skills             | Folder: `<name>/SKILL.md` + `references/source.md` + `meta.yml` |
| Everything else    | Single file: `<name>.yml` (or `.md`) + sidecar `.aip/source.md` + `.aip/meta.yml` |

Option 3c (schema-driven) is the long-term-clean answer if we end
up wanting more than two output shapes. v0.1 doesn't need that
flexibility.

### Item 4 — File system layout & integration with Claude Code

#### Problem

Claude Code reads `~/.claude/skills/` (personal) and
`./.claude/skills/` (project) at session startup. For our skill
output to integrate with existing agent workflows, we need to write
into those directories. For non-skill docs, we don't have that
constraint.

#### Options

##### Option 4a — In place with Claude Code's skills dir

`aip compile <source.md> --schema skill --name my-skill` writes to
`~/.claude/skills/my-skill/` by default (or `./.claude/skills/`
with a `--project` flag). For non-skill docs, output goes wherever
the user puts it (path-agnostic).

**Pros**
- Skills are immediately discoverable by Claude Code — no copy or
  sync step.
- Personal vs project distinction maps to existing Anthropic
  convention.
- Other doc types live in repo-natural places.

**Cons**
- Two patterns to learn (skill location vs. doc location).
- `aip compile` for skills WRITES into `~/.claude/skills/` —
  that's an opinionated default, even if overridable.

##### Option 4b — Single `aip` root for everything

`~/.aip/skills/`, `~/.aip/docs/`, etc. Claude Code doesn't see this
directly; we'd need a sync step to mirror skills back into
`.claude/skills/`.

**Pros**
- One canonical root for all our managed content.
- Cleaner separation of "Anthropic's stuff" vs. "our stuff."

**Cons**
- Sync step or symlinks needed for Claude Code to see skills.
- Adds a global config step.
- High adoption friction.

##### Option 4c — Path-agnostic (no opinion)

`aip compile` requires `--out` for every invocation; no defaults.

**Pros**
- Minimum opinion. Maximum flexibility.

**Cons**
- Every invocation is verbose.
- No discoverability story.

#### Tentative lean

**Option 4a (in place with Claude Code).** Skills compile to
`~/.claude/skills/<name>/` by default; `--project` writes to
`./.claude/skills/<name>/`; `--out <path>` overrides for
non-default locations. Other doc types are path-agnostic — the
user supplies `--out` or `aip` writes to a default within the
source's directory.

This makes `aip compile` for skills do the obvious thing: produce
something Claude Code immediately picks up. The opinion is small
and Anthropic-aligned; the override is one flag away.

## Items deferred to their own discussions

- **DB-publishing layer** (`aip publish`, `aip get`, `aip list`,
  `aip archive` and friends). All the hard governance problems —
  provenance, idempotency, sharing, permissions, versioning,
  deprecation, schema migration — live there. Separate discussion
  when we're ready.
- **Connector interface contract** (when we DO get to publishing).
  Already flagged as Open Question §1 in the [main spec](../spec.md).
- **Tool naming.** Resolved 2026-05-15: **`aip`** (package and
  binary). See
  [identity-and-naming.md](identity-and-naming.md).

## Open questions

### §1 — What does the compiled SKILL.md *body* contain?

Anthropic spec says SKILL.md body must be markdown. Our compile
step produces structured content. Three plausible shapes:

- **A: Well-structured markdown** (sections, lists, tables) —
  "structuredness" is conventional, not parser-required. Modern
  LLMs parse markdown extremely well; agents read it like any other
  prose. Stays human-inspectable in `cat` / IDE preview. Pays a
  small parsing tax vs raw YAML.
- **B: YAML in a code fence inside the body** —
  ```` ```yaml … ``` ````. Markdown-valid; structurally accessible
  if the agent or downstream tool parses the fence. Looks weird as
  markdown; doesn't read well to humans.
- **C: Most structure in frontmatter, body is minimal** —
  frontmatter `metadata:` carries the structured payload. Body is
  a short prose description for human readers. Strains frontmatter
  ergonomically with large payloads; loses the body-loaded
  progressive-disclosure benefit.

Lean: **A** for v0.1. Modern agents parse structured markdown
well; the human-inspectability is real value; Anthropic spec is
honored without weirdness. Revisit if we ever need parser access
to the structured content from a non-LLM consumer.

### §2 — Re-compile semantics

What happens when the source MD changes after compile?

- Always overwrite SKILL.md silently
- Hash the source on compile, store in `meta.yml`, warn on
  re-compile if the SKILL.md hash has drifted from the recorded
  hash (hand-editing detected)
- Refuse to re-compile if hand-edits detected; require explicit
  `--force`

Lean: hash + warn (middle option). Allow hand-edits but track them.

### §3 — Schema auto-discovery in `validate.py`

`uv run scripts/validate.py <doc>` — does it auto-discover the schema
from the doc's `schema:` field, or require `--schema`?

Lean: auto-discover from `schema:`; `--schema` overrides. Exit with
a clear error if `schema:` is missing AND `--schema` not provided.

### §4 — Sidecar dir / file naming

Currently `meta.yml` (skill folder) and `.aip/` (non-skill docs).
CLI tool name is now `aip` — sidecar dir stays `.aip/`. Locked.

### §5 — Compiling into an existing skill folder

If a skill folder already exists at `~/.claude/skills/my-skill/`
(e.g. a hand-authored skill with `scripts/`), and the agent compiles
into it — do we preserve existing `scripts/` content?

Lean: preserve existing subdirs (don't touch them), only manage
SKILL.md, `references/`, and `meta.yml`.

### §6 — Agent vs script split: resolved

**Resolved 2026-05-16.** There is no separate CLI binary. Compile,
draft-schema, and install are agent behaviors guided by SKILL.md.
Validate and validate-schema are Python scripts bundled in `scripts/`,
invoked via `uv run` by both the agent (inline) and CI (directly).
See [§Usage scenarios](#usage-scenarios) and
[§Validation surface — v0.1](#validation-surface--v01).

### §7 — Schema discovery convention (open)

For Scenario 1 (no schema specified) to work, the agent must know
what schemas already exist. The AIP skill should expose:
1. AIP example schemas (bundled in `examples/schemas/` in the `aip`
   repo and referenced from the skill).
2. Project-local schemas — the agent scans for `*.schema.json` files
   in the current project.
3. Schemas embedded in the user's installed skills — convention for
   where these live inside a skill folder is not yet defined.

Open questions: Should there be a `schemas/` convention inside skill
folders? Should `uv run scripts/validate_schema.py` have a `--register` flag to
add a validated schema to a known list? How does the agent discover
schemas from other users / teams? This needs its own discussion before
the AIP skill can be fully specified.

## Tentative leans summary

| Item                                        | Lean / Status                                                                           |
|---------------------------------------------|-----------------------------------------------------------------------------------------|
| Separate CLI binary?                        | **No** — validation is scripts in `scripts/` of the `aip` skill (resolved 2026-05-16)  |
| Validation surface                          | `uv run scripts/validate.py` + `uv run scripts/validate_schema.py` (resolved 2026-05-16) |
| compile / draft-schema as commands?         | **No** — agent behaviors guided by SKILL.md knowledge (resolved 2026-05-16)            |
| Script language                             | Python with PEP 723 inline deps, run via `uv run` (resolved 2026-05-16)                |
| 1. What does compilation produce?           | Whole skill folder; SKILL.md primary, source in `references/`                          |
| 2. Where does metadata live?               | Hybrid — agent-facing in SKILL.md frontmatter; tooling in `meta.yml`                   |
| 3. Skills vs general docs output shape?     | Folder for skills, single-file + `.aip/` sidecar for docs                              |
| 4. File system layout vs Claude Code?       | Agent installs directly to `~/.claude/skills/` or `.claude/skills/`                    |
| 5. Sidecar dir name                         | `.aip/`                                                                                 |
| 6. Agent vs script split                    | Resolved — see §6                                                                       |
| 7. Schema discovery convention              | **Open** — see §7                                                                       |

The v0.1 validation surface is two scripts in `scripts/`:

```bash
uv run scripts/validate.py <skill-folder|doc.yml> [--schema <name|path>]
uv run scripts/validate_schema.py <schema.json>
```

Compile, draft-schema, and install are agent behaviors guided by the
AIP skill — not scripts. Everything else (publish, get, list, archive)
is deferred to the DB-publishing discussion.

## Sources

- [Agent Skills specification](https://agentskills.io/specification)
- [Claude Code skills docs](https://code.claude.com/docs/en/skills)
- [Anthropic skills repo](https://github.com/anthropics/skills)
- [SKILL.md format reference](https://www.agensi.io/learn/skill-md-format-reference)
- [Where Claude skills are stored](https://www.agensi.io/learn/where-are-claude-skills-stored)
