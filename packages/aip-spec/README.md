# AIP — Agent Instruction Protocol

*The procedure format, its validator, and the authoring skill.*

AIP is an extension to the [Agent Skills Spec](https://agentskills.io/home). The freeform
markdown body is replaced with a fenced YAML block validated against a
[JSON Schema](https://json-schema.org/). It models skills as an execution graph.

This repo is the **spec**: the pydantic models that define the format, the validator, the
runtime block every skill carries, the `aip` authoring skill that compiles source material
into it, and a complete example. The **runtime**, which executes procedures with a client
and server (`aip run`, `aip server`, the inspector), is
[zach-blumenfeld/aip](https://github.com/zach-blumenfeld/aip); it depends on this package.

## Why Use AIP?

AIP provides improved performance and stronger governance for autonomous agent skills.

**Performance**
- **Structured skills outperform freeform** and AIP enforces this authoring discipline. AIP requires schema-validated commitments to structured YAML with a purpose, triggers and non-triggers, steps with script-backed nodes and I/O edges, and anti-patterns. Early A/B evidence in our pre-print paper: [AIP: A Graph Representation for Learning and Governing Agent Skills](https://arxiv.org/pdf/2606.04781) demonstrates lift for Claude Sonnet across a wide variety of SkillsBench tasks.
- **Concrete tuning surface.** The schema gives a structured place to iterate when running evals — adjust typed fields, tighten validation. Plain markdown retunes only by rewriting prose.
- **Drift caught at write time.** Validation surfaces missing fields, wrong types, and rename mistakes before an agent silently misreads them.

**Governance**
- **Validated against a standard.** Every skill validates against the one AIP procedure schema and its graph rules. Quality gate before any consumer sees the skill.
- **Queryable at corpus scale.** Cross-skill questions become single queries ("every runbook missing a gotchas section") — no doc-trawling.
- **Database-ingestable.** Schema-validated YAML projects into a graph database for governed distribution, audit, and analytics.

## Install

One line installs [uv](https://docs.astral.sh/uv/) if missing, the `aip-spec` CLI, and the
`aip` authoring skill into every agent it detects (Claude Code, Cursor, Windsurf, Copilot,
Gemini CLI, Cline, Codex, Pi, OpenCode, Junie):

```bash
curl -sSfL https://raw.githubusercontent.com/zach-blumenfeld/aip-spec/main/install.sh | bash
```

Prefer Python tooling:

```bash
uv tool install git+https://github.com/zach-blumenfeld/aip-spec.git@v0.6a1
aip-spec skill install                 # every detected agent
aip-spec skill install claude-code     # one agent;  aip-spec skill list  shows them
aip-spec skill install --path ./.claude/skills    # a project-local skills directory
aip-spec skill remove
```

For the runtime as well (`aip run`, the client and the server), use the installer in
[zach-blumenfeld/aip](https://github.com/zach-blumenfeld/aip); it pulls this package in.

Once installed, ask your agent something like *"author an AIP procedure skill for X"* or *"validate this AIP skill folder."* The skill walks the rest of the conversation.

### Model Recommendation for Co-Authoring

Use the **largest frontier model available** when using the AIP skill. The work is cognitively intense and underrepresented in current training data — smaller models struggle.

For *consuming* the resulting skill, the opposite holds: AIP's structure is what makes smaller, cheaper models more competitive on workflow-heavy tasks.

## Procedures

The AIP skill exposes two top-level procedures:

1. **Author an AIP skill** — bring source material (or describe verbally); the agent compiles it into an execution graph validated against the AIP procedure schema, runs it, and tests it. Details in [`SKILL.md` § Authoring an Agent Skill](SKILL.md#authoring-an-agent-skill).
2. **Validate an AIP skill** — run `aip-spec validate` directly, or let the agent run it as part of authoring. Details in [`SKILL.md` § Validating an AIP Skill](SKILL.md#validating-an-aip-skill).

## AIP Skill Spec

The format of an AIP skill is defined in [`SKILL.md` § AIP Specification](SKILL.md#aip-specification). It follows the Agent Skills directory layout, requires a `source/` directory holding the human-readable material the skill was compiled from, requires a body that is the fixed AIP runtime block followed by exactly one fenced YAML block, so every skill carries its own execution semantics and any agent can run it with no aip tooling present, and adds one frontmatter key, `metadata.aip-version`.

## The Procedure Format

There is one format. It is defined by the pydantic models in [`src/aip_spec/models.py`](src/aip_spec/models.py); the JSON Schema at [`assets/procedure.schema.json`](assets/procedure.schema.json) is generated from them and committed for editors and non-Python consumers. Regenerate it with `aip-spec schema --write assets/procedure.schema.json`; a test fails if it drifts. The runtime block every authored skill carries at the top of its body lives in the package too ([`src/aip_spec/runtime.md`](src/aip_spec/runtime.md); `aip-spec runtime` prints it); the validator rejects a skill whose block is missing or edited. Steps are typed by `kind`: `decision`, `execution`, `client_task`, `router`, and `end`. See [`examples/billing-support`](examples/billing-support) for a complete skill; `aip-spec example billing-support --out .` copies it out of the installed package.

## Validation

```bash
aip-spec validate <path/to/skill-folder>
```

It checks frontmatter (Agent Skills rules plus `metadata.aip-version`), folder structure (`source/` present), body shape, the YAML against the format models, and graph checks the models cannot express: unique step names, a runnable start, exactly one end, every edge resolving, every step reachable from the start and able to reach the end, unique input names, thresholds naming real questions, every consumed key produced on every path to it or declared on the start step, each key produced exactly once, `outputs` on every client task, a `requires` block when there are scripts, and every referenced asset, reference, and script present on disk. A `0.5a1` skill is reported as one upgrade, `runtime_block_outdated`, naming the three edits it needs.

Output is JSON Lines on stderr (`path`, `kind`, `message`, optional `location`, optional `severity`) and a one-line human summary on stdout. Exit 0 on success, 1 on any error.

## Using the Package

```python
from aip_spec import validate_skill, ProcedureSpec, json_schema, runtime_text, example_dir, skill_dir

loaded, issues = validate_skill("./billing-support")   # LoadedSkill | None, list[Issue]
```

`aip_spec` imports only pydantic and pyyaml. `skill_dir()` is the bundled authoring skill and `example_dir(name)` a bundled example; `aip_spec.agents` is the agent detection `aip-spec skill install` uses, which the `aip` package shares.

## Development & Contributing

```bash
uv sync --group dev && uv run pytest -q
```

### Bumping the AIP format version

The format version (currently `0.6a1`) is referenced in several places that must stay in sync. In this repo, in order:

1. **`src/aip_spec/models.py`** — `FORMAT_VERSION`, and `pyproject.toml`'s `version`. The validator rejects skills whose `metadata.aip-version` differs from `FORMAT_VERSION`, and reports skills in a version listed in `LEGACY_VERSIONS` as `runtime_block_outdated` (a warning when the old format is still accepted, an error after a breaking change such as `0.6a0`).
2. **`src/aip_spec/runtime.md`** — the block's heading carries the version; if the text changes, keep the previous text as `runtime-<old>.md`, add `<old>` to `LEGACY_VERSIONS`, and give it an entry in `UPGRADES` in `src/aip_spec/skill.py` (the edits an `<old>` skill needs, which the validator prints).
3. **`assets/procedure.schema.json`** — regenerate with `aip-spec schema --write assets/procedure.schema.json`.
4. **`SKILL.md`** — the frontmatter version, the embedded runtime block, and every example that shows `metadata.aip-version`.
5. **`examples/`** — each example skill's `metadata.aip-version`.
6. **`README.md`** — install commands and any version references.
7. **`CHANGELOG.md`** — promote `[Unreleased]` to the new version section with a date.
8. **`install.sh`** — the default `AIP_SPEC_REF`.
9. **Git tag** — create the `v<X>` tag after the version-bump commit lands.

Then, in [zach-blumenfeld/aip](https://github.com/zach-blumenfeld/aip): the git pin on this package, the `aip-runtime` skill's `aip-version`, its `install.sh` tag, and its CHANGELOG. The spec is tagged first, always, because the pin names the tag.

Drift is caught automatically: the schema-sync test fails if the committed schema is stale, the runtime-block test fails if `SKILL.md` and `runtime.md` disagree, and validation of the bundled example fails on an `aip_version_mismatch`.

### Changelog

See [`CHANGELOG.md`](CHANGELOG.md). The format follows [Keep a Changelog](https://keepachangelog.com/). Add notable changes under `[Unreleased]` as you make them; promote to a versioned section when you tag the release.

## Why is the AIP SKILL.md not written in AIP?

For the same reason that AI requires humans to build it: something has to exist before. Eventually the AIP skill itself may be authored in AIP form, just as agents may eventually build agents — but we're not there yet.
