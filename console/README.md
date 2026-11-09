# aip-console

The console (formerly inspector) for [AIP](https://github.com/zach-blumenfeld/aip): the catalog, each
procedure as a card canvas with its source, the run console, history and the audit queries. It is an
npm package with its own small Node process; the aip server serves no UI.

```
npx aip-console                                     # the server `aip config` names (`local` included)
npx aip-console --server http://localhost:8000      # or a server by its address
npx aip-console ./some-procedure-folder             # or one folder, with no server
```

The package installs two commands, `aip-console` and `aip-inspector`, which are the same. The process
serves the page on `http://localhost:4280/` (`--port`), and:

- **the page calls the server directly** for the catalog, the runs and the audit queries: nothing is
  proxied. The aip server answers CORS for loopback origins, where the console runs (`aip server
  --allow-origin` adds others). When the server is the one `aip config server local` names, which `aip`
  starts on demand and stops when idle, the console wakes it when the page finds nothing answering.
- **runs go through the `aip` CLI on this machine.** Starting a run spawns `aip run <name> --progress`;
  answering a pause, or retrying a failed step, spawns `aip resume <run-id> --progress`. Each JSON line
  the CLI prints (aip's `docs/cli-json.md`: one per history entry, then the paused, done or error
  object) is relayed to the page as it arrives, over a server-sent event stream. Cancel kills the CLI
  and the scripts it started. So scripts run here, next to the data: their files land in the working
  directory (`--workdir`, default the current one); a `Decide` is answered by the decision model this
  machine's `aip config` names; and the CLI records the run on the server itself, as agent `console`
  in the browser tab's session. The CLI is started from an empty directory and given the working
  directory as `--workdir`, so a folder there named like a published procedure does not turn a
  catalog run into a folder's.

With a program directory (one holding `procedure.aip`) instead of a server, the console shows that
folder's procedure, compiled by the CLI each time the page opens, runs it locally and unrecorded, and
lists this machine's runs of it; the catalog, source and audit pages are hidden.

At startup the console runs `aip --version` and refuses to start if `aip` is missing or older than
`0.9.0` (`uv tool install 'agent-instruction-protocol[server]'`, or the aip repo's installer): it
reads bundles, pauses that carry tasks and the 0.9 run record, which date from that release. `--aip
PATH` (or `AIP_BIN`) picks another `aip` than the one on the PATH.

The console's process answers only pages on this machine: it listens on 127.0.0.1, refuses a foreign
`Host` (DNS rebinding) and any post that is not same-origin JSON, since a post starts a run.

## Pages

Routes are hash-based.

- `#/` **catalog**: the published names with the revision each runs as, search by what a procedure
  does, and a toggle that lists the *drafts* apart (bundles the server holds with no revision, because
  a run of a folder or an `.rl` file was recorded against them).
- `#/p/<name>[@rev]` **procedure**: the **card canvas**, then what `aip info` says (when to use it,
  inputs, result, what its scripts require), and the name's revisions with pin and retire. A draft
  opens as `#/p/bundle:<bundle id>`.
- `#/p/<ref>/files[/<path>]` **source**: `procedure.aip` as it was stored, in the colours of the
  grammar the VS Code extension ships, and the bundle's files. `#/p/<name>/diff[/<a>..<b>]` compares
  two revisions file by file, with a line diff for each changed text file.
- `#/run[/<ref>]` **run console**: a field per input, the steps as the CLI reports them, the run's
  record as it stands at each stop, and a form per pause. A pause may carry several tasks at once
  (the passes of a `For` batch waiting at one step): they are shown together and answered together.
- `#/runs` **history**, filtered by procedure, status, agent, session, user, and draft or published
  (the address carries the filters); `#/runs/<id>` is **one run's record**.
- `#/audit` the server's **audit queries** as lists, with their parameters as filters and a form to
  keep a query of your own.
- `#/server` the console's server, and a bearer token for this tab.

### The card canvas

One card per step: its kind as a badge, its description as the title, what it reads and produces
(off the graph's `READ_BY` and `PRODUCES` edges), a decision's questions, an aggregate's
aggregations, a script or a prompt file, and one port per way out, each quoting the description of
the step it leads to. A route has a port per label and one for its `Confidence_Below` check, and
says whose answer steers it (a model's, a script's, an agent's). Loops are frames around the cards
of their body, with the loop's header and its own way out. Drag to pan, wheel or buttons to zoom,
`fit` to see it whole; click a card to read the lines of `procedure.aip` that wrote it, click a port
to go where it leads. It is drawn from the bundle's own graph: `GET /catalog/{ref}/graph` on the
server, or `aip compile --json` through the launcher for a folder. The component (`src/canvas/`)
keeps no console state, so the VS Code extension's preview can draw the same picture.

### A run's record

The record is the run's history as the runtime wrote it; the page answers what the raw JSON leaves a
reader to work out. Every step says how long it took, and the run where its time went (its steps,
the model, waiting on agents). A decision says which model answered and how sure it was of each
answer; a task says which agent and session answered it and after how long; a route says what it
read, where it went, and whether its confidence check fired and on what numbers; an aggregate says
how each answer counted and which the confidence bar turned. The passes of a loop are nested under
the loop, each with the test that let it run, and the loop says why it ended (its condition held,
its items ran out, it hit its cap). A run of a draft wears a `draft` badge, in the list and on its
page.

## Developing

```
npm install
npm run build                                          # dist/, which bin/aip-console.mjs serves
node bin/aip-console.mjs --server http://localhost:8000
```

For hot reload, keep that process running and start Vite beside it: `npm run dev` serves the page on
`http://localhost:5173/` and proxies `/console` to the console's process (`CONSOLE`, default
`http://localhost:4280`).

To have a server with something in it, from the repository root (one level up):

```
uv run aip server --port 8000
AIP_SERVER=http://localhost:8000 uv run aip publish examples/language/billing-support-agent
```

## Tests

`npm test` runs node's test runner over the modules that need no browser: the grammar tokenizer on
the example programs, the canvas's model and layout on graphs the compiler printed, a run's history
nested under its loops on records the server kept, the forms' typing, the launcher's reading of what
`aip` prints. Node 22.18 or newer (it runs the TypeScript as it is).

`npm run e2e` drives the real thing and needs this repository's `aip` (`AIP_REPO`, default `..`)
with Relate installed (`../scripts/install-relate.sh`), and `uv`. Before anything starts,
`e2e/prepare.mjs` writes a fresh `.aip-e2e/`: an `aip` on the consoles' PATH that runs the
checkout's CLI, and procedures copied from `../examples/language` (two revisions of
`billing-support-agent` whose escalate script files its ticket under the run's working directory and
fails, or stalls, when the message asks it to; the loop examples as shipped). Then the bundle is
built and four processes start: `e2e/model.mjs`, a decision model with the TypeSafe API shape that
answers from marks in the text it is given (`[angry]` picks a label, `[unsure]` lowers the
confidence, `[break:WORD]` fails the questions that mention WORD); an `aip server` on a Relate store
under `.aip-e2e/`; the console against it; and the console on the first revision's folder. Global
setup publishes the procedures. The CLI runs with its own `AIP_HOME` and no `AIP_CONFIG`, so nothing
on your machine changes what the specs see.

The `console` project covers the canvas (cards, ports, frames, the source slice, pan and zoom), the
source view and the diff, the run page (an agent that decides, a model that decides and a check that
fires, a failing script and its retry, a loop, a loop at its cap, several tasks at once), history
with its filters and the record of a run, drafts, the audit queries, and the launcher itself (an old
`aip` on the PATH, `aip config`, the loopback guards). The `folder` project runs a folder with no
server.

First time: `npx playwright install chromium`, or skip the download and drive an installed Google
Chrome with `PLAYWRIGHT_CHANNEL=chrome npm run e2e`.
