# AIP Schema Authoring
Guide for authoring AIP compliant schemas

## Trigger When
The user wants to create or refine an AIP-compliant JSON Schema

## AIP Schema Spec
AIP schemas represent families/categories of AIP skills. They are used to govern and validate AIP skills. 

### AIP Schema Requirements
Hard requirements validated by the [`validate_schema.py`](../scripts/validate_schema.py).

- AIP schemas follow [the JSON Schema spec](https://json-schema.org/draft/2020-12/json-schema-core). 
- Required root metadata (all must be non-empty strings): `$schema`, `$id` (URI form), `title`, `description`.
- Additional required metadata and floor properties are declared in [`assets/base.schema.json`](../assets/base.schema.json) — copy it into each new schema; do not `$ref` it. The base has two zones:
  - **Chevron-placeholder fields** (`$id`, `title`, `description`, `aip.version`, `aip.tag`) — replace with schema-family-specific values.
  - **Literal copy** (`$schema`, `type`, `additionalProperties`, `required`, `properties` floor, and `aip.spec`) — copy verbatim, do not modify. `aip.spec` is the URL pointing at the AIP spec version the base was bumped to; modifying it breaks the conformance contract.

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
  - Good names:`runbook`, `document-template`, `reference`, `post-mortem`, `deliberation`. 
  - Bad names: `search-first`, `friday-deploy-check` — those are skills *built on* a schema, not schemas themselves.
  - If the user's content fits an existing schema, prefer
  reuse. If it's genuinely a new category, scope the new schema as broadly as that category warrants — one schema should support many related skills.
- **Default to permissive** — required-minimum core, freeform-text leaves. Type a field only when an agent or a governance query would iterate or filter by a sub-field. See [SKILL.md § Selective Typing](../SKILL.md#selective-typing) for the rule and the four field shapes. Over-typing the first draft is the most common authoring failure.
- AIP schema files should be named with the convention: `<lowercase kebab-case of title field>.schema.json`
- New AIP schemas  should be distinct from existing schemas in [`assets/aip-schemas`](../assets/aip-schemas)

## Checklist
Follow these steps sequentially
1. Read the [AIP Schema Spec](#aip-schema-spec)
2. Understand [what makes a good skill](skill-creation-best-practices.md). It is helpful background context when authoring schemas.
3. Identify the category of skill this schema will cover and the title and description fields for the skill.
   - Offer a multiple-choice list of recommendations plus a free-text option to the user 
      - The title is short and slightly descriptive, optimized for human display and understanding. <65 chars.
      - descriptions described the category in 1-2 sentences
      - Offer a multiple-choice list of recommendations plus a free-text option. If they type their own, validate against the methodology above; on failure, state why and offer fresh suggestions plus free-text. Repeat until valid.
4. Establish identity and AIP metadata. For each item below, propose a value; the user can accept the recommendation or provide their own.
   - `$id`: propose a URI in this priority order. User-supplied alternatives must be a URI in a namespace they control.
      - Refining an existing schema → keep its current `$id`.
      - Other AIP schemas exist in the project → reuse their namespace pattern with the new filename.
      - Git remote available → derive from it (e.g., `https://github.com/<owner>/<repo>/schemas/<kebab-title>.schema.json`).
      - None of the above → propose a placeholder based on the user's stated org/handle.
   - `aip.version`: propose `0.1` for new schemas; bump from the previous version when refining. This is the *schema's own* version — not the AIP protocol version, which is declared by `aip.spec` (the URL to AIP spec version this schema targets).
   - `aip.tag`: propose omitting; include only when a discovery hint clearly helps.
5. Identify the core structure: main fields, required vs optional, etc. Apply [SKILL.md's Selective Typing rule](../SKILL.md#selective-typing) to keep the floor permissive — type only what an agent or query would iterate by; leave the rest as prose.
6. Write schema file to a temporary location. `<lowercase kebab-case of title field>.schema.json`
7. Validate:
   1. Run `uv run scripts/validate_schema.py <draft>` 
   2. Manually check against [AIP Schema Best Practices](#aip-schema-best-practices)
   On failure, apply tiered recovery:                                          
      - Trivial (typo, missing required field, formatting drift): fix silently and re-run.
      - Substantive (schema doesn't fit, semantic mismatch, structural conflict): surface the error in plain language with your proposed fix; confirm before retrying.
8. Iterate until clean.
9. Move schema file to appropriate location