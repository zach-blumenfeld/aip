# Local demo: Claude Code and Codex

One machine, two agents, one record. Claude Code writes a procedure with `make_procedure` and
runs it; Codex runs the same procedure; the console shows both runs, and the history is filtered
by agent and by session.

The outputs below are from the run of 2026-11-09 on a Mac, from a clean `aip config`. Run ids,
times and bundle ids will differ on yours. Long JSON is cut where marked `...`. That run kept
the maintainer's own config and store out of it (`AIP_CONFIG`, `AIP_LOCAL_PORT` and
`AIP_LOCAL_DATA` pointed at a scratch directory), so its paths and port are written here as a
first-time user sees them: `~/.config/aip/config.json`, port 8247, the default store.

## 0. Install

```sh
curl -LsSf https://raw.githubusercontent.com/zach-blumenfeld/aip/main/install.sh | sh
aip --version
```

```
aip 0.9.0 language 0.9
```

The run recorded here used this repository's checkout (`uv run aip`), because 0.9 is not on PyPI
yet; `uv sync` installs Relate (`relate-db`) with the rest.

## 1. Configure

A clean config records nothing and has no decision model:

```sh
aip config
```

```
server: none (runs are not recorded; run `aip config server local` to record runs on this machine, or `aip config server URL` for a server elsewhere)
decision model: none (a Decide fails the run with no_decision_model; run `aip config --decision-model-key KEY`, and `aip config --decision-model URL` for an endpoint other than TypeSafe's)
batch: 10
```

Record runs on this machine, and give the decision model its key:

```sh
aip config server local
aip config --decision-model-key "$TYPESAFE_API_KEY"
```

```
wrote /Users/you/.config/aip/config.json
server: local  http://127.0.0.1:8247, started when a command needs it; its store is /Users/you/.local/share/aip/server/store.rl  (from /Users/you/.config/aip/config.json)
decision model: https://api.typesafe.ai  (TypeSafe's, the default)  key: set  (from /Users/you/.config/aip/config.json)
batch: 10
```

Install the skill into both agents:

```sh
aip skill install claude-code
aip skill install codex
```

Each prints the folder it wrote. The recorded run wrote to a scratch directory instead,
`aip skill install --path DIR`, which printed `installed aip -> DIR/aip  (DIR)`.

The first command that needs the server starts it. The catalog already holds `make_procedure`:

```sh
aip list
```

```
make_procedure  @1  1 revision(s)  Build an AIP procedure from a description: write its program folder, compile it, and revise it until it compiles.
```

## 2. Claude Code makes `dynamic_policy`

Each agent says who it is through the environment it starts in. `aip` records `AIP_AGENT` and
`AIP_SESSION` on every run the agent makes:

```sh
mkdir -p ~/aip-demo && cd ~/aip-demo
AIP_AGENT=claude-code AIP_SESSION=demo-cc-1 claude
```

Ask it:

> Use aip to make a procedure called dynamic_policy. Do a task the requester describes, checked
> against the policies the requester supplies. Inputs: the task (a string) and the policies (a
> list of strings). The agent does the task. Then, in a loop of at most 3 rounds: the decision
> model checks the work against each policy separately, one true-or-false question per policy,
> batched; an aggregation says whether every policy holds with confidence above 0.7; if so the
> loop ends, otherwise the agent fixes the work and the loop goes round. Fail if it still does
> not hold after 3 rounds. The result is the work and the verdict for every policy. Then publish
> it.

The skill sends the agent to `make_procedure`. What it runs:

```sh
aip search "write a new procedure"
```

```
make_procedure@1  score 8.627  Build an AIP procedure from a description: write its program folder, compile it, and revise it until it compiles.
```

```sh
aip run make_procedure --inputs '{"name": "dynamic_policy", "description": "Do a task the requester describes, ...", "materials": ""}'
```

```json
{
  "paused": "task",
  "step": "write",
  "tasks": [
    {
      "index": 0,
      "prompt": "# Write an AIP procedure\n\nWrite the program folder of a procedure called `dynamic_policy`. ...",
      "answer_with": {"path": "string"},
      ...
    }
  ],
  "hint": "answer with {\"path\": <string>}",
  "run_id": "84dff96178a04316",
  "recorded": true
}
```

The agent writes `dynamic_policy/procedure.aip`, `assets/task.md` and `assets/fix.md`, then
answers with the folder. The `compile` step runs the compiler; it compiled first time, so the
loop ended before `fix`:

```sh
aip resume 84dff96178a04316 --answers '{"path": "/Users/you/aip-demo/dynamic_policy"}'
```

```json
{
  "done": true,
  "result": {
    "path": "/Users/you/aip-demo/dynamic_policy",
    "bundle_id": "36a7ea858e415f1b96ace76d3ee32e248b65a3288ac7dfde6ba88ab4462d389f",
    "diagnostics": []
  },
  "run_id": "84dff96178a04316",
  "recorded": true
}
```

```sh
aip publish dynamic_policy
```

```
dynamic_policy@1  bundle 36a7ea858e41
```

## 3. Claude Code runs it

> Run dynamic_policy: write a two-sentence reply to a customer who was charged twice for their
> March invoice. Policies: the reply apologises for the double charge; the reply says the
> duplicate charge will be refunded within 5 business days; the reply names the invoice month.

```sh
aip run dynamic_policy --inputs '{"task": "Write a two-sentence reply to a customer who was charged twice for their March invoice.", "policies": ["The reply apologises for the double charge.", "The reply says the duplicate charge will be refunded within 5 business days.", "The reply names the invoice month."]}'
```

It pauses on `draft`, a task for the agent (`"paused": "task"`, `"step": "draft"`, run
`2d28eefed04749dd`). The agent answers with its draft; the decision model checks the three
policies in one call, every verdict holds, and the run is done:

```sh
aip resume 2d28eefed04749dd --answers '{"work": "We are sorry you were charged twice for your March invoice. The duplicate charge will be refunded to your original payment method within 5 business days."}'
```

```json
{
  "done": true,
  "result": {
    "work": "We are sorry you were charged twice for your March invoice. The duplicate charge will be refunded to your original payment method within 5 business days.",
    "verdicts": [
      {"follows": {"value": true, "confidence": 0.98, "noul": 0.99}},
      {"follows": {"value": true, "confidence": 0.96, "noul": 0.98}},
      {"follows": {"value": true, "confidence": 0.96, "noul": 0.98}}
    ]
  },
  "run_id": "2d28eefed04749dd",
  "recorded": true
}
```

```sh
aip runs 2d28eefed04749dd
```

```
run 2d28eefed04749dd  dynamic_policy@1  done
  bundle    36a7ea858e415f1b96ace76d3ee32e248b65a3288ac7dfde6ba88ab4462d389f
  target    dynamic_policy
  agent     claude-code   session demo-cc-1   user -
  started   2026-11-10T07:36:48.031+00:00   finished 2026-11-10T07:36:50.107+00:00

STEP             KIND        PASS                      WHEN          +MS  WHAT
start            Start       -                         07:36:48.031    0  task, policies
draft            Task_Agent  -                         07:36:49.939    1  answered by claude-code after 1.9s -> work
check            Decide      revise 0 / each_policy 0  07:36:50.106  166  follows=true 0.98  (by jev-1.14.0, one call for 3 passes)
check            Decide      revise 0 / each_policy 1  07:36:50.106  166  follows=true 0.96  (by jev-1.14.0, one call for 3 passes)
check            Decide      revise 0 / each_policy 2  07:36:50.106  166  follows=true 0.96  (by jev-1.14.0, one call for 3 passes)
each_policy      For         revise 0                  07:36:50.106       exit: items, 3 passes
summarize_check  Aggregate   revise 0                  07:36:50.107    0  all_hold=true
revise           Loop        -                         07:36:50.107       exit: until at summarize_check, 1 pass
end              End         -                         07:36:50.107    0  work, verdicts
```

**A policy the model cannot be sure of fails the run.** The first try of this demo had the
policy "Do not offer any discount or credit." The model judged it followed every time, but
with confidence 0.04, then 0.3, then 0.36. That is under the 0.7 the aggregation asks for, so
every pass went to `fix`, and the third ended the run with
`{"error": "loop_cap", "message": "revise ran 3 passes without its condition holding (At_Most 3, Else_Fail)"}`
(run `b06300fc3b934eb0`). The record keeps that run too. A policy written as something the work
does, not something it leaves out, is one the model can check.

## 4. The console

```sh
npx aip-console
```

```
aip-console: http://localhost:4280/  (server http://127.0.0.1:8247; aip 0.9.0; workdir /Users/you/aip-demo)
```

- `#/p/dynamic_policy`: the procedure, its step graph (the `revise` loop and the `For` inside it as
  nodes, each with its body beside it), its inputs and result.
- `#/runs`: the history, newest first. Each run shows its agent, session and user.
- `#/runs/2d28eefed04749dd`: the run. Who ran it, how long the model took (166 ms) and how long the
  agent took (1.9 s), and the path it took through the graph (`each_policy` 3 passes, `revise`
  1 pass).

## 5. Codex runs it again

```sh
cd ~/aip-demo
AIP_AGENT=codex AIP_SESSION=demo-cx-1 codex
```

> Run dynamic_policy: write a two-sentence reply to a customer whose order arrived a week late.
> Policies: the reply apologises for the delay; the reply says a replacement shipping estimate
> will follow by email; the reply thanks the customer.

**Not yet run.** Codex was not installed on the machine that recorded this page (see the plan's
D1 comment). Its commands are the same `aip run dynamic_policy` and `aip resume` as section 3,
recorded with `agent codex` and `session demo-cx-1`.

## 6. The history, filtered

```sh
aip runs
```

```
RUN               NAME              STATUS  AGENT        STARTED                        UPDATED
2d28eefed04749dd  dynamic_policy@1  done    claude-code  2026-11-10T07:36:48.031+00:00  2026-11-10T07:36:50.107+00:00
b06300fc3b934eb0  dynamic_policy@1  failed  claude-code  2026-11-10T07:36:30.725+00:00  2026-11-10T07:36:45.155+00:00
84dff96178a04316  make_procedure@1  done    claude-code  2026-11-10T07:36:03.725+00:00  2026-11-10T07:36:26.081+00:00
```

```sh
aip runs --agent claude-code --session demo-cc-1 --name dynamic_policy
```

```
RUN               NAME              STATUS  AGENT        STARTED                        UPDATED
2d28eefed04749dd  dynamic_policy@1  done    claude-code  2026-11-10T07:36:48.031+00:00  2026-11-10T07:36:50.107+00:00
b06300fc3b934eb0  dynamic_policy@1  failed  claude-code  2026-11-10T07:36:30.725+00:00  2026-11-10T07:36:45.155+00:00
```

```sh
aip runs --agent codex
```

Not yet run (section 5). In the console the same filters are the `agent` and `session` fields on
`#/runs`, and clicking an agent or a session in the table filters by it.
