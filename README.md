<table>
  <tr>
    <td width="200" align="center" valign="middle">
      <img src="img/aip-logo.png" alt="aip logo" width="200" />
    </td>
    <td valign="middle">
      <h1>AIP — Agent Instruction Protocol</h1>
      <p><em>Graph Procedures for Predictability & Governance</em></p>
    </td>
  </tr>
</table>

## What Is AIP?

Agent Instruction Protocol (AIP) is a protocol that uses graphs to represent and run procedures.

A **procedure** is an instance of step-by-step know-how: an executable workflow that guides an agent on how to perform a task using tools and logical sequences.

Two protocols cover parts of this today. 

1. **Model Context Protocol (MCP)** _decouples tools, resources, and other assets_ into a portable service any agent can call. 
2. **Agent Skills** _represent procedural knowledge_ in a portable way that humans can read and maintain. 

AIP seeks to accomplish both these goals with a single unified protocol, built to give teams running autonomous agents _**predictability, governance, portability, and cost savings**_. 

By treating procedures as first-class citizens, AIP provides a client-server architecture for not just calling individual tools but sequenced workflows of tools and steps, with typed I/O contracts, that can be distributed, executed by economical AI models, and governed by humans on the backend.

Our research shows AIP lifting Claude Sonnet's task pass rate from 51% to 63% over the same skills as Agent Skills ([Evidence So Far](#evidence-so-far)).

## AIP Design

AIP is two pieces:

1. **A spec.** A serialized representation of procedures, for information exchange and for distillation: compiling memory, documents, and other data into portable procedures that can be run by any agent. The AIP spec is an extension of the [Agent Skills spec](https://agentskills.io/home) and an AIP skill can be used exactly like an Agent Skill. The freeform markdown body is replaced with a fenced YAML block validated against a [JSON Schema](https://json-schema.org/): typed steps with inputs and edges, decisions with named questions, scripts, tasks for the client, and routers. The spec lives in [zach-blumenfeld/aip-spec](https://github.com/zach-blumenfeld/aip-spec).
2. **A runtime protocol.** A client-server architecture for executing procedures that uses the graph topology to enforce sequencing and typed I/O between steps. The server walks the graph, validates every step's input and output, and follows routers; the `aip` client runs the scripts next to the data and answers decisions with a structured decision model, and the agent or person behind it handles only the pauses. Published procedures are content-hashed revisions in a catalog the server searches, and every run is recorded against the revision that ran. The runtime is this repository.

## How It Works

```mermaid
flowchart LR
    subgraph authoring["Authoring (once, with a frontier model)"]
        doc["runbook, playbook,<br/>freeform SKILL.md"] --> skill["aip skill<br/>compiles to an AIP step graph"]
        skill --> validate["aip-spec validate"]
        validate --> publish["aip publish"]
    end
    subgraph clients["Clients"]
        agent["any agent +<br/>aip-runtime meta-skill"] --> cli["aip CLI<br/>search · info · run · resume"]
        insp["aip-console<br/>catalog · run console · history · governance"]
        scripts["scripts run here,<br/>next to the data"]
        model["decision model (TypeSafe)<br/>answers questions, flags low confidence"]
        cli --> scripts
        cli --> model
    end
    subgraph server["aip server (one HTTP API)"]
        api["/catalog · /runs · /governance"]
        engine["execution engine<br/>steps · routing · validation"]
        api --> engine
    end
    subgraph backend["Backend (one interface)"]
        neo["Neo4j<br/>catalog · files · runs · answers<br/>full-text search · graph queries"]
        fs["Filesystem<br/>a directory"]
    end
    publish --> api
    cli --> api
    insp --> api
    engine --> backend
    api --> backend
```

The agent never decides anything the procedure can decide. It starts a run, and the server walks the graph: it validates each step's input and follows routers, while the `aip` client runs the scripts and asks the decision model. It stops only at a pause the agent must handle: a task to perform, a decision answered below its threshold to confirm or override, or, with no decision model configured, the questions themselves. Every step, answer, and pause is recorded against the revision that ran, which is what the history and governance views read.

## Evidence So Far

Our paper [AIP: A Graph Representation for Learning and Governing Agent Skills](https://arxiv.org/pdf/2606.04781), published at a VLDB 2026 workshop, measured the previous format (`0.3a3`, skills as structured YAML loaded into context, before the server existed) on a stratified core of 24 [SkillsBench](https://www.skillsbench.ai) tasks. Each task's human-curated skill was converted to AIP once by Claude Opus; Claude Sonnet 4.6 then solved the task with either the original or the conversion, five trials per task.

| Skill given to the solver | Pass rate | Mean reward |
|---|---|---|
| Human-curated Agent Skill | 50.8% | 0.567 |
| The same skill converted to AIP | **63.3%** | **0.668** |

Tool-call counts were about equal, and wall clock was lower on the AIP side in two of the three task cohorts. The format has moved on since (typed step kinds, declared inputs and outputs, a decision model with thresholds, the runtime block, and a server that holds each run while the client runs its scripts and decisions); measuring this release the same way is the next study, and the harness is [aip-skillbench](https://github.com/zach-blumenfeld/aip-skillbench).

## Install

One line installs [uv](https://docs.astral.sh/uv/) if missing, the `aip` CLI with [`aip-spec`](https://github.com/zach-blumenfeld/aip-spec) (the format and its validator), and both Agent Skills, `aip` (authoring and validating AIP skills) and `aip-runtime` (running published procedures), into every agent it detects (Claude Code, Cursor, Windsurf, Copilot, Gemini CLI, Cline, Codex, Pi, OpenCode, Junie):

```bash
curl -sSfL https://raw.githubusercontent.com/zach-blumenfeld/aip/main/install.sh | bash    # aip + aip-spec + both skills
```

Only the format, no runtime (author and validate skills, nothing to run them against):

```bash
curl -sSfL https://raw.githubusercontent.com/zach-blumenfeld/aip-spec/main/install.sh | bash   # aip-spec + the aip skill
```

Prefer Python tooling:

```bash
uv tool install git+https://github.com/zach-blumenfeld/aip-spec.git@v0.6a1   # `aip-spec`, the validator the skill calls
uv tool install "aip[server] @ git+https://github.com/zach-blumenfeld/aip.git@v0.6a1"      # `aip` with `aip server`; pulls aip-spec in
aip skill install                   # both skills, every detected agent
aip skill install claude-code       # one agent;  aip skill list  shows them
aip skill install --path ./.claude/skills    # a project-local skills directory
aip skill remove
```

Coming from 0.5a1: skills need three edits to validate under 0.6a0, listed in [`docs/upgrading.md`](docs/upgrading.md). A 0.6a0 skill validates under 0.6a1 with one warning; regenerating its runtime block clears it.

Once installed, ask your agent something like *"author an AIP procedure skill for X"* or *"validate this AIP skill folder."* The skill walks the rest of the conversation. With `AIP_SERVER` set, the `aip-runtime` skill has the agent search the catalog and run a matching procedure instead of doing the steps by hand.

The [End-to-End Walkthrough](#end-to-end-walkthrough) below takes a fresh machine through install, a Neo4j-backed server with the console, an agent run, and authoring a skill.

### Model Recommendation for Co-Authoring

Use the **largest frontier model available** when using the AIP skill. The work is cognitively intense and underrepresented in current training data — smaller models struggle.

For *consuming* the resulting skill, the opposite holds: AIP's structure is what makes smaller, cheaper models more competitive on workflow-heavy tasks.

## End-to-End Walkthrough

### Prerequisites

- macOS or Linux with `curl`.
- A Neo4j database. [Aura](https://console.neo4j.io) works.
- A [TypeSafe](https://typesafe.ai) API key, set on the client. Optional: without it, every decision step pauses and asks you/agent to answer instead of a decision model.
- [Claude Code](https://claude.com/claude-code) for steps 5 and 6. Any agent `aip skill list` names works the same way.

### 1. Install

```bash
curl -sSfL https://raw.githubusercontent.com/zach-blumenfeld/aip/main/install.sh | bash
```

That installs [uv](https://docs.astral.sh/uv/) if missing, then two commands, `aip-spec` (the format and validator) and `aip` (runtime, server, client), and puts two Agent Skills into every agent it detects: `aip` for authoring and `aip-runtime` for running published procedures. Check:

```bash
aip --help
aip skill list          # which agents got the skills
```

If `aip` is not found, open a new terminal. uv installs commands into `~/.local/bin`.

### 2. Start a server on Neo4j, with the example published

```bash
aip server --init       # writes ~/.config/aip/server.toml, every setting commented
```

Open that file and set 5 lines. 

Under `[backend]`:
```toml
kind = "neo4j"
uri = "neo4j+s://xxxxxxxx.databases.neo4j.io"   # from Aura
user = "neo4j"
password = "..."
database = "neo4j"
```

Then start the aip server:

```bash
aip server
```
Leave it running. In a second terminal you will publish an AIP skill to the server. 
You will use the hello-world example for now.  Later you will see how to compile your own. 

```bash
aip config --server http://localhost:8000      # where the client and the agents send requests
aip config --decision-model "..."              # your TYPESAFE_API_KEY: optional but highly recommended
aip-spec example billing-support --out .       # the bundled example skill, written to ./billing-support
aip publish billing-support                    # validates, uploads, prints billing-support@<revision>
```

`aip publish <folder>` is how any skill gets onto the server. `aip list` shows the catalog.

### 3. The console

The console (formerly inspector) is a separate npm package; the server serves no UI. In another
terminal, start it against the server and open the URL it prints:

```bash
npx aip-console --server http://localhost:8000
```

Four tabs across the top plus the server link at the right:

- **catalog**: every published name with its step graph drawn. Click `billing-support` for the procedure page: purpose, triggers, each step with its inputs and questions, the files it ships (source viewer), the diff between any two revisions, and the governance controls (pin a revision, retire one).
- **run**: the run console. Pick a procedure, fill the start input, start. The console walks the steps and stops at every pause for you to answer: a decision the model was unsure about, a task it needs the client to do, or the questions themselves when there is no model.
- **history**: every run, step by step, with what each step got and produced.
- **governance**: corpus queries across all runs: decisions the client overrode at review, decisions answered by hand, scripts that failed (with the client's stderr), skills missing fields, branches no run has taken.
- **server link** (top right): the server URL and bearer token the page uses.

Try two runs of `billing-support`. Message `I was charged twice this month and I am furious, fix it or I cancel`: the model marks it billing and angry (with no decision-model key, you answer the two questions on the page), the router sends it to the escalation script, which runs on your machine, and the run ends; its ticket id and the tier2 queue are on the escalate step in the history tab. Message `Hi, could you tell me whether my March invoice was a duplicate?`: calm, so the run pauses with a client task asking you to draft the reply from the policy; type one and the run ends, with your reply recorded on the reply step.

### 4. See it in Neo4j

Open your database in Neo4j Browser or Query and run these. The skill and its procedure graph:

```cypher
MATCH (n:Name {name: 'billing-support'})-[:HAS_REVISION]->(s:Skill)-[:HAS_PROCEDURE]->(p:Procedure)
MATCH p1 = (p)-[:HAS_STEP]->(st:Step)
OPTIONAL MATCH p2 = (st)-[:NEXT|THEN]->(:Step)
OPTIONAL MATCH p3 = (st)-[:ASKS]->(:Question)
RETURN n, s, p, p1, p2, p3
```

Or just the control flow, from the start step to the end, with each router's condition on its `THEN` edge:

```cypher
MATCH (n:Name {name: 'billing-support'})-[:HAS_REVISION]->(s:Skill)-[:HAS_PROCEDURE]->(p:Procedure)
MATCH controlFlow = (p)-[:STARTS_AT]->(:Step)-[:NEXT|THEN*]->(:Step)
RETURN controlFlow
```

The data flow is a second edge set over the same steps: one `Data` node per key, `PRODUCES` from the step that declares it (an output, or the decision whose question it answers), `FEEDS` into every step that reads it, and `SUPPLIES` from the procedure for the start inputs the client provides. Follow a value from the client to the result:

```cypher
MATCH (n:Name {name: 'billing-support'})-[:HAS_REVISION]->(s:Skill)-[:HAS_PROCEDURE]->(p:Procedure)
MATCH dataFlow = (p)-[:SUPPLIES]->(:Data)-[:FEEDS|PRODUCES*]->()
RETURN dataFlow
```

Every run of the skill, with the steps they ran and, for decisions a model answered, its answers (`Answer` nodes; a decision answered by hand has none, and its answers are on the `StepRun`):

```cypher
MATCH (r:Run {name: 'billing-support'})-[:OF_SKILL]->(s:Skill)
MATCH p1 = (r)-[:STEP_RUN]->(sr:StepRun)
OPTIONAL MATCH p2 = (sr)-[:FOLLOWED_BY]->(:StepRun)
OPTIONAL MATCH p3 = (sr)-[:OF_STEP]->(:Step)
OPTIONAL MATCH p4 = (sr)-[:ANSWERED]->(:Answer)-[:OF_QUESTION]->(:Question)
RETURN r, s, p1, p2, p3, p4
```

Just the run trails, when that gets busy:

```cypher
MATCH p = (r:Run {name: 'billing-support'})-[:STEP_RUN]->(:StepRun)-[:FOLLOWED_BY*0..]->(:StepRun)
RETURN p
```

Every file of every revision is also in there as `File` nodes with exact bytes; `aip get billing-support --out ./restored` rebuilds the folder from them and verifies the hashes.

### 5. Run it through an agent

The installer put the `aip-runtime` skill into Claude Code if it found it so you should be able to just ask the below to see it work:

- `A customer wrote: "I was charged twice! Refund me today or I'm gone." Handle it.`
- `A customer asks politely whether they can still get a refund on a subscription they forgot to cancel last month. Deal with it.`

`aip skill list` shows `installed`, and if not, `aip skill install claude-code` does it now. Step 2 pointed the `aip` command at your server with `aip config`. The agent never learns the URL; the skill tells it to run `aip search`, `aip run`, and `aip resume`, and those read the config.

Watch it search the catalog, find `billing-support`, start the run, and answer each pause ([`docs/examples/aip-runtime-session.md`](docs/examples/aip-runtime-session.md) is a recorded session; an agent may also skip the skill and improvise, so if it does, ask again naming the catalog). The first ends in a tier2 ticket opened by the skill's script, which `aip` ran on your machine. The second pauses with a client task, and the agent drafts the reply itself. Both runs then appear in the console's history tab and in the Cypher above. Ask it to run something unrelated and it should say the catalog has nothing for it rather than improvise.

### 6. Compile and publish your own skill

The `aip` authoring skill turns a document into a procedure. Put the material in a folder: a runbook in markdown, an existing freeform `SKILL.md`, a support playbook, anything with steps and decisions. Use the largest model you have; this is the hard part. In Claude Code, from that folder:

```
Author an AIP skill from ./refund-runbook.md
```

The agent asks you to pick a name, scaffolds `./<name>/` with your document under `source/`, writes `SKILL.md` as a step graph (decisions with questions, scripts, tasks for the client, routers), runs `aip-spec validate` until it passes, then walks your source line by line checking nothing was dropped. Then:

```bash
aip validate ./<name>                    # the same checks, any time
aip info ./<name>                        # what it does, the input it expects, how it flows
aip run ./<name> --interactive           # run it locally, answering on the terminal
aip publish ./<name>                     # onto the server; refresh the console
```

Edit, validate, publish again: the same name gets a new revision, and the console's diff shows what changed. Pin a revision when the catalog should resolve to it regardless of what is published later.

## Procedures

The AIP skill exposes two top-level procedures:

1. **Author an AIP skill** — bring source material (or describe verbally); the agent compiles it into an execution graph validated against the AIP procedure schema, runs it, and tests it. Details in [`SKILL.md` § Authoring an Agent Skill](https://github.com/zach-blumenfeld/aip-spec/blob/main/SKILL.md#authoring-an-agent-skill) in the spec repo.
2. **Validate an AIP skill** — run `aip-spec validate` (or `aip validate`, the same checks) directly, or let the agent run it as part of authoring. Details in [`SKILL.md` § Validating an AIP Skill](https://github.com/zach-blumenfeld/aip-spec/blob/main/SKILL.md#validating-an-aip-skill).

The authoring skill lives in [zach-blumenfeld/aip-spec](https://github.com/zach-blumenfeld/aip-spec); `aip skill install` writes the copy bundled in that package.

## AIP Skill Spec

The format of an AIP skill is defined in [`SKILL.md` § AIP Specification](https://github.com/zach-blumenfeld/aip-spec/blob/main/SKILL.md#aip-specification) in the spec repo, [zach-blumenfeld/aip-spec](https://github.com/zach-blumenfeld/aip-spec). It follows the Agent Skills directory layout, requires a `source/` directory holding the human-readable material the skill was compiled from, requires a body that is the fixed AIP runtime block followed by exactly one fenced YAML block, so every skill carries its own execution semantics and any agent can run it with no aip tooling present, and adds one frontmatter key, `metadata.aip-version`.

## The Procedure Format

There is one format, and it lives in [`aip-spec`](https://github.com/zach-blumenfeld/aip-spec): the pydantic models in `src/aip_spec/models.py`, the JSON Schema generated from them at [`assets/procedure.schema.json`](https://github.com/zach-blumenfeld/aip-spec/blob/main/assets/procedure.schema.json) for editors and non-Python consumers, and the runtime block every authored skill carries at the top of its body (`aip-spec runtime` or `aip runtime` prints it; the validator rejects a skill whose block is missing or edited). Steps are typed by `kind`: `decision`, `execution`, `client_task`, `router`, and `end`. The `billing-support` example ships in that package: `aip-spec example billing-support --out .` copies it out.

This package depends on `aip-spec` and adds the runtime: `aip.spec.loader` builds the executable `Procedure` from a validated folder, and `aip.spec` re-exports the format so `from aip.spec import ProcedureSpec` keeps working. For the server case, it also ships the `aip-runtime` meta-skill ([`skills/aip-runtime/SKILL.md`](skills/aip-runtime/SKILL.md)), the one page an agent reads to find and run published procedures through the client; `aip skill install` writes it beside the authoring skill, and `aip runtime --skill --out <skills dir>` writes it alone.

## Validation

```bash
aip-spec validate <path/to/skill-folder>             # what the authoring skill runs
aip validate <path/to/skill-folder>                  # the same checks, from this package
```

Both run the checks in `aip_spec`: frontmatter (Agent Skills rules plus `metadata.aip-version`), folder structure (`source/` present), body shape, the YAML against the format models, and graph checks the models cannot express: unique step names, a runnable start, exactly one end, every edge resolving, every step reachable from the start and able to reach the end, unique input names, thresholds naming real questions, every key a step reads produced on every path to it (or a start input) and produced exactly once, `outputs` on every client task, a `requires` block when there are scripts, and every referenced asset, reference, and script present on disk.

Output is JSON Lines on stderr (`path`, `kind`, `message`, optional `location`, optional `severity`) and a one-line human summary on stdout. Exit 0 on success, 1 on any error.

## Running a Skill

```bash
aip info <path/to/skill-folder>                       # what it does, the input it expects, how it flows
aip info <path/to/skill-folder> --example-input > start.json   # a start input to edit
aip run <path/to/skill-folder> --input start.json     # runs until the client must decide
aip resume <run-id> --input answer.json              # continues a paused run, from any directory
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
aip runs [<run-id>]                                    # the server's runs; one run's state and history
aip governance [<query>]                               # the governance queries, or one query's rows
```

Every one of these is a thin wrapper over the Python SDK, `aip.Client` ([`docs/sdk.md`](docs/sdk.md)): `aip.Client().run("billing-support", {...})` returns the same pause or done the CLI prints, as typed objects, and shares its run files.

The web client, the console (formerly inspector; [aip-inspector](https://github.com/zach-blumenfeld/aip-inspector)),
is its own npm package: `npx aip-console --server URL` serves the catalog, source, run console, history and
governance views from a local Node process, and its page calls the server directly (the server answers CORS for
loopback origins; `aip server --allow-origin ORIGIN` adds others). The server serves no UI. The console checks
`aip --version` (`aip <version> format <format>`) at startup, since interactive runs go through the `aip` CLI.

`aip run` drives the procedure locally with the same engine the server uses. It stops one of three ways and prints one JSON object for each ([`docs/cli-json.md`](docs/cli-json.md)): paused (exit 0) when the client has to act, a client task to perform, a decision answered below its threshold to confirm or override, or, when this client has no decision-model key, a decision's questions to answer yourself; done (exit 0) with the end step's state; or error (exit 1) with the failing step and why. A pause carries only the paused step's declared inputs and what to answer with; every outcome prints a `run_id`, the run file is `~/.aip/runs/<run-id>.json` (`AIP_HOME` moves it, `--run-file` picks a path), `aip resume <run-id> --input answer.json` continues from any directory, and `aip resume <run-id>` with no input retries a failed step. `--progress` adds a JSON line per completed step and `--debug` a traceback on failure. Decision thresholds are the author's, from SKILL.md; nothing at run time overrides them. On a server, the server holds the run's state and history and the run file is only a handle.

### Configuring the server

`aip server --init` writes `~/.config/aip/server.toml`, every setting commented, and `aip server` reads it from there. The file is also looked for as `--config FILE`, `$AIP_SERVER_CONFIG`, and `./aip-server.toml`, in that order, the first found wins; `--example-config` prints the same template. Precedence, highest first: flags, the environment (a `./.env` or `--env-file` is loaded into it without overriding anything already set), the file, defaults. The filesystem catalog lives in `~/.local/share/aip/server` unless `root` says otherwise. The startup log names what it loaded and the backend.

The file has two tables. `[server]` is the listener and tokens; `[backend]` picks `filesystem` (`root`) or `neo4j` (`uri`, `user`, `password`, `database`, `cache_dir`). Secrets can live in the file, in `.env`, or in the environment as `NEO4J_*`; the file never overrides a variable that is already set. The server holds no decision-model key, and a `[decision_model]` table is refused with a pointer to the client setting below.

**Decision model.** Decision steps are answered by [TypeSafe](https://typesafe.ai) through `typesafe-sdk`, on the client: `aip config --decision-model KEY` stores the key in `~/.config/aip/config.json`, and `TYPESAFE_API_KEY` overrides it. That holds for `aip run <name>` against a server as much as for `aip run <folder>`. Without a key every decision step pauses with its `questions` for you to answer by hand; with one, the model answers, the author's thresholds come with the step, and the run only pauses with a `review` block when an answer falls under its threshold. The server records each decision with its attribution (`resolver` `typesafe` or `manual`, `model`, `confidence`, `reviewed`), which the `overridden-decisions` and `manual-decisions` governance queries read.

**Scripts and trust.** A procedure's execution steps are scripts, and they run on the client, in the `aip` process's user account, never on the server: `aip run <name>` fetches the revision's `scripts/` and `assets/` into `~/.aip/cache/<name>@<revision>/`, checks each file against the server's manifest, and runs the script with whatever that user can read, write, or reach. `aip` does not sandbox them; the step's `timeout` (or `AIP_STEP_TIMEOUT`) is the only limit it applies. Running a published procedure is therefore running its author's code on your machine, the same trust as a CI runner: give the `publish` scope only to people whose code your clients would run, and pin revisions where that matters. The server runs no user code and holds no model key, so publishing no longer means code execution on the server; it still decides what every client runs, so keep it on localhost or behind a token.

## Loading Skills into Neo4j

The Neo4j driver ships with the `server` extra the installer uses; in a clone, `uv sync --extra neo4j` adds it.

```bash
export NEO4J_URI=neo4j://localhost:7687 NEO4J_USERNAME=neo4j NEO4J_PASSWORD=...
aip db load <path/to/skill-folder>                     # validates, then writes one revision
aip db list                                            # every skill and revision in the database
aip db export <name> --out ./restored                  # rebuilds <name>/ byte for byte and verifies hashes
```

Each load is lossless: every file under the skill folder is stored as a `File` node with its exact bytes, mode, and sha256, so `export` reproduces a folder that validates and runs identically. Alongside the files, the parsed procedure is projected as `Procedure`, `Step` (labelled by kind), `Data`, and `Question` nodes: `NEXT` edges (and a router's `THEN {value}` edges) are the control flow, `PRODUCES` and `FEEDS` (one `Data` node per key, since every key has one producer) are the data flow, `SUPPLIES` marks the start inputs, `ASKS` and `YIELDS` tie a question to the key its answer lands under, and `USES` points at the `File` nodes a step runs, renders, or may load; the `requires` block sits on the `Procedure` node. Skills are keyed `name@revision`, where the revision is a hash of the files: reloading unchanged content is a no-op, changed content adds a revision, and many skills coexist in one database. A `Name` node groups the revisions of one skill and carries its pin; `Run` and `StepRun` nodes record executions, linked `FOLLOWED_BY` in order and `OF_STEP` to the step they ran.

`aip db` is a thin shim over the server's Neo4j backend (`aip.server.backends.neo4j`), which also serves the catalog, a full-text search index over names, descriptions, purposes, and triggers, and a hash-verified materialisation cache under `~/.cache/aip/` (`AIP_CACHE_DIR` overrides) that the server loads procedures from. The filesystem backend (`aip.server.backends.filesystem`) offers the same contract over a plain directory.

## Development & Contributing

```bash
uv sync --group dev                                    # pytest and the Neo4j driver
uv run pytest -q                                       # the Neo4j backend tests skip unless NEO4J_URI is set
uv tool install --editable .                           # `aip` on PATH, tracking your edits; `uv tool uninstall aip` removes it
```

`aip-spec` installs from the git tag pinned in `pyproject.toml`. To work against a sibling checkout instead, layer it on per command: `uv run --with-editable ../aip-spec pytest -q`. (A `[tool.uv.sources]` path override is not an option: uv applies a git-fetched project's sources when installing it, which broke `uv tool install`.)

The design behind the client-server architecture is [`docs/server-design.md`](docs/server-design.md).

### Bumping the AIP format version

The format version (currently `0.6a1`) is referenced in both repos, and the spec is tagged first, always, because the pin here names the tag. In [`aip-spec`](https://github.com/zach-blumenfeld/aip-spec), in order:

1. `FORMAT_VERSION` in `src/aip_spec/models.py` and `version` in `pyproject.toml`.
2. `src/aip_spec/runtime.md` — the block's heading carries the version; if the text changes, keep the previous text as `runtime-<old>.md` and add `<old>` to `LEGACY_VERSIONS`.
3. `assets/procedure.schema.json` — regenerate with `aip-spec schema --write assets/procedure.schema.json`.
4. `SKILL.md` — the frontmatter version, the embedded runtime block, and every example that shows `metadata.aip-version`.
5. `examples/` — each example skill's `metadata.aip-version`.
6. `README.md` — install commands and any version references.
7. `CHANGELOG.md` — promote `[Unreleased]` to the new version section with a date.
8. `install.sh` — the default `AIP_SPEC_REF`.
9. The `v<X>` tag, after the version-bump commit lands.

Then here:

1. The git pin on `aip-spec` in `pyproject.toml`, and `uv lock`.
2. `skills/aip-runtime/SKILL.md` and its package copy — `metadata.aip-version`.
3. `install.sh` — the default `AIP_SPEC_REF`, and `AIP_REF` once this repo's own tag exists.
4. `CHANGELOG.md` — promote `[Unreleased]`.

Drift is caught automatically: the spec's schema-sync and runtime-block tests fail if its files disagree, validation of the bundled example fails on an `aip_version_mismatch`, and `tests/test_runtime_skill.py` here fails if the `aip-runtime` skill's version lags `FORMAT_VERSION`.

### Changelog

See [`CHANGELOG.md`](CHANGELOG.md). The format follows [Keep a Changelog](https://keepachangelog.com/). Add notable changes under `[Unreleased]` as you make them; promote to a versioned section when you tag the release.
