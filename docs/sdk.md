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
client = aip.Client("local")                                 # this machine's, started by the first call that needs it
client = aip.Client(agent="my-framework 2.1")                 # who the record says ran it
```

With no argument the client points where `aip config` points, which may be nowhere: then runs
work and are not recorded, and the catalog methods raise `NoServer`. `local` (`aip config server
local`) is a server on this machine that the first call starts and that stops when idle
(`docs/server-design.md`, The local server); a run does not fail when it cannot be started, it
is `recorded=False`. The decision model is an
endpoint with the TypeSafe API shape: the configured one decides (`aip config --decision-model
URL --decision-model-key KEY`, or `AIP_DECISION_MODEL` and `AIP_DECISION_MODEL_KEY`; the URL
defaults to TypeSafe's), and `decision_client=` injects a client with the SDK's shape instead
(tests). With no model a `Decide` fails the run (`no_decision_model`, resumable once one is
configured), and a model that fails is `decision_model_failed` naming the `model`, the
`endpoint` and the `cause`; a procedure that must run without a model has the agent decide in a
`Task_Agent`, as `examples/language/billing-support-agent` does. `home=` moves `~/.aip`
(default `AIP_HOME`).

## Running

```python
result = client.run("examples/language/billing-support", {"message": "I was charged twice for March."})
while isinstance(result, aip.Paused):
    result = client.resume(result, answers_for(result))      # your code, a model, or a person
print(result.result)                                         # aip.Done: the End step's keys
```

`run(target, inputs, *, batch=None, agent=None, session=None, workdir=None, on_step=None,
on_pause=None, force=False, agent_version=None, on_warning=None)` runs a target until it stops. The target is a program directory (compiled
here), an `.rl` bundle, or a catalog reference `name[@rev]` (fetched from the server, or from
the bundle cache when `pull` put it there); every run runs on this machine from the bundle
cache, and when a server is configured it is recorded there at every stop (a folder or file as
a run of a *draft*, unless the server holds that very bundle as a published revision). `workdir` is where its scripts read and write files (default the current
directory); `batch` how many `For` passes run at once (default 10, `aip config --batch`);
`agent` and `session` the run's identity (default `AIP_AGENT` / the client's `agent`, and
`AIP_SESSION`), with `agent_version` beside them when the agent has a version to give (runs are
filtered by `agent` alone). `force` runs a `name@revision` that is retired, which is otherwise
`aip.RetiredRevision`. When the procedure has a `Decide` and no decision model is configured,
the run is not refused, since it may never reach that step: `on_warning` is called with one
sentence before the first step runs, and the result (or the `RunError`'s `error`) carries the
same sentence as `warning`. It returns:

- `aip.Paused`: `kind` (`task`, the one kind: a `Task_Agent` step waits for the agent; a
  `Decide` never pauses), `step`, `tasks` (a list of `aip.Task`, one per `For` pass waiting at
  the step; one outside a loop), `hint` (one line on the shape of an answer), `run_id`,
  `run_file`, `recorded`. A `Task` has `index` (what the answer is keyed by), `pass_`, `passes`,
  `prompt`, `state`, `references`, `answer_with` and `labels` (the values each `choice` or
  `score` in `answer_with` may take), and inside a `Loop` with a cap `last_pass` (whether this
  pass is the last the cap allows) and `pass_of` (the cap); both are `None` elsewhere.
  `paused.task` is the one task of a pause outside a loop.
- `aip.Done`: `run_id`, `result`, `run_file`, `recorded`.

`recorded` is `True` when the server has this stop, `False` when the post failed
(`client.recording_error` says why; the next stop tries again), `None` when no server is
configured. `resume(run, answers=None, *, agent=None, session=None, on_step=None,
on_pause=None)` answers a pause (`agent` and `session` say who answers, for the task's
`answered_by`; by default they are found as `run` finds them, else they are the run's own); `run` is the `Paused` (or the
`RunError`), a run id, or a run file's path; `answers` is keyed by task index
(`{"0": {...}, "1": {...}}`), a list in task order, or the one answer object for a single task,
and answers every task of the pause; an answer-typed key is the bare value or `{"value": ...}`
among the key's labels. Answers are as strict as inputs: a key or a task missing, one the pause
did not ask for, or anything on an answer but its value raises a `RunError` (`invalid_output`,
its `error` naming them under `missing`, `invalid`, `missing_tasks`, `invalid_tasks`), nothing
is applied, and the pause stands: call `resume` again with the right answers. With no answers
`resume` retries the step a failed run stopped at; a run that failed at a loop's cap
(`loop_cap`, `resumable` false) is over and is not retried. `on_step` receives each history
entry's progress line the moment the run writes it, inside a batch of `For` passes too;
`on_pause`, if given, answers pauses in-process: return the answers to go on, or None to stop
and get the `Paused` back. Each result's `to_json()` is exactly the object the CLI prints
(`docs/cli-json.md`).

## Errors

Everything raises a subclass of `aip.AipError`, whose `kind` uses the CLI's vocabulary:

| error | when |
|---|---|
| `aip.RunError` | a run stopped on an error; `error` is the CLI's error object, plus `step`, `run_id`, `resumable`, `run_file`, `recorded`, `cause` (the exception behind it, if any) and `stopped` (False when the call changed nothing: a refused answer, a run with nothing to resume) |
| `aip.CompileError` | a program directory that does not compile; `diagnostics` are the compiler's |
| `aip.InvalidBundle` | an `.rl` that is not a usable bundle; `kind` is the bundle error's code (`not_a_bundle`, `bundle_tampered`, `bundle_language_version`, `bundle_format`) |
| `aip.NotFound` | a target that is neither a folder, a bundle file, nor a name the server knows. For a published name the message is the server's and the same from `run`, `describe`, `pull` and `get`: `no procedure 'billing-support'; did you mean `billing_support`?` (the hint when the name with `_` for `-` is published), `no revision 7 of billing_support`, `billing_support has no live revision` |
| `aip.RetiredRevision` | `run("name@revision")` on a retired revision (`kind` `retired`); `run(..., force=True)` runs it anyway |
| `aip.NoServer` | a catalog call, or a reference not in the cache, with no server configured |
| `aip.InvalidInput` | inputs or answers that are not usable, a run id with no run file, a run that has nothing to resume |
| `aip.ServerError` | a call to the server failed: `status`, `kind`, `message` from its error envelope (`status` 0, kind `unreachable`, when nothing answered) |

A resumable `RunError` is resumed like a pause, `client.resume(exc)`, once the cause is fixed. A
server that is down does not stop a run: the run goes on unrecorded (`recorded=False`), and a
catalog reference still runs from the bundle cache.

## Compiling, describing, the catalog

| method | returns | CLI |
|---|---|---|
| `compile(folder, output=None)` | `Compiled`: `ok`, `name`, `bundle_id`, `diagnostics`, `errors`, `output` (the `.rl` written when asked; an output path that does not end in `.rl` is `InvalidInput`) | `aip compile` |
| `describe(target)` | `Description`: `name`, `bundle_id`, `description`, `inputs`, `result`, `steps`, `revision`, `example_inputs`, `data`, `summary()`. In `data`: `result_on_some_paths` (the result keys a run has only when its path produced them), `retired` for a retired revision, and `warning` when the procedure has a `Decide` and this client has no decision model | `aip info` |
| `search(query, limit=10)` | `[Hit]`: `name`, `revision`, `bundle_id`, `score`, `description` | `aip search` |
| `list()` | `[Entry]`: `name`, `description`, `pinned`, `latest`, `resolves`, `revisions` | `aip list` |
| `pull(ref)`, `pull_all()` | `Pulled`: `name`, `revision`, `bundle_id`, `path`, `fetched`; the bundle is in the cache, so `run` works offline | `aip pull`, `aip pull --all` |
| `publish(target, draft=False)` | `Published`: `name`, `revision`, `bundle_id`, `existed`, `draft`; a folder is compiled here, an `.rl` taken as is. With `draft` the bundle is uploaded with no revision (`revision` None, `draft` True; `draft` False when the server already has it as a revision), and a later `publish` of the same bundle gives it one | `aip publish [--draft] [--json]` |
| `upgrade()` | `[Published]`: the procedures the package ships (`make_procedure`), published to the server; one it already holds comes back with `existed` true | `aip upgrade` |
| `get(ref, out, force=False)` | `Fetched`: `path`, `name`, `bundle_id`, `revision`; the program directory written at `out` | `aip get` |
| `pin(name, revision)` | `Pinned` (`revision=None` clears it); a retired revision is refused (`ServerError`, kind `retired`) | `aip pin name@revision`, `aip pin name --clear` |
| `retire("name@revision")` | `Retired`; a pin on that revision is cleared with it | `aip retire name@revision` |
| `runs(name=None, status=None, agent=None, session=None, limit=50, user=None, draft=None)` | `[RunSummary]`, the most recently started first: `run_id`, `name`, `revision`, `status`, `draft`, `identity`, `started`, `updated`; the server's runs when one is configured, else this machine's run files | `aip runs` |
| `run_record(run_id)` | `RunRecord`: `status`, `identity`, `started`, `finished`, `pause`, `error`, `result`, `history` (the entries, one per step run; for a run paused inside a `For`, the passes it has made so far included), `table()` (the step table), from this machine's run file or the server; `InvalidInput` when neither has it | `aip runs <run_id>` |
| `audit(query=None, **params)` | `[AuditQuery]` (`query`, `description`, `builtin`), or the query's rows; `params` are `name`, `agent`, `session`, `user`, `draft`, `window`, `limit`, `repeats`, `key` | `aip audit` |
| `save_audit(name, cypher, description="")`, `delete_audit(name)` | `AuditQuery`; a query of your own kept on the server and run by name | `aip audit --save`, `--delete` |
| `export_runs(output, name=None, *, since=None, agent=None, session=None, user=None, draft=None, force=False)` | `Exported`: `path`, `runs`, `procedures`, `bundles` (a procedure's revisions and drafts are a bundle each); the runs that match and the procedures they ran, as one Relate file | `aip export runs` |
| `aip.settings()`, `aip.configure(server, token, decision_model, decision_model_key, batch, clear)` | `Settings`: `server` (the URL), `local` (it is this machine's, started on demand), `token_set`, `decision_model_endpoint`, `decision_model_key_set`, `decision_model_configured`, `batch` (the secrets are on it but never in its text) | `aip config` |

Records from the server keep the object as sent in `data`, which is what the CLI prints under
`--json`. `aip export <bundle.rl>` and `aip fmt` are the language's tooling, and `aip server` serves: none
of them is a client call, so none is on `Client`. (`aip db`, which wrote Neo4j with no server, is
gone: the server is the store's only writer, so loading is `publish`, listing is `list`, and
getting a revision's folder back is `get`.)

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
that speak it (`docs/mcp.md`): `search`, `describe`, `compile`, `run`, `resume` and `pull` as
tools, with the MCP client's name as the run's `agent`.
