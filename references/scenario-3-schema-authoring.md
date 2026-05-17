# Scenario 3 — schema authoring

When the user wants to create or refine an AIP-compliant JSON Schema
rather than compile a doc. Conversational — no fixed step sequence.

## General approach

1. **Understand the domain** the schema will validate. Pull in
   reference material: other schemas, user examples, web sources.
2. **Identify the core structure**: main fields, required vs
   optional, the strict-core / open-extensions split.
3. **Draft and validate** with required AIP root metadata (see
   SKILL.md → Format essentials → AIP-compliant schema). Run
   `uv run scripts/validate_schema.py <draft>`.
4. **Iterate.** Don't dump the schema JSON by default — offer:
   *"Want to see the schema, or should I describe what's in it?"*
   Most users will want a description. Gather feedback, refine,
   re-validate. Watch for:
   - Reserved property names (`id`, `schemaId` inside `$defs`, `key`,
     `idx`, `_source`) — not allowed
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

## Required AIP root metadata (reference)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:uuid:<generated>",
  "title": "Short display name",
  "description": "One or two sentences.",
  "aip": { "version": "0.1", "tag": "discovery-tag" },
  "type": "object",
  "properties": { "schemaId": { "const": "urn:uuid:<same-as-$id>" }, ... }
}
```

Generate `$id` with `uuidgen` or Python `uuid.uuid4()`.
