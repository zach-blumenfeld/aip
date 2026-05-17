# AIP example schemas

This directory contains reference schemas bundled with the AIP skill.
The AIP skill scans this directory in Scenario 1 (no schema specified)
to recommend candidate schemas to the user — see
[spec.md §Schema discovery](../../spec.md#schema-discovery).

## Current state

**v0.1: this directory may be empty.** The canonical AIP example
schemas are still being curated. The `workflow/schemas/` folder in the
repo root contains prototype schemas (`deliberation.schema.json`,
`generic.schema.json`) that predate the session 5 metadata requirements
— they're useful as structural references but need a metadata refresh
(`$schema`, `$id`, `title`, `description`, top-level `aip:` namespace)
before being promoted here.

## Layout convention

Each example schema lives in its own subdirectory:

```
references/examples/
├── deliberation/
│   ├── deliberation.schema.json    # the schema itself
│   └── README.md                   # optional schema documentation
├── runbook/
│   ├── runbook.schema.json
│   └── README.md
...
```

The subdirectory name should match the schema's `title` (lowercase,
hyphenated) for human discoverability.

## What a bundled schema must satisfy

Every schema in this directory must pass
`uv run scripts/validate_schema.py <schema-path>`. See
[spec.md §AIP schema conventions](../../spec.md#aip-schema-conventions)
for the full rule set.

Minimum metadata at the schema root:

- `$schema` — JSON Schema dialect (e.g.
  `https://json-schema.org/draft/2020-12/schema`)
- `$id` — UUID URN (`urn:uuid:<uuid>`)
- `title` — short display name
- `description` — short prose description
- `aip:` — at minimum an empty object `{}` (AIP-compliance marker;
  `aip.version` and `aip.tag` recommended but optional in v0.1)

Plus the structural conventions: no reserved property names
(`id`, `schemaId`, `key`, `idx`, `_source`), strict-core /
open-extensions pattern at the root (`additionalProperties: false`,
with an optional `extensions` property), and clearly-named `$defs`
entries.
