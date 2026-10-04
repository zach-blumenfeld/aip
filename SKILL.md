---
name: aip
description: Create skills as Agent Instruction Protocol (AIP) — schema-validated structure that gates quality at write time, catches silent drift, and makes a skill corpus queryable for governance and analytics. Use whenever authoring a skill an autonomous agent will consume, including net-new skills, and compiling existing material (runbooks, deliberations, specs, decision logs, post-mortems). Default to using this any time the consumer is an autonomous agent — the structural constraint is what makes a skill production-grade.
metadata:
  aip-version: "0.5a0"
---

# AIP — Agent Instruction Protocol

## Trigger When

1. Authoring an agent skill (SKILL.md) for an autonomous agent
2. Validating an AIP skill

## Do not Use When

- Authoring one-off prompts
- Authoring content no agent will consume (human-only wikis, FAQs, casual notes)

## What AIP Is

AIP is an extension to the [Agent Skills Spec](https://agentskills.io/specification.md) that enables a structured graph workflow. The freeform markdown body is replaced with a fenced YAML block validated against a [JSON Schema](https://json-schema.org/) representing a graph workflow of the underlying procedural logic.  This specification can then be used to configure an AIP server that together with the AIP client offers traversal protocol over this graph for fast structured workflow execution. 

## Why Use AIP

AIP provides improved performance and stronger governance for autonomous agent skills.

**Performance**
- **Early A/B evidence.** AIP-structured skills scored higher than freeform-markdown equivalents on a behavior rubric in every session (+0.37 mean, 1–5 scale; largest gap +0.67 on a weaker agent — structure helps cheaper models close the gap). Small sample.
- **Tuning surface.** The schema gives a structured place to iterate when a skill underperforms — adjust typed fields, tighten validation. Plain markdown retunes only by rewriting prose.
- **Drift caught at write time.** Validation surfaces missing fields, wrong types, and rename mistakes before an agent silently misreads them.

**Governance**
- **Validated against a standard.** Every skill validates against the one AIP procedure schema and its graph rules. Quality gate before any consumer sees the skill.
- **Queryable at corpus scale.** Cross-skill questions become single queries ("every runbook missing a gotchas section") — no doc-trawling.
- **Database-ingestable.** Schema-validated YAML projects into a graph database for audit and analytics, no per-skill ETL.

## AIP Specification

Terminology and execution semantics are defined once, in the runtime block every skill carries at the top of its body; see the example under Body.

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
| `metadata.aip-version`  | Yes      | AIP format version this skill is written in. Currently `"0.5a0"`. *AIP-specific.*                  |
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
  aip-version: "0.5a0"
  author: example-org
  version: "1.0"
```

#### Body

The body — everything after the closing `---` of the frontmatter — must be the AIP runtime block, verbatim, followed by exactly one fenced YAML code block. No other prose or code blocks. The runtime block gives whoever executes the skill the terminology and semantics they need; copy it exactly as shown below. The YAML inside the fence is the procedure; it validates against the AIP procedure schema.     

Example (pared down for illustration — real skills typically carry more steps and richer detail), from the bundled `examples/billing-support` skill. The first step is the start; the router branches server-side on the value the client chose:

````markdown
# AIP runtime — format 0.5a0

You are executing an (Agent Instruction Protocol) AIP procedure: the fenced YAML block in this skill's `SKILL.md`. AIP is a protocol for cheaply, quickly, and accurately executing multi-step tasks using a graph-based workflow. AIP is portable, so while designed for execution with an AIP client and server, you, the agent can play both roles instead. 

## Running

If the `aip` command is available (`aip --help` succeeds), use it: run `aip run <this skill's folder> --input <start.json>` with the start step's inputs as JSON. When an AIP server is configured (`AIP_SERVER` or `aip config --server`), `aip run <this skill's name>` does the same against the published copy, and `aip search "<words>"` finds procedures by what they do. When the run needs you it prints a JSON pause and exits with code 3. `paused` says why: `decision` — answer the listed questions; `review` — confirm or override the flagged answers; `client_task` — do the task and produce the keys in `expects`. Put your answer in a JSON file and run the `resume` command the pause printed. Repeat until the output has `"done": true`; `state` is the result. If `aip` is not available, execute the procedure yourself, following the semantics below.

Critical terminology:

- **Client**: whoever drives the run: posts each step's input, reviews uncertain decisions, performs client tasks, and makes the final call at every step. As a plain Agent Skill, it is the agent that activated the skill.
- **Server**: runs each step and validates its input against the step's `inputs`. Without one, the activating agent does this itself: runs scripts, answers decision questions by its own judgment, and follows routers.
- **State**: the JSON object a step receives. Each step declares its required keys as `inputs`; extra keys pass through.
- **Step kinds**: `execution` runs a script, `decision` asks typed questions about the state, `client_task` hands work to the client, `router` branches on a value in the state, `end` declares the final state's shape.

## Execution

The state is one JSON object. It starts as the start step's `inputs` and flows along `inputs_to`; each step's output is merged over it, so keys accumulate and extra keys pass through untouched. A step runs only if the state holds every key it declares in `inputs`, with the declared types. The client may change the state before any step runs; it has the final say at every step.

- **`execution`**: run `script` with one JSON object on stdin, `{"currentState": <state>, "assets": {<file stem>: <content>}, "expects": <the next step's inputs>}`. The script writes one JSON object to stdout; it is merged over the state.
- **`decision`**: answer each question against the state. Each answer collapses to one value under its question name and is merged over the state: a noul to `true`/`false`, a choice to its label, a score to its level number. With a decision model, an answer under its threshold is sent to the client to confirm or override before continuing; without one, the client answers the questions.
- **`client_task`**: render `template` with `{key}` from the state, `{assets[stem]}` for its assets, and `{meta.name}` for the skill name. The client performs the task, loading `references` if their descriptions apply, and returns the next step's `inputs`; they are merged over the state.
- **`router`**: read the state's `branch_on` key and continue at `branches[value]`. A value with no branch is an error.
- **`end`**: the state must hold `end`'s `inputs`. That state is the procedure's result.

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
- If a question only applies to some inputs (severity only matters for bugs), say what the answer is for the others in its `instructions` ("non-bugs are level 0"), or ask it in a separate decision after a router. Otherwise the model hedges on every input it does not apply to and flags them all for review.



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
3. Lock the skill name
    - Ask the user what to call the skill. The name is short and slightly descriptive — it becomes the folder name. Lowercase kebab-case, <65 chars, no leading/trailing/consecutive hyphens.
    - Offer a multiple-choice list of recommendations plus a free-text option. If they type their own, validate against the rules above; on failure, state why and offer fresh suggestions plus free-text. Repeat until valid.
4. Scaffold skill directory at `./<skill-name>/` in the current working directory (not `/tmp`)
    ```shell
    skill-name/
    ├── SKILL.md                       # Required: metadata + YAML-compliant instructions
    ├── source/                        # Required: the canonical human-readable material this skill was compiled from
    ├── scripts/                       # Optional: executable code
    ├── assets/                        # Optional: templates, resources
    ├── references/                    # Optional: documentation
    └── ...                            # Any additional files or directories
    ```
    fill in the /source materials with
    - reference docs you will use to create the skill (domain-specific context).  including
      - a source SKILL.md a user provided for transition to AIP format
      - a README.md outlining you logic from above and intent of the skill
      - Any other documentation or reference you will use to create the AIP skill
    Also populate the following at the skill folder root if the skill needs them:
    - `scripts/` — executable code the skill invokes (e.g., validators, processors).
    - `assets/` — templates, output formats, or other resources the skill references.
    - `references/` — supporting documentation the skill loads on demand (progressive disclosure).
5. Create and validate the AIP `SKILL.md`
   1. Draft `SKILL.md` at the skill folder root using the source materials. Choose each step's kind per Best Practices.
         - Frontmatter: `name`, `description`, `metadata.aip-version`.
         - Body: the AIP runtime block, verbatim (copy it from the example under Body), then exactly one fenced YAML block. No other prose, no second code block. The YAML validates against the AIP procedure schema (`assets/procedure.schema.json`).
   2. Run `uv run scripts/validate.py ./<skill-name>`. Re-run after every edit to `SKILL.md` or to the skill's files — eyeball checks routinely miss required-field and broken-reference bugs.
      - **Trivial** (typo, missing required field, formatting drift): fix silently and re-run.
      - **Substantive** (format doesn't fit, semantic mismatch, structural conflict): surface the error in plain language with your proposed fix; confirm before retrying.
   3. Once validation passes, run a thorough completeness check where you check for dropped logic or key context that was left out from the source. Walk the source line by line. For each distinct piece of source content:
      1. Find it in the body: a field, a step description, a question, a template, a reference, or a script. Note where. If it is there, move on.
      2. If it is not there, it was dropped. Decide which, and act:
         - **Erroneous drop** — the format can and should carry it. Re-author the body to include it. Expect this case.
         - **Deliberate drop** — not actionable (background, history, rationale) or redundant. Record it in `source/README.md` with rationale.

      The check passes when every source item has been found in the body or recorded as a deliberate drop. Rules, conditions, thresholds, lookups, branching, and the context needed to apply them are never deliberate drops.
   4. Functional test the skill.
      1. Run it: `uv run aip run ./<skill-name> --input <start.json>` with realistic start inputs. With `TYPESAFE_API_KEY` set, decisions run against the model; without it, answer the questions yourself when it pauses. Resume through every pause to `"done": true`. Use enough inputs to reach every router branch at least once.
      2. Spawn a fresh agent if possible, i.e. Agent/Task tool if present, `claude -p` via bash, or whatever the runtime exposes. Spawn 2–3 fresh sessions against the skill folder using prompts derived from `trigger_when` and `purpose`. For each session, capture script errors and the final response.
      3. Evaluate against:
         - **Script errors** — non-zero exits, stderr noise, exceptions
         - **Decision quality** — answers and confidences on the test inputs make sense; thresholds flag the genuinely ambiguous ones and no others.
         - **Quality** — response matches what `description` promises; no missing sections, no hallucinated steps.
         - **Intent capture** — the response addresses the prompt's stated need, not an adjacent one.
         - **Over-restriction** — compare against what agent reasoning would produce unaided. If a script or decision stripped reasoning, nuance, or form that mattered, revise it or convert the step to a decision or client task.
         - **Correctness** — run each script against the task's actual example inputs and expected outputs, not just "no errors". Verify it produces the right result on known cases; logic bugs (e.g. a wrong key mapping in a conditional) only surface against real fixtures.

      If the runtime truly cannot spawn fresh agents, test functionally yourself and tell user: *"Functional testing not conducted with fresh agents — runtime does not support fresh agent invocation"*
   5. Iterate until the body validates, every source item is classified, AND the skill passes functional test.
6. Install
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

### Validating an AIP Skill

```bash
uv run scripts/validate.py <path/to/skill-folder>
```
Checks: frontmatter — required fields (`name`, `description`, `metadata.aip-version`), Agent Skills format rules on `name` (length, charset, hyphen rules, folder-name match), length caps on `description` and `compatibility`, type rules on `license`/`allowed-tools`/`metadata` values, `metadata.aip-version` matches the validator's format version. Required folder structure (`source/` present). Body is the AIP runtime block, verbatim, then exactly one fenced YAML block. The YAML validates against the AIP procedure schema. Graph rules: unique step names, a runnable start, exactly one `end`, every `inputs_to` and router branch resolves, every step reachable from the start and able to reach the end, unique input names, thresholds name real questions, every referenced asset, reference, and script exists on disk.

**Output contract:**
- Exit 0 on success, 1 on any error.
- stdout: single-line human summary.
- stderr: JSON Lines, one record per error or warning. Stream-parse to classify.

**On failure, apply tiered recovery:**
- **Trivial** (typo, missing required field, formatting drift): fix silently and re-run.
- **Substantive** (format doesn't fit, semantic mismatch, structural conflict): surface the error in plain language with your proposed fix; confirm before retrying.

**When to run:** after every edit to a skill. Eyeball checks routinely miss required-field and broken-reference bugs.

## Anti-Patterns

1. Dropping content from original SKILL.md to over compress a SKILL.md
2. Dumping YAML bodies into chat without asking. Default to a natural-language summary; offer the raw artifact if the user wants it.
3. Skipping the bundled validator under user scope restrictions. `scripts/validate.py` is part of this skill's contract, not a third-party resource — run it anyway and surface that you're doing so.
4. Encoding rules, lookup tables, numeric calculations/thresholds, or other scriptable logic as prose instead of via scripts; or asking the client for a judgment a decision step can make.
5. Inventing AIP frontmatter keywords at the root. The only AIP-specific field is `metadata.aip-version`. No bare-root `aip_version:`, `aip:`, etc.
