# Running a procedure

How to run a procedure with the `aip` command: what to configure, how a run moves and pauses,
how to answer it, and where the run is kept. A procedure is a folder holding `procedure.aip`
(the language: [`docs/language/spec.md`](language/spec.md)); the compiler turns it into a
bundle, one `.rl` file. What running one requires of any runtime is
[`docs/language/runtime.md`](language/runtime.md); every JSON object the CLI prints is in
[`docs/cli-json.md`](cli-json.md), field by field. This page is the tour between them.

The outputs below were recorded from this checkout with no server and no decision model
configured. Run ids, times and paths will differ on yours; the run id is shown as
`4f1c9a2e7b3d5068` and the home directory as `/home/you`, as in the other docs.

## Install and configure

```sh
curl -LsSf https://raw.githubusercontent.com/zach-blumenfeld/aip/main/install.sh | sh
aip --version
```

```
aip 0.9.0 language 0.9
```

The installer puts `agent-instruction-protocol` in place with uv, sets `aip config server local`,
and installs the `aip` skill into the agents it finds. `aip config` with no arguments shows
where this client points. A clean config, before the installer has set the server:

```
$ aip config
server: none (runs are not recorded; run `aip config server local` to record runs on this machine, or `aip config server URL` for a server elsewhere)
decision model: none (a Decide fails the run with no_decision_model; run `aip config --decision-model-key KEY`, and `aip config --decision-model URL` for an endpoint other than TypeSafe's)
batch: 10
script timeout: 300 seconds per script
runah:
  model uri:   https://api.anthropic.com/v1
  model name:  claude-opus-5-5
  model key:   none (`aip runah` refuses to start; `aip config runah --model-key KEY` (and `--model-uri URL --model-name NAME` for an endpoint other than Anthropic's), or AIP_RUNAH_MODEL_KEY)
  per task:    at most 40 tool calls, 500000 tokens
```

The file is `~/.config/aip/config.json` (`AIP_CONFIG` moves it). Each setting has an
environment variable that overrides the file for one command:

| Setting | `aip config` | Environment | Default |
|---|---|---|---|
| where runs are recorded, and the catalog | `server local`, `server URL` (with `--token T`), `server none` | `AIP_SERVER`, `AIP_TOKEN` | none; the installer sets `local` |
| the decision model's endpoint | `--decision-model URL` | `AIP_DECISION_MODEL` | `https://api.typesafe.ai`, TypeSafe's |
| the decision model's key | `--decision-model-key KEY` | `AIP_DECISION_MODEL_KEY` | none: a `Decide` fails the run |
| `For` passes run at once | `--batch N` | `AIP_BATCH` | 10 |
| seconds one script may run | `--script-timeout N` (`0` or `none`: no cap) | `AIP_SCRIPT_TIMEOUT` | 300 |
| runah's chat model | `runah --model-uri URL --model-name NAME --model-key KEY` | `AIP_RUNAH_MODEL_URI`, `AIP_RUNAH_MODEL_NAME`, `AIP_RUNAH_MODEL_KEY` | `https://api.anthropic.com/v1`, `claude-opus-5-5`, no key |
| runah's caps per task | `runah --max-tool-calls-per-task N --max-tokens-per-task N` | | 40 tool calls, 500000 tokens |

An empty string forgets a setting (`aip config --decision-model-key ""`); `aip config --clear`
forgets them all. Keys are never printed. `aip config server local` records runs on this
machine with nothing to start: the first command that needs a server starts one on the loopback
interface and it stops when idle ([`docs/server-design.md`](server-design.md), The local server).

aip calls no chat model unless you ask it to. A `Decide` step asks the decision model, as it
always has, and that is a model of one narrow kind: questions in, typed answers with their
confidence out. Everything else a model might do in a run, the `Task_Agent` steps, is handed to
whoever runs the procedure. `aip runah` is the one exception, and you choose it per command: a
small harness the runtime can host for you, which takes the agent's turns and stops where a
person must answer. The procedure still decides what happens, and the record still says who
answered each task.

## Run a procedure

`aip run` takes a target in any of three forms: a program folder (the directory holding
`procedure.aip`), a bundle (`file.rl`), or a published name (`billing_support`, or
`billing_support@2` for one revision). `aip info <target>` says what it does, what it needs and
what it returns, and `--example-inputs` prints the inputs to fill in:

```
$ aip info examples/language/billing-support-agent --example-inputs
{
  "message": "<string>"
}
```

```
$ aip run examples/language/billing-support-agent -i '{"message": "I was charged twice for March. Could you check?"}'
{
  "paused": "task",
  "step": "triage",
  "tasks": [
    {
      "index": 0,
      "pass": null,
      "passes": [],
      "prompt": "Read the customer's message and classify it.\n\nCustomer message:\nI was charged twice for March. Could you check?\n\nAnswer `billing` with true when the message is about a charge, invoice, refund, or\nsubscription payment, and `tone` with `angry` for explicit frustration, threats to cancel,\nor demands, else `calm`.",
      "state": {
        "message": "I was charged twice for March. Could you check?"
      },
      "references": [],
      "answer_with": {
        "billing": "true_or_false",
        "tone": "choice"
      },
      "labels": {
        "tone": [
          "angry",
          "calm"
        ]
      }
    }
  ],
  "hint": "answer with {\"billing\": true | false, \"tone\": \"angry\" | \"calm\"}; the bare value is enough for a true_or_false, choice or score key ({\"value\": ...} is the same answer)",
  "run_id": "4f1c9a2e7b3d5068",
  "run_file": "/home/you/.aip/runs/4f1c9a2e7b3d5068.json"
}
aip: not recorded: no server is configured; run `aip config server local` to record runs on this machine, or `aip config server URL` for a server elsewhere
```

(The last line is on stderr.) `-i` (`--inputs`) and `--answers` take JSON inline, `@path` for a
file, or `-` for stdin. Every run runs on this machine, whatever the target: a folder is compiled,
an `.rl` verified, a name fetched from the server (or taken from the cache, where `aip pull` put
it earlier), and the bundle is kept in `~/.aip/bundles/<bundle id>.rl` (`AIP_HOME` moves
`~/.aip`). A run stays on the exact bundle it started on, whatever happens to the folder after.

The run goes step by step until it pauses, ends, or fails, and prints one JSON object on stdout
for how it stopped:

| exit code | printed | what to do |
|---|---|---|
| 0 | `{"paused": "task", ...}` | answer the tasks with `aip resume` |
| 0 | `{"done": true, "result": {...}, ...}` | nothing: `result` is the outcome |
| 1 | `{"error": <kind>, ...}` | read `message`; when `resumable` is true, fix the cause and `aip resume` |

Other flags on `run`: `--workdir DIR` (the run's working directory, below; default the current
one), `--batch N` (for this run), `--agent A` and `--session S` (who is running, for the record;
default `AIP_AGENT`, else `cli`, and `AIP_SESSION`), `--force` (run a retired `name@rev`),
`--progress` (one JSON line per step as it is written, then the final object on one line) and
`--debug` (a traceback on stderr when the command itself fails).

## Answer a pause

Only a `Task_Agent` step pauses. Each task carries its `prompt`, the `state` it reads,
`references` to load only if the prompt calls for them, `answer_with` (the keys to answer and
their types) and `labels` (the values a `choice` or `score` key may take). Do the task, then
answer with every key of `answer_with` and nothing else:

```
$ aip resume 4f1c9a2e7b3d5068 --answers '{"billing": true, "tone": "calm"}' --progress
{"event": "step", "step": "triage", "kind": "Task_Agent", "pass": null, "passes": [], "answered_by": {"agent": "cli", "session": null}, "seconds": 0.003}
{"event": "step", "step": "by_tone", "kind": "Route", "pass": null, "passes": [], "to": "reply", "seconds": 0.0}
{"paused": "task", "step": "reply", "tasks": [{"index": 0, ..., "answer_with": {"reply": "string"}, "labels": {}}], "hint": "answer with {\"reply\": <string>}", "run_id": "4f1c9a2e7b3d5068", "run_file": "/home/you/.aip/runs/4f1c9a2e7b3d5068.json"}
```

The route was the procedure's: on `angry` it would have run its own script to open a ticket, and
no task would have asked for a reply. One more answer and the run is done:

```
$ aip resume 4f1c9a2e7b3d5068 --answers '{"reply": "Sorry about that; duplicate charges are refunded in full within 5 business days."}'
{
  "done": true,
  "result": {
    "message": "I was charged twice for March. Could you check?",
    "reply": "Sorry about that; duplicate charges are refunded in full within 5 business days."
  },
  "run_id": "4f1c9a2e7b3d5068",
  "run_file": "/home/you/.aip/runs/4f1c9a2e7b3d5068.json"
}
```

- **Several tasks.** Inside a `For` loop the passes run in batches (`--batch`), and every pass
  waiting at the same step goes out as one pause with one task per pass. Answer them all in one
  `resume`, keyed by each task's `index`: `{"0": {"reply": "..."}, "1": {"reply": "..."}}`. The
  `hint` shows the shape.
- **Answers are strict.** A key missing, a key the task did not ask for, a value outside the
  labels, or a task left out is refused as `invalid_output` naming each one; nothing is applied
  and the same pause waits to be answered again. Answering `{"billing": true}` above gives
  `"error": "invalid_output"`, `"missing": ["tone"]`, `"resumable": true`.
- **What it took.** An agent may say what answering cost it, for the record:
  `aip resume <run_id> --answers ... --work '{"model": "my-model", "tool_calls": 2, "tokens": 1200, "seconds": 4.5}'`
  (keyed by task index, like the answers, when the pause has several tasks). aip checks none of
  it, and keeps it on the task's history entry marked `reported`.

`aip resume` works from any directory, by run id or by the run file's path.

## Retry a failed step

A step that fails while running (a script exits non-zero or runs past the timeout, the machine
lacks what `Requires` names, the decision model is missing or fails) leaves the run at the state
before it, and the error says `"resumable": true`. Fix the cause and run `aip resume <run_id>`
with no answers: the step runs again, from the same bundle, and the run carries on. Here a second
run of `billing-support-agent`, on `Fix it today or I cancel.`, was answered `angry`, which sends
it to the `escalate` script, with the script cap set to 0.001 seconds (`AIP_SCRIPT_TIMEOUT=0.001`);
the retry ran without it:

```
$ aip resume 7d20b9e4c1a65f38 --answers '{"billing": true, "tone": "angry"}'
{
  "error": "timeout",
  "step": "escalate",
  "message": "the script scripts/escalate.py did not finish within 0.001 seconds, the cap on one script (`aip config --script-timeout N` or AIP_SCRIPT_TIMEOUT raises it); resume the run to try it again",
  "script": "scripts/escalate.py",
  "seconds": 0.001,
  "pass": null,
  "passes": [],
  "run_id": "7d20b9e4c1a65f38",
  "resumable": true,
  "run_file": "/home/you/.aip/runs/7d20b9e4c1a65f38.json"
}
$ aip resume 7d20b9e4c1a65f38 --progress
{"event": "step", "step": "escalate", "kind": "Execute", "pass": null, "passes": [], "seconds": 0.016}
{"event": "step", "step": "end", "kind": "End", "pass": null, "passes": [], "seconds": 0.0}
{"done": true, "result": {"message": "Fix it today or I cancel.", "ticket_id": 76495, "queue": "tier2"}, "run_id": "7d20b9e4c1a65f38", "run_file": "/home/you/.aip/runs/7d20b9e4c1a65f38.json"}
```

A loop that reaches its cap with `Else_Fail` (`loop_cap`) is the one failure a retry cannot
help: `resumable` is false and the run is over. An error before any step ran (inputs that do not
fit `Start`, a target that cannot be found or compiled) writes no run file: fix it and `aip run`
again. `aip resume` on a run that is done answers `not_paused`.

## runah: run ahead

`aip runah` runs a procedure as `aip run` does and keeps going, with a chat model answering each
`Task_Agent` task:

```
aip config runah --model-key KEY
aip runah <folder | bundle.rl | name[@rev]> -i '{...}' [--human STEP,STEP]
aip runah <run_id> [--answers '{...}'] [--human STEP,STEP]
```

- It refuses before starting when no model key is configured (`invalid_input`, naming the
  config line), so it never starts a run it cannot carry.
- Scripts, `Decide` steps, routes and loops run exactly as in `aip run`.
- At a task, unless its step is named in `--human`, the model answers it in one short chat with
  five tools confined to the run's working directory: `read_file`, `list_files`, `search`,
  `write_file` and `compile` (the procedure's own files are readable as `bundle:<path>`). Its
  answer is checked exactly as a resume's; a refused answer goes back to the model with the
  reasons, up to three times. A pause with several tasks is one chat per task, and the answers go
  in together.
- It stops at a `--human` step, at the end, at an error, or when the model gives up (a fourth
  refused answer, its tool-call or token cap for the task, an endpoint that keeps failing), and
  prints the same paused, done or error object as `aip run`. A pause it did not answer carries
  `answerer`: `{"answered": false, "step", "reason"}`, with what the model spent when it tried.
- `--human` is kept by the run, so a later `aip runah <run_id>` need not repeat it; given again it
  replaces the list (`""` for none). Given a run id, `--answers` go into the standing pause
  first; with none, the model answers that pause, or a failed step is retried.
- `run`, `resume` and `runah` mix on one run: answer a human step with `aip resume` and the run
  pauses at the next task; answer it with `aip runah <run_id> --answers ...` and the model carries
  on.

A task the model answered is recorded with `answered_by: {"agent": "runah", "model": <the id the
endpoint reported in its reply, not the configured name>}`, its tool calls (name, a summary of
the arguments, seconds), its tokens, and `work: "observed"`. The run's own `agent` stays whoever
launched it. The model's endpoint is any that serves OpenAI Chat Completions; the details are in
[`docs/runah.md`](runah.md).

## Where runs are kept, and how to look at them

Every stop writes the run file, `~/.aip/runs/<run_id>.json`: the whole run, its state, its
history (one entry per step run, every loop pass included), the pending pause or the error, and
its working directory. That is what lets `aip resume` work from anywhere. Do not edit it.

When a server is configured, the run is also posted there at every stop, and the printed object
carries `"recorded": true` (or `false`, with the reason on stderr; the next stop tries again). A
run of a folder or a file is recorded as a run of a *draft* bundle, unless the server holds that
very bundle as a published revision. With no server the run works the same and is not recorded.

```
$ aip runs
RUN               NAME                           STATUS  AGENT  STARTED                        UPDATED
4f1c9a2e7b3d5068  billing_support_agent (draft)  done    cli    2026-11-10T22:55:30.768+00:00  2026-11-10T22:55:31.016+00:00

$ aip runs 4f1c9a2e7b3d5068
run 4f1c9a2e7b3d5068  billing_support_agent  draft  done
  bundle    6e98638919e8fdeb81c8f0b06626162323fd8dd69ae6f95d7f0791ad9cbaaad2
  target    /home/you/aip/examples/language/billing-support-agent
  agent     cli   session -   user -
  started   2026-11-10T22:55:30.768+00:00   finished 2026-11-10T22:55:31.016+00:00

STEP     KIND        PASS  WHEN          +MS  WHAT
start    Start       -     22:55:30.771    3  message
triage   Task_Agent  -     22:55:30.934    3  answered by cli after 0.2s -> billing=true, tone=calm
by_tone  Route       -     22:55:30.934    0  -> reply  (tone is calm)
reply    Task_Agent  -     22:55:31.016    1  answered by cli (my-model), reported: 2 tool calls, 1200 tokens, 4.5s -> reply
end      End         -     22:55:31.016    0  message, reply

result: {"message": "I was charged twice for March. Could you check?", "reply": "Sorry about that; duplicate charges are refunded in full within 5 business days."}
```

(The `reply` row is the answer given with `--work` above; a runah answer reads `answered by
runah (<model>), observed: ...`.) `aip runs` lists the server's runs when one is configured, else
this machine's run files, and filters by `--name`, `--status`, `--agent`, `--session`, `--user`,
`--draft` or `--published`; `aip runs <run_id> --json` prints the whole record.

Over the server's record:

- `aip audit` lists the audit queries and `aip audit <query>` runs one (which routes fired their
  confidence check, which scripts fail, which branches no run took, and more;
  [`docs/server-design.md`](server-design.md), Audit). `--save NAME --cypher ...` keeps a query
  of your own on the server.
- `aip export runs [name] -o FILE` writes the matching runs and the procedures they ran as one
  file that opens with no server ([`docs/language/queries.md`](language/queries.md) has queries
  over it).
- The console, the npm package `aip-console`, shows the same runs over the step graph.

The catalog commands work against the configured server: `aip search`, `aip list`, `aip publish
<folder>` (prints `name@revision`; `--draft` keeps it out of the catalog), `aip get <name>`
(writes the program folder back), `aip pull <name>` (caches the bundle so `aip run <name>` works
offline), `aip pin` and `aip retire`. `aip compile` and `aip fmt` need no server.

## Scripts

An `Execute` step runs its script on this machine, from the bundle's files unpacked under
`~/.aip/cache/<bundle id>/`. The script gets one JSON object on stdin (`state`, the keys the step
reads; `assets`, the files it `Use`s; `expects`, the keys it must produce) and prints one JSON
object on stdout. It runs with your environment plus `AIP_WORKDIR`, the run's working directory
(`--workdir`, kept in the run file, so a resume from elsewhere uses the same one), which is where
it reads and writes the run's files. Before the first script of a run, the machine is checked
against the procedure's `Requires`, and everything missing is named at once (`requires_unmet`).

One script may run for `aip config --script-timeout` seconds (`AIP_SCRIPT_TIMEOUT`; 300 by
default; `0` or `none` for no cap). That is the only cap on a script, wherever one runs: `run`,
`resume` and `runah` alike. It does not bound runah's model, which is capped per task by tool
calls and tokens instead. A script past the cap fails the step with `timeout`, which names the
setting and is resumable.

A script runs as you, with your credentials, your files and your network. Running a procedure
means trusting its scripts: read them (`aip get <name>` writes the folder; a bundle's files are in
the cache) before running a procedure you did not write, and above all one a model wrote.
`build_procedure` tries the draft it writes without running any of its scripts (the SDK's
`Client.run(..., scripts=False)`, which stops at the first `Execute` with `script_not_run`), and
the Studio shows a draft's scripts before it runs.

## The decision model

A `Decide` step puts its questions to the decision model and records its answers whole, each
with a confidence and probabilities that a route or an aggregation may check. The model is an
endpoint with the TypeSafe API shape: `aip config --decision-model-key KEY` is enough for
TypeSafe's, and `aip config --decision-model URL` points at another endpoint with the same shape.
A `Decide` is never answered by hand; a procedure that wants the agent to decide uses a
`Task_Agent`, as `billing-support-agent` does.

With no model configured, `aip run` warns on stderr before the first step when the procedure has
a `Decide` (the object it prints carries the same sentence as `warning`), and a run that reaches
one fails there, resumable:

```
$ aip run examples/language/billing-support -i '{"message": "I was charged twice"}'
{
  "error": "no_decision_model",
  "step": "triage",
  "message": "triage is a decision and no decision model is configured; a Decide is always answered by a decision model, so configure one: run `aip config --decision-model-key KEY`, and `aip config --decision-model URL` for an endpoint other than TypeSafe's; then `aip resume <run_id>` asks it",
  ...
  "resumable": true,
  ...
}
```

Configure the model, then `aip resume <run_id>` with no answers asks it. A model that fails
(unreachable, the key refused, a reply that is not an answer) fails the step as
`decision_model_failed`, retried the same way. `AIP_DECISION_MODEL_KEY=` set to nothing runs one
command with no model whatever the file says.

## Errors

Every error has `error` (the kind), `step`, `message`, `run_id` and `resumable`:

| kind | in short |
|---|---|
| `invalid_input` | the inputs, a target, a run id or a JSON argument cannot be used |
| `invalid_output` | a script's result or an answer does not fit the step's keys; an answer's pause stands |
| `no_branch` | a route read a value none of its branches names |
| `script_failed`, `timeout`, `requires_unmet` | a script could not run or finish |
| `no_decision_model`, `decision_model_failed` | a `Decide` had no model, or the model failed |
| `loop_cap` | a loop ran out of passes; not resumable |
| `not_paused` | `resume` on a run with nothing to answer or retry |
| `server` | anything else |

The extra keys of each, and every example, are in [`docs/cli-json.md`](cli-json.md).

## Other ways in

The same runs, the same run files and the same record, from elsewhere:

- **An agent** reads the `aip` skill (`aip skill install` writes it into the agents on this
  machine) and uses `aip run` and `aip resume` itself; `skills/aip/SKILL.md` is what it is told.
- **Python**: `aip.Client` is the runtime as a library, and every command above is one of its
  calls ([`docs/sdk.md`](sdk.md)).
- **MCP**: `aip mcp` serves `search`, `describe`, `compile`, `run`, `resume`, `runah` and `pull`
  as tools, each answering with the object the command prints ([`docs/mcp.md`](mcp.md)).
- **A whole session**, from installing to two agents' runs side by side in the console, is
  [`docs/demo/local.md`](demo/local.md).
