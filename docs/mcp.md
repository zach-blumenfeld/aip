# `aip mcp`: the runtime as an MCP server

`aip mcp` is the SDK (`aip.Client`, `docs/sdk.md`) in a process that speaks the
[Model Context Protocol](https://modelcontextprotocol.io/), so an agent framework or a coding
agent reaches procedures with the MCP client it already has. It adds nothing of its own: six
tools, each one SDK call, each answering with the object the `aip` command prints for the same
thing (`docs/cli-json.md`). The module is `aip.mcp`.

```
aip mcp [--agent A] [--session S]             over stdio: the command an MCP client is given
aip mcp --http PORT [--host HOST]             over streamable HTTP, at http://HOST:PORT/mcp
```

An MCP client's configuration names the command and nothing else:

```json
{"mcpServers": {"aip": {"command": "aip", "args": ["mcp"]}}}
```

The server uses what `aip config` holds on its machine: the server runs are recorded on (with
`aip config server local`, the first call starts it), its token, the decision model's endpoint
and key, the batch size. Runs happen in the `aip mcp` process, from the same bundle cache and
with the same run files as the command line, so a run started over MCP can be resumed with `aip
resume <run_id>` and read with `aip runs <run_id>`, and the other way round.

## The tools

| tool | arguments | answers with | SDK |
|---|---|---|---|
| `search` | `query`, `limit` (10) | `hits`, best first: `name`, `revision`, `score`, `description` | `Client.search` |
| `describe` | `target` | the description `aip info --json` prints, with `example_inputs` | `Client.describe` |
| `compile` | `folder`, `output` (a path ending in `.rl`, optional) | `ok`, `name`, `bundle_id`, `diagnostics`, `output` | `Client.compile` |
| `run` | `target`, `inputs`, and optionally `session`, `batch`, `workdir` | where the run stopped: paused, done or error | `Client.run` |
| `resume` | `run_id`, `answers` (none: retry a failed step) | where the run stopped | `Client.resume` |
| `pull` | `ref` (none: every published name) | `pulled`: `ref`, `name`, `revision`, `bundle_id`, `path`, `fetched` | `Client.pull`, `pull_all` |

A `target` is what `aip run` takes: a published name (`name`, `name@rev`), a program directory,
or an `.rl` bundle; paths are the server's machine's. `run` and `resume` answer with exactly the
objects of `docs/cli-json.md`: `{"paused": "task", "step", "tasks", "hint", "run_id", ...}`,
`{"done": true, "result", "run_id", ...}` or `{"error": <kind>, "message", "resumable", ...}`,
with `recorded` when a server is configured. `answers` answers every task of the pause: the one
answer object for a single task, a list in task order, or an object keyed by task index.
`workdir` is where the procedure's scripts read and write files; it defaults to the directory
`aip mcp` was started in.

**A pause and an error are results, not MCP errors.** A run that pauses, a run that fails, an
answer that is refused (`invalid_output`: the pause stands, answer again) and a call that
cannot be made (`invalid_input`, with `kind`: `not_found`, `no_server`, `compile_error`, ...)
all come back as an ordinary tool result whose first key says which, as on the command line.
The caller's model reads one contract, and a framework that turns a tool error into an
exception does not lose a pause to it. A program directory that does not compile carries the
compiler's `diagnostics` in the error object (the CLI prints them on stderr). Only a bug in the
server is an MCP error (`isError`).

Each result is sent both ways MCP allows: as structured content, and as the same JSON in a text
block for clients that read only text. While a run moves, each step it runs is an MCP progress
notification (`Decide check (pass 1)`) for a client that sent a progress token. The server's
`instructions`, which an MCP client hands to its model, say how the tools fit together: search,
describe, run, answer each pause with `resume`.

## Who ran it

The record's identity fields (`docs/language/runtime.md`, The record) are filled from the
connection:

- **`agent`** is the name the MCP client gave for itself when it connected (`clientInfo.name`:
  `claude-code`, `langgraph`, ...). `aip mcp --agent A` replaces it, for a client whose name
  says nothing; with neither there is `AIP_AGENT`, then `mcp`. The client's version is not
  recorded: `aip runs --agent claude-code` finds the runs of every version.
- **`session`** is the `session` argument of the `run` call, else `aip mcp --session` or
  `AIP_SESSION`, else an id made when the server started (`mcp-3f9a1c2e`), so the runs of one
  stdio connection are found together. A framework that wants its own grouping passes
  `session` on each `run`.
- **`user`** is the server token's name, as everywhere.

Whoever answers a pause is on the task's history entry (`answered_by`), by the same rule.

## An example client

`examples/agents/mcp-smoke/run.py` is the smallest client: the MCP SDK's own `Client`, no
framework and no model. It starts `aip mcp` over stdio, describes `dynamic-policy`, runs it and
answers its pauses with canned text, then `aip runs --agent mcp-smoke` shows the run.

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
