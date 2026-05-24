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

## What AIP is

AIP is a thin protocol for creating YAML structured agent skills that comply with json schemas. 

AIP complies with the Agent Skills Spec but adds this YAML structure

**Base Agent Skill**
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
│   ├── skill-type.schema.json     # Required: schema spec
│   └── ...                        # Any additional files or directories sourced to create this AIP skill
├── scripts/                       # Optional: executable code
├── assets/                        # Optional: templates, resources
├── references/                    # Optional: documentation
└── ...                            # Any additional files or directories
```

The `schema.json` follows the [json-schema.org](https://json-schema.org/) with some required fields. You can find out more below if required

The `schema.json` is not unique to a skill but rather skill types/categories
- runbooks 
- rulebooks
- doc-templates
- ...

An AIP skill uses the SKILL.md and keeps the markdown format and file type.  The YAML body is fenced in a code block:


````markdown
---
name: search-first
description: >
  Runbook for the search-first workflow — .....
metadata:
  aip:
    spec: https://raw.githubusercontent.com/zach-blumenfeld/aip/main/spec.md
    schemaId: urn:uuid:8c4f7e3a-1b5d-4f8e-9a2c-6b3e5f7d8c9a
  origin: ECC
---

```yaml
purpose: >
  Research existing tools, libraries, MCP servers, ...

trigger_when: ...

steps:...

anti_patterns:...

always_remember:...

...

```
````

## Why Use AIP

AIP has the following benefits over the base Agent Skill Spec:

- Higher performance on procedure heavy workflows:  Recent research (links TBD) note
- ...?

## Authoring an Agent Skill

Checklist.  Follow sequentially.

1. First read the [skill creation best practices guide](references/skill-creation-best-practices.md) and follow that same advise here. 
2. Establish the type of skill the user wants to author
3. Identify source materials for domain-specific context
4. Establish the Schema to use:
    - Bias to schema reuse over drafting new ones.
    - Find existing schemas in [](assets/aip-schemas) 
    - If you must draft a new schema see [references/author-schema.md](references/author-schema.md)
5. Lock the skill name
    - Ask the user what to call the skill. The name is short and slightly descriptive — it becomes the folder name. Lowercase kebab-case, <65 chars, no leading/trailing/consecutive hyphens.
    - Offer a multiple-choice list of recommendations plus a free-text option. If they type their own, validate against the rules above; on failure, state why and offer fresh suggestions plus free-text. Repeat until valid.
6. Scaffold skill directory 
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
7. Create and validate the AIP `SKILL.md`
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
8. Install
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


## Anti-Patterns

1. Unnecessarily drafting a new schema when a sufficient schema already exists for the skill type
2. Drafting schemas that are specific to individual skills rather than the category / type / family of the skill
3. Dropping content from original SKILL.md to over compress a SKILL.md

