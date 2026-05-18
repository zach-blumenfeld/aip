# Scenario 3 — schema authoring

When the user wants to create or refine an AIP-compliant JSON Schema
rather than compile a doc. Conversational — no fixed step sequence.

## General approach

1. **Understand the domain** the schema will validate. Pull in
   reference material: other schemas, user examples, web sources.
2. **Identify the core structure**: main fields, required vs
   optional, the strict-core / open-extensions split.
3. **Draft and validate** with required AIP root metadata and
   structural rules (see [AIP-compliant schema requirements](#aip-compliant-schema-requirements)
   below). Run `uv run scripts/validate_schema.py <draft>`.
4. **Iterate.** Don't dump the schema JSON by default — offer:
   *"Want to see the schema, or should I describe what's in it?"*
   Most users will want a description. Gather feedback, refine,
   re-validate. Watch for:
   - Reserved property names (`id`, `schemaId`, `key`, `idx`,
     `_source`) — never allowed, anywhere in the schema
   - DB-specific keywords (`x-graph-*`, `x-neo4j-*`) — not allowed
   - Strict-core pattern violations (open key sets at object roots)
5. **Settle.** When the validator passes and the user is satisfied,
   offer to install at `references/examples/<name>/` as a bundled
   reference, or use it immediately for a Scenario 2 compile.

## Depth selector applies

- **Quick:** "Give me a draft based on what we've discussed; I'll
  review."
- **Balanced:** "Let's settle the main fields together, then you
  draft and I'll review."
- **Thorough:** "Walk me through every decision before drafting."

## Scoping the schema's name and shape

Custom schemas should be scoped to the **category of work** the
skill enables, not to the specific skill instance. Good names:
`runbook`, `document-template`, `reference`, `post-mortem`,
`deliberation`. Bad names: `search-first`, `friday-deploy-check` —
those are skills *built on* a schema, not schemas themselves.

If the user's content fits an existing schema category, prefer
reuse. If it's genuinely a new category, scope the new schema as
broadly as that category warrants — one schema should support many
related skills.

## AIP-compliant schema requirements

Required root metadata:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:uuid:<generated>",
  "title": "Short display name",
  "description": "One or two sentences.",
  "aip": { "version": "0.1", "tag": "discovery-tag" },
  "type": "object",
  "properties": { ... }
}
```

Generate `$id` with `uuidgen` or Python `uuid.uuid4()`.

Structural rules:

- **Reserved property names** (never define, anywhere in the schema):
  `id`, `schemaId`, `key`, `idx`, `_source`. All five are
  connector-injected at ingest time.
- **Strict-core / open-extensions:** every object subschema (root,
  `$defs` entries, nested properties, array items, `oneOf` branches)
  must explicitly declare `additionalProperties` — `false` to close
  the key set (the default choice), or `true` / a schema when
  intentionally open. JSON Schema's silent default of `true` is not
  allowed. Pattern for doc-specific overflow: closed parent with an
  `extensions:` property whose value is an open object.
- **`$defs` entries become node types in storage** when a connector
  ingests — give each a clearly-named key.
- **No DB-specific keywords** (no `x-graph-*`, `x-neo4j-*`). Schemas
  are vendor-neutral.

## Avoid JSON Schema reserved keywords as property names

JSON Schema's meta-schema types some annotation keywords (`examples`,
`enum`, `required`, `format`) as non-object values. Naive linters in
VS Code, JetBrains, and similar IDEs apply this rule path-blind —
flagging `properties.examples` (a data property whose value is
correctly a sub-schema object) as the wrong type. Spec-compliant
validators (jsonschema, ajv default mode, the AIP validators)
correctly distinguish keyword-position from data-position and don't
flag this. But every author who opens the schema in a JSON-Schema-
aware IDE sees the squiggle.

`validate_schema.py` emits a soft warning when it sees one of these
names under `properties` or `$defs.*.properties`. Pick a synonym
instead:

| Reserved keyword | Meta-schema type | Suggested alternatives                  |
|------------------|------------------|------------------------------------------|
| `examples`       | array            | `worked_examples`, `cases`, `scenarios`  |
| `enum`           | array            | `options`, `choices`, `valid_values`     |
| `required`       | array            | `required_fields`, `mandatory`           |
| `format`         | string           | `format_type`, `style`                   |
| `const`          | (special)        | `fixed_value`, `literal`                 |
| `default`        | (annotation)     | `default_value`, `initial`               |

Keywords like `title`, `description`, `type` are also reserved but
their meta-schema types are strings — they typically don't trip
linters but are confusing as data-property names. Prefer synonyms.
