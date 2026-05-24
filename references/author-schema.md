# AIP Schema Authoring
Guide for authoring AIP compliant schemas

## Trigger When
The user wants to create or refine an AIP-compliant JSON Schema

## AIP Schema Spec

### AIP Schema Requirements
Hard requirements validated by the [`validate_schema.py`](../scripts/validate_schema.py) script.

- AIP schemas follow [the JSON Schema spec](https://json-schema.org/draft/2020-12/json-schema-core). 
- Additional required metadata and floor properties are declared in [`assets/base.schema.json`](../assets/base.schema.json) — copy it into each new schema; do not `$ref` it.

Beyond the base schema, every AIP schema must also satisfy:
- Strict schemas only: every object subschema (root,
  `$defs` entries, nested properties, array items, `oneOf` branches)
  must explicitly declare `additionalProperties` — `false`
- Property naming: avoid JSON Schema reserved keywords as property names. Spec-compliant validators (including AIP's) handle them correctly under `properties`/`$defs.*.properties`, but JSON-Schema-aware IDEs (VS Code, JetBrains) flag false squiggles. `validate_schema.py` emits a soft warning. Pick a synonym:

| Reserved keyword | Meta-schema type | Suggested alternatives                                 |
|------------------|------------------|--------------------------------------------------------|
| `examples`       | array            | `cases`, `samples`, `worked_examples`, `scenarios`     |
| `enum`           | array            | `options`, `choices`, `allowed_values`, `valid_values` |
| `required`       | array            | `mandatory`, `must_have`, `required_fields`            |
| `format`         | string           | `style`, `shape`, `format_type`                        |
| `const`          | (special)        | `literal`, `fixed_value`                               |
| `default`        | (annotation)     | `default_value`, `initial`                             |

### AIP Schema Best Practices
- AIP schemas should be scoped to the **category of work** a family of skills enable, not to a specific skill instance. 
  - Good names:`runbook`, `document-template`, `reference`, `post-mortem`,
  `deliberation`. 
  - Bad names: `search-first`, `friday-deploy-check` — those are skills *built on* a schema, not schemas themselves.
  - If the user's content fits an existing schema, prefer
  reuse. If it's genuinely a new category, scope the new schema as broadly as that category warrants — one schema should support many related skills.


## Checklist
Follow these steps sequentially when 
1. Read the AIP schema spec in this directory: `aip-schema-spec.md`. YOu must comply
2. Understand the users domain-specific context and keep in context what makes a good skill as outlined in `skill-creation-best-practices.md`
3. Identify the type/category of skill this schema will cover and title and description for the skill.  
   1. should not be scoped to single-skill.  i.e. ... but instead represent a category ...
   2. Should be distinct from existing schemas in [assets/aip-schemas](..assets/aip-schemas)
   3. Ask the user with proposed names and descriptions. Offer a multiple-choice list of recommendations plus a free-text option. 
      - The title is short and slightly descriptive, optimized for human display and understanding. <65 chars
      - descriptions described the type category of skill. 
      - Offer a multiple-choice list of recommendations plus a free-text option. If they type their own, validate against the methodology above; on failure, state why and offer fresh suggestions plus free-text. Repeat until valid.
4. 


Lowercase kebab-case,