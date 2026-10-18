# AIP design note: execution steps run on the client

Status: accepted 2026-10-17 (supersedes server-design.md §6 and §7). Originally drafted in
aip-skillbench. Scope: execution steps (scripts), and
decision steps under the same rule (see "Decision steps").

## The problem

Today the server executes a skill's scripts. In the benchmark that works only because the server
and the agent share one container's disk: a skill script reads `/root/data/tess_lc.txt` and writes
`/root/results/` and the agent sees both. With the server on its own machine, as a customer
deployment would have it, an execution step reads files that are not there and writes results the
client never sees. The run state carries only the JSON a script returns. Nothing in the protocol
says where a step's files come from or go.

The root-owned-output failure in campaign 28 (drone-planning-control, runtime trial 2) was a
symptom of the shared disk, not the problem.

## The split

The same split MCP uses in practice and every CI system uses by design: work runs next to the
data, orchestration is central.

| | aip server | aip client (`aip` command) |
|---|---|---|
| holds | the catalog: skills at pinned revisions, including scripts and assets | a cached copy of the skill's `scripts/` and `assets/` for the run |
| owns | the graph, routing, input/output validation, run history | execution of every execution step, next to the files |
| talks to | the client only in reply to client requests | the server; the local disk; the agent only at a pause |

The client is a program, not the agent. When the server says "the next step is execution step
`prepare`, here is its rendered input", the client runs the script and posts the result back
without involving the agent. Execution steps, routers, validation and end steps flow through on
their own. The agent (or a human) sees `aip run` take a while and then finish or stop at a pause.
No server-to-client calls exist; the client always initiates. That is the direction MCP converged
on after retiring its server-initiated callbacks (sampling, elicitation, roots).

## Run flow

1. `aip run <skill>@<revision> --input start.json`. The client resolves the revision with the
   server, fetches that revision's `scripts/` and `assets/` once (lossless download, cached by
   content hash), and opens a run.
2. The server replies with the next step. For an execution step: the step name, the script uri,
   the rendered stdin payload (`currentState`, `assets`, `expects`) exactly as today's
   `Execution.render` produces it, and the step's timeout.
3. The client runs the script locally with the same contract as today: JSON in on stdin, JSON out
   on stdout, stderr for diagnostics, cwd set to the script's folder in the cache, working files
   relative to the client's working directory. It posts the result to the server.
4. The server validates the result against the next step's declared inputs, applies routers, and
   replies with the next step. Repeat.
5. At a client task (and, until decisions are designed, at a decision with no answer) the server
   replies with a pause; the client writes the run file and returns to the agent. `aip resume`
   continues from step 2.
6. At `end` the server records the run and the client prints the final state.

The whole skill's `scripts/` folder is fetched, not one script per step, because scripts import
siblings (`common.py` in the exoplanet skill) and read assets by relative path.

## What the format needs (aip-spec)

1. **Declared environment.** A skill with execution steps must declare what the client machine
   needs: interpreter and minimum version, packages, external tools. Today this is a free-text
   `compatibility` line ("Python 3 with numpy, scipy, astropy ...") that nothing checks. The
   client checks the declaration before the first execution step and reports "this machine lacks
   X" instead of a mid-run traceback. The validator requires the block whenever execution steps
   exist. Shape to decide: a `requires` block with `interpreter`, `packages`, `tools`.
2. **Launch command.** Scripts are Python only today (`python <script>`). The stdin/stdout JSON
   contract is language-neutral, so a step may declare how it is launched (`command: ["bash",
   "run.sh"]`, `["groovy", "x.groovy"]`) with `python` as the default. Every extra language is one
   more thing the environment declaration must name.
3. **Files in state.** State stays JSON. Scripts read and write the client's disk; state carries
   paths and summaries, never file contents. Authoring guidance, and a lint for very large state
   values.

## Failure handling (aip)

- A non-zero exit, timeout, or non-JSON stdout stops the run at that step. The run is left in an
  error state with the step name, exit code and stderr; the state before the step is kept, so
  `aip resume` retries the same step after the user fixes the cause. No automatic retries by
  default; an optional per-step `retries` for known-flaky steps is a small format addition.
- Environment failures are reported before any step runs (see above), so "your machine is missing
  lightkurve" and "the procedure has a bug" are distinguishable.
- Timeouts are the step's declared value; the client honours them, the server records them.

## Trust

The client runs code the server hands it. That is the same trust as installing a skill today,
with two guards: skills are addressed by pinned revision with a content hash the client verifies,
and the server is one the client was configured to trust (`aip config`). Untrusted clients or
untrusted catalogs are out of scope for this design; that is the case for server-side execution
with an artifact store, which this design does not preclude for skills whose scripts never touch
files.

## Consequences

- **Benchmark.** aip-runtime mode already behaves like this by accident (co-located server). After
  the change it behaves like this by design, and server-owned file ownership goes away. Until
  then the workaround is deployment config: start the in-container server as the agent user.
- **Server statelessness.** With the client holding the run file and the history in the backend
  (Neo4j or filesystem), any server replica can answer any request. Keep per-run state out of
  server memory.
- **Integration.** The client is the executor any agent harness talks to, through the `aip`
  command. Wrapping it as a local MCP server is deliberately deferred: it adds a layer to the
  stack for no new capability, and a published procedure is already a tool from the agent's view
  (typed start input, runs to completion, pauses only when it must) with a whole workflow behind
  it, which covers many of the cases people reach for MCP for today.
- **Client tasks stay with the calling agent.** A configured model is not used to perform client
  tasks. Most need tools (edit code, fix a build, write files), which would make the aip client an
  agent harness of its own, and the calling agent already has the context and is waiting. A later
  opt-in for text-only client tasks (report, draft, classification) via a configured model is
  possible but out of scope.

## Decision steps

Same rule as scripts: the client resolves them automatically; the agent only sees a decision
nothing else could answer.

- **Today:** the server answers a decision with the decision model (TypeSafe) when the key is in
  the server's environment, otherwise pauses; the client only ever answers a pause.
- **After:** the client answers the decision with the decision model when its key is configured
  on the client (`aip config`), applies the author's confidence thresholds (sent with the step), and pauses for the agent
  only when no resolver is configured or confidence is below threshold (a review pause, accepted
  with an empty answer or overridden). It posts the answer to the server with attribution.
- **Server:** validates the answer against the declared question type, routes on it, and records
  in the run history: resolver kind (`typesafe` or `manual`), model name, confidence if any,
  whether it was reviewed, and the final answer. That record is the provenance, regardless of
  which resolver ran.

Deliberately not included: a general-model resolver (a plain chat call or a harness sub-agent).
Its self-reported confidence is not calibrated, so the threshold and review pause would be
meaningless for it. An agent that wants to delegate a pause to a sub-agent can do so in its own
harness and answer with `resume`; that needs no protocol support.

Consequence: the server needs no model-vendor key at all, which fits self-hosted deployments.
In the benchmark harness, the key passed by `--decision-model` moves from the in-container
server's environment to the solver's.

## Open questions for the implementer

1. Does the client fetch `scripts/` and `assets/` via the existing lossless `aip get`, or a
   run-scoped endpoint that returns only those two folders? (Prefer the latter: the client should
   not need the graph.)
2. Working directory for file side effects: the client's cwd at `aip run`, or a `--workdir`
   recorded in the run file? (Prefer recording it, so `resume` from elsewhere still works; this
   is the same fix as keeping the run file under the user's home.)
3. Cache location and eviction for fetched skill revisions.
