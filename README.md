<table>
  <tr>
    <td width="200" align="center" valign="middle">
      <img src="img/aip-logo.png" alt="aip logo" width="200" />
    </td>
    <td valign="middle">
      <h1>AIP — Agent Instruction Protocol</h1>
      <p><em>Structured Skills for Performance &amp; Governance</em></p>
    </td>
  </tr>
</table>

## What Is AIP?

AIP is an extension to the [Agent Skills Spec](https://agentskills.io/home). The freeform markdown body is replaced with a fenced YAML block validated against a [JSON Schema](https://json-schema.org/). It models skills as an execution graph. 

## Why Use AIP?

AIP provides improved performance and stronger governance for autonomous agent skills.

**Performance**
- **Structured skills outperform freeform** and AIP enforced this authoring discipline. AIP requires schema-validated commitments to structured YAML with triggers, steps with script-backed nodes and I/O edges, scenarios, integrations, and anti-patterns. Early A/B evidence in [`zach-blumenfeld/aip-test`](https://github.com/zach-blumenfeld/aip-test) suggests the lift is biggest on under-structured markdown skills (tables and ASCII diagrams parsed into typed YAML).
- **Concrete tuning surface.** Schemas give a structured place to iterate when running evals — adjust typed fields, tighten validation. Plain markdown retunes only by rewriting prose.
- **Drift caught at write time.** Validation surfaces missing fields, wrong types, and rename mistakes before an agent silently misreads them.

**Governance**
- **Validated against a standard.** Every skill conforms to its schema; every schema to the AIP base. Quality gate before any consumer sees the skill.
- **Queryable at corpus scale.** Cross-skill questions become single queries ("every runbook missing a gotchas section") — no doc-trawling.
- **Database-ingestable.** Schema-validated YAML projects into a graph database for governed distribution, audit, and analytics.

## Quickstart

AIP ships as an Agent Skill for co-authoring AIP artifacts (skills & schemas). Install it into your agent's skills directory; the skill activates the next time you talk to your agent about authoring or validating an AIP artifact.

**Requirements:** [uv](https://docs.astral.sh/uv/) — used to run the bundled Python validators. Install with

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Install AIP, latest** (Claude Code, project-local, tracks `main`):

```bash
git clone --depth 1 https://github.com/zach-blumenfeld/aip.git ./.claude/skills/aip
```

**Install AIP, fixed version** (Claude Code, project-local, pinned to `v0.3a3`):

```bash
git clone --depth 1 --branch v0.3a3 https://github.com/zach-blumenfeld/aip.git ./.claude/skills/aip
```

Replace `v0.3a3` with whichever release you want — see [tags](https://github.com/zach-blumenfeld/aip/tags) for the list.

For **user-global install** or **other agents**, change the target directory:

- **Claude Code, user-global:** `~/.claude/skills/aip`
- **Other Agent-Skills–compatible runtimes:** check the runtime's docs for where it loads skills from.

Once installed, ask your agent something like *"author an AIP procedure skill for X"* or *"validate this AIP skill folder."* The skill walks the rest of the conversation.

### Model Recommendation for Co-Authoring

Use the **largest frontier model available** when using the AIP skill. The work is cognitively intense and underrepresented in current training data — smaller models struggle.

For *consuming* the resulting skill, the opposite holds: AIP's structure is what makes smaller, cheaper models more competitive on workflow-heavy tasks.

## Procedures

The AIP skill exposes three top-level procedures:

1. **Author an AIP skill** — bring source material (or describe verbally); the agent compiles it into a YAML body validated against a schema. Details in [`SKILL.md` § Authoring an Agent Skill](SKILL.md#authoring-an-agent-skill).
2. **Author or refine an AIP schema** — the agent walks through schema design, applying execution-graph framing and permissive-on-prose defaults. Details in [`references/author-schema.md`](references/author-schema.md).
3. **Validate an AIP skill or schema** — run the bundled scripts directly, or let the agent run them as part of authoring. Details in [`SKILL.md` § Validating an AIP Skill or Schema](SKILL.md#validating-an-aip-skill-or-schema).

## AIP Skill Spec

The format of an AIP skill is defined in [`SKILL.md` § AIP Specification](SKILL.md#aip-specification). It extends the Agent Skills directory layout with a `source/` directory holding the bundled schema, requires a fenced YAML body, and adds two AIP-namespaced frontmatter fields (`metadata.aip.spec`, `metadata.aip.schemaId`).

## AIP Schema Spec

The conventions every AIP schema must follow live in [`references/author-schema.md`](references/author-schema.md). Hard requirements (validated by `validate_schema.py`) cover JSON Schema conformance, AIP namespace metadata, strict `additionalProperties: false`, the universal `purpose` + `trigger_when` floor, and JSON Schema reserved-keyword avoidance. Best practices cover category scoping, designing for execution graphs, permissive-on-prose defaults, and file naming.

## Validation Scripts

Two Python scripts under `scripts/`, run via `uv run` — no install step, no virtualenv:

```bash
uv run scripts/validate.py <path/to/skill-folder>
uv run scripts/validate_schema.py <path/to/schema.json>
```

`validate.py` validates an AIP skill end-to-end: frontmatter (including Agent Skills format rules and AIP-namespace fields), folder structure (`source/` with a bundled `*.schema.json`), AIP-compliance of the bundled schema, body fence shape, body-against-schema. `validate_schema.py` validates a JSON Schema against AIP conventions in isolation.

Both emit JSON Lines on stderr (`path`, `kind`, `message`, optional `location`, optional `severity`) and a one-line human summary on stdout. Exit 0 on success, 1 on any error; warnings are advisory.

## Development & Contributing

### Bumping the AIP protocol version

The AIP protocol version (currently `v0.3a3`) is referenced in **multiple places** that must stay in sync. When bumping (e.g., `v0.3a3` → `v0.3`):

1. **`SKILL.md` frontmatter** — `metadata.aip.version`.
2. **`SKILL.md` body** — the "Currently:" URL under `##### metadata.aip.spec`, and every example URL (frontmatter examples, YAML examples, worked examples).
3. **`assets/base.schema.json`** — the literal `aip.spec` URL.
4. **`README.md`** — install commands and any version references.
5. **`CHANGELOG.md`** — promote `[Unreleased]` to the new version section with a date.
6. **Git tag** — create the `v<X>` tag after the version-bump commit lands.

Drift between any of these is caught automatically: `validate.py` and `validate_schema.py` read the AIP version from `SKILL.md`'s frontmatter and require each artifact's `aip.spec` to match. Mismatches surface as `aip_spec_mismatch`.

### Changelog

See [`CHANGELOG.md`](CHANGELOG.md). The format follows [Keep a Changelog](https://keepachangelog.com/). Add notable changes under `[Unreleased]` as you make them; promote to a versioned section when you tag the release.

## Why is the AIP SKILL.md not written in AIP?

For the same reason that AI requires humans to build it: something has to exist before. Eventually the AIP skill itself may be authored in AIP form, just as agents may eventually build agents — but we're not there yet.
