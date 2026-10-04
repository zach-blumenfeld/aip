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
- **Structured skills outperform freeform** and AIP enforces this authoring discipline. AIP requires schema-validated commitments to structured YAML with a purpose, triggers and non-triggers, steps with script-backed nodes and I/O edges, and anti-patterns. Early A/B evidence in our pre-print paper: [AIP: A Graph Representation for Learning and Governing Agent
Skills](https://arxiv.org/pdf/2606.04781) demonstrates lift for Claude Sonnet across a wide variety of SkillsBench tasks.
- **Concrete tuning surface.** The schema gives a structured place to iterate when running evals — adjust typed fields, tighten validation. Plain markdown retunes only by rewriting prose.
- **Drift caught at write time.** Validation surfaces missing fields, wrong types, and rename mistakes before an agent silently misreads them.

**Governance**
- **Validated against a standard.** Every skill validates against the one AIP procedure schema and its graph rules. Quality gate before any consumer sees the skill.
- **Queryable at corpus scale.** Cross-skill questions become single queries ("every runbook missing a gotchas section") — no doc-trawling.
- **Database-ingestable.** Schema-validated YAML projects into a graph database for governed distribution, audit, and analytics.

## Quickstart

AIP ships as an Agent Skill for co-authoring AIP skills. Install it into your agent's skills directory; the skill activates the next time you talk to your agent about authoring or validating an AIP artifact.

**Requirements:** [uv](https://docs.astral.sh/uv/) — used to run the bundled Python validator. Install with

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

AIP `0.4a0` is in active development on the `aip-s1` branch and is not tagged yet. Install from the branch.

**Install AIP** (Claude Code, project-local, tracks `aip-s1`):

```bash
git clone --depth 1 --branch aip-s1 https://github.com/zach-blumenfeld/aip.git ./.claude/skills/aip
```

The released [tags](https://github.com/zach-blumenfeld/aip/tags) (`v0.3a3` and earlier) predate the 0.4a0 format and do not work with the current tooling. Once 0.4a0 is tagged and merged to `main`, pin a release with `--branch v0.4a0` instead.

For **user-global install** or **other agents**, change the target directory:

- **Claude Code, user-global:** `~/.claude/skills/aip`
- **Other Agent-Skills–compatible runtimes:** check the runtime's docs for where it loads skills from.

Once installed, ask your agent something like *"author an AIP procedure skill for X"* or *"validate this AIP skill folder."* The skill walks the rest of the conversation.

### Model Recommendation for Co-Authoring

Use the **largest frontier model available** when using the AIP skill. The work is cognitively intense and underrepresented in current training data — smaller models struggle.

For *consuming* the resulting skill, the opposite holds: AIP's structure is what makes smaller, cheaper models more competitive on workflow-heavy tasks.

## Procedures

The AIP skill exposes two top-level procedures:

1. **Author an AIP skill** — bring source material (or describe verbally); the agent compiles it into an execution graph validated against the AIP procedure schema, runs it, and tests it. Details in [`SKILL.md` § Authoring an Agent Skill](SKILL.md#authoring-an-agent-skill).
2. **Validate an AIP skill** — run the bundled validator directly, or let the agent run it as part of authoring. Details in [`SKILL.md` § Validating an AIP Skill](SKILL.md#validating-an-aip-skill).

## AIP Skill Spec

The format of an AIP skill is defined in [`SKILL.md` § AIP Specification](SKILL.md#aip-specification). It follows the Agent Skills directory layout, requires a `source/` directory holding the human-readable material the skill was compiled from, requires a body that is the fixed AIP runtime block followed by exactly one fenced YAML block, so every skill carries its own execution semantics and any agent can run it with no aip tooling present, and adds one frontmatter key, `metadata.aip-version`.

## The Procedure Format

There is one format. It is defined by the pydantic models in `src/aip/spec/models.py`; the JSON Schema at [`assets/procedure.schema.json`](assets/procedure.schema.json) is generated from them and committed for editors and non-Python consumers. Regenerate it with `aip schema --write assets/procedure.schema.json`; a test fails if it drifts. The runtime block every authored skill carries at the top of its body lives in the package too (`aip runtime` prints it); the validator rejects a skill whose block is missing or edited. For the server case, the package also ships the `aip-runtime` meta-skill ([`skills/aip-runtime/SKILL.md`](skills/aip-runtime/SKILL.md); `aip runtime --skill --out <skills dir>` writes it), the one page an agent reads to find and run published procedures through the client. Steps are typed by `kind`: `decision`, `execution`, `client_task`, `router`, and `end`. See [`examples/billing-support`](examples/billing-support) for a complete skill.

## Installing the `aip` CLI

```bash
uv tool install --editable .        # from the repo root; puts `aip` on PATH, tracks your edits
uv tool uninstall aip               # to remove
```

Inside the repo, `uv run aip ...` works without installing. Every command below assumes `aip` is on PATH.

## Validation

```bash
aip validate <path/to/skill-folder>                  # with the CLI installed
uv run scripts/validate.py <path/to/skill-folder>   # from a plain git clone, no install
```

Both run the same checks: frontmatter (Agent Skills rules plus `metadata.aip-version`), folder structure (`source/` present), body shape, the YAML against the format models, and graph checks the models cannot express: unique step names, a runnable start, exactly one end, every edge resolving, every step reachable from the start and able to reach the end, unique input names, thresholds naming real questions, and every referenced asset, reference, and script present on disk.

Output is JSON Lines on stderr (`path`, `kind`, `message`, optional `location`, optional `severity`) and a one-line human summary on stdout. Exit 0 on success, 1 on any error.

## Running a Skill

```bash
aip info <path/to/skill-folder>                       # what it does, the input it expects, how it flows
aip info <path/to/skill-folder> --example-input > start.json   # a start input to edit
aip run <path/to/skill-folder> --input start.json     # runs until the client must decide
aip resume <run-file> --input answer.json             # continues a paused run
aip run <path/to/skill-folder> --interactive           # prompts on the terminal instead
```

With a server (`aip server --backend filesystem|neo4j`, see [`docs/server-design.md`](docs/server-design.md)), the same commands take a published name, and the catalog has its own:

```bash
export AIP_SERVER=http://localhost:8000               # or: aip config --server URL [--token T]
aip publish <path/to/skill-folder>                     # validate, upload, prints name@revision
aip search "refund"                                    # ranked by the server
aip list                                               # every name with the revision it resolves to
aip info <name> --example-input > start.json
aip run <name> --input start.json                      # runs on the server; same pause and resume
aip get <name>[@revision] --out ./restored             # the folder back, hash-verified and validated
aip pin <name> <revision>  /  aip retire <name>@<revision>
```

`aip run` drives the procedure locally with the same engine the server uses. It follows the server's suggested input from step to step and pauses, writing a run file and exiting with code 3, when the client has to act: a client task to perform, a decision answered below its threshold to confirm or override, or, when `TYPESAFE_API_KEY` is not set, a decision's questions to answer yourself. The pause is printed as JSON with what is expected next and the exact resume command. `--threshold name=value` overrides a decision threshold for the run.

## Loading Skills into Neo4j

```bash
uv sync --extra neo4j                                  # the driver is an optional dependency
export NEO4J_URI=neo4j://localhost:7687 NEO4J_USERNAME=neo4j NEO4J_PASSWORD=...
aip db load <path/to/skill-folder>                     # validates, then writes one revision
aip db list                                            # every skill and revision in the database
aip db export <name> --out ./restored                  # rebuilds <name>/ byte for byte and verifies hashes
```

Each load is lossless: every file under the skill folder is stored as a `File` node with its exact bytes, mode, and sha256, so `export` reproduces a folder that validates and runs identically. Alongside the files, the parsed procedure is projected as `Procedure`, `Step` (labelled by kind), `Input`, and `Question` nodes with `INPUTS_TO`, `BRANCH`, `DECLARES_INPUT`, `ASKS`, and `USES` edges, the last pointing at the `File` nodes a step runs, renders, or may load. Skills are keyed `name@revision`, where the revision is a hash of the files: reloading unchanged content is a no-op, changed content adds a revision, and many skills coexist in one database. A `Name` node groups the revisions of one skill and carries its pin; `Run` and `StepRun` nodes record executions, linked `NEXT` in order and `OF_STEP` to the step they ran.

`aip db` is a thin shim over the server's Neo4j backend (`aip.server.backends.neo4j`), which also serves the catalog, a full-text search index over names, descriptions, purposes, and triggers, and a hash-verified materialisation cache under `~/.cache/aip/` (`AIP_CACHE_DIR` overrides) that the server executes from. The filesystem backend (`aip.server.backends.filesystem`) offers the same contract over a plain directory.

## Development & Contributing

```bash
uv sync --group dev                                    # pytest and the Neo4j driver
uv run pytest -q                                       # the Neo4j backend tests skip unless NEO4J_URI is set
```

The rebuild toward the client-server architecture is tracked milestone by milestone in [`docs/PLAN.md`](docs/PLAN.md); the design it implements is [`docs/server-design.md`](docs/server-design.md).

### Bumping the AIP protocol version

The AIP format version (currently `0.5a0`) is referenced in **multiple places** that must stay in sync. When bumping:

1. **`src/aip/spec/models.py`** — `FORMAT_VERSION`. The validator rejects skills whose `metadata.aip-version` differs from it, except the versions in `LEGACY_VERSIONS`, which pass with a `runtime_block_outdated` warning.
2. **`src/aip/spec/runtime.md`** — the block's heading carries the version; if the text changes, keep the previous text as `runtime-<old>.md` and add `<old>` to `LEGACY_VERSIONS`.
3. **`assets/procedure.schema.json`** — regenerate with `aip schema --write assets/procedure.schema.json`.
4. **`SKILL.md`** — the frontmatter version, the embedded runtime block, and every example that shows `metadata.aip-version`.
5. **`examples/`** — each example skill's `metadata.aip-version`.
6. **`README.md`** — install commands and any version references.
7. **`CHANGELOG.md`** — promote `[Unreleased]` to the new version section with a date.
8. **Git tag** — create the `v<X>` tag after the version-bump commit lands.

Drift is caught automatically: the schema-sync test fails if the committed schema is stale, and validation of the bundled example fails on an `aip_version_mismatch`.

### Changelog

See [`CHANGELOG.md`](CHANGELOG.md). The format follows [Keep a Changelog](https://keepachangelog.com/). Add notable changes under `[Unreleased]` as you make them; promote to a versioned section when you tag the release.

## Why is the AIP SKILL.md not written in AIP?

For the same reason that AI requires humans to build it: something has to exist before. Eventually the AIP skill itself may be authored in AIP form, just as agents may eventually build agents — but we're not there yet.
