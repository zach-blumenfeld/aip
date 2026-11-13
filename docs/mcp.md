# `aip mcp`: the runtime as an MCP server

`aip mcp` is the SDK (`aip.Client`, `docs/sdk.md`) in a process that speaks the
[Model Context Protocol](https://modelcontextprotocol.io/), so an agent framework or a coding
agent reaches procedures with the MCP client it already has. It adds nothing of its own: seven
tools, each one SDK call, each answering with the object the `aip` command prints for the same
thing (`docs/cli-json.md`). The module is `aip.mcp`.

```
aip mcp [--agent A] [--session S]             over stdio: the command an MCP client is given
aip mcp --http PORT [--host HOST]             over streamable HTTP, at http://HOST:PORT/mcp
```

An MCP client's configuration names the command, and the environment `aip` should see:

```json
{"mcpServers": {"aip": {"command": "aip", "args": ["mcp"],
                        "env": {"AIP_SERVER": "local", "AIP_AGENT": "my-agent"}}}}
```

**A stdio client must forward its environment.** An MCP client starts `aip mcp` with a minimal
environment of its own, not the shell's: whatever `AIP_*` variables you set where the agent runs
(`AIP_SERVER`, `AIP_TOKEN`, `AIP_HOME`, `AIP_CONFIG`, `AIP_DECISION_MODEL`,
`AIP_DECISION_MODEL_KEY`, `AIP_AGENT`, `AIP_SESSION`) do not reach it unless the configuration
passes them, in its `env` block or, from Python, with `StdioServerParameters(command="aip",
args=["mcp"], env=dict(os.environ))` as `examples/agents/mcp-smoke/run.py` does. A client that
does not is talking to a different `aip` than the shell beside it: the one the user's config
file describes, with the default `~/.aip`. The usual signs are `no_server` from `search` while
`aip search` works in the terminal, or `no_decision_model` with the key exported. With nothing
set in the environment, `env` may be left out.

The server uses what `aip config` holds on its machine (and those variables, which override
it): the server runs are recorded on (with `aip config server local`, the first call starts
it), its token, the decision model's endpoint and key, the batch size. Runs happen in the `aip
mcp` process, from the same bundle cache and with the same run files as the command line, so a
run started over MCP can be resumed with `aip resume <run_id>` and read with `aip runs
<run_id>`, and the other way round.

## The tools

| tool | arguments | answers with | SDK |
|---|---|---|---|
| `search` | `query`, `limit` (10) | `hits`, best first: `name`, `revision`, `bundle_id`, `score`, `description` | `Client.search` |
| `describe` | `target` | the description `aip info --json` prints, with `example_inputs`, `result_on_some_paths`, and a `warning` when it has a `Decide` and no decision model is configured | `Client.describe` |
| `compile` | `folder`, `output` (a path ending in `.rl`, optional; any other name is refused) | `ok`, `name`, `bundle_id`, `diagnostics`, `output` | `Client.compile` |
| `run` | `target`, `inputs`, and optionally `session`, `batch`, `workdir` | where the run stopped: paused, done or error | `Client.run` |
| `resume` | `run_id`, `answers` (none: retry a failed step), and optionally `work` (what answering cost you: `model`, `tool_calls`, `tokens`, `seconds`; kept marked `reported`) | where the run stopped | `Client.resume` |
| `agent` | `task`, and optionally `session` (one an earlier reply gave: `task` is then the person's reply to its note) | `aip agent --json`'s outcome: `session`, `status`, `note`, `run_id`, `runs`; this server's chat model (`aip config agent`) drove `assist` (`docs/agent.md`), recorded as agent `agent` | `Client.ask` |
| `pull` | `ref` (none: every published name) | `pulled`: `ref`, `name`, `revision`, `bundle_id`, `path`, `fetched` | `Client.pull`, `pull_all` |

A `target` is what `aip run` takes: a published name (`name`, `name@rev`), a program directory,
or an `.rl` bundle; paths are the server's machine's. `run` and `resume` answer with exactly the
objects of `docs/cli-json.md`: `{"paused": "task", "step", "tasks", "hint", "run_id", ...}`,
`{"done": true, "result", "run_id", ...}` or `{"error": <kind>, "message", "resumable", ...}`,
with `recorded` when a server is configured. `answers` answers every task of the pause: the one
answer object for a single task, a list in task order, or an object keyed by task index.
`workdir` is where the procedure's scripts read and write files; it defaults to the directory
`aip mcp` was started in.

A hit's `score` is BM25's over the name, the description, the `Use_When` lines and the step
descriptions (a query that is exactly a published name scores 100 more). It orders the hits of
one search and means nothing across searches, and there is no floor: a query that fits nothing
still ranks whatever shares a word with it, a fraction of a point where a real match scores
tens. So the first hit is the best there is, not necessarily a match; read its `description`.
`bundle_id` is the id of the bundle the name resolves to, the one `describe` and `pull` report.

`describe`'s `result` lists every key the `End` step names; `result_on_some_paths` is the ones
a run has only when the path it took produced them (`billing_support`: `ticket_id` and `queue`
on the angry branch, `reply` on the calm one). `run` refuses a retired `name@revision` (`kind:
"retired"`; the command line's `--force` is not offered here), and its reply carries `warning`
when the procedure has a `Decide` and no decision model is configured: the run fails if it
reaches that step, and it says so before the first step rather than at it.

**A pause and an error are results, not MCP errors.** A run that pauses, a run that fails, an
answer that is refused (`invalid_output`: the pause stands, answer again) and a call that
cannot be made (`invalid_input`, with `kind`: `not_found`, `no_server`, `compile_error`, ...)
all come back as an ordinary tool result whose first key says which, as on the command line.
The caller's model reads one contract, and a framework that turns a tool error into an
exception does not lose a pause to it. A program directory that does not compile carries the
compiler's `diagnostics` in the error object (the CLI prints them on stderr). Arguments that
do not fit a tool are answered the same way, `invalid_input` with `kind: "invalid_arguments"`
and a plain sentence: `search was not called: `query` is missing. Its arguments are `query`,
`limit`.`, or for a string where `resume` wants the answers, `` `answers` is an object or a
list, not a string``. Only a bug in the server is an MCP error (`isError`).

Each result is sent both ways MCP allows: as structured content, and as the same JSON in a text
block for clients that read only text. While a run moves, each step it runs is an MCP progress
notification for a client that sent a progress token. Its message names the step and, inside
loops, which pass of which loop, innermost first: `Execute check: revise pass 1 of each_ticket
pass 2`, so two tasks answered at one step in different passes are told apart. The last
notification of a call says where the run stopped: `paused at draft: 2 task(s) to answer`,
`done`, or `error script_failed at escalate`. There is no `total`: how many steps a run takes
depends on its routes and loops. The server's
`instructions`, which an MCP client hands to its model, say how the tools fit together: search,
describe, run, answer each pause with `resume`.

## Who ran it

The record's identity fields (`docs/language/runtime.md`, The record) are filled from the
connection:

- **`agent`** is the name the MCP client gave for itself when it connected (`clientInfo.name`:
  `claude-code`, `langgraph`, ...). `aip mcp --agent A` replaces it, for a client whose name
  says nothing; with neither there is `AIP_AGENT`, then `mcp`. The client's version
  (`clientInfo.version`) is recorded beside it as **`agent_version`**, when the agent is the
  client's own name. The name alone is the filter: `aip runs --agent claude-code` finds the runs
  of every version, and `aip runs <run_id>` (and `--json`, under `identity`) shows which one.
- **`session`** is the `session` argument of the `run` call, else `aip mcp --session` or
  `AIP_SESSION`, else an id made when the server started (`mcp-3f9a1c2e`), so the runs of one
  stdio connection are found together. A framework that wants its own grouping passes
  `session` on each `run`.
- **`user`** is the server token's name, as everywhere; the local server has no tokens, so its
  runs have none.

Whoever answers a pause is on the task's history entry (`answered_by`), by the same rule.

## An example client

`examples/agents/mcp-smoke/run.py` is the smallest client: the MCP SDK's own `Client`, no
framework and no model. It starts `aip mcp` over stdio with its own environment passed on,
describes `dynamic-policy`, runs it and answers its pauses with canned text, then `aip runs
--agent mcp-smoke` shows the run.

```
uv run python examples/agents/mcp-smoke/run.py
```

From Python the same server can be built in process, `aip.mcp.build(client)`, which is how
`tests/test_mcp.py` drives it. The package depends on the MCP Python SDK (`mcp`, 2.x), imported
only by `aip.mcp`.

## Over HTTP

`aip mcp --http 8765` serves the same tools at `http://127.0.0.1:8765/mcp` (streamable HTTP).
It is one `aip` client shared by whoever connects: one config, one bundle cache, one working
directory, and no authentication of its own, so keep it on loopback or behind something that
authenticates. Each caller is still its own `agent`, and passes `session` to keep its runs
apart.
