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
retired or not) or `name@latest` (the newest live one, whatever is pinned).

| Call | What it does |
|---|---|
| `GET /catalog` | every published name: `name`, `description`, `pinned`, `latest`, `resolves`, and `revisions` newest first (`revision`, `bundle_id`, `published_at`, `retired`) |
| `GET /catalog/search?q=&limit=` | published procedures by what they do, best first: `name`, `revision`, `bundle_id`, `score`, `description` |
| `GET /catalog/{ref}` | the description `aip info` prints (header, inputs, result, steps, loops) with `name`, `revision`, `bundle_id`, `draft`, `published_at`, `retired` |
| `GET /catalog/{ref}` with `Accept: application/octet-stream` | the bundle itself, an `.rl`, for `aip pull` and `aip get` |
| `POST /catalog` (the `.rl` bytes) | publish: verify the bundle, merge it by id, assign the next revision under its procedure's name. `{"name", "revision", "bundle_id", "existed"}`; a bundle that already has a revision keeps it (and is live again if it was retired); `existed` says the store held the bundle before |
| `POST /catalog/{name}/pin` `{"revision"}` | make the name resolve to a revision; `null` clears the pin |
| `POST /catalog/{name}/retire` `{"revision"}` | stop the name resolving to a revision |
| `POST /bundles` (the `.rl` bytes) | hold a bundle with no revision, a draft: `{"bundle_id", "name", "existed", "draft"}` |
| `GET /bundles?drafts=` | every bundle held, newest first, each with `draft` and its `revision` if it has one; `drafts=true` for the drafts alone |
| `GET /bundles/{bundle_id}` | describe a bundle by id, or with `Accept: application/octet-stream` hand it back |
| `POST /runs` (the run as JSON) | record a run where it stopped: the whole run each time, upserted by `run_id`. The bundle it names must be held (404 `unknown_bundle` otherwise). Replies `{"run_id", "user"}` |
| `GET /runs?name=&status=&agent=&session=&user=&draft=&limit=` | runs, most recently updated first: `run_id`, `name`, `revision`, `bundle_id`, `status`, `draft`, `identity`, `started`, `finished`, `created`, `updated`, `entries` |
| `GET /runs/{run_id}` | one run's record, as it was posted |
| `GET /governance`, `GET /governance/{query}?name=&agent=&session=&user=&window=&limit=` | the named queries of `aip.server.governance` and their rows |

**An upload is read as a bundle is read anywhere** (`aip.compiler.read_bundle`): every file's
bytes against its hash, the source and files against the bundle id, and the stored graph against
the one the stored source compiles to. A file that is not a bundle, was edited by hand, or is of
another language version is refused with the bundle error's own kind (422 `not_a_bundle`,
`bundle_tampered`, `bundle_language_version`), and nothing is stored.

**A bundle handed back is the bundle's own subgraph**, read out of the store and written to a
new `.rl`. Its bytes differ from the file that was uploaded, and its id does not: the id is the
content's, and the client verifies what it receives the same way.

**Errors** are `{"error": {"kind", "message", "location"?, ...}}` with the status: 401
`missing_token` or `invalid_token`, 403 `forbidden`, 404 `not_found` or `unknown_bundle`, 422
`invalid_request` or a bundle error's kind, 500 `internal`.

**Auth** is a bearer token. A token has scopes, `read` (every GET), `run` (upload a draft, record
a run) and `publish` (publish, pin, retire), and may have a name. `--token` grants all three and
`--read-token` only `read`; the config file's `[tokens]` table gives one token per person
(`zach = "..."`), with every scope, and that name is the `user` of the runs recorded with it.
With no token configured the server is open, and a loopback client needs none either way
(`--no-localhost` turns that off). The server answers CORS for pages on a loopback origin, where
the console runs, and for the origins in `allow_origins`.

**Identity.** A run says who ran it: `agent` and `session` are the client's claim (`--agent`,
`AIP_AGENT`, `--session`, `AIP_SESSION`); `user` is the server's, the name of the token the run
was posted with, written into the record whatever the client sent, and `null` on an open server.

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
| `Run` | `run_id`, `bundle_id`, `name`, `revision`, `draft`, `status`, `agent`, `session`, `user`, `started`, `finished`, `created`, `updated`, `position`, `batch`, `entries` (how many); when paused `paused_at`, `paused_since`, `tasks`; when failed `error` (the kind), `error_step`, `error_message`; `json` (the run without its history) |
| `Entry` | one per history entry: `run_id`, `bundle_id`, `seq`, `step`, `kind`, `pass`, `loop` (the innermost), `loops` (each enclosing loop and pass, `revise 0`), `at`, `seconds`; a `Decide`: `model`, `endpoint`, `model_seconds`, `history_sent`, `batched`, `batch_size`; a `Task_Agent`: `agent`, `session`, `waited_seconds`; a `Route`: `read`, `value`, `to`, `check_fired`, `check_reason`, `check_confidence`, `check_below`; an `Execute`: `script`; a loop's exit: `exit` (`until`, `items`, `times`, `cap`), `exit_where`, `iterations`; the first entry of a `Loop` pass: `until_holds`, `until_where`; `sha` and `json` (the entry as posted) |
| `Answer` | one per answer object an entry produced: `run_id`, `bundle_id`, `seq`, `step`, `name`, `value`, `source` (`measured`, `scripted`, `agent`, `aggregated`), `confidence`, `score`, `probabilities` (JSON); an aggregation's: `answers` (how many it judged), `held`, `barred` |
| `Meta` | `key: 'builtins'`, `offered` (the ids of the built-in bundles this store has been offered) |

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
brought back after someone retires it. None ships yet; `make_procedure` is the first (plan K1).

## 4. Configuration

`aip server --init` writes `~/.config/aip/server.toml` with every setting commented;
`--example-config` prints it. Precedence: flags, the environment (a `.env` is loaded into it
without overriding), the file, defaults (`src/aip/server/config.py`). `[server]` is the listener
(`host`, `port`, `token`, `read_token`, `localhost_open`, `log_level`, `allow_origins`),
`[tokens]` names people, `[backend]` picks the store (`kind = "relate"` with `path`, or `"neo4j"`
with `uri`, `user`, `password`, `database`). A file that still says `kind = "filesystem"` or
`root` is refused with where the store is now.

## 5. Still to come

The local server started on demand by `aip run`, the rest of the governance queries under their
new name `aip audit`, stored queries, and `aip export runs` (plan S2); the console on this API
(C1); `aip mcp` (M1).
