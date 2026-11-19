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
   2026-11-11: Relate is public. The release is `relate-db` 1.0.0 on PyPI (`import relate`; source,
   CLI binaries and docs at github.com/relatedb/relate and relatedb.ai); milestone R6 moves the pin
   there from the pre-release 0.16.1 wheel.
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

## Decided after the first build (2026-11-09)

27. **Settled 2026-11-09.** `Agent_Fallback` is removed: a `Decide` always needs a decision model,
    so every decision answer carries confidence and probabilities and a route's check always means
    something. An agent decides in a `Task_Agent` by producing an answer under declared labels
    (`Produce tone: choice [angry, calm]`); a script may do the same and may supply a confidence.
    A confidence check on an agent's or an input's answer is a compile error. The decision model
    is an endpoint with the TypeSafe API shape, URL and key in `aip config`, not a vendor.
    Milestones L4 and R4, done. Why, moved here from the spec's decisions table: the fallback let
    the agent answer a decision by hand, and a hand answer has no confidence, so the route's
    check either fired on every one (0.9's first build) or had to be skipped for it (0.8's
    `reason: manual`, 0.9 for a day as `reason: hand`); a `Confidence_Below` on a fallback
    decision never meant what it said. With the agent's decisions in a `Task_Agent`, every
    decision answer carries a confidence, every check on one is honest, and governance still sees
    which routes an agent steers.
28. **Settled 2026-11-09.** The graph's data flow reads left to right, as 0.8 did: `Data` (was
    `Key`), `SUPPLIES` (was `HAS_KEY`), `(Data)-[:READ_BY]->(Step)` (was `READS`, reversed).
    Reviewed in a Browser: the flow edges stay distinct (`NEXT`, `BRANCH`, `BELOW`, `CONTINUES`,
    `AGAIN`, `ENTERS`), `CONTAINS` is membership and stays, `OVER`'s double duty is noted and left.
    The queries are `queries.md`.
29. **Settled 2026-11-09.** One package. `aip-spec` existed so a SKILL.md could be validated
    without the runtime; a bundle can only be run by the runtime, so the compiler folds into
    `agent-instruction-protocol` (milestone L5). The name stays: PyPI refused `aip` as too close
    to existing names, and `aip-lang` or `aip-runtime` would each name one part and mismatch the
    `aip` import and command just the same. `aip-spec` is left at 0.8 on PyPI.
30. **Settled 2026-11-09.** Agent Skills compatibility becomes an export, `aip export --skill`
    (milestone K2, after the demo): a SKILL.md and the files, derived from the graph, followed by
    hand with no guarantees, from a bundle or a published name through the server. Discovery in
    0.9 is the catalog over MCP.
31. **Settled 2026-11-09.** The console moves into this repo as `console/`, by subtree at the
    start of C1 with its history kept, released by its own npm workflow from that folder; the
    Python build excludes it, so the PyPI wheel carries no npm content, which was the reason for
    two repos. One plan, one history, one commit when the server API and the console change
    together, and one home for the card canvas the console and the VS Code extension share.
    `aip-console-dev` becomes an archive; D5 moves one repo.

## Decided after the first-use reports (2026-11-09)

Three fresh agents ran every example through every branch (`reviews/2026-11-09-first-use-*.md`).
Zach decided the product questions they raised; milestones L6 and R5 carry them.

32. **Settled 2026-11-09.** A rejected answer leaves the pause in place. The run stays paused with
    the same tasks, the error names what was wrong, the agent answers again. (The runtime had
    marked the run failed and required a bare resume first; the docs had always promised this.)
33. **Settled 2026-11-09.** A task on a loop's last allowed pass says so (`last_pass: true`,
    `pass_of`), so an agent asked to fix knows no check follows; the cap stays tested at the head.
    `loop_cap` is not resumable, since a retry fails the same way.
34. **Settled 2026-11-09.** `index` and `iterations` are scoped by loop name: `revise.index`,
    `revise.iterations`; the bare keys are shorthands for the innermost active loop and the last
    loop that exited; none survives into a final state. A loop's name is a reserved key.
35. **Settled 2026-11-09.** `With Confidence_Above p` holds strictly above `p`. The model's
    probabilities arrive in hundredths (577 of 577 observed values), so a bar on that grid ties
    about one answer in a hundred; "above" means above.
36. **Settled 2026-11-09.** A `score` answer's `value` is the label, not the level's number;
    routes, conditions, agents and scripts all speak labels; the expected value stays as `score`.
37. **Settled 2026-11-09.** fixed-policy carries its approved claims in the `policy_claims`
    string and an `assets/claims.md` for the agent, so the question is answerable; billing-support
    checks `Confidence_Below 0.9`, which the model's calibration makes reachable (clear messages at
    1.0, mixed ones near 0.82). The sentence "the first pass always runs" leaves the spec.
38. **Settled 2026-11-09, in milestone L6**, where the plan was silent. (a) A `score` answer's
    `probabilities` are keyed by label, as a `choice`'s are, once its `value` is a label: an
    answer that names its value `high` and its probabilities `"2"` would need the label list
    beside it to be read. The model's level numbers are mapped on receipt; `score` stays the
    expected level, a float. (b) Loops are spec section 2.6, after 2.5, so that every reference
    to 2.2 through 2.5 in the code and the docs still points where it did. (c) The compiler
    reports one mistake once by not reporting consequences: any flow that does not resolve
    silences `unreachable_step` in its region (the plan named `unknown_step` and
    `missing_loop_exit`; a missing `Next_Step` and a flow across a loop's braces cascade the
    same way), and a second producer silences the `type_mismatch` after it. (d) The `noul` alias
    of `true_or_false` is gone from the type vocabulary; `noul` remains only as the model's field
    on a `true_or_false` answer. (e) A step sees a loop's number under the last word of its path,
    as it sees any read (`Read revise.iterations` hands it `iterations`), so two loops' numbers
    in one step are read as the loops' whole keys, `Read review, revise`.
39. **Found in L6, decided and done in R5 (2026-11-09).** Two reads of one step that end in the
    same word (`Read review.iterations, revise.iterations`, or `Read first.tone, second.tone`
    from two decisions) were handed to the step under one name, and one was lost without a
    word. It is a compile error, `ambiguous_read`, naming both reads and the fix: read the keys
    whole (`Read review, revise`) and name the field in the script or the template.
41. **Decided in R5 (2026-11-09), where the plan left a choice.** (a) A pause is answered whole:
    a task left out refuses the answers (`missing_tasks`) as an extra one does (`invalid_tasks`),
    and nothing is applied. R2 had a missing index fail its pass, which is the
    failed-then-bare-resume dance the reports asked to be rid of. (b) The runtime's loop keys are
    kept beside the state (`loops` in the run file), not stripped from it at the end, so no
    saved state holds one at any time, a resumable failed run included. (c) The `Until` test at
    the head of a pass is a field, `until`, on the first entry the pass writes at the loop's
    level, not an entry of its own, so the history keeps one entry per step run. (d)
    `last_pass` and `pass_of` are on a task only when its innermost loop is a capped `Loop`, so
    they speak of the same loop as the task's `pass`. (e) A `Task_Agent` entry's `answered_by`
    is who resumed (`AIP_AGENT`, `AIP_SESSION`, else the run's own identity), which may differ
    from who started the run. (f) A loop's exit entry has no `seconds`: its time is its passes'.
    (g) `--progress` prints an entry the moment it is written, which inside a batch is the
    order things happened in and can differ from the history's pass order. (h) The line `not
    recorded: no server is configured` is `aip run`'s alone; a server that is configured and
    refuses a stop is still reported at every stop.

## Revised after public feedback (2026-11-09)

40. **Settled 2026-11-09, revising item 22.** The Studio comes back, as a card canvas (public
    aip#25, a user's screenshot: description as the card's title, inputs and outputs on the card,
    exits as ports quoting the next step, a route's branches as ports). C1 draws it read-only from
    the compiler's graph; E2 shows the same component in VS Code; C2 makes it an editor in a Studio
    tab where every operation is a text edit at a span in `procedure.aip`, compiled and redrawn,
    saved as a draft revision through the server. What item 22 rejected was a second model of a
    procedure with its own serializer and linter; this has neither, the compiler is the only rule
    book. Authoring with an agent stays in the IDE; the Studio is for reading and adjusting.

42. **Settled 2026-11-09.** `aip governance` is renamed `aip audit` (endpoint `/audit`, module
    `aip.server.audit`, console tab "Audit"). The named queries review the record and the catalog;
    none decides who may do what, which is what "governance" promises. "Governance" stays as the
    word for what the record, pins and retirements add up to. `manual-decisions` retires with the
    fallback; `unmeasured-routes` becomes `agent-routes`, read off the source class on the route's
    edge. Milestone S2.

43. **Decided in S1 (2026-11-09), where the plan left a choice.** (a) The server's facts about a
    bundle live on nodes of its own (`Name`, `Revision`, `Bundle`), never on the bundle's nodes, so
    the subgraph handed back for `pull` is the graph `aip compile` wrote and verifies untouched.
    A draft is a `Bundle` with no `Revision`; publishing one promotes it. (b) Publishing a bundle
    whose revision was retired brings that revision back rather than numbering a second one for
    the same content. (c) A run is stored twice over on purpose: the record as posted (JSON on the
    `Run` and on each `Entry`), so `GET /runs/{id}` is lossless, and its single-valued fields as
    properties, so Cypher can ask about them. (d) Search is BM25 in the server's memory on both
    backends; Neo4j's full-text index is not used, so ranking does not depend on the database.
    (e) Tokens gained a third scope, `run` (upload a draft, record a run), between `read` and
    `publish`, and a `[tokens]` table of `name = "token"` gives the `user` of a run; S2 owns the
    client's side. (f) `GET /governance` serves the four queries the new store settles
    (`confidence-fired`, `failing-aggregations`, `model-answers`, `agent-routes`); the 0.8 set's
    other queries and stored queries are not served until S2 rewrites them as `aip audit`.
    (g) The Relate store is asked for as `store.rl` and kept as `store.cl` while the pinned
    release needs that suffix. (h) `write_graph` matches an edge's ends by label, read off the
    node id's prefix, so Neo4j can use an index; `.rl` files are unchanged by it.

44. **Decided in S2 (2026-11-09), where the plan left a choice.** (a) `local` is a value of the
    server setting, and a client with nothing configured still records nowhere: `aip config
    server local` is what the installer sets, `aip config server none` turns it off, and
    `AIP_SERVER` takes any of the three for one command. A config that defaulted to `local`
    would have made "no server configured" (item 3 of the plan's summary, R3's proof)
    unreachable, and would start a process for anyone who only ran `aip run` once. (b) The
    local server listens on 8247, not on 8000 where `aip server` does, so the two do not
    collide and a 0.8 server on 8000 is not mistaken for it; it opens the default store file,
    reads no config file, and is told from anything else on its port by `GET /health`. (c) Any
    request starts it, not only `aip run`: `aip runs` after an idle stop has to work too. It
    stops after 15 minutes without a request. A run never fails for want of it. (d) "Draft" is
    the store's word (S1 left this open): a run is a draft's when its bundle has no revision at
    the time it is recorded, so a folder that compiles to a published bundle's id is recorded
    as a run of that revision, and the client's run file takes the server's answer. (e) The
    audit queries keep their 0.8 names where the question is the same (`cycles`,
    `repeated-cycles`), though what they read is now `For` and `Loop` blocks; `repeated-cycles`
    counts `Loop`s only, since a `For`'s passes are its list's length. `missing-fields` reads
    the three header lists (`Use_When`, `Do_Not_Use_When`, `Avoid`). (f) `failing-scripts`
    counts the runs that stand failed at a script. The record keeps where a run stands and not
    the attempts before, so a failure that was retried past leaves no trace; keeping attempts
    would be a change to the record (R-track), not to a query. (g) `lineage` is the one
    built-in that is not a single statement: a collected list is derived from the key each pass
    gathered, and `COLLECTS` points from the loop to that key, so no directed path in the
    bundle's graph runs through a `For`. (h) Stored queries live in the store on both backends
    (`AuditQuery` nodes); every audit query runs in a transaction that is never committed, and
    one with a writing clause is refused when stored. (i) An export is a second store written
    by the store's own statements, served as bytes by `GET /export/runs`, so it works the same
    from a remote server and on Neo4j, and every query in `queries.md` runs on the file.

45. **Decided in C1 (2026-11-09), where the plan left a choice.** (a) "The server's graph for a
    revision" is an endpoint: `GET /catalog/{ref}/graph` and `GET /bundles/{bundle_id}/graph`
    answer the bundle's nodes and edges as JSON, with the source and the files' contents. A
    page cannot open an `.rl`, and the alternative (the launcher fetching the bundle and
    compiling it again) would have made the picture of a revision depend on the machine the
    console runs on. The source view and the diff read the same reply, so the 0.8 file
    endpoints are not brought back. (b) The canvas is one column in written order, loops as
    frames with their bodies inset, every wire in a lane of its own in a gutter on the right.
    A card's rows are one line each, clipped, so the layout is a pure function of the graph
    with no measuring of the page: the same graph always draws the same picture, in the
    console and in the extension. A port carries its target's description as text, so the
    picture can be read without following a wire. (c) "The shipped grammar's colours" are
    taken literally: the console runs a small TextMate tokenizer of its own over
    `editors/vscode/syntaxes/aip.tmLanguage.json` and takes the colours from the extension's
    `package.json`, both imported at build time. No copy of the grammar, and no list of
    keywords, lives in `console/` (the rule that keywords are listed once). The tokenizer
    covers what that grammar uses and no more; the extension's own harness asks the real
    engine the same questions. (d) A draft opens at `#/p/bundle:<bundle id>`: it has no name
    that resolves to it. The catalog's toggle lists drafts in a table of their own under the
    published names, since several drafts may share one name. (e) The console's runs are
    recorded as agent `console` and, as their session, an id the browser tab keeps for its
    lifetime, so "filter history by agent and session" has something to show from the page
    itself. (f) The run page shows the run from this machine's run file after every stop
    (`aip runs <id> --json` through the launcher), not from the CLI's final object: an answer
    that was refused leaves the run paused, and the run file is what says so. (g) Folder mode
    takes a program directory, compiles it through the CLI each time the page opens and
    shows the compiler's diagnostics; its history is this machine's run files of that folder.
    (h) A console whose server is the local one wakes it (`aip list`, through the launcher)
    when the page finds nothing answering: it stops itself after 15 idle minutes, and a page
    left open would otherwise meet a dead address. (i) The console's release tag is
    `console-vX.Y.Z`, since `vX.Y.Z` in this repository is the Python package's. (j) Gone with
    the Studio and not replaced: skill zips (a procedure is published and fetched as a bundle,
    `aip publish` and `aip get`), and the step graph's data-flow and run-traffic modes (a card
    lists what its step reads and produces; traffic over the canvas is worth doing once the
    canvas has been used).

46. **Settled 2026-11-09 (L7), revising part of item 12.** `Again` goes. `Again <step>` let a
    step in a loop body re-run a step written before the loop, and was the one edge (`AGAIN`)
    that closed a cycle outside a loop node. Zach, after reading the console's graph of
    ticket-triage: "Again goes." ticket-triage and make_procedure wrote the check before the
    loop, a lone `fix` in the body, and `Again check` jumping back out, while fixed-policy and
    dynamic-policy wrote the check inside the body: one idea two ways, and the `Again` way made
    a loop whose pass (`revise.iterations`, the record's nesting, the picture) did not contain
    its own test. The rule now: the check goes inside the loop, `Until` watches its key, and
    every cycle in a bundle is a loop node, `ENTERS` in and `CONTINUES` back. What it costs:
    (a) `iterations` counts checks, so work that passes its first check leaves 1, where the
    check-before shape left 0. (b) A cap reached after a fix leaves that fix unchecked, so a
    loop that checks then fixes takes `At_Most n+1` for `n` checked fixes; ticket-triage went
    from 3 to 4 and make_procedure from 5 to 6, and in the last pass the agent is still asked
    for a fix nothing will check (the task says `last_pass: true`). An `Else_Fail` loop that
    could skip that last fix would need the cap to be tested where the check fails, which is
    a second meaning for the cap; not done. (c) The parser still knows the word, and its
    aliases `Redo` and `Redo_Step`, only to say what to write instead ("is gone: write the
    step inside the loop and end it with `Continue`"). (d) The language version stays 0.9,
    since nothing is released, so a bundle an earlier 0.9 compiler wrote with an `AGAIN` edge
    is refused by name, `bundle_format`, rather than as a source that no longer compiles.
    (e) `Until` is tested at the loop node before each pass and the moment the watched key is
    produced in the body; the engine already did exactly that, and the spec now says it in
    those words.

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
