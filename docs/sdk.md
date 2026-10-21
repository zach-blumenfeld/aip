# The Python SDK

`aip.Client` is the one runtime, as a library. The `aip` command is a thin wrapper over it:
every client command parses its arguments, calls one `Client` method, and prints the result, so
anything the CLI does a program can do too, and agent frameworks (LangGraph, ADK) sit on the same
calls. The run files are shared: a run started with `client.run` can be resumed by
`aip resume <run_id>`, and the other way round.

```python
import aip

client = aip.Client()                                  # the configured server (`aip config`, AIP_SERVER)
client = aip.Client("https://aip.example.com", token="...")
client = aip.Client("./skills")                        # a folder: local runs only, no catalog
```

With no argument the client points where `aip config` points, which may be nowhere; then only
skill folders run. A folder argument is a skill folder or a folder of skill folders; runs are
local and there is no catalog. A skill folder's path runs locally from any client, as on the
command line. `decision_client=` injects a TypeSafe client; otherwise the configured key
(`TYPESAFE_API_KEY`, `aip config --decision-model`) resolves decisions, and without one every
decision pauses.

## Running

```python
result = client.run("billing-support", {"message": "I was charged twice for March."})
while isinstance(result, aip.Paused):
    result = client.resume(result, answer_for(result))  # your code, a model, or a person
print(result.state)                                     # aip.Done: the end step's inputs
```

`run(skill, input, *, workdir=None, run_file=None, on_step=None, on_pause=None)` starts a run and
steps it until it stops; `skill` is a folder or a published `name[@revision]`, `workdir` where its
scripts read and write files (default the current directory). It returns:

- `aip.Paused`: `kind` (`decision`, `client_task`, `review`), `step`, `state` (the step's
  declared inputs only), `run_id`, `run_file`, and the kind's own fields: `task`, `references`,
  `answer_with`; `questions`; `proposed_answers`, `review`.
- `aip.Done`: `run_id`, `state`, `run_file`.

`resume(run, answer=None)` answers a pause; `run` is the `Paused`, a run id, or a run file's path.
With no answer it retries a failed step. `on_step` receives each step's progress line as it
completes, and `on_pause`, if given, answers pauses in-process: return the answer to go on, or
None to stop and get the `Paused` back. Each result's `to_json()` is exactly the object the CLI
prints (`docs/cli-json.md`).

## Errors

Everything raises a subclass of `aip.AipError`, whose `kind` uses the CLI's vocabulary:

| error | when |
|---|---|
| `aip.RunError` | a run stopped on an error; `error` is the CLI's error object, plus `step`, `run_id`, `resumable`, `run_file`, and `cause` (the exception behind it) |
| `aip.ServerError` | a call to the server failed: `status`, `kind`, `message` from its error envelope |
| `aip.NoServer` | a catalog call, or a published name, with no server configured |
| `aip.NotFound` | a skill that is neither a folder nor a name this client can look up |
| `aip.InvalidSkill` | a folder that does not validate (`validation` lists every issue) |
| `aip.InvalidInput` | an input or answer that is not an object, or a run id with no run file |

A resumable `RunError` is resumed like a pause, `client.resume(exc)`, once the cause is fixed.

## The catalog, runs and governance

| method | returns | CLI |
|---|---|---|
| `search(query, limit=10)` | `[Hit]`: `name`, `revision`, `score`, `description` | `aip search` |
| `list()` | `[Entry]`: `name`, `description`, `pinned`, `latest`, `revisions`, `resolves` | `aip list` |
| `info(skill)` | `SkillInfo`: `name`, `revision`, `start_step`, `inputs`, `result`, `example_input`, `data`, `summary()` | `aip info` |
| `validate(folder)` | `Validation`: `valid`, `name`, `issues`, `errors`, `warnings` | `aip validate` |
| `publish(folder)` | `Published`: `name`, `revision`, `id`, `warnings`; validates first, raising `InvalidSkill` | `aip publish` |
| `get(ref, out=".")` | `Fetched`: `path`, `validation` | `aip get` |
| `pin(name, revision)` | `Pinned` (`revision=None` clears it) | `aip pin` |
| `retire("name@revision")` | `Retired` | `aip retire` |
| `runs(name=None, status=None, limit=50)` | `[RunSummary]` | `aip runs` |
| `run_record(run_id)` | `RunRecord`: `status`, `pause`, `state`, `history`, from the server or a local run file | `aip runs <run_id>` |
| `governance(query=None, *, name, window, limit)` | `[GovernanceQuery]`, or the query's rows | `aip governance` |
| `aip.settings()`, `aip.configure(server, token, decision_model, clear)` | `Settings` | `aip config` |

Records from the server keep the object as sent in `data`, which is what the CLI prints under
`--json`. `aip schema`, `aip runtime` and `aip skill` are the format's tooling, `aip db` loads
Neo4j directly, and `aip server` serves: none of them is a client call, so none is on `Client`.

## As an agent tool

A published procedure is already shaped like a tool: typed start input, runs to completion,
stops only when it needs the caller. A LangGraph tool that runs one and hands pauses back to
the model:

<!-- sdk: tool -->
```python
import json

import aip
from langchain_core.tools import tool

client = aip.Client()


@tool
def run_procedure(name: str, input: dict) -> str:
    """Run a published AIP procedure. Returns its result, or a pause to answer with answer_procedure."""
    try:
        return json.dumps(client.run(name, input).to_json())
    except aip.RunError as exc:
        return json.dumps(exc.to_json())


@tool
def answer_procedure(run_id: str, answer: dict | None = None) -> str:
    """Answer a paused AIP run, or omit the answer to retry a failed step. Returns where it stopped next."""
    try:
        return json.dumps(client.resume(run_id, answer).to_json())
    except aip.RunError as exc:
        return json.dumps(exc.to_json())
```

The model sees exactly the CLI's JSON (`docs/cli-json.md`), so the aip-runtime skill's guidance
applies unchanged. Pass `tools=[run_procedure, answer_procedure]` to `create_react_agent` or
bind them to a chat model.
