# Run modes: local and served

A procedure can be run two ways with the same `aip` command. This page says what each is, who
holds what, and why you would pick one. "Today" is the current code; "planned" is the rest of
`docs/client-execution.md` (decisions moving to the client; scripts already have).

## The two modes

| | local run | served run |
|---|---|---|
| command | `aip run ./some-skill-folder` | `aip run some-skill` with `AIP_SERVER` set |
| where the procedure comes from | a folder on disk | the server's catalog, at a pinned revision |
| scripts run | on your machine, in the `aip` process | on your machine, in the `aip` process, from a verified cache of the revision's `scripts/` and `assets/` |
| `requires` checked against | your machine | your machine |
| decisions resolved | your decision-model key, else pause to you | today: the server's key. planned: your key, else pause |
| run record | the run file only | the server's run store (filesystem or Neo4j); the run file is a handle |
| search, publish, pin, retire, governance queries, console | none | yes |

A local run is one process and one file. A served run is a client talking to a catalog that
remembers.

## Who holds what

**Local run, today and planned.** The run file, `~/.aip/runs/<run-id>.json`, holds everything:
the state, the full history, the pause. `aip resume <run-id>` rebuilds the run from it, from any
directory. Nothing else records the run.

**Served run, today.** The server's run record is the state and the history, and it is the only
copy. The client's run file holds a handle: run id, server, revision, the run's version, and the
pending pause, and the run's working directory. Each request carries the run id and one thing
(the answer to a pause, the report of a script the client ran, or nothing to retry a failed
step; planned, also decision answers with attribution); the server loads the run, validates,
merges, routes, stores under a version check, and replies with the next pause or the next
script to run, filtered to that step's declared keys. The server keeps nothing
in process memory between requests, so any replica can answer any request, and of two posts
racing on one run exactly one is applied (the other gets a 409). The client never sees or
resends accumulated state. The client runs every script next to its data, with the run's
working directory as `AIP_WORKDIR`, and posts the output (or the exit code and stderr); the
server never runs user code. Decisions still use the server's key.

**Served run, planned.** The same record and requests, but the client also resolves decisions
with its own key, posting each answer with attribution; the server holds no model key
(`docs/client-execution.md`).

## Why pick each

**Local run.** Authoring and testing a skill, running something once on your own data, air-gapped
machines, and the aip-skillbench "aip-spec" condition. Costs: no catalog (the agent needs the
folder), no record of the run beyond one file, no governance, and the procedure is whatever is
in the folder, not a pinned revision. Anyone with the folder can edit it
and nothing notices.

**Served run.** Anything more than one person or one agent. You get discovery (`aip search`), a
pinned revision per run (its thresholds are the author's, so its behaviour is fixed by the
revision), a run history that governance queries and the console read, and a client that only
ever carries what the current step needs, which is what lets a small model run a long procedure. Costs: a server to operate, a token, and
the trust that the client runs the scripts it is handed and reports honestly, the same
trust as a CI runner.

Rule of thumb: local to write it, served to run it.

## What stays the same in both

The format, the CLI's JSON output (pauses, done, errors: `docs/cli-json.md`), the answer files,
and the validator. A skill that runs locally runs served without change, except that a served
run pins a revision and its outputs carry the server's `run_id`. The filtering of state to
declared keys applies to both: each step, and each pause, sees only the step's declared inputs,
locally and on the server alike, so authors see the same thing in either mode.
