# Run modes: local and served

A procedure can be run two ways with the same `aip` command. This page says what each is, who
holds what, and why you would pick one. "Today" is the current code; "planned" is
`docs/client-execution.md` plus the state rules in `docs/state.md`.

## The two modes

| | local run | served run |
|---|---|---|
| command | `aip run ./some-skill-folder` | `aip run some-skill` with `AIP_SERVER` set |
| where the procedure comes from | a folder on disk | the server's catalog, at a pinned revision |
| scripts run | on your machine, in the `aip` process | today: on the server. planned: on your machine |
| decisions resolved | your decision-model key, else pause to you | today: the server's key. planned: your key, else pause |
| run record | `run.json` only | the server's run store (filesystem or Neo4j) |
| search, publish, pin, retire, governance queries, console | none | yes |

A local run is one process and one file. A served run is a client talking to a catalog that
remembers.

## Who holds what

**Local run, today and planned.** The run file holds everything: the state, the full history,
the pause, the thresholds. `aip resume` rebuilds the run from it. Nothing else records the run.

**Served run, today.** The client still holds everything in `run.json` and resends the full
state and history on every request. The server recomputes from what it is sent, appends the new
entries to its own run record, and replies. Two copies of the ledger; the client's copy drives the
computation.

**Served run, planned.** The server's run record is the state and the history, and it is the only
copy. The client's run file holds a handle: run id, server, what is pending. Each request carries
the run id and one thing (a script result, decision answers, or a client-task answer); the server
loads the run, validates, merges, routes, stores, and replies with the next pause, filtered to
that step's declared keys. The server keeps nothing in process memory between requests, so any
replica can answer any request. The client never sees or resends accumulated state.

## Why pick each

**Local run.** Authoring and testing a skill, running something once on your own data, air-gapped
machines, and the aip-skillbench "aip-spec" condition. Costs: no catalog (the agent needs the
folder), no record of the run beyond one file, no governance, no shared thresholds, and the
procedure is whatever is in the folder, not a pinned revision. Anyone with the folder can edit it
and nothing notices.

**Served run.** Anything more than one person or one agent. You get discovery (`aip search`), a
pinned revision per run, a run history that governance queries and the console read, thresholds
managed per procedure, and (planned) a client that only ever carries what the current step needs,
which is what lets a small model run a long procedure. Costs: a server to operate, a token, and
the trust that the client runs the scripts it is handed (planned) and reports honestly, the same
trust as a CI runner.

Rule of thumb: local to write it, served to run it.

## What stays the same in both

The format, the CLI's JSON output (pauses, done, errors: `docs/cli-json.md`), the answer files,
and the validator. A skill that runs locally runs served without change, except that a served
run pins a revision and its outputs carry the server's `run_id`. The filtering of state to
declared keys applies to both: each step, and each pause, sees only the step's declared inputs,
locally and on the server alike, so authors see the same thing in either mode.
