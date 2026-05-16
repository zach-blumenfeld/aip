# Discussion: ki + AIP as a complete system (and what to call it)

> **Status: deliberation, early.** Captures a framing that surfaced
> mid-AIP-work: ki (information / declarative knowledge) and AIP
> (instruction / procedural knowledge) are two halves of a single
> conceptual whole — the persistent knowledge an agent needs to
> operate autonomously. Open question: is this a project we'd
> build, or a frame we'd use in writing/talks? Naming follows the
> answer.

## What triggered this

While working on AIP's identity ([identity-and-naming.md](identity-and-naming.md)),
the relationship between ki and AIP came into focus:

- **ki** = a knowledge index. Unstructured / semi-structured notes,
  conversations, references. Retrieval-style access (vector + graph).
  Answers "what do I / we / the team know about X?"
- **AIP** = a structured protocol for compiled agent instructions.
  Skills, runbooks, deliberations, specs. Schema-validated;
  queryable; round-trippable. Answers "what should the agent do
  about Y?"

These map cleanly onto cognitive science's classic distinction:

| Type of knowledge        | Cognitive-science term | What it covers                  | Project |
|--------------------------|------------------------|---------------------------------|---------|
| Knowing **that**         | Declarative knowledge  | Facts, history, prior decisions | ki      |
| Knowing **how**          | Procedural knowledge   | Skills, rules, runbooks         | AIP     |

Cognitive science treats these as the two complementary halves of
any complete knowledge system. **Truly autonomous behavior requires
both.** Today's agent ecosystem has fragmented tooling for each
side (vector stores / RAG for declarative; skill frameworks /
prompt management for procedural) and nothing that names the pair.

ki + AIP together = **the persistent knowledge layer an agent
needs to operate without continuous human supervision.** Persistent
across sessions; growable over time; queryable by both humans and
agents; cross-linkable (an instruction in AIP can reference a doc
in ki for context, and vice versa).

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

## The conceptual frame is sound

Before debating names, worth being explicit about what the frame
*is* and *isn't*:

**Is:**
- A declarative + procedural knowledge layer for autonomous agents
- Persistent across sessions; survives between agent runs
- Queryable by both humans (governance, audit, learning) and
  agents (context retrieval, skill loading)
- The substrate the agent operates *on* — distinct from the
  substrate the agent operates *with* (LLM, tools, MCP)

**Is not:**
- The agent runtime (LangGraph, ADK, AgentOps live here)
- The model layer (LLMs, embedding models)
- The tool layer (MCP servers, function calling)
- Working memory (in-context state during a session)
- Just RAG — RAG is a retrieval pattern; this is an architectural
  layer that may or may not use RAG mechanically

## Fast KL design principles

ThnkMark's knowledge layer should be **fast to adopt** — not just
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

**ThnkMark (ki + AIP) takes a deliberately different stance.**

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

This distinction should shape positioning: ThnkMark is about the
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
   ThnkMark is *not* (see above).

## Candidate names

Each candidate carries a different framing. Worth picking the
*framing* before the name.

### Cognitive-science accurate

- **Agent Cognitive Layer** — technical, accurate, slightly academic
- **Agent Cognition Layer** — same family, fewer adjective syllables
- **Cognitive Substrate** — emphasizes the foundation angle

### Substrate / foundation metaphor

- **Agent Substrate** — what the agent runs on. Clean, technical,
  evocative. Subtitles naturally as "Agent Substrate = ki (the
  information layer) + AIP (the instruction layer)."
- **Agent Bedrock** — collides with AWS Bedrock; reject

### Greek philosophy (the literal info + skill dichotomy)

- **Episteme & Techne** — Episteme = declarative knowledge;
  Techne = skill/craft. Captures the dichotomy with one-word
  precision. Pretentious; great for the right audience,
  alienating for others. Probably reject for marketing; could
  show up in spec-doc footnotes for the philosophy nerds.

### Borrowing the user's own framing

- **I&I** (Information & Instruction) — pair-of-protocols story.
  Brands as "the I&I stack," "the I&I layer," "I&I-compliant
  agent." More descriptive than evocative.

### Comprehensive-collection metaphor

- **Agent Codex** — taken (GitHub Codex). Reject.
- **Agent Atlas** — broad mapping; available; less differentiated
- **Agent Almanac** — reference + procedural; calendar/farm flavor;
  unusual but evocative
- **Agent Compendium** — comprehensive collection; heavy

### Persistent-knowledge framing

- **Agent Knowledge Layer (AKL)** — descriptive, accurate,
  slightly flat
- **Persistent Agent Knowledge** — over-specified
- **Agent Memory Architecture** — collides with various
  AI-memory frameworks

## Tentative leans

### Honest pick across the candidates

**Agent Substrate.** It captures that this is what the agent
operates *on*, names a thing people can point at, doesn't lean on
jargon, subtitles cleanly. The two-component story is natural:
"Agent Substrate = ki (the information layer) + AIP (the
instruction layer)."

**Runner-up: I&I / Information & Instruction.** Borrows the framing
that surfaced the concept. Maps to a pair-of-protocols story: ki
provides the I, AIP provides the I, together they form the I&I
stack. More descriptive than brandable; might land harder in
text than in talks.

### But: the harder question first

Before committing to a name, **decide what this is:**

#### Option A — Umbrella project we'd build

A real project that ships its own components: cross-link tooling
between ki and AIP, joint query layer, unified governance, shared
identity / auth across both. Branded; marketed; has a website.

→ Name needs to be brandable. **Lean: Agent Substrate.**

#### Option B — Conceptual frame we'd use in writing/talks

Just a way to talk about ki and AIP together. No new code, no new
brand. ki ships, AIP ships, the umbrella name appears in slides
and spec docs but isn't a thing you can `pip install`.

→ Name can stay descriptive. **Lean: Information & Instruction.**

#### Option C — Both, sequenced

Start as a conceptual frame (Option B). Promote to umbrella project
(Option A) if and when the cross-link tooling, joint queries, or
unified governance materialize as real work that needs an owner.

→ Name should work as both. **Lean: Agent Substrate.**

**My read:** Option C is the right path. Don't build umbrella
infrastructure before there's joint work to coordinate. But pick
a name now that *could* graduate to project-level if the umbrella
becomes load-bearing. Substrate works as both a concept word ("the
agent's knowledge substrate") and a project name ("Agent Substrate
v0.1").

## Open questions

### §1 — Project vs. frame (the load-bearing question)

Settled in Option C above as a tentative lean. Re-open if/when:
- Cross-doc references between ki and AIP need a shared schema
- Joint governance / audit queries become a real ask
- Auth / identity needs to flow across both

These are the signals that the frame should graduate to a project.

### §2 — How does ki itself get extracted / repositioned?

ki is currently the parent repo. AIP is a sub-project being
extracted out. If we eventually name an umbrella over both, what
happens to ki's identity? Three paths:

- **Keep ki as-is.** ki stays a knowledge index; AIP stays an
  instruction protocol; Agent Substrate is the conceptual umbrella.
  Each component keeps its own positioning.
- **Reposition ki under the umbrella.** ki becomes "the information
  side of Agent Substrate." Tighter integration story, but ki
  loses some standalone identity.
- **Rebrand ki entirely** to match the umbrella naming. Disruptive;
  probably wrong unless there's a strong reason.

Lean: keep ki as-is. The umbrella names the relationship, not the
components.

### §3 — Does this affect AIP's identity?

AIP committed to "Agent Instruction Protocol" with a clean
upstream-of-execution positioning. The umbrella frame doesn't
change that — AIP is still AIP; it's just *also* the procedural
half of a larger conceptual whole. The "AIP, with \<tool\> as the
reference implementation" positioning is unchanged.

What might change: AIP's marketing material can reference the
umbrella ("AIP is the instruction half of the Agent Substrate
pair"). Optional; not required.

### §4 — Would other components join the umbrella later?

Today: ki (information) + AIP (instruction). Future plausible
additions:

- A **memory** layer — ephemeral, in-session working memory that
  agents accumulate during a task and discard at task end. ki is
  long-term memory; this would be short-term.
- A **identity / auth** layer — who the agent IS (its persona,
  permissions, history) vs. what it knows or does.
- A **observability** layer — what the agent did, what it said,
  what it looked at. Adjacent to ki (which captures decisions)
  but operationally distinct.

If any of these grow into real components, the umbrella name
should accommodate them. Substrate / Cognitive Layer both
accommodate gracefully; "I&I" doesn't (it's literally just two
things by name).

This argues mildly for Substrate or Cognitive Layer over I&I if
we expect the umbrella to grow.

### §5 — Brand / domain availability

Defer to the same extraction-time check as AIP. Quick mental
collision check on Agent Substrate:

- "Substrate" alone is heavily used (chemistry, biology, blockchain
  / Polkadot)
- "Agent Substrate" specifically is less used; possibly available
- Domain check needed: `agentsubstrate.dev`, `.io`, `.org`

## Tentative leans summary

| Question                                  | Lean                                                                              |
|-------------------------------------------|-----------------------------------------------------------------------------------|
| Is this a real project or just a frame?   | **Frame now, project later** (Option C); promote when joint work materializes     |
| Umbrella name lean                        | **Agent Substrate** — works as concept word AND as future project name            |
| Runner-up name                            | I&I (Information & Instruction) — descriptive, borrows the framing                |
| Why not "context graph"?                  | "Context" overloaded + passive; "graph" too narrow (data structure ≠ value)       |
| Does this change ki's identity?           | No — ki stays ki; the umbrella names the relationship, not the components         |
| Does this change AIP's identity?          | No — AIP stays "Agent Instruction Protocol" with upstream-of-execution positioning |

## Items deferred

- Brand / domain / repo / package naming for the umbrella, if/when
  it graduates to a project.
- Cross-link schema between ki and AIP (e.g., an AIP doc citing a
  ki note, or a ki note referencing an AIP-validated runbook).
  Real work, but only when the joint use case is concrete.
- Joint governance / audit story across both.
- The "memory / identity / observability" components that might
  later join the umbrella (Open Question §4).
