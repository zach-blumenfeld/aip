# Discussion: fastKL — the information + instruction system

> **Status: framing settled, details in progress.** The umbrella
> name for ki + AIP is **fastKL** — a fast, lightweight knowledge
> layer for autonomous agents. It contains two layers: an
> **information layer** (implemented by ki) and an **instruction
> layer** (built on the AIP protocol, persisted via `aip-graph` /
> `aip-graph-neo4j`). Naming is decided; open questions are about
> architecture details and sequencing, not identity.

## What fastKL is

**fastKL** = a fast, lightweight knowledge layer for autonomous
agents. It contains two layers:

| Layer                 | What it is                                                                                                                                                       | Implemented by                                  |
|-----------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------|-------------------------------------------------|
| **Information layer** | Declarative knowledge — facts, history, prior decisions. Unstructured / semi-structured notes, conversations, references. Answers "what do we know about X?"    | `ki`                                            |
| **Instruction layer** | Procedural knowledge — skills, runbooks, deliberations, specs. Schema-validated; queryable; round-trippable. Answers "what should the agent do about Y?"        | AIP protocol + `aip-graph` / `aip-graph-neo4j` |

`aip-graph` is the concept of a persistent graph store for
AIP-compiled instructions. `aip-graph-neo4j` is the tentative name
for the Neo4j implementation of that concept. (The naming pattern
mirrors AIP connectors generally: `aip-graph-<vendor>`.)

These map onto cognitive science's classic distinction:

| Type of knowledge    | Cognitive-science term | fastKL layer       |
|----------------------|------------------------|--------------------|
| Knowing **that**     | Declarative knowledge  | Information (ki)   |
| Knowing **how**      | Procedural knowledge   | Instruction (AIP)  |

Cognitive science treats these as the two complementary halves of
any complete knowledge system. **Truly autonomous behavior requires
both.** Today's agent ecosystem has fragmented tooling for each
side (vector stores / RAG for declarative; skill frameworks /
prompt management for procedural) and nothing that names the pair.

fastKL = **the persistent knowledge layer an agent needs to operate
without continuous human supervision.** Persistent across sessions;
growable over time; queryable by both humans and agents;
cross-linkable (an instruction in AIP can reference a doc in ki
for context, and vice versa).

## Why naming the pair matters

Without a name for the pair, three things are harder:

1. **Positioning.** "We have ki" and "we have AIP" leaves the
   complementary story untold. A named umbrella lets people see
   the full picture.
2. **Architecture conversations.** "Where does X go — ki or
   AIP?" is a recurring decision; having a name for the *system*
   they form together makes the architecture explicable in one
   sentence.
3. **Roadmap framing.** Future work (cross-references between
   the two, unified governance, joint queries spanning both)
   needs an umbrella to belong to.

## What fastKL is and is not

**Is:**
- A two-layer (information + instruction) knowledge layer for autonomous agents
- Persistent across sessions; survives between agent runs
- Queryable by both humans (governance, audit, learning) and
  agents (context retrieval, skill loading)
- The knowledge substrate the agent operates *on* — distinct from
  the substrate the agent operates *with* (LLM, tools, MCP)

**Is not:**
- The agent runtime (LangGraph, ADK, AgentOps live here)
- The model layer (LLMs, embedding models)
- The tool layer (MCP servers, function calling)
- Working memory (in-context state during a session)
- Just RAG — RAG is a retrieval pattern; fastKL is an architectural
  layer that may or may not use RAG mechanically

## Fast KL design principles

fastKL's knowledge layer should be **fast to adopt** — not just
fast at runtime. The guiding principles:

### 1. Easy to get started
One command to install, zero configuration to run. The first useful
thing should work within minutes, not after a setup session. The AIP
skill's conversational compile flow is the on-ramp — if you've never
authored a structured skill before, the agent walks you through it.

### 2. No specialized knowledge required
Users should not need to know JSON Schema, graph databases, or any
AIP internals to get value. Standard formats (Markdown, JSON Schema,
YAML) that practitioners already know, or can pick up from the output
the tool produces. The skill itself teaches the format by example.

### 3. No infrastructure required to start
No database, no cloud service, no third-party account. The core
value — schema validation, structured compilation, agent-readable
output — is available with just the skill and `uv`. Connectors
(`aip-neo4j`, `aip-postgres`) unlock corpus-scale queries but are
strictly optional and come later.

### 4. No complex multi-vendor lock-in
Schemas are pure JSON Schema — no database-specific keywords, no
proprietary extensions. Switching storage backends means swapping a
connector package, not re-authoring your documents. Nothing
Anthropic-specific except the reference implementation's delivery
format (AgentSkills SKILL.md — itself an open standard).

### 5. Standard formats throughout
Markdown → YAML → JSON Schema. No custom DSL, no proprietary graph
language, no special query format required at the protocol layer.
Connectors translate to the target store's native query language —
Cypher for Neo4j, SQL for Postgres — but that's a connector concern,
not an AIP concern.

### 6. Incremental adoption
Each step delivers standalone value:

| Step               | What you get                                  |
|--------------------|-----------------------------------------------|
| Install the skill  | Conversational skill authoring + validation   |
| Compile one doc    | Schema-validated, token-efficient agent input |
| Add a connector    | Cross-doc queries, corpus-scale insights      |
| Add more schemas   | Richer corpus; training data; governance      |

You stop at any step and the prior steps still pay off.

### 7. Human-readable source stays canonical
The prose document is the source of truth. The compiled YAML is a
build artifact — disposable and reproducible. Authors edit Markdown;
the compiled form follows. No round-trip brittleness where "you must
edit the JSON or the compile will overwrite it."

### 8. Instructions-first, not instrumentation-first
Getting value does not require runtime tracing, logging
infrastructure, or execution history. The knowledge layer is useful
*before the first agent run.* See [§ Instructions first, traces
later](#instructions-first-traces-later--a-deliberate-stance) for
the full positioning argument.

## Instructions first, traces later — a deliberate stance

The broader industry discourse around "context graphs" and
"knowledge layers" tends to foreground **decision traces and
execution history** — logs of what the agent did, what paths it
explored, which tools it called. Companies like Foundation Capital,
Windmill, and others position this as the core of an agent knowledge
layer.

**fastKL (ki + AIP) takes a deliberately different stance.**

A decision trace is an *instance of an instruction being executed*.
It is downstream. The instruction itself — the runbook, the skill,
the deliberation — is upstream. An agent that reads a well-authored
AIP-compiled skill before acting is already at a higher quality
baseline than one that only learns from its own traces. Traces are
derivative; instructions are constitutive.

|                | Instructions (ki + AIP focus)          | Traces (context-graph focus)             |
|----------------|----------------------------------------|------------------------------------------|
| **When**       | Before execution — what the agent reads | After execution — what the agent did    |
| **Role**       | Constitute agent behavior              | Record agent behavior                    |
| **Authorship** | Human-authored, agent-compiled         | System-generated, agent-produced         |
| **Persistence**| Durable across agents and runs         | Tied to a specific run / agent instance  |

For an MVP knowledge layer:
- **Traces are nice-to-haves.** They add value — learning from
  past runs, surfacing patterns, diagnosing failures. But they are
  not the foundation.
- **Traces can often be inferred.** A ki note documenting a prior
  decision, or an AIP deliberation schema capturing options
  considered, carries the signal traces would provide — without
  requiring runtime instrumentation.

This distinction should shape positioning: fastKL is about the
instruction layer that drives agent behavior, not the observability
layer that records it. Decision traces belong to a future
observability component (see Open Question §4), not the MVP.

## Why "context graph" doesn't land

The dumb-reach name. Four reasons it falls short:

1. **"Context" is overloaded.** Already means LLM context windows,
   MCP context, prompt context. Adding another meaning is lossy.
2. **"Context" is passive.** Implies what the agent SEES, not
   what drives the agent. Misses the AIP half — instructions are
   prescriptive, not contextual.
3. **"Graph" is too narrow.** Implies the *structure* is the
   value, when the value is what the structure *enables*
   (autonomous operation). A name should anchor on the outcome,
   not the data structure.
4. **It leads with traces.** Most "context graph" framing centers
   on execution history and decision traces — exactly what
   fastKL is *not* (see above).

## Naming decision — settled

The umbrella name is **fastKL**. It captures the core promise:
a fast, lightweight knowledge layer. No jargon, no overloaded
terms ("context", "substrate"), works as both a concept word and
a future project name.

**Names considered and rejected** (for the record):
- *Agent Substrate* — accurate but abstract; "substrate" is
  overloaded in chemistry and blockchain
- *I&I (Information & Instruction)* — descriptive but doesn't
  scale gracefully if the umbrella grows beyond two layers
- *Agent Cognitive Layer / Agent Cognition Layer* — too academic
- *Episteme & Techne* — Greek philosophy precision; alienating for
  most audiences
- *Agent Atlas, Almanac, Compendium* — collection metaphors; don't
  convey speed or agent-specificity
- *ThnkMark* — playful (think + markdown + Invincible/Omni-Man
  reference); rejected because it doesn't convey what it is to a
  first-time reader

**Frame vs. project:** fastKL starts as a conceptual frame (ki and
AIP keep their own identities and repos). It can graduate to an
umbrella project if cross-link tooling, joint governance, or joint
queries materialize as real work. No new code or repo needed today.

## Open questions

### §1 — Project vs. frame (settled: frame now, project later)

fastKL is currently a conceptual frame — ki and AIP ship
independently; fastKL names their relationship. Promote to an
umbrella project when:
- Cross-doc references between ki and AIP need a shared schema
- Joint governance / audit queries become a real ask
- Auth / identity needs to flow across both

### §2 — How does ki get repositioned?

ki is currently the parent repo; AIP is being extracted out.
Lean: **keep ki as-is.** ki stays a knowledge index implementing
the information layer; fastKL names the relationship, not the
components. ki does not need to rebrand.

### §3 — Does this affect AIP's identity?

No. AIP stays "Agent Instruction Protocol" with its upstream-of-
execution positioning unchanged. Marketing copy can optionally
reference fastKL ("AIP is the instruction layer of fastKL").

### §4 — aip-graph naming (tentative, needs its own discussion)

The instruction layer's persistence mechanism is tentatively called
`aip-graph` (concept) / `aip-graph-neo4j` (Neo4j implementation).
This name hasn't been fully deliberated. Open questions:
- Is `aip-graph` distinct enough from `aip-neo4j` (previous
  connector naming)? Does it imply graph-only storage?
- Should it be `aip-store` or `aip-publish` to stay
  backend-neutral?
- How does `aip-graph` relate to the connector interface contract
  (spec.md §1 open question)?

Needs its own discussion doc before implementation.

### §5 — Would other layers join fastKL later?

Today: information (ki) + instruction (AIP). Future plausible
additions:
- **Working memory** — ephemeral in-session state; ki covers
  long-term, this would be short-term.
- **Identity / auth** — who the agent IS vs. what it knows or does.
- **Observability** — traces and execution history (deliberately
  out of MVP scope; see [§ Instructions first, traces
  later](#instructions-first-traces-later--a-deliberate-stance)).

fastKL as a name accommodates additional layers gracefully.

### §6 — Brand / domain availability

`fastKL` — check `fastkl.dev`, `.io`, `.org` before public
launch. No known collisions.

## Decisions summary

| Question                               | Decision                                                                          |
|----------------------------------------|-----------------------------------------------------------------------------------|
| Umbrella name                          | **fastKL** — fast, lightweight knowledge layer                                    |
| Structure                              | Information layer (ki) + Instruction layer (AIP + aip-graph)                     |
| Frame vs. project?                     | Frame now; promote to project when joint work materializes                        |
| Does this change ki's identity?        | No — ki stays ki, implements the information layer                                |
| Does this change AIP's identity?       | No — AIP stays "Agent Instruction Protocol", implements the instruction layer     |
| Why not "context graph"?               | Overloaded, passive, trace-centric — the opposite of fastKL's stance             |

## Items deferred

- `aip-graph` naming deliberation (Open Question §4 above).
- Cross-link schema between ki and AIP documents.
- Joint governance / audit story across both layers.
- Observability / working memory / identity as future fastKL layers
  (Open Question §5).
- Brand / domain check for `fastKL` before public launch.
