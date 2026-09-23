<table>
  <tr>
    <td width="200" align="center" valign="middle">
      <img src="img/aip-logo.png" alt="aip logo" width="200" />
    </td>
    <td valign="middle">
      <h1>AIP — Agent Instruction Protocol</h1>
      <p><em>Structured Skills for Performance & Governance</em></p>
    </td>
  </tr>
</table>

## What Is AIP?

AIP is an extension to the [Agent Skills Spec](https://agentskills.io/home). The freeform markdown body is replaced with a fenced YAML block validated against a [JSON Schema](https://json-schema.org/). It models skills as an execution graph. 

## Why Use AIP?

AIP provides improved performance and stronger governance for autonomous agent skills.

**Performance**
- **Structured skills outperform freeform** and AIP enforced this authoring discipline. AIP requires schema-validated commitments to structured YAML with triggers, steps with script-backed nodes and I/O edges, scenarios, integrations, and anti-patterns. Early A/B evidence in our pre-print paper: [AIP: A Graph Representation for Learning and Governing Agent
Skills](https://arxiv.org/pdf/2606.04781) demonstrates lift for Claude Sonnet across a wide variety of SKillsBench tasks.
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

**Install AIP, fixed version** (Claude Code, project-local, pinned to `v0.4a0`):

```bash
git clone --depth 1 --branch v0.4a0 https://github.com/zach-blumenfeld/aip.git ./.claude/skills/aip
```

Replace `v0.4a0` with whichever release you want — see [tags](https://github.com/zach-blumenfeld/aip/tags) for the list.

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

The format of an AIP skill is defined in [`SKILL.md` § AIP Specification](SKILL.md#aip-specification). It follows the Agent Skills directory layout, requires a `source/` directory holding the human-readable material the skill was compiled from, requires a body that is an optional prose preamble followed by exactly one fenced YAML block, and adds one frontmatter key, `metadata.aip-version`.

## The Procedure Format

There is one format. It is defined by the pydantic models in `src/aip/spec/models.py`; the JSON Schema at [`assets/procedure.schema.json`](assets/procedure.schema.json) is generated from them and committed for editors and non-Python consumers. Regenerate it with `uv run aip schema --write assets/procedure.schema.json`; a test fails if it drifts. Steps are typed by `kind`: `decision`, `execution`, `client_task`, `router`, and `end`. See [`examples/billing-support`](examples/billing-support) for a complete skill.

## Validation

```bash
uv run scripts/validate.py <path/to/skill-folder>   # from a plain git clone, no install
uv run aip validate <path/to/skill-folder>           # with the package installed
```

Both run the same checks: frontmatter (Agent Skills rules plus `metadata.aip-version`), folder structure (`source/` present), body shape, the YAML against the format models, and graph checks the models cannot express: unique step names, a runnable start, exactly one end, every edge resolving, every step reachable from the start and able to reach the end, and every referenced asset, reference, and script present on disk.

Output is JSON Lines on stderr (`path`, `kind`, `message`, optional `location`, optional `severity`) and a one-line human summary on stdout. Exit 0 on success, 1 on any error.

## Development & Contributing

### Bumping the AIP protocol version

The AIP format version (currently `0.4a0`) is referenced in **multiple places** that must stay in sync. When bumping:

1. **`src/aip/spec/models.py`** — `FORMAT_VERSION`. The validator rejects skills whose `metadata.aip-version` differs from it.
2. **`assets/procedure.schema.json`** — regenerate with `uv run aip schema --write assets/procedure.schema.json`.
3. **`SKILL.md`** — the frontmatter version and every example that shows `metadata.aip-version`.
4. **`examples/`** — each example skill's `metadata.aip-version`.
5. **`README.md`** — install commands and any version references.
6. **`CHANGELOG.md`** — promote `[Unreleased]` to the new version section with a date.
7. **Git tag** — create the `v<X>` tag after the version-bump commit lands.

Drift is caught automatically: the schema-sync test fails if the committed schema is stale, and validation of the bundled example fails on an `aip_version_mismatch`.

### Changelog

See [`CHANGELOG.md`](CHANGELOG.md). The format follows [Keep a Changelog](https://keepachangelog.com/). Add notable changes under `[Unreleased]` as you make them; promote to a versioned section when you tag the release.

## Why is the AIP SKILL.md not written in AIP?

For the same reason that AI requires humans to build it: something has to exist before. Eventually the AIP skill itself may be authored in AIP form, just as agents may eventually build agents — but we're not there yet.
