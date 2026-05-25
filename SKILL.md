---
name: aip
description: Create skills as governance-ready AIP Instructions — schema-validated structure that gates quality at write time, catches silent drift, and makes a skill corpus queryable for governance and analytics. Use whenever authoring a skill an autonomous agent will consume, including net-new skills, compiling existing material (runbooks, deliberations, specs, decision logs, post-mortems), and drafting/refining the JSON Schemas skills validate against. Default to using this any time the consumer is an autonomous agent — the structural constraint is what makes a skill production-grade.
---

# AIP — Agent Instruction Protocol

## Trigger When

1. Authoring an agent skill (SKILL.md) for an autonomous agent
2. Creating an AIP schema
3. Validating an AIP skill or schema

## Do not Use When

- Authoring one-off prompts
- Authoring content no agent will consume (human-only wikis, FAQs, casual notes)

## What AIP Is

AIP is a thin extension to the [Agent Skills Spec](https://agentskills.io/specification.md). The freeform markdown body is replaced with a fenced YAML block validated against a [JSON Schema](https://json-schema.org/).

## Why Use AIP

AIP provides improved performance and stronger governance for autonomous agent skills.

**Performance**
- **Early A/B evidence.** AIP-structured skills scored higher than freeform-markdown equivalents on a behavior rubric in every session (+0.37 mean, 1–5 scale; largest gap +0.67 on a weaker agent — structure helps cheaper models close the gap). Small sample.
- **Tuning surface.** Schemas give a structured place to iterate when a skill underperforms — adjust typed fields, tighten validation. Plain markdown retunes only by rewriting prose.
- **Drift caught at write time.** Validation surfaces missing fields, wrong types, and rename mistakes before an agent silently misreads them.

**Governance**
- **Validated against a standard.** Every skill conforms to its schema; every schema to the AIP base. Quality gate before any consumer sees the skill.
- **Queryable at corpus scale.** Cross-skill questions become single queries ("every runbook missing a gotchas section") — no doc-trawling.
- **Database-ingestable.** Schema-validated YAML projects into a graph database for audit and analytics, no per-skill ETL.


## AIP Specification

### Directory Structure

AIP extends the directory structure of [Agent Skills](https://agentskills.io/specification.md):

**Agent Skill**
```shell
skill-name/
├── SKILL.md                       # Required: metadata + YAML-compliant instructions
├── scripts/                       # Optional: executable code
├── assets/                        # Optional: templates, resources
├── references/                    # Optional: documentation
└── ...                            # Any additional files or directories
```
**AIP Skill**
```shell
skill-name/
├── SKILL.md                       # Required: metadata + YAML-compliant instructions
├── source/                        # Required: AIP schema & canonical human-readable source
│   ├── skill-type.schema.json     # Required: the schema this skill validates against. Bundled locally even when reusing a shared schema, so the skill is self-contained.
│   └── ...                        # Any additional files or directories sourced to create this AIP skill
├── scripts/                       # Optional: executable code
├── assets/                        # Optional: templates, resources
├── references/                    # Optional: documentation
└── ...                            # Any additional files or directories
```

The `schema.json` follows the [json-schema.org](https://json-schema.org/) with some required fields. You can find out more below if required.

The `schema.json` is not unique to a skill but rather skill types/categories
- runbooks 
- rulebooks
- doc-templates
- ...

### `SKILL.md` Format

An AIP skill uses the `SKILL.md` file with Markdown format and file type. 

An AIP `SKILL.md` has two components
1. Frontmatter
2. Body

#### Frontmatter

YAML metadata at the top of `SKILL.md`, delimited by `---` markers.

| Field                   | Required | Notes                                                                                              |
|-------------------------|----------|----------------------------------------------------------------------------------------------------|
| `name`                  | Yes      | 1–64 chars; lowercase `a–z`, `0–9`, `-`. Must match the parent directory name.                     |
| `description`           | Yes      | 1–1024 chars. Describes *what* the skill encodes and *when* to use it; include specific keywords that help agents identify relevant tasks. |
| `metadata.aip.spec`     | Yes      | URL to the AIP spec version this skill conforms to. *AIP-specific.*                                |
| `metadata.aip.schemaId` | Yes      | URI matching the `$id` of the schema this skill validates against. The schema file is bundled in `source/` so the skill is self-contained, even when the `$id` points to a shared canonical URL. *AIP-specific.* |
| `license`               | No       | License name or reference to a bundled license file.                                               |
| `compatibility`         | No       | 1–500 chars. Environment requirements (intended product, system packages, network, runtime).       |
| Other `metadata.*` keys | No       | Arbitrary string→string mapping for team-specific metadata. Use unique key names.                  |
| `allowed-tools`         | No       | Space-separated string of pre-approved tools. Experimental — support varies.                       |

##### `name`

- 1–64 characters
- Lowercase Unicode alphanumeric (`a–z`, `0–9`) and hyphens only
- Must not start or end with a hyphen
- Must not contain consecutive hyphens (`--`)
- Must match the parent directory name

**Valid:** `pdf-processing`, `data-analysis`, `code-review`
**Invalid:** `PDF-Processing` (uppercase), `-pdf` (leading hyphen), `pdf--processing` (consecutive hyphens)

##### `description`

- 1–1024 characters
- Describes both *what* the skill does and *when* to use it
- Include specific keywords that help agents identify relevant tasks

**Good:** `Extracts text and tables from PDF files, fills PDF forms, and merges multiple PDFs. Use when working with PDF documents or when the user mentions PDFs, forms, or document extraction.`

**Poor:** `Helps with PDFs.`

##### `metadata.aip.spec` *(AIP-specific)*

URL to the AIP spec version this skill conforms to. Makes the skill self-describing — an AIP-unaware agent encountering the file can fetch the URL to learn the AIP format.

**Example:** `https://raw.githubusercontent.com/zach-blumenfeld/aip/main/README.md`

##### `metadata.aip.schemaId` *(AIP-specific)*

URI matching the `$id` of the schema this skill's YAML body validates against. Frontmatter is the single source of truth — the body does *not* repeat this.

**Example:** `https://github.com/zach-blumenfeld/aip/assets/aip-schemas/runbook.schema.json`

##### `license`

License name or short reference to a bundled license file. Keep it short.

**Example:** `Apache-2.0` or `Proprietary. LICENSE.txt has complete terms`

##### `compatibility`

- 1–500 characters
- Use only when the skill has specific environment requirements (intended product, system packages, network access, runtime versions)
- Most skills don't need this field

**Examples:**
- `Designed for Claude Code (or similar products)`
- `Requires git, docker, jq, and access to the internet`
- `Requires Python 3.14+ and uv`

##### `metadata`

- Map of string keys to string values for arbitrary team-specific properties
- AIP reserves the `metadata.aip.*` namespace for its own fields (see above)
- Use unique key names to avoid conflicts with future spec additions

**Example:**

```yaml
metadata:
  aip:
    spec: https://raw.githubusercontent.com/zach-blumenfeld/aip/main/README.md
    schemaId: https://github.com/zach-blumenfeld/aip/assets/aip-schemas/runbook.schema.json
  author: example-org
  version: "1.0"
```

##### `allowed-tools`

- Space-separated string of pre-approved tools the skill may use
- Experimental — support varies between agent implementations

**Example:** `Bash(git:*) Bash(jq:*) Read`

#### Body

The body — everything after the closing `---` of the frontmatter — must be **exactly one fenced YAML code block** with optional whitespace before and after. No surrounding prose or code blocks. The YAML inside the fence is the instructions the agent follows once the skill activates; it validates against the schema referenced by `metadata.aip.schemaId`.

Example:

````markdown
```yaml
purpose: >
  Research existing tools before writing custom code; recommend reuse or
  extension wherever an existing solution fits.

trigger_when:
  - Starting a new feature that likely has existing solutions.
  - Adding a dependency or integration.
  - User asks "add X functionality" and you're about to write code.

steps:
  - name: need-analysis
    description: Define what functionality is needed; identify language and framework constraints.
  - name: parallel-search
    description: Search npm/PyPI, MCP servers, available skills, and GitHub in parallel.
    parallel: true
  - name: evaluate
    description: Score candidates on functionality, maintenance, community, docs, license, and dependencies.
  - name: decide
    description: Choose Adopt as-is, Extend/Wrap, Compose, or Build Custom.
    one_of:
      - Adopt as-is
      - Extend / Wrap
      - Compose
      - Build Custom

decisions:
  - signal: Exact match, well-maintained, permissive license.
    action: Adopt — recommend the package and request approval before install.
  - signal: Partial match with good foundation.
    action: Extend — recommend the package plus a thin wrapper.
  - signal: Nothing suitable found.
    action: Build — explain why custom code is warranted.

anti_patterns:
  - Jumping to code without checking if a tool exists.
  - Ignoring MCP servers that already provide the capability.
  - Wrapping a library so heavily it loses its benefits.
```
````

### Optional directories

#### `scripts/`

Contains executable code that agents can run. Scripts should:

* Be self-contained or clearly document dependencies
* Include helpful error messages
* Handle edge cases gracefully

Supported languages depend on the agent implementation. Common options include Python, Bash, and JavaScript.

#### `references/`

Contains additional documentation that agents can read when needed:

* `REFERENCE.md` - Detailed technical reference
* `FORMS.md` - Form templates or structured data formats
* Domain-specific files (`finance.md`, `legal.md`, etc.)

Keep individual [reference files](#file-references) focused. Agents load these on demand, so smaller files mean less use of context.

#### `assets/`

Contains static resources:

* Templates (document templates, configuration templates)
* Images (diagrams, examples)
* Data files (lookup tables, schemas)

### Progressive disclosure

Agents load skills in three tiers, pulling more detail only as needed:

1. **Metadata (~100 tokens).** `name` and `description` load at startup for *every* installed skill. `description` is the only signal an agent has before deciding to activate the skill — make it specific and keyword-rich.
2. **Body (target <5000 tokens, ~500 lines).** The full `SKILL.md` body loads once the skill activates.
3. **Resources (on demand).** Files under `scripts/`, `references/`, and `assets/` load only when the skill body references them. Tell the agent *when* to load each (e.g., "Read `references/api-errors.md` if the API returns a non-200 status").

If the body would exceed the budget, push detail into `references/` rather than letting `SKILL.md` bloat. Body tokens cost every invocation; reference tokens cost only when loaded.

### File references

When referencing other files in your skill, use relative paths from the skill root:

```markdown SKILL.md theme={null}
See [the reference guide](references/REFERENCE.md) for details.

Run the extraction script:
scripts/extract.py
```

AIP Skills have the following 


## Authoring an Agent Skill

### Best Practices

#### Selective Typing

The highest-leverage authoring decision is the *shape* of each field in the body. Over-type and the body grows larger AND harder to read; under-type and the body stops being queryable.

**Rule: type a field only when an agent or a governance query would iterate or filter by a sub-field of it.** Otherwise leave it as prose.

Two independent questions per field:

1. **Is the content plural?** If yes, it's a list. The label of each item stays queryable even when the body is prose.
2. **Would something loop over items and look up a sub-field?** If yes, type the items as records. If no, keep items as prose.

Four shapes fall out:

- **Full typed records** — `steps` (`[{name, description, parallel?, one_of?}]`), `decisions` (`[{signal, action}]`), `examples` (`[{need, found, action, ...}]`). Iterated by sub-field.
- **Thin `{label, body}` envelopes** — `modes` (`[{name, body: |...}]`), `search_shortcuts` (`[{category, body: |...}]`), `integrations` (`[{partner, body: |...}]`). Label is queryable; body stays as prose.
- **List of strings** — `trigger_when`, `anti_patterns`. Plural with one-line items. Don't envelope.
- **Single `|`-block** — singular freeform content (`purpose`, `scope_and_approval`). Nothing iterates; nothing filters.

Each `{label, body}` envelope adds ~8–12 tokens of YAML scaffolding per item. Negligible for 2–10 items; consider flat strings or splitting the skill at 50+.

**Default to less typing.** If a field doesn't pass the "would something filter by a sub-field?" test, it's prose. Don't re-encode every bullet as a record or every table row as a sub-field. Over-typing is the failure mode — bigger body, harder to read, no queryability gain.

#### Body Drafting Style

- **Imperative form.** "Search npm before writing a utility" beats
  "the user should consider searching npm."
- **Explain the *why*, sparingly.** A short line of reasoning beats
  a paragraph of all-caps MUSTs. LLMs reason from intent.
- **Keep the prompt lean.** Skill bodies that feel padded waste
  tokens on every invocation.
- **No surprises.** Body contents should match what `description`
  promises.
- **Block scalars inside a sequence are indentation-sensitive.** A
  top-level `|`-block is easy; `[{name, body: |...}]` items with
  code fences or already-indented content are tricky. If an envelope
  keeps breaking, fall back to a list of strings with the label as
  a prefix.

### Checklist.  

Follow sequentially.

1. First read the [skill creation best practices guide](references/skill-creation-best-practices.md) and follow that same spirit here in addition to above AIP spec and best practices.
2. Identify source materials for domain-specific context
3. Establish the type of skill the user wants to author and the schema to use:
    - Bias to schema reuse over drafting new ones.
    - Find existing schemas in [aip-schemas](assets/aip-schemas) 
    - If you must draft a new schema see [references/author-schema.md](references/author-schema.md)
4. Lock the skill name
    - Ask the user what to call the skill. The name is short and slightly descriptive — it becomes the folder name. Lowercase kebab-case, <65 chars, no leading/trailing/consecutive hyphens.
    - Offer a multiple-choice list of recommendations plus a free-text option. If they type their own, validate against the rules above; on failure, state why and offer fresh suggestions plus free-text. Repeat until valid.
5. Scaffold skill directory 
    write first to a temporary location
    ```shell
    skill-name/
    ├── SKILL.md                       # Required: metadata + YAML-compliant instructions
    ├── source/                        # Required: AIP schema & canonical human-readable source
    ├── scripts/                       # Optional: executable code
    ├── assets/                        # Optional: templates, resources
    ├── references/                    # Optional: documentation
    └── ...                            # Any additional files or directories
    ```
    fill in the /source materials with
    - The schema used above
    - reference docs you will use to create the skill (domain-specific context).  including
      - a source SKILL.md a user provided for transition to AIP format
      - a README.md outlining you logic from above and intent of the skill
      - Any other documentation or reference you will use to create the AIP skill
    Also populate the following at the temp folder root if the skill needs them:
    - `scripts/` — executable code the skill invokes (e.g., validators, processors).
    - `assets/` — templates, output formats, or other resources the skill references.
    - `references/` — supporting documentation the skill loads on demand (progressive disclosure).
6. Create and validate the AIP `SKILL.md`
   1. Draft `SKILL.md` at the temp folder root using the source materials and the schema from `/source`. 
         - Frontmatter: `name`, `description`, `metadata.aip.spec`, `metadata.aip.schemaId` (matches the schema's `$id`).  
         - Body: exactly one fenced YAML block. No surrounding prose, no second code block. The body validates against the schema. 
   **#TODO:** Instead of the below have validate.py check for schema and run validate_schema itself
   2. Run `uv run scripts/validate.py <temp-folder>`. Re-run after every edit to `SKILL.md` or the schema — eyeball checks routinely miss AIP-namespace and required-metadata bugs. If editing schemas, also run `uv run scripts/validate_schema.py <schema file>`. On failure, apply tiered recovery:                                          
      - **Trivial** (typo, missing required field, formatting drift): fix silently and re-run.
      - **Substantive** (schema doesn't fit, semantic mismatch, structural conflict): surface the error in plain language with your proposed fix; confirm before retrying.
   3. Once validation passes, run a completeness check: walk the source domain-specific context line-by-line against the compiled body and classify every distinct piece of source content.                                                                         
      - **Mapped** — captured faithfully in the body. 
      - **Schema gap** — schema lacks a field for it. Fix the schema, re-point `schemaId`, re-compile. 
      - **Body drop** — schema has capacity, the body missed it. Re-author the body.                        
      - **Deliberate drop** — redundant or genuinely doesn't belong. Record it in `source/README.md` with rationale.
   4. Iterate until the body validates AND every source item is classified.
7. Install
   1. Ask the user what to do next:
      - **Install now** — proceed below.
      - **Iterate further** — keep editing in the temp folder.
      - **Leave it as-is** — they'll handle placement manually. Tell them the temp path and stop.
   2. If installing, confirm the location with the user. Standard Agent Skills locations:
      - **Project-local** — the host agent's project skills directory (e.g., `./.claude/skills/<name>/` for Claude Code). Default if CWD is in a git repo.
      - **User-global** — the host agent's user-wide skills directory (e.g., `~/.claude/skills/<name>/` for Claude Code). Default otherwise.
   3. If a folder already exists at the destination, ask before overwriting. For prior AIP Instructions, preserve top-level `scripts/`, `assets/`, `references/` and overwrite only `SKILL.md` and `source/`.
   4. Move `<temp-folder>/` → `<install-location>/<name>/` (folder name must equal `name` in frontmatter).
   5. Tell the user the install path. Project-local installs may need a fresh agent session to activate.

## Creating an AIP Schema
Follow the directions in [`author-schema.md`](references/author-schema.md)

## Validating an AIP Skill or Schema
For an AIP Skill 

## Anti-Patterns

1. Unnecessarily drafting a new schema when a sufficient schema already exists for the skill type
2. Drafting schemas that are specific to individual skills rather than the category / type / family of the skill
3. Dropping content from original SKILL.md to over compress a SKILL.md

