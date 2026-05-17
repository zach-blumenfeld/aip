# Schema discovery

Used in Scenario 1 of the AIP skill (no schema specified by the user).
Search three sources for candidate schemas; for each candidate, read
`$id`, `title`, `description`, and `aip.tag`, then rank against the
user's intent.

## Sources

| Source                 | Where                                                                                  | Include only if…                                       |
|------------------------|----------------------------------------------------------------------------------------|--------------------------------------------------------|
| Bundled examples       | `references/examples/*/` (in this skill's folder)                                      | Always include.                                        |
| Project-local schemas  | `*.schema.json` under CWD (max depth 4, respect `.gitignore`)                          | Schema has a top-level `aip:` object.                  |
| Installed Instructions | `<host-agent>/skills/*/schema/*.schema.json` in user-global and project-local skill dirs (e.g., `~/.claude/skills/` and `./.claude/skills/` for Claude Code) | Containing skill's `SKILL.md` has `metadata.aip.spec`. |

## Dedup precedence

When the same `$id` appears in multiple sources, prefer in order:
**bundled > project-local > installed**.

## Why the filters matter

They keep out random `*.schema.json` files (AJV fixtures, npm package
schemas) and non-AIP installed skills. Non-AIP schemas won't validate
against AIP's expectations and won't carry the metadata an agent
relies on.

## If no candidate fits

Offer to draft a custom schema (Scenario 3 — see
[scenario-3-schema-authoring.md](scenario-3-schema-authoring.md)).
But try discovery first — schema reuse is the preference, especially
for v0.1 when the bundled corpus is still small.
