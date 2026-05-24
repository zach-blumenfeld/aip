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

Steps:

1. Establish the type of skill they want to author

    ...?
    
    Try to use existing schemas rather than creating new ones.

2. Get the schema

    If you must draft a new schema see `references/draft-schema.md`
    Otherwise get your schema from `assets/aip-schemas`

3. Identify source materials

    Expect users to bring previous Markdown files, SKILL.md or other documentation.
    If users have no source - collect all the details you need from them to make a complete skill
    source materials require a reference markdown SKILL.md in base agent skill format. This either comes from the user, or you need to create it.  See anthropic skill guidance for creating a good skill `references/md-skill-guidance` if you are creating. 

4. Lock the skill name

    Ask the user want they want to call the skill names should be ...?
    Offer a multiple choice list with your recommendations and an option for them to type something.
    If they type their own, validate against recommendations above
    if validation fails, state why and provide a multiple choice list with suggested variations and option for them to type something.  repeat until a choice is made

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
    fill in the /source materials.  With
    - The schema used above
    - reference docs used to create the skill.  including
      - a source SKILL.md a user provided for transition to AIP format
      - a README.md outlining you logic from above and intent of the skill
      - Any other documentation or referenced you will use to create the AIP skill
    
6. Create and validate the AIP SKILL - see 


## Anti-Patterns

1. Unnecessarily drafting a new schema when a sufficient schema already exists for the skill type
2. Drafting schemas that are specific to individual skills rather than the category / type / family of the skill
3. Dropping content from original SKILL.md to over compress a SKILL.md

