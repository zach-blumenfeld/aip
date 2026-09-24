---
name: aip
description: Create skills as governance-ready AIP Instructions — schema-validated structure that gates quality at write time, catches silent drift, and makes a skill corpus queryable for governance and analytics. Use whenever authoring a skill an autonomous agent will consume, including net-new skills, compiling existing material (runbooks, deliberations, specs, decision logs, post-mortems), and drafting/refining the JSON Schemas skills validate against. Default to using this any time the consumer is an autonomous agent — the structural constraint is what makes a skill production-grade.
metadata:
  aip:
    version: "0.4a0"
---

# AIP — Agent Instruction Protocol

## Trigger When

1. Authoring an agent skill (SKILL.md) for an autonomous agent
2. Creating an AIP schema
3. Validating an AIP skill or schema

## Do not Use When

- Authoring one-off prompts
- Authoring content no agent will consume (human-only wikis, FAQs, casual notes)

## What AIP Is

AIP is an extension to the [Agent Skills Spec](https://agentskills.io/specification.md) that enables a structured graph workflow. The freeform markdown body is replaced with a fenced YAML block validated against a [JSON Schema](https://json-schema.org/) representing a graph workflow of the underlying procedural logic.  This specification can then be used to configure an AIP server that together with the AIP client offers traversal protocol over this graph for fast structured workflow execution. 

## Why Use AIP

AIP provides improved performance and stronger governance for autonomous agent skills.

**Performance**
- **Early A/B evidence.** AIP-structured skills scored higher than freeform-markdown equivalents on a behavior rubric in every session (+0.37 mean, 1–5 scale; largest gap +0.67 on a weaker agent — structure helps cheaper models close the gap). Small sample.
- **Tuning surface.** Schemas give a structured place to iterate when a skill underperforms — adjust typed fields, tighten validation. Plain markdown retunes only by rewriting prose.
- **Drift caught at write time.** Validation surfaces missing fields, wrong types, and rename mistakes before an agent silently misreads them.

**Governance**
- **Validated against a standard.** Every skill conforms to its schema; every schema to the AIP base. Quality gate before any consumer sees the skill.
- **Queryable at corpus scale.** Cross-skill questions become single queries ("every runbook missing a gotchas section") — no doc-trawling.
- **Database-ingestable.** Schema-validated YAML projects into a graph database for audit and analytics, no per-skill ETL.


## AIP Specification

### Terminology

- **Client**: whoever drives the run: posts each step's input, reviews uncertain decisions, performs client tasks, and makes the final call at every step. With an AIP server, that is the agent or person on the other end. As a plain Agent Skill, it is the agent that activated the skill.
- **Server**: runs each step and validates its input against the step's `inputs`. Without one, the activating agent does this itself: runs scripts, answers decision questions by its own judgment, and follows routers.
- **State**: the JSON object a step receives. Each step declares its required keys as `inputs`; extra keys pass through.
- **Step kinds**: `execution` runs a script, `decision` asks typed questions about the state, `client_task` hands work to the client, `router` branches on a value in the state, `end` declares the final state's shape.

### Directory Structure

AIP extends the directory structure of [Agent Skills](https://agentskills.io/specification.md):

**Agent Skill**
```shell
skill-name/
├── SKILL.md                       # Required: metadata + YAML-compliant instructions
├── scripts/                       # Optional: executable code
├── assets/                        # Optional: templates, resources
├── references/                    # Optional: documentation
└── ...                            # Any additional files or directories
```
**AIP Skill**
```shell
skill-name/
├── SKILL.md                       # Required: metadata + YAML-compliant instructions
├── source/                        # Required: the canonical human-readable material this skill was compiled from
│   ├── README.md                  # Recommended: provenance and the log of what was deliberately dropped, with rationale
│   └── ...                        # Runbooks, specs, decision logs, or other material sourced to create this AIP skill
├── scripts/                       # Optional: executable code
├── assets/                        # Optional: templates, resources
├── references/                    # Optional: documentation
└── ...                            # Any additional files or directories
```

The YAML body of SKILL.md validates against the AIP procedure schema at assets/procedure.schema.json.

### `SKILL.md` Format

An AIP skill uses the `SKILL.md` file with Markdown format and file type. 

An AIP `SKILL.md` has two components
1. Frontmatter
2. Body

#### Frontmatter

YAML metadata at the top of `SKILL.md`, delimited by `---` markers.

| Field                   | Required | Notes                                                                                              |
|-------------------------|----------|----------------------------------------------------------------------------------------------------|
| `name`                  | Yes      | 1–64 chars; lowercase `a–z`, `0–9`, hyphens; no leading, trailing, or consecutive hyphens. Must match the parent directory name. |
| `description`           | Yes      | 1–1024 chars. Describes *what* the skill encodes and *when* to use it; include specific keywords that help agents identify relevant tasks. |
| `metadata.aip-version`  | Yes      | AIP format version this skill is written in. Currently `"0.4a0"`. *AIP-specific.*                  |
| `license`               | No       | License name or reference to a bundled license file, e.g. `Apache-2.0`.                            |
| `compatibility`         | No       | 1–500 chars. Only when the skill has specific environment requirements (intended product, system packages, network access, runtime versions); most skills don't need it. |
| Other `metadata.*` keys | No       | Arbitrary string→string mapping for properties not defined by the Agent Skills spec, e.g. `author`, `version` (the skill's own version, distinct from `aip-version`). Use unique key names. |
| `allowed-tools`         | No       | Space-separated string of pre-approved tools, e.g. `Bash(git:*) Read`. Experimental — support varies. |

##### `metadata`

- Map of string keys to string values for properties not defined by the Agent Skills spec, e.g. `author`, `version` (the skill's own version, distinct from `aip-version`)
- AIP reserves `metadata.aip-*` keys for its own fields (see above)
- Use unique key names to avoid conflicts with future spec additions

**Example:**

```yaml
metadata:
  aip-version: "0.4a0"
  author: example-org
  version: "1.0"
```

#### Body

The body — everything after the closing `---` of the frontmatter — must be **exactly one fenced YAML code block** with optional whitespace before and after. No surrounding prose or code blocks. The YAML inside the fence is the instructions the agent follows once the skill activates; it validates against the AIP procedure schema.

Example (pared down for illustration — real skills typically carry more steps and richer detail), from the bundled `examples/billing-support` skill. The first step is the start; the router branches server-side on the value the client chose:

````markdown
```yaml
purpose: >
  Turn an inbound billing message into either a tier-2 ticket or a drafted reply.
  A structured decision model classifies the message; the client confirms low-confidence
  calls; a script opens the ticket; the client drafts the reply against the refund policy.

trigger_when:
  - A customer message about a charge, invoice, refund, or subscription arrives.
  - Support asks to triage a billing complaint.

do_not_use_when:
  - The message is about product bugs or feature requests rather than billing.

steps:
  - name: triage
    kind: decision
    description: Classify whether the message is about billing and how upset the customer is.
    inputs:
      - name: message
        type: string
        description: The customer's message, verbatim.
    questions:
      billing:
        type: noul
        instructions: Is this message about a charge, invoice, refund, or subscription payment?
      tone:
        type: choice
        instructions: How upset is the customer? Angry means explicit frustration, threats to cancel, or demands.
        criteria:
          angry: Frustrated, demanding, or threatening to leave.
          calm: Neutral or polite, asking a question.
    thresholds:
      billing: 0.15
      tone: 0.6
    inputs_to: by-tone

  - name: by-tone
    kind: router
    description: Angry customers go to a human queue; calm ones get a drafted reply.
    branch_on: tone
    branches:
      angry: escalate
      calm: reply

  - name: escalate
    kind: execution
    description: Open a tier-2 ticket for the message.
    inputs:
      - name: message
        type: string
      - name: tone
        type: string
    script: scripts/escalate.py
    assets:
      - assets/config.json
    inputs_to: end

  - name: reply
    kind: client_task
    description: Draft a calm reply grounded in the refund policy.
    inputs:
      - name: message
        type: string
      - name: tone
        type: string
    template: assets/reply.md
    assets:
      - assets/policy.md
    references:
      - path: references/help.md
        description: Escalation contacts and plan matrix. Only for plan changes, currency issues, or charges older than 30 days.
    inputs_to: end

  - name: end
    kind: end
    description: The original message plus either a ticket or a drafted reply.
    inputs:
      - name: message
        type: string

anti_patterns:
  - Replying to an angry customer with a templated answer instead of escalating.
  - Promising a refund the policy does not cover.
```
````

### Optional directories

#### `scripts/`

Contains executable code that agents can run. Scripts should:

* Be self-contained or clearly document dependencies
* Include helpful error messages
* Handle edge cases gracefully

Supported languages depend on the agent implementation. Common options include Python, Bash, and JavaScript.

#### `references/`

Contains additional documentation that agents can read when needed:

* `REFERENCE.md` - Detailed technical reference
* `FORMS.md` - Form templates or structured data formats
* Domain-specific files (`finance.md`, `legal.md`, etc.)

Keep individual [reference files](#file-references) focused. Agents load these on demand, so smaller files mean less use of context.

#### `assets/`

Contains static resources:

* Templates (document templates, configuration templates)
* Images (diagrams, examples)
* Data files (lookup tables, schemas)

### Progressive disclosure

Agents load skills in three tiers, pulling more detail only as needed:

1. **Metadata (~100 tokens).** `name` and `description` load at startup for *every* installed skill. `description` is the only signal an agent has before deciding to activate the skill — make it specific and keyword-rich.
2. **Body (target <5000 tokens, ~500 lines).** The full `SKILL.md` body loads once the skill activates.
3. **Resources (on demand).** Files under `scripts/`, `references/`, and `assets/` load only when the skill body references them. Tell the agent *when* to load each (e.g., "Read `references/api-errors.md` if the API returns a non-200 status").

If the body would exceed the budget, push detail into `references/` rather than letting `SKILL.md` bloat. Body tokens cost every invocation; reference tokens cost only when loaded.

### File references

When referencing other files in your skill, use relative paths from the skill root:

```markdown SKILL.md
See [the reference guide](references/REFERENCE.md) for details.

script:scripts/extract.py
```

## Best Practices

### Choose the Step Kind

Treat `SKILL.md` as an execution graph: steps are nodes, inputs flow over edges. Pick each step's kind in this order; note choices and why in `source/README.md`.

1. **Script (`execution`)** when the logic can be written as code over the declared inputs:
   - domain-specific logic
   - **deterministic** if/then/else, when/unless, or "only if" rules over structured inputs
   - lookup tables
   - numeric calculations, thresholds, or caps
   - validation against a fixed set of rules
2. **Decision (`decision`)** when the step must judge the input — which case applies, whether a condition holds, how severe something is — and the answer space can be written down before seeing the input: yes/no, one of a fixed set, or a position on a described scale. The answer becomes a typed value in the state: a `router` can branch on it, a script can take it as input, or the procedure can end on it. Uncertain answers go to the client for review via `thresholds`, so a decision is never less safe than asking the client.
3. **Client task (`client_task`)** only when the output must be generated: text, code, a plan, a synthesis. If a judgment seems to need information the state lacks, add an upstream script that puts it in the state instead of falling back to a client task.

While scripting is critical, scripting the wrong things results in brittle errors and over-restriction. Asking the client for what a script or decision can do also costs speed, consistency, and calibration.

#### When Writing Scripts
**Be lean and fast — prefer a maintained library over re-implementing a heavy algorithm (e.g. an optimization solver). You don't know the consumer's runtime budget - default to efficient; slow scripts risk timing out.**

Favor fewer script files for simplicity.  Only create separate scripts files for truly independent self-contained logic.

#### When Writing Decisions

There are three types:
1. **Noul** for one yes/no question. Phrase it so a high value means yes; make the boundary unambiguous; add `criteria` with `true` and `false` when the boundary needs spelling out. [Docs](https://docs.typesafe.ai/primitives/noul)
   ```yaml
   has_personal_data:
     type: noul
     instructions: Does the message contain personal data?
     criteria:
       true: Names, emails, phone numbers, addresses, or account identifiers appear.
       false: No identifying details beyond what is needed to answer the sender.
   ```
2. **Choice** for a decision over a fixed set of labels. Descriptions must separate the options from each other; include an `other` option when inputs may fall outside the list. [Docs](https://docs.typesafe.ai/primitives/choice)
   ```yaml
   team:
     type: choice
     instructions: Which team should handle this ticket?
     criteria:
       billing: Charges, invoices, refunds, subscription payments.
       technical: Errors, outages, or a feature not working.
       other: Fits neither.
   ```
3. **Score** for a position on an ordered scale, lowest level first. Describe situations, not degrees; one dimension per question — split a multifaceted judgment into separate scores. [Docs](https://docs.typesafe.ai/primitives/score)
   ```yaml
   severity:
     type: score
     instructions: How severe is the reported bug?
     criteria:
       - Cosmetic; everything still works.
       - A feature is degraded but a workaround exists.
       - A core feature is unusable for the reporter.
   ```

Further advice ([System One concepts](https://docs.typesafe.ai/concepts/system-one)):
- Put every question about the same input in one decision step; one call answers them all.
- The step's `inputs` are the content being judged. Criteria go in `instructions`, not in the inputs.
- A question's name is the key downstream steps declare in `inputs` and a router names in `branch_on`. Branch keys are the choice labels, `true`/`false` for a noul, or level numbers for a score.
- Set `thresholds` per question: raise when a false positive is costly, lower when a false negative is.



### Use Simple Type Vocabulary

Use a small, simple vocabulary for step input types.  Only expand where absolutely necessary. The server compiles each step's `inputs` to a JSON Schema and validates the client's input against it at runtime, so these are enforced, not advisory.

- `string`
- `integer`
- `float`
- `boolean`
- `object` — JSON-like key/value map
- `list[*]` — collection of any of above


### Body Drafting Style

- **Imperative form.** "Search npm before writing a utility" beats
  "the user should consider searching npm."
- **Explain the *why*, sparingly.** A short line of reasoning beats
  a paragraph of all-caps MUSTs. LLMs reason from intent.
- **Keep the prompt lean.** Skill bodies that feel padded waste
  tokens on every invocation.
- **No surprises.** Body contents should match what `description`
  promises.
- **Quote YAML booleans used as labels.** `yes`, `no`, `on`, `off`,
  `true`, and `false` parse as booleans, not strings. As choice labels
  or router branch keys, write them quoted (`"yes": ...`) or pick
  another label.

## Procedures
### Authoring an Agent Skill

Checklist. Follow sequentially.

1. First read the [skill creation best practices guide](references/skill-creation-best-practices.md) and follow that same spirit here in addition to above AIP spec and best practices.
2. Identify source materials for domain-specific context
3. Establish the type of skill the user wants to author and the schema to use:
    - Bias to schema reuse over drafting new ones.
    - Find existing schemas in [aip-schemas](assets/aip-schemas) 
    - If you must draft a new schema see [references/author-schema.md](references/author-schema.md)
4. Lock the skill name
    - Ask the user what to call the skill. The name is short and slightly descriptive — it becomes the folder name. Lowercase kebab-case, <65 chars, no leading/trailing/consecutive hyphens.
    - Offer a multiple-choice list of recommendations plus a free-text option. If they type their own, validate against the rules above; on failure, state why and offer fresh suggestions plus free-text. Repeat until valid.
5. Scaffold skill directory at `./<skill-name>/` in the current working directory (not `/tmp`)
    ```shell
    skill-name/
    ├── SKILL.md                       # Required: metadata + YAML-compliant instructions
    ├── source/                        # Required: AIP schema & canonical human-readable source
    ├── scripts/                       # Optional: executable code
    ├── assets/                        # Optional: templates, resources
    ├── references/                    # Optional: documentation
    └── ...                            # Any additional files or directories
    ```
    fill in the /source materials with
    - The schema used above
    - reference docs you will use to create the skill (domain-specific context).  including
      - a source SKILL.md a user provided for transition to AIP format
      - a README.md outlining you logic from above and intent of the skill
      - Any other documentation or reference you will use to create the AIP skill
    Also populate the following at the skill folder root if the skill needs them:
    - `scripts/` — executable code the skill invokes (e.g., validators, processors).
    - `assets/` — templates, output formats, or other resources the skill references.
    - `references/` — supporting documentation the skill loads on demand (progressive disclosure).
6. Create and validate the AIP `SKILL.md`
   1. Draft `SKILL.md` at the skill folder root using the source materials and the schema from `/source`. 
         - Frontmatter: `name`, `description`, `metadata.aip.spec`, `metadata.aip.schemaId` (matches the schema's `$id`).  
         - Body: exactly one fenced YAML block. No surrounding prose, no second code block. The body validates against the schema.
   2. Run `uv run scripts/validate.py ./<skill-name>`. Re-run after every edit to `SKILL.md` or the schema — eyeball checks routinely miss AIP-namespace and required-metadata bugs.
      - **Trivial** (typo, missing required field, formatting drift): fix silently and re-run.
      - **Substantive** (schema doesn't fit, semantic mismatch, structural conflict): surface the error in plain language with your proposed fix; confirm before retrying.
   3. Once validation passes, run a completeness check: walk the source domain-specific context line-by-line against the compiled body and classify every distinct piece of source content.                                                                         
      - **Mapped** — captured faithfully in the body. 
      - **Schema gap** — schema lacks a field for it. Fix the schema, re-point `schemaId`, re-compile. 
      - **Body drop** — schema has capacity, the body missed it. Re-author the body.                        
      - **Deliberate drop** — redundant or genuinely doesn't belong. Record it in `source/README.md` with rationale.
   4. Functional test the skill. Spawn a fresh agent if possible, i.e. Agent/Task tool if present, `claude -p` via bash, or whatever the runtime exposes. Spawn 2–3 fresh sessions against the skill folder using prompts derived from `trigger_when` and `purpose`. For each session, capture script errors and the final response. Evaluate against:
      - **Script errors** — non-zero exits, stderr noise, exceptions
      - **Quality** — response matches what `description` promises; no missing sections, no hallucinated steps.
      - **Intent capture** — the response addresses the prompt's stated need, not an adjacent one.
      - **Over-restriction** — compare against what agent reasoning would produce unaided. If a script-backed step stripped reasoning, nuance, or form that mattered, revise or convert back to a prose step.
      - **Correctness** — run each script against the task's actual example inputs and expected outputs, not just "no errors". Verify it produces the right result on known cases; logic bugs (e.g. a wrong key mapping in a conditional) only surface against real fixtures.

      If the runtime truly cannot spawn fresh agents, test functionally yourself and tell user: *"Functional testing not conducted with fresh agents — runtime does not support fresh agent invocation"*
   5. Iterate until the body validates, every source item is classified, AND the skill passes functional test.
7. Install
   1. Ask the user what to do next:
      - **Install now** — proceed below.
      - **Iterate further** — keep editing the skill folder in place.
      - **Leave it as-is** — the skill folder stays in the current working directory. Tell them the path and stop.
   2. If installing, confirm the location with the user. Standard Agent Skills locations:
      - **Project-local** — the host agent's project skills directory (e.g., `./.claude/skills/<name>/` for Claude Code). Default if CWD is in a git repo.
      - **User-global** — the host agent's user-wide skills directory (e.g., `~/.claude/skills/<name>/` for Claude Code). Default otherwise.
   3. If a folder already exists at the destination, ask before overwriting. For prior AIP Instructions, preserve top-level `scripts/`, `assets/`, `references/` and overwrite only `SKILL.md` and `source/`.
   4. Move `./<skill-name>/` → `<install-location>/<skill-name>/` (folder name must equal `name` in frontmatter).
   5. Tell the user the install path. Project-local installs may need a fresh agent session to activate.

### Creating an AIP Schema
Follow the directions in [`author-schema.md`](references/author-schema.md)

### Validating an AIP Skill or Schema

Two scripts cover validation.

**Validate an AIP skill:**
```bash
uv run scripts/validate.py <path/to/skill-folder>
```
Checks: full frontmatter validation — required fields (`name`, `description`, `metadata.aip.spec`, `metadata.aip.schemaId`), Agent Skills format rules on `name` (length, charset, hyphen rules, folder-name match), length caps on `description` and `compatibility`, type rules on `license`/`allowed-tools`/non-AIP `metadata` values, URL form on `metadata.aip.spec`. Required folder structure (`source/` present with a bundled `*.schema.json`). AIP-compliance of the bundled schema (delegates to `validate_schema.py`). Body is exactly one fenced YAML block. Body validates against the schema referenced by `metadata.aip.schemaId`.

**Validate an AIP schema:**
```bash
uv run scripts/validate_schema.py <path/to/schema.json>
```
Checks: required root metadata (`$schema`, `$id`, `title`, `description` — all non-empty strings); `$id` is a URI; required `aip:` namespace with `aip.version`; universal floor properties (`purpose`, `trigger_when`); strict-core (every object subschema declares `additionalProperties: false`); `$defs` naming. Plus soft warnings on JSON Schema reserved-keyword collisions.

**Output contract** (both scripts):
- Exit 0 on success, 1 on any error.
- stdout: single-line human summary.
- stderr: JSON Lines, one record per error or warning. Stream-parse to classify.

**On failure, apply tiered recovery:**
- **Trivial** (typo, missing required field, formatting drift): fix silently and re-run.
- **Substantive** (schema doesn't fit, semantic mismatch, structural conflict): surface the error in plain language with your proposed fix; confirm before retrying.

**When to run:** after every edit to a schema or skill. Eyeball checks routinely miss AIP-namespace and required-metadata bugs.

## Anti-Patterns

1. Unnecessarily drafting a new schema when a sufficient schema already exists for the skill type
2. Drafting schemas that are specific to individual skills rather than the category / type / family of the skill
3. Dropping content from original SKILL.md to over compress a SKILL.md
4. Dumping JSON Schemas or YAML bodies into chat without asking. Default to a natural-language summary; offer the raw artifact if the user wants it.
5. Skipping the bundled validators under user scope restrictions. `scripts/validate.py` and `scripts/validate_schema.py` are part of this skill's contract, not third-party resources — run them anyway and surface that you're doing so.
6. Encoding rules, lookup tables, numeric calculations/thresholds, or other scriptable logic as prose instead of via scripts.
7. Inventing AIP frontmatter keywords at the root. All AIP-specific fields go under `metadata.aip.*` (e.g., `metadata.aip.spec`, `metadata.aip.schemaId`). No bare-root `aip_spec:`, `aip_schema:`, etc.

