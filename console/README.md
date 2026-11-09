# aip-console

The console (formerly inspector) for [AIP](https://github.com/zach-blumenfeld/aip): catalog, source and
revision diff, run console, history and governance. It is an npm package with its own small Node process;
the aip server serves no UI.

```
npx aip-console --server http://localhost:8000      # or: npx aip-console ./some-skill-folder
```

The package installs two commands, `aip-console` and `aip-inspector`, which are the same. The process
serves the page on `http://localhost:4280/` (`--port`), and:

- **the page calls the server directly** for catalog, history and governance: nothing is proxied. The aip
  server answers CORS for loopback origins, where the console runs (`aip server --allow-origin` adds others).
- **runs go through the `aip` CLI on this machine.** Starting a run spawns `aip run <name> --progress`;
  answering a pause, or retrying a failed step, spawns `aip resume <run-id> --progress`. Each JSON line the
  CLI prints (aip's `docs/cli-json.md`: one per completed step, then the pause, done or error object) is
  relayed to the page as it arrives, over a server-sent event stream. Cancel kills the CLI and the
  scripts it started. So scripts run here, next to the data: their files land in the working directory
  (`--workdir`, default the current one), and decisions are resolved by this machine's decision model
  (`aip config --decision-model`), or answered on the page when there is none. The CLI itself is started
  from an empty directory and given the working directory as `--workdir`, so a folder in the working
  directory named like a published skill (`./billing-support`) does not turn a served run into a local one.

Without `--server`, the console uses the server `aip config` names. With a skill folder instead, runs are
local (`aip run ./folder`) and the catalog, history and governance pages are hidden.

At startup the console runs `aip --version` and refuses to start if `aip` is missing or older than
`0.8.0` (`uv tool install agent-instruction-protocol`, or the aip repo's installer): the console reads and edits
format 0.8, whose `start` step, decision `confidence` and `fallback`, router confidence check and `no_decision_model`
stop date from that release. `--aip PATH` (or `AIP_BIN`) picks another `aip` than the one on the PATH.

The console's process answers only pages on this machine: it listens on 127.0.0.1, refuses a foreign
`Host` (DNS rebinding) and any post that is not same-origin JSON, since a post starts a run.

Routes are hash-based: `#/` catalog (with what each name's scripts require, and a place to publish a skill zip:
a folder with `SKILL.md`, zipped, is unpacked in the page and posted to the server, which validates it and names
the skill from the frontmatter, so an existing name gets a new revision and the same bytes land on the revision
already there; the validator's issues are listed when it is refused), `#/p/<name>[@rev]` procedure
(its `requires`, each step's inputs and outputs, the graph as control flow, as key-level data flow, or as run
traffic, where every recorded run of the revision is read and each edge thickens with the runs that took it, each
step wears the runs that reached it and how many failed there, and a table below ranks the steps by reach; the
graph draws top-down or, with `left to right` ticked, across the page, a choice the browser remembers for the run page
too; pin
and retire, and `download zip`: the revision as `<name>@<rev>.zip` with one `<name>/` folder inside, the Agent Skills
layout, packed in the page from the manifest and the files),
`#/p/<ref>/files[/<path>]` source manifest and viewer (with the same download), `#/p/<name>/diff[/<a>..<b>]` the diff between two
revisions (manifest by hash, line diff for changed text files, both computed client-side),
`#/run[/<ref>]` the run console, `#/runs[/<id>]` history (each step's declared state in and out, the
machine that ran it, each decision's resolver and the confidence its model recorded, and whether a router's
confidence check fired and why), `#/governance` the corpus queries of
`GET /governance` as lists (with the runs each fired check sent elsewhere for `confidence-fired`, the source class
of each flagged router for `unmeasured-routes`, the model/by-hand split of `manual-decisions` and the stderr clients
reported for `failing-scripts`), plus a form to keep a query of your own on the server, which a Neo4j-backed
server stores and runs read-only and lists beside the built-ins, and `#/server` (the console's server, and a
bearer token for this tab).

## Studio

`#/studio` builds a procedure in the browser: steps, edges, typed inputs and outputs, with lint on every edit.
It exports a skill zip with a placeholder for each script and template. **Complete with an agent** writes the
scaffold to `<workdir>/studio/<name>/` and gives you one prompt to paste into your coding agent. The Studio watches
the folder, validates the agent's work with `aip-spec` (on the PATH, or `--aip-spec PATH`), checks it against your
design, runs its scripts, and only then lets you accept it.

- [Tutorial](examples/studio/README.md): an example design taken to a finished skill, agent step included.
- [Reference](docs/studio.md): every Studio feature.

## Developing

```
npm install
npm run build                                          # dist/, which bin/aip-console.mjs serves
node bin/aip-console.mjs --server http://localhost:8000
```

For hot reload, keep that process running and start Vite beside it: `npm run dev` serves the page on
`http://localhost:5173/` and proxies `/console` to the console's process (`CONSOLE`, default
`http://localhost:4280`).

To start a server, from a clone of the aip repo:

```
uv run aip server --backend filesystem --root /tmp/aip-root --port 8000
AIP_SERVER=http://localhost:8000 uv run aip publish "$(uv run aip-spec example billing-support --out /tmp)"
```

## Tests

`npm run e2e` needs the sibling aip repo (`AIP_REPO`, default `../aip`) and `uv`. Before anything starts,
`e2e/prepare.mjs` writes a fresh `.aip-e2e/`: an `aip` on the consoles' PATH that runs the aip repo's CLI,
and two revisions of aip-spec's `billing-support` whose escalate script files its ticket under the run's
working directory (and fails, or stalls, when the message asks it to). Then the bundle is built and three
processes start: a filesystem-backed `aip server`, the console against it, and the console on the first
revision's folder. Global setup publishes both revisions. The CLI runs with its own `AIP_HOME`, no
`AIP_CONFIG` and no `TYPESAFE_API_KEY`, so nothing on your machine changes what the specs see, and every
decision pauses for the page to answer.

The `console` project drives both branches from the run page (the escalate script's ticket must land in the
console's working directory), a failing script and its retry, cancel, history with attribution, governance, skill
zips (a download matches the manifest byte for byte, an upload under its own name makes a revision, the same zip
lands on it again, a downloaded zip uploads back onto its revision, and a broken one lists the validator's issues),
the 0.6a0 views over fixture runs posted to the run API (a model-answered decision, a script reported from
another machine, a failed script), and the launcher itself (an old `aip` on the PATH, `aip config`, the loopback guards). The `folder` project
runs the same skill from the folder console with no server.

First time: `npx playwright install chromium`, or skip the download and drive an installed Google Chrome
with `PLAYWRIGHT_CHANNEL=chrome npm run e2e`.
