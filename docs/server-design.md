# The AIP server

What `aip server` is in 0.9: the catalog of published procedures and the record of their runs,
over one graph store. The language and what running it requires are `docs/language/spec.md` and
`docs/language/runtime.md`; the client's side of every call below is `src/aip/client/server.py`.
(Through 0.8 the server also stepped runs and stored skill folders, on Neo4j or a directory;
that design is in the git history of this file. The filesystem backend, its file lock and
`aip db` are gone.)

## 1. What the server does, and does not

- **It holds bundles.** A bundle is the compiled procedure, one `.rl` file (`docs/language/bundle.md`).
  The server stores its graph and gives it a *revision* under the procedure's name when it is
  published, or holds it with no revision, a *draft*, so that a run of a folder or a file can be
  recorded. A bundle is merged by its id, a hash of the source and files: storing one the store
  holds changes nothing.
- **It holds the record of runs.** Every run is local to its client: the client loads the bundle
  from its cache, calls the decision model itself, runs the scripts next to its data, and posts
  the run where it stopped. The server never runs a step, a script or a model, and holds no
  decision-model key.
- **It answers questions over both**, because they are one graph: a run's entries are tied to
  the steps of the procedure they ran (`docs/language/queries.md`).
- **It serves no UI.** The console is a client like the `aip` command.

One process writes a store. With the Relate backend that is a rule of the engine (the server is
the only writer of its file); with Neo4j several servers may share a database.

## 2. The HTTP API

`ref` is `name` (the pinned revision, else the newest live one), `name@<revision>` (that one,
retired or not) or `name@latest` (the newest live one, whatever is pinned). A reference the
store does not have is 404 `not_found` in one of three sentences, which every client command
passes on as it is: `no procedure 'billing-support'; did you mean `billing_support`?` (the
question when the name with `_` for `-` is published: a folder is `billing-support`, its
procedure `billing_support`), `no revision 7 of billing_support`, and `billing_support has no
live revision: all 2 are retired`.

**Retire wins over pin.** A retired revision does not resolve by name, pinned or not: retiring
the pinned revision clears the pin, and pinning a retired one is refused (409 `retired`). A
name whose every revision is retired stays in `GET /catalog` with `resolves` null and the
description of its newest revision (`aip list` prints `@- (retired)`); search, which covers what
names resolve to, no longer finds it. `name@<revision>` still names a retired revision, for the
runs that reference it, and its description says `retired: true`; the client refuses to run one
unless forced (`aip run name@rev --force`). Publishing its bundle again brings it back.

| Call | What it does |
|---|---|
| `GET /catalog` | every published name: `name`, `description`, `pinned`, `latest`, `resolves`, and `revisions` newest first (`revision`, `bundle_id`, `published_at`, `retired`) |
| `GET /catalog/search?q=&limit=` | published procedures by what they do, best first: `name`, `revision`, `bundle_id`, `score`, `description` |
| `GET /catalog/{ref}` | the description `aip info` prints (header, inputs, result, steps, loops) with `name`, `revision`, `bundle_id`, `draft`, `published_at`, `retired` |
| `GET /catalog/{ref}` with `Accept: application/octet-stream` | the bundle itself, an `.rl`, for `aip pull` and `aip get` |
| `POST /catalog` (the `.rl` bytes) | publish: verify the bundle, merge it by id, assign the next revision under its procedure's name. `{"name", "revision", "bundle_id", "existed"}`; a bundle that already has a revision keeps it (and is live again if it was retired); `existed` says the store held the bundle before |
| `POST /catalog/{name}/pin` `{"revision"}` | make the name resolve to a revision; `null` clears the pin; 409 `retired` for a retired one |
| `POST /catalog/{name}/retire` `{"revision"}` | stop the name resolving to a revision, and clear a pin on it |
| `POST /bundles` (the `.rl` bytes) | hold a bundle with no revision, a draft: `{"bundle_id", "name", "existed", "draft"}` |
| `GET /bundles?drafts=` | every bundle held, newest first, each with `draft` and its `revision` if it has one; `drafts=true` for the drafts alone |
| `GET /bundles/{bundle_id}` | describe a bundle by id, or with `Accept: application/octet-stream` hand it back |
| `GET /catalog/{ref}/graph`, `GET /bundles/{bundle_id}/graph` | the bundle's own graph as JSON: `name`, `revision`, `draft`, `bundle_id` and `graph`, the `nodes` and `edges` of `docs/language/bundle.md` in the shape `aip compile --json` prints, here with the source (`Procedure.source`) and each file's contents (`File.text`, or `base64`). What a page draws a procedure from and shows as its source, without opening an `.rl` |
| `POST /runs` (the run as JSON) | record a run where it stopped: the whole run each time, upserted by `run_id`. The bundle it names must be held (404 `unknown_bundle` otherwise). Replies `{"run_id", "user", "draft", "revision"}`: who the token stands for, and what the store holds the bundle as |
| `GET /runs?name=&status=&agent=&session=&user=&draft=&limit=` | runs, most recently started first (a run answered later keeps its place): `run_id`, `name`, `revision`, `bundle_id`, `status`, `draft`, `identity`, `started`, `finished`, `created`, `updated`, `entries` |
| `GET /runs/{run_id}` | one run's record, as it was posted |
| `GET /audit` | the audit queries: the built-ins of `aip.server.audit`, then the ones stored here, each `query`, `description`, `builtin`, `needs` (parameters it cannot run without) and `path` |
| `GET /audit/{query}?name=&agent=&session=&user=&draft=&window=&limit=&repeats=&key=` | one query's rows (section 4) |
| `PUT /audit/{name}` `{"description", "cypher"}`, `DELETE /audit/{name}` | store a query of one's own (422 when it writes or does not parse), remove it |
| `GET /export/runs?name=&since=&agent=&session=&user=&draft=` | one Relate file holding the runs that match and the procedures they ran (`aip export runs`); `X-AIP-Runs`, `X-AIP-Procedures` and `X-AIP-Bundles` count them (a procedure's revisions and drafts are a bundle each); 404 when no run matches |
| `GET /health` | `{"aip", "language", "backend", "local"}`, with no token: how a client tells an aip server from whatever else answers on a port. A local server (section 6) adds its `pid` |

**An upload is read as a bundle is read anywhere** (`aip.compiler.read_bundle`): every file's
bytes against its hash, the source and files against the bundle id, and the stored graph against
the one the stored source compiles to. A file that is not a bundle, was edited by hand, or is of
another language version is refused with the bundle error's own kind (422 `not_a_bundle`,
`bundle_tampered`, `bundle_language_version`, `bundle_format`), and nothing is stored.

**A bundle handed back is the bundle's own subgraph**, read out of the store and written to a
new `.rl`. Its bytes differ from the file that was uploaded, and its id does not: the id is the
content's, and the client verifies what it receives the same way.

**Errors** are `{"error": {"kind", "message", "location"?, ...}}` with the status: 401
`missing_token` or `invalid_token`, 403 `forbidden`, 404 `not_found` or `unknown_bundle`, 422
`invalid_request` or a bundle error's kind, 500 `internal`.

**Auth** is a bearer token. A token has scopes, `read` (every GET), `run` (upload a draft, record
a run) and `publish` (publish, pin, retire, store or remove an audit query), and may have a name. `--token` grants all three and
`--read-token` only `read`; the config file's `[tokens]` table gives one token per person
(`zach = "..."`), with every scope, and that name is the `user` of the runs recorded with it.
With no token configured the server is open, and a loopback client needs none either way
(`--no-localhost` turns that off). The server answers CORS for pages on a loopback origin, where
the console runs, and for the origins in `allow_origins`.

**Identity.** A run says who ran it: `agent` and `session` are the client's claim (`--agent`,
`AIP_AGENT`, `--session`, `AIP_SESSION`); `user` is the server's, the name of the token the run
was posted with, written into the record whatever the client sent, and `null` on an open server.
`agent_version` is beside them when the client gave one (`aip mcp` sends the MCP client's own
version): it is kept on the run and shown with it, and runs are filtered by `agent` alone.

**Draft or published** is the server's to say as well. A run is a *draft's* when the bundle it
ran has no revision in the store, and otherwise it is a run of the revision the bundle is
published as, whether the client ran it by name or from a folder that compiles to the same id:
`draft` and `revision` are written into the record at every stop from what the store holds, and
the reply carries them, so the client's run file says the same. A run recorded while its bundle
was a draft stays a draft's run once it is over; publishing the bundle later does not rewrite it.

## 3. The store

One graph. `src/aip/server/store.py` holds every statement, and both backends run them
unchanged.

A bundle's graph is stored exactly as `aip compile` wrote it (`aip.compiler.write_graph`: the
nodes and edges of `docs/language/bundle.md`, each node with `bundle_id` and `id`). Beside it the
server writes its own nodes, told from a bundle's by label:

| Node | Properties |
|---|---|
| `Name` | `name`, `pinned` (a revision, when one is pinned) |
| `Revision` | `id` (`name@revision`), `name`, `revision` (text), `number`, `bundle_id`, `published_at`, `retired` |
| `Bundle` | `bundle_id`, `name`, `description`, `stored_at`, `draft` (true until published), `described` (the description `GET /catalog/{ref}` returns, as JSON) |
| `Run` | `run_id`, `bundle_id`, `name`, `revision`, `draft`, `status`, `agent`, `agent_version` (when given), `session`, `user`, `started`, `finished`, `created`, `updated`, `position`, `batch`, `entries` (how many); when paused `paused_at`, `paused_since`, `tasks`; when failed `error` (the kind), `error_step`, `error_message`; `json` (the run without its history) |
| `Entry` | one per history entry: `run_id`, `bundle_id`, `seq`, `step`, `kind`, `pass`, `loop` (the innermost), `loops` (each enclosing loop and pass, `revise 0`), `at`, `seconds`; a `Decide`: `model`, `endpoint`, `model_seconds`, `history_sent`, `batched`, `batch_size`; a `Task_Agent`: `agent`, `session`, `waited_seconds`; a `Route`: `read`, `value`, `to`, `check_fired`, `check_reason`, `check_confidence`, `check_below`; an `Execute`: `script`; a loop's exit: `exit` (`until`, `items`, `times`, `cap`), `exit_where`, `iterations`; the first entry of a `Loop` pass: `until_holds`, `until_where`; `sha` and `json` (the entry as posted) |
| `Answer` | one per answer object an entry produced: `run_id`, `bundle_id`, `seq`, `step`, `name`, `value`, `source` (`measured`, `scripted`, `agent`, `aggregated`), `confidence`, `score`, `probabilities` (JSON); an aggregation's: `answers` (how many it judged), `held`, `barred` |
| `Meta` | `key: 'builtins'`, `offered` (the ids of the built-in bundles this store has been offered) |
| `AuditQuery` | a stored audit query: `name`, `description`, `cypher`, `stored_at` |

| Edge | From → to | Meaning |
|---|---|---|
| `HAS_REVISION` | `Name` → `Revision` | |
| `OF` | `Revision` → `Bundle`; `Run` → `Bundle` | the bundle a revision is, the bundle a run ran |
| `HOLDS` | `Bundle` → `Procedure` | into the bundle's own graph |
| `HAS_ENTRY` | `Run` → `Entry` | |
| `THEN` | `Entry` → `Entry` | the next entry of the same run |
| `AT` | `Entry` → `Step` or `Loop` | the node of the procedure the entry ran |
| `GAVE` | `Entry` → `Answer` | |
| `ANSWERS` | `Answer` → `Question` or `Aggregation` | a decision's answer to its question; an aggregation's result |

A property whose value would be null is left out. A run is upserted whole at every stop: the
`Run` node is rewritten, and of the history only the entries that are new or changed are
written (each carries the hash of its JSON), so recording a long run is not quadratic in its
length. `GET /runs/{run_id}` rebuilds the record from `Run.json` and the entries' `json`, so
what comes back is what was posted, with the server's `user`.

A run paused inside a `For` is posted with the entries its passes have written so far, pass by
pass in input order, although the engine itself appends a pass's entries to the history only
when its batch completes (`docs/language/runtime.md`, The record). So a paused loop's work is
in the store while the run waits: its `Entry` and `Answer` nodes, the run's `entries` count,
and the audit queries over them. When a pass that was waiting moves on, the entries after it
shift, and those are the ones rewritten at the next stop.

Search is BM25 with Porter stemming (`aip.server.search`) over the name, description, `Use_When`
lines and step descriptions of the revision each name resolves to, in the server's memory, the
same on both backends; an exact name wins outright.

### Backends

- **Relate** (the default, `aip.server.backends.relate`). One file under the data directory,
  `~/.local/share/aip/server/store.rl` unless `--path` or `backend.path` says otherwise (kept as
  `store.cl` while the pinned engine release still carries its old name; `aip.compiler.relate`
  knows). No other process is needed. A connection belongs to the thread that opened it, so one
  worker thread owns it and runs every transaction in turn. Look inside with the engine's own
  CLI or a Browser on `relate serve --read-only`, and `docs/language/queries.md`.
- **Neo4j** (`aip.server.backends.neo4j`, `--backend neo4j`, `NEO4J_URI`, `NEO4J_USERNAME`,
  `NEO4J_PASSWORD`, `NEO4J_DATABASE`). For a shared deployment, Aura included. The driver's
  managed transactions; uniqueness constraints on the server's nodes and an index on
  `(bundle_id, id)` for each label of a bundle's graph.

`tests/server/` runs one suite over both (`NEO4J_URI` unset skips the Neo4j half):
`test_contract.py` is the API through the client, `test_queries.py` runs every query of
`docs/language/queries.md` and checks what the store kept of each kind of run.

### Built-in bundles

`aip.server.builtins.publish_builtins` runs when the app is built: each `.rl` shipped under
`aip/server/bundles/` that the store has not been offered before is published, and the store
remembers the ids it has been offered, so a built-in appears on a store's first start and is not
brought back after someone retires it. One ships: `make_procedure`, the procedure that writes a
procedure from a description (`examples/language/make_procedure/` is its source; the `.rl` in
the package is that folder compiled, and a test fails when the two disagree). So `aip list` on a
store that has just been created shows `make_procedure@1`, and a package upgrade that carries a
changed one publishes it as the next revision on the server's next start. `aip upgrade` publishes
the same bundles from a client, as `aip publish` would, for a server that runs an older package
than the client; a bundle the server already holds keeps its revision.

## 4. Audit

`aip audit` asks the store questions by name (`src/aip/server/audit.py`, one Cypher statement
each, the same on both backends; "governance" is what the record, the pins and the retirements
add up to, and none of these decides who may do what, so the command says what it does). Every
query takes the same parameters: `name`, `agent`, `session`, `user` and `draft` filter the runs
(`draft=true` the runs of a bundle with no revision, `false` those of a published one), `window`
is how many of the most recent matching runs are looked at (default 100), `limit` how many rows
come back (default 50).

| Query | Rows |
|---|---|
| `confidence-fired` | per procedure, route and reason (`below`, `absent`): how often the route's `Confidence_Below` fired in the windowed runs, and in which |
| `failing-aggregations` | per aggregation: how often it was computed, how often it did not hold, how many answers its bar turned |
| `model-answers` | per question: how many answers the decision model gave, their mean and lowest confidence, the mean time of the call |
| `failing-scripts` | per `Execute` step and error (`script_failed`, `timeout`, `requires_unmet`): the windowed runs that stand failed there, the script, the latest message. A run that was resumed past the failure no longer counts: the record keeps where a run stands, not the attempts before |
| `untaken-branches` | branches of a route (its `Confidence_Below` line included) that none of the windowed runs took, in the bundles those runs ran |
| `repeated-cycles` | per `Loop` and how it ended (`until`, `times`, `cap`): the runs where it went round more than `repeats` times (default 1), and the most passes |
| `agent-routes` | routes an agent's answer steers (the source class on the route's `READ_BY` edge), with the runs through each |
| `missing-fields` | procedures whose header has no `Use_When`, `Do_Not_Use_When` or `Avoid` line, with how many of each it has |
| `empty-results` | procedures whose `End` returns only `Start` inputs |
| `unused-data` | keys a step produces, and questions a `Decide` asks, that nothing reads |
| `cycles` | every `For` and `Loop`: what bounds it and which keys its body produces again on every pass |
| `lineage` | for `key=`: every key it is derived from, how many steps back, and the steps that produce each, through a `For`'s collected list too |

The first six read the windowed runs. The last six read the revision each published name
resolves to (`name` narrows them; the run filters do not apply). Two 0.8 queries are gone with
the agent fallback: `manual-decisions` (no answer is given by hand) and `unmeasured-routes` (a
route an agent steers is a design, not a flag; `agent-routes` lists them).

**Stored queries.** `PUT /audit/{name}` keeps a query of your own in the store (`aip audit --save
NAME --cypher '...'`), listed after the built-ins with `builtin: false` and run by name like
them, with the same parameters bound (`$name`, `$agent`, `$session`, `$user`, `$draft`,
`$window`, `$limit`, `$repeats`, `$key`, and `$bundles`, the ids of the resolved revisions). The
name is kebab-case and not a built-in's. Every audit query runs in a transaction that is never
committed (Neo4j's read transaction, a rolled-back one on Relate), and Cypher with a writing
clause, or that the database cannot parse (it is planned with `EXPLAIN`, not run), is refused
when it is stored (422). A stored query's rows are whatever it returns: a node comes back as
`{"labels", "properties"}`, a relationship as `{"type", "properties"}`, a path as its `nodes`
and `relationships`, so `RETURN r` answers like any other query. One that fails when it is run
answers 422 with the database's message.

**Export.** `GET /export/runs` writes the runs that match, the graph of every bundle among them
and those bundles' revisions into a new Relate file with the statements the store itself uses,
so the file is a small store: every query of `docs/language/queries.md` answers on it as it
does here, with no server. `since` is a date or a timestamp a run started at or after.

## 5. Configuration

`aip server --init` writes `~/.config/aip/server.toml` with every setting commented;
`--example-config` prints it. Precedence: flags, the environment (a `.env` is loaded into it
without overriding), the file, defaults (`src/aip/server/config.py`). `[server]` is the listener
(`host`, `port`, `token`, `read_token`, `localhost_open`, `log_level`, `allow_origins`),
`[tokens]` names people, `[backend]` picks the store (`kind = "relate"` with `path`, or `"neo4j"`
with `uri`, `user`, `password`, `database`). A file that still says `kind = "filesystem"` or
`root` is refused with where the store is now.

## 6. The local server

`aip config server local` (what the installer sets) points a client at a server on its own
machine that nobody starts by hand (`src/aip/client/local.py`). The first request that finds
nothing answering starts `aip server --local` as a process of its own and is sent again; every
later command reuses it; it stops when no request has arrived for 15 minutes, and the next
command starts it again. Nothing is lost in between: the store is the Relate file `aip server`
opens by default.

| | Default | Moved by |
|---|---|---|
| address | `http://127.0.0.1:8247` | `AIP_LOCAL_PORT` |
| store and log | `~/.local/share/aip/server/store.rl`, `local.log` beside it | `AIP_LOCAL_DATA` (the directory) |
| idle before it stops | 900 seconds | `AIP_LOCAL_IDLE` (0: never) |

`--local` means loopback only, the Relate backend, no token, and no config file or `.env` read,
so it is the same server whichever directory the client stood in. The port is not 8000, where
`aip server` listens by default, so a server started by hand and the local one do not collide;
they do share the default store file, which one process holds at a time. A client tells its
server from anything else on the port by `GET /health`, and reports what it found when it is not
one. A run never fails because of this: when the local server cannot be started (the server
extra or Relate is missing, the port is taken, another process holds the store), the stop is
reported as not recorded with the reason, and the last line of the log. `aip server --local
--stop` stops it by hand, which an upgrade needs: a running server keeps the code it started
with. A remote server is `aip config server URL --token T`; the token's name on the server is
the `user` of the runs.

## 7. Around the server

`aip mcp` (`docs/mcp.md`) is the client as an MCP server: it records runs here as any client
does, and with `aip config server local` its first call starts the local server the same way.
The console (`console/`, plan C1)
is on this API: it reads the catalog, the graph of a revision or a draft, the runs and the audit
queries from the page, and runs procedures through the `aip` CLI on its own machine.
