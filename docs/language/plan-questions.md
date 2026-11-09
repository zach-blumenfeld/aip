# Open questions before the end-to-end plan

Questions raised on 2026-11-07 against Zach's rough notes for the first pass (build a
procedure, compile and run it in Claude Code, view it in the console, use it from several
agents, filter run history by session and agent, host a remote server). Answer by number.
Settled items are marked.

## The compiled form

1. **Settled 2026-11-07, confirmed 2026-11-08 after the bias check.** The Relate single-file
   database is the bundle, extension `.rl` (CypherLite was renamed Relate on 2026-11-04: CLI
   `relate`, `pip install relate-db`, `import relate`, npm `@relate/relate`, docs relatedb.ai).
   No zip, no skill export. Export writes the program directory back. Chosen on engineering
   grounds: load from a URL, push and pull to a shared graph, and a browser build come with the
   engine; the remaining cost is that the artifact is one project's format, offset by the stored
   source and the export. Nothing is on PyPI yet (wheels on the GitHub releases page), so the
   first milestone proves a clean install on a fresh machine.
2. **Settled 2026-11-08.** Accept that every runner needs the Relate wheel. The aip package
   pins one Relate version. Revisit with a pure-Python loader only if a real platform turns
   out to have no wheel; the stored source makes that possible later.
3. **Settled 2026-11-08.** Lossless means the source is stored: the procedure node carries
   `procedure.aip` as text, each file under `assets/`, `references/`, `scripts/` is a node with
   bytes and hash, the step graph is derived beside them. Export is a copy. Consequences assumed:
   compile checks that graph and stored source agree, so a hand-edited `.rl` fails to run; the
   bundle id is the hash over source and file hashes, not over Parquet bytes; `aip publish` merges
   the `.rl` into the store's graph; `aip get` clones the subgraph back out into a `.rl`.
4. **Settled 2026-11-08.** Both at once: the runtime loads the `.rl` into an in-memory Relate
   database (Relate's `--load` takes a path or a URL) and reads each step with a Cypher query.
   Measured: a step query costs about 40 µs against a model call's seconds, so speed does not
   decide this; one body of Cypher for compile, run, server and console does. A remote
   procedure is pulled into a local `.rl` first.

## Store, server and the one-writer rule

5. **Settled 2026-11-08.** One verb, `aip run <target>`, where the target is a published name, a
   folder or an `.rl` file; all three run locally from the bundle cache. Whether a run is
   recorded depends only on whether a server is configured, as with setting a tracing endpoint
   once. The server owns the store (Relate or Neo4j, local or remote) and is its only writer;
   the CLI never opens the store. `run-draft` is dropped: a folder or file run against a server
   uploads the bundle by id first (skipped if present), the server keeps it as an unlisted draft
   revision, and the run points at it; a later `aip publish` of the same id just assigns the
   revision number. Without a server the run still works and prints "not recorded" with the
   command that fixes it. Identity: the bundle id is the sha256 over the source text and file
   bytes, never the `.rl` bytes; the name comes from the `Procedure` header; a procedure on the
   server is a name with revisions, each a bundle id. Cache: `aip run name` pulls the `.rl` once
   per id; `aip pull name[@rev]` and `aip pull --all` warm it. Recording costs microseconds per
   step on loopback and is sent without blocking a step. Open detail: does `aip run` start the
   local server on demand (recommended) or does the user run `aip server`?

6. **Settled 2026-11-08.** Two backends: Relate, the default and the local case, and Neo4j
   (including Aura) for a shared deployment. Same Cypher, one implementation. The filesystem
   backend is removed.
7. **Settled 2026-11-08, by question 5.** The client pulls the procedure's `.rl` into its cache
   and executes locally; the server never executes. Record events stream to the server.
8. **Settled 2026-11-08.** A small cloud VM running `aip server` on a Neo4j Aura backend; clients
   send a bearer token held in `aip config`. The console points at it too.

## Agents and pauses

9. **Settled 2026-11-08, revised 2026-11-09.** `Task_Agent` always pauses. `Decide` never
   pauses: it needs a decision model, and with none configured, or a failed call, the run fails
   and `aip resume` retries the step (`Agent_Fallback` was removed; it made a route's confidence
   check meaningless on every hand answer, and an agent decides in a `Task_Agent` instead, by
   producing an answer under declared labels). `Execute` never pauses; a failing script fails the
   run. `Start` with missing inputs fails before the first step. The decision model is an
   endpoint with the TypeSafe API shape, URL and key in `aip config`, not a vendor.
10. **Settled 2026-11-08.** One pause carrying N tasks, each with its pass index and state; one
    `aip resume` with N answers keyed by pass index. The agent chooses its own concurrency. A
    missing index fails that pass.
11. **Settled 2026-11-08.** The runtime on the agent's machine calls the model, with the key in
    the client's `aip config`, as today. Every demo machine carries a key.
12. **Settled 2026-11-08.** MCP. One Python library is the runtime (compile, cache, walk, model,
    record); the CLI, the SDK and `aip mcp` are thin front doors on it, so the MCP server is the
    SDK running in a process the framework starts over stdio (or hosted over HTTP). Tools:
    `search`, `describe`, `run` (returns a result or a pause with run id and tasks), `resume`.
    ADK, LangGraph, MAF and Strands connect with their MCP clients; the coding agents use MCP or
    the CLI via the skill. Using MCP in every demo exercises the SDK for real, which was the
    point. MCP client info gives the framework identity for question 14 for free.
13. **Settled 2026-11-08.** Codex CLI.
14. **Settled 2026-11-08.** Three claimed fields on every run: `agent` (framework or tool name
    and version, from MCP client info, else `--agent` / `AIP_AGENT`), `session` (caller-supplied
    id grouping runs, `--session` / `AIP_SESSION`, else one per process), `user` (the server
    token's identity). Claimed, not verified, as with trace tags; verified per-agent tokens are
    a later governance item.

## make_procedure

15. **Settled 2026-11-08.** No new language feature. `Task_Agent` steps have the agent write the
    program folder and `Produce` its path; an `Execute` step runs the compiler on that path and
    produces `ok: true_or_false` (value only, as the spec allows for `Execute`) plus the error
    list; a `Loop ... Until compiled.ok` revises. Files are a path in state.
16. **Settled 2026-11-08.** The `.rl` ships inside the aip Python package. A server publishes it
    as a built-in revision on first start, local or remote, and `aip upgrade` republishes a newer
    one. Its source is also an example in the repo.
17. **Settled 2026-11-08.** Replaced. One skill named `aip` covers running and authoring;
    authoring is `make_procedure`. The 0.8 distillation examples stay as an archive.
18. **Settled 2026-11-08.** Hand-written first. Order: compiler and linter, runtime and local
    server, console, then `make_procedure`, written by hand with the finished tools.

## Demo content and the old world

19. **Settled 2026-11-08.** Two test procedures, each milestone naming which it proves against.
    `dynamic-policy` is the headline (loops, batching, aggregation, agent pauses) and is what
    `make_procedure` produces in demo step 1. `billing-support` is the second (Route with a
    confidence check, Execute running a script; `billing-support-agent` is the same triage done by a `Task_Agent` under labels, for a machine with no model). Together they cover every step
    kind; `make_procedure` becomes the third once it exists.
20. **Settled 2026-11-08.** Abandon, no upgrade tool. `validate`, `upgrade` and `schema` go. The
    old catalog stays as an archive; anything worth keeping is rewritten by hand or with
    `make_procedure`. Scene 8 of the end-to-end doc is dropped.
21. **Settled 2026-11-08.** aip 0.9.0 on the same package; the changelog says 0.8 procedures do
    not run.
22. **Settled 2026-11-08, revised the same day.** Remove the Studio (code, `docs/studio.md`,
    `docs/studio-lint.md`, `examples/studio`, its e2e specs) and build no workbench tab. The
    console stays: catalog, runs, history, governance. Authoring lives in the IDE, where the agent
    already is: the VS Code extension gains (a) diagnostics from the compiler on every change,
    shown as squiggles, (b) an interactive graph preview in a split pane like the markdown
    preview, drawn from the compiler's graph output with source positions (click a node to jump
    to the step; hover a key for its producer and readers; loops as boxes; routes with branches
    and confidence bar), (c) commands: compile, run in the terminal, publish, import from the
    catalog into a folder. A low-code user talks to Claude Code or Codex in the IDE's panel; the
    agent and the view share one compiler on one folder, so errors are shared by construction.
    `make_procedure` is available for "build this from a description" but nothing forces it.
    Needs: `aip compile --json` with source positions, an extension build step, the console's
    graph layout moved into the extension. JetBrains keeps the grammar only. An embedded agent
    in the console is a possible later step for users without an IDE.
23. **Settled 2026-11-08.** The server assigns the next revision number on publish; the source
    carries no version. Republishing an unchanged bundle id is a no-op.

## Tooling and process

24. **Settled 2026-11-08, by question 22.** The compiler is the linter: `aip compile --json`
    reports every error with line and column, and the VS Code extension runs it on every change
    and shows squiggles. No language server in this pass.
25. **Settled 2026-11-08.** Audience first: graph experts, colleagues and a couple of expert
    customers; built with a conference talk in mind, and a live stream soon. No fixed date: the
    work runs continuously in agent sessions with Zach checking in, so milestones are ordered by
    what can be shown next, and each must be demoable on its own because any one may be the
    stream's state that day.
26. **Settled 2026-11-08.** The plan lives in aip-lang, private. Hard constraint from Zach: Relate
    (formerly CypherLite) is not publicly released. Every conversation, document and line of
    code that mentions it stays private until Zach explicitly gives the go-ahead. So the 0.9
    work cannot land on the public aip or aip-console repos while it depends on Relate; it is
    built in private (aip-lang, or a private fork of aip) and moved when cleared. Checked on
    2026-11-08: no pushed branch of aip or aip-console mentions it; the `cypherlite-backend`
    branch in `~/dev/aip` is local only and must stay so.

## Zach's rough notes (2026-11-07, verbatim)

We want to show
1. build a general procedure to do something non trivial but also something that won't take forever
2. compile and run it in claude code
3. view it in the console
4. locally use with 3-4 different agents including another coding agent, ADK, LangGraph, MAF (or whatever the new one is for microsoft) and strands
5. show run history in console with clear session and agent identifiers that we can filter by.
6. host a remote server and track things centrally there using client server protocol

I want aip to compile to CypherLite - this is a lossless mapping. aip runtime accesses aip through
cypherlite; it can run on the cl file directly.

    # AIP should have a procedure for making a procedure
    aip make_procedure "policy_draft" ...
    aip compile ./policy_draft -o policy_draft.cl
    aip run-draft policy_draft.cl ...
    aip publish policy_draft.cl   # publish to local catalog
    aip run policy_draft          # runs published version
    # published runs retain run history, versioning, runs just as in aip today.
    # Locally this is a cypherlite backend, no filesystem, just the cypherlite option
    # run the console pointed locally

4: use the python sdk + cli as needed.

General architecture: AIP compiles to cypherlite/relate. run/run-draft cursor over the graph using
cypherlite/relate. AIP can configure a server like before; everything works like before; you may
want to stash the cypherlite locally for fast runs. aip should now batch steps for pauses: multiple
(the batch number at a time) are sent to the agent and the agent needs some way to run them.
Otherwise carry over from before. The skills will be different. aip-runtime carries over with these
updates. No aip-compile yet: make_procedure focuses on authoring from a description and past
materials, in the spirit of aip-compile but (1) it is a native aip procedure, mentioned in the
runtime skill, (2) less distillation from lots of material, more the language semantics from the
user's description and other materials. Consequence: one skill, called "aip".

aip-console works like before with studio as-is plus schema updates. A separate workbench tab for
editing an aip file with graph compile side by side; need not be done for the first pass.
Linter is critical, or some way to edit easily in VS Code.
