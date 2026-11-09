# The Python SDK

`aip.Client` is the runtime as a library. The `aip` command is a thin wrapper over it: every
client command parses its arguments, calls one `Client` method and prints the result, so
anything the CLI does a program can do too, and `aip mcp` and the agent frameworks sit on the
same calls. The run files are shared: a run started with `client.run` can be resumed by
`aip resume <run_id>`, and the other way round.

```python
import aip

client = aip.Client()                                        # the configured server, if any (`aip config`)
client = aip.Client("https://aip.example.com", token="...")  # a server
client = aip.Client(agent="my-framework 2.1")                 # who the record says ran it
```

With no argument the client points where `aip config` points, which may be nowhere: then runs
work and are not recorded, and the catalog methods raise `NoServer`. `decision_client=`
injects a TypeSafe client; otherwise the configured key (`TYPESAFE_API_KEY`, `aip config
--decision-model`) decides, and without one a decision is the agent's where the step says
`Agent_Fallback true` and fails the run (`no_decision_model`, resumable) where not. `home=`
moves `~/.aip` (default `AIP_HOME`).

## Running

```python
result = client.run("examples/language/billing-support", {"message": "I was charged twice for March."})
while isinstance(result, aip.Paused):
    result = client.resume(result, answers_for(result))      # your code, a model, or a person
print(result.result)                                         # aip.Done: the End step's keys
```

`run(target, inputs, *, batch=None, agent=None, session=None, workdir=None, on_step=None,
on_pause=None)` runs a target until it stops. The target is a program directory (compiled
here), an `.rl` bundle, or a catalog reference `name[@rev]` (fetched from the server, or from
the bundle cache when `pull` put it there); every run runs on this machine from the bundle
cache, and when a server is configured it is recorded there at every stop (a folder or file as
a run of a *draft*). `workdir` is where its scripts read and write files (default the current
directory); `batch` how many `For` passes run at once (default 10, `aip config --batch`);
`agent` and `session` the run's identity (default `AIP_AGENT` / the client's `agent`, and
`AIP_SESSION`). It returns:

- `aip.Paused`: `kind` (`task` or `decision`), `step`, `reason` (for a decision: why the agent
  is asked), `tasks` (a list of `aip.Task`, one per `For` pass waiting at the step; one outside a
  loop), `run_id`, `run_file`, `recorded`. A `Task` has `index` (what the answer is keyed by),
  `pass_`, `passes`, `state`, `answer_with`, and `prompt` and `references` for a task or
  `questions` for a decision. `paused.task` is the one task of a pause outside a loop.
- `aip.Done`: `run_id`, `result`, `run_file`, `recorded`.

`recorded` is `True` when the server has this stop, `False` when the post failed
(`client.recording_error` says why; the next stop tries again), `None` when no server is
configured. `resume(run, answers=None)` answers a pause; `run` is the `Paused` (or the
`RunError`), a run id, or a run file's path; `answers` is keyed by task index
(`{"0": {...}, "1": {...}}`), a list in task order, or the one answer object for a single task.
With no answers it retries the step a failed run stopped at. `on_step` receives each record
entry's progress line as the run writes it; `on_pause`, if given, answers pauses in-process:
return the answers to go on, or None to stop and get the `Paused` back. Each result's
`to_json()` is exactly the object the CLI prints (`docs/cli-json.md`).

## Errors

Everything raises a subclass of `aip.AipError`, whose `kind` uses the CLI's vocabulary:

| error | when |
|---|---|
| `aip.RunError` | a run stopped on an error; `error` is the CLI's error object, plus `step`, `run_id`, `resumable`, `run_file`, `recorded` and `cause` (the exception behind it, if any) |
| `aip.CompileError` | a program directory that does not compile; `diagnostics` are the compiler's |
| `aip.InvalidBundle` | an `.rl` that is not a usable bundle; `kind` is the bundle error's code (`not_a_bundle`, `bundle_tampered`, `bundle_language_version`) |
| `aip.NotFound` | a target that is neither a folder, a bundle file, nor a name the server knows |
| `aip.NoServer` | a catalog call, or a reference not in the cache, with no server configured |
| `aip.InvalidInput` | inputs or answers that are not usable, a run id with no run file, a run that has nothing to resume |
| `aip.ServerError` | a call to the server failed: `status`, `kind`, `message` from its error envelope (`status` 0, kind `unreachable`, when nothing answered) |

A resumable `RunError` is resumed like a pause, `client.resume(exc)`, once the cause is fixed. A
server that is down does not stop a run: the run goes on unrecorded (`recorded=False`), and a
catalog reference still runs from the bundle cache.

## Compiling, describing, the catalog

| method | returns | CLI |
|---|---|---|
| `compile(folder, output=None)` | `Compiled`: `ok`, `name`, `bundle_id`, `diagnostics`, `errors`, `output` (the `.rl` written when asked) | `aip compile` |
| `describe(target)` | `Description`: `name`, `bundle_id`, `description`, `inputs`, `result`, `steps`, `revision`, `example_inputs`, `data`, `summary()` | `aip info` |
| `search(query, limit=10)` | `[Hit]`: `name`, `revision`, `bundle_id`, `score`, `description` | `aip search` |
| `list()` | `[Entry]`: `name`, `description`, `pinned`, `latest`, `resolves`, `revisions` | `aip list` |
| `pull(ref)`, `pull_all()` | `Pulled`: `name`, `revision`, `bundle_id`, `path`, `fetched`; the bundle is in the cache, so `run` works offline | `aip pull`, `aip pull --all` |
| `publish(target)` | `Published`: `name`, `revision`, `bundle_id`, `existed`; a folder is compiled here, an `.rl` taken as is | `aip publish` |
| `get(ref, out, force=False)` | `Fetched`: `path`, `name`, `bundle_id`, `revision`; the program directory written at `out` | `aip get` |
| `pin(name, revision)` | `Pinned` (`revision=None` clears it) | `aip pin` |
| `retire("name@revision")` | `Retired` | `aip retire` |
| `runs(name=None, status=None, agent=None, session=None, limit=50)` | `[RunSummary]` | `aip runs` |
| `run_record(run_id)` | `RunRecord`: `status`, `identity`, `pause`, `error`, `result`, `history`, from this machine's run file or the server | `aip runs <run_id>` |
| `governance(query=None, **params)` | `[GovernanceQuery]`, or the query's rows | `aip governance` |
| `aip.settings()`, `aip.configure(server, token, decision_model, batch, clear)` | `Settings` | `aip config` |

Records from the server keep the object as sent in `data`, which is what the CLI prints under
`--json`. `aip export` and `aip fmt` are the language's tooling, and `aip server` and `aip db`
serve: none of them is a client call, so none is on `Client`.

## As an agent tool

A procedure is already shaped like a tool: typed inputs, runs to completion, stops only when it
needs the caller. A LangGraph tool that runs one and hands pauses back to the model:

<!-- sdk: tool -->
```python
import json

import aip
from langchain_core.tools import tool

client = aip.Client(agent="langgraph")


@tool
def run_procedure(name: str, inputs: dict) -> str:
    """Run a published AIP procedure. Returns its result, or a pause to answer with answer_procedure."""
    try:
        return json.dumps(client.run(name, inputs).to_json())
    except aip.RunError as exc:
        return json.dumps(exc.to_json())


@tool
def answer_procedure(run_id: str, answers: dict | None = None) -> str:
    """Answer a paused AIP run (one object per task, keyed by index), or omit the answers to retry a failed step."""
    try:
        return json.dumps(client.resume(run_id, answers).to_json())
    except aip.RunError as exc:
        return json.dumps(exc.to_json())
```

The model sees exactly the CLI's JSON (`docs/cli-json.md`), so the `aip` skill's guidance
applies unchanged. Pass `tools=[run_procedure, answer_procedure]` to `create_react_agent` or
bind them to a chat model. `aip mcp` exposes the same calls as an MCP server for frameworks
that speak it.
