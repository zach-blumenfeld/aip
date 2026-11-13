# `aip agent`

`aip agent "<task>"` does a task with the catalog's procedures. A chat model outside the run
drives the `assist` procedure: the procedure pauses, the model answers, the run carries on. AIP
does no orchestration and the runtime never calls a chat model; `aip agent` is a caller of the
runtime like Claude Code or a framework over MCP, and the record shows its answers as it shows
theirs, `answered_by: {"agent": "agent", "session": ...}`.

It replaced the run-ahead verb of A2 to R8 (plan aip#29, A3, 2026-11-12), which put the model
inside the run, one tool-using chat per task. Who answers a step then needed a flag (`--human`), a sentence matched in a prompt,
tools on every task, and depth and budgets for runs started from runs. With the model outside,
the question goes away: whoever drives the run answers its pauses.

## The harness

All of it is `src/aip/agent.py`, around these three lines:

```python
r = client.run("assist", {"task": task, "outcome": outcome}, agent="agent", session=session)
while isinstance(r, Paused):
    r = client.resume(r, answers=chat(r))       # one model call per pause, no tools
```

`chat` is one Chat Completions call (`aip.chat.ChatClient`). The message is the pause as it comes:
each task's prompt, the state it reads, the text of every file it references (from the run's
bundle), the keys to answer with and their labels. The model answers with one JSON object. The
answer goes in through `resume`, which checks it as it checks anyone's; a refusal goes back to the
model with the reason, up to three times, then the run is left paused as it is and the command
says so. The model's id, its tokens and the seconds the call took are kept on the task's entry
(`work: "reported"`, as `aip resume --work` keeps an agent's own account).

```
aip config agent --model-key KEY          # Anthropic's endpoint and claude-opus-5-5 by default
aip agent "count the lines mentioning refund in each .txt file in ./notes"
aip agent "the notes are in ./meeting-notes"     # the same shell: your reply to its question
aip agent --new "another task"                   # a new session
aip agent --session ID "..."                     # a session by its id
```

`--json` prints the outcome as one object: `session`, `status` (`done`; `paused` when an answer
would not hold or the endpoint failed, with `reason` and the `pause`; `failed` with the `error`),
`note`, `result`, `run_id`, `runs` (every run this call started), `model_calls` and `tokens`.
`--progress` prints a JSON line per step and per model call as they happen. The model, endpoint
and key come from `aip config agent` (`--model-uri`, `--model-name`, `--model-key`;
`AIP_AGENT_MODEL_URI`, `AIP_AGENT_MODEL_NAME`, `AIP_AGENT_MODEL_KEY`); any endpoint with the
OpenAI Chat Completions shape works.

The SDK's call is `Client.ask(text, session=None, new=False)`, which returns the same outcome; the
MCP server's tool is `agent` (`{task, session?}`), for a caller that wants the whole task done by
this machine's model rather than answering each pause itself.

## Sessions

A session is a conversation with the person. The first `aip agent` in a shell starts one and
runs `assist` on the task. Each later call in the same shell runs `assist` again on the same
task, with `outcome` saying "You asked: <the last run's note>. The person answered: <the text>",
so the model has its own question and the reply. The shell's current session is kept under
`~/.aip/agent/` (`shells/<the shell's process id>`, and `sessions/<id>.json` with the task, the
runs and the last note); `--new` starts another and `--session ID` picks one.

Every run `aip agent` starts, and every run `assist` starts beneath it, carries `agent: agent` and
the session: the runtime hands both to `assist`'s scripts (`AIP_AGENT`, `AIP_SESSION`), and the
client in `act` uses them. So `aip runs --session ID` lists all of it, and `aip runs <run_id>`
shows each step and who answered it.

## What `assist` may do

`examples/language/assist`, shipped built-in:

```
Start { task, outcome }
Execute search       the catalog's hits for the task, and this session's runs -> catalog
Loop work Until done, At_Most 50, Else_Exit {
  Task_Agent plan    Read task, catalog, outcome; Use references/aip-skill.md
                     Produce verb: choice [search, runs, run, resume, publish, finish],
                             args: object, note: string, done: true_or_false
  Execute act        scripts/act.py: one verb, no model -> outcome;  Continue
}
End { Read note }
```

`plan` is the model's one step; `act` is the allow-list, six verbs and nothing else: `search` and
`runs` read the catalog and the record; `run` and `resume` start or continue any procedure,
`build_procedure` included, which is how `assist` makes a procedure; `publish` puts a folder in
the catalog under a new name, or as a draft (a name the catalog has is refused); `finish` ends.
There is no verb to retire, pin or publish over a name, and `assist` never runs itself. A child
run's pause comes back as the outcome, with its tasks and their references' text, and the next
`plan` answers it with `resume`: one flat loop, no run started from a run's model, no depth.
`references/aip-skill.md` is the page that tells `plan` the verbs and their JSON. The prompt
(`assets/plan.md`) says: search first; never invent data to make a run succeed; when only the
person can go on, finish with the question.

A child runs under the script cap like any script (`aip config --script-timeout`, 300 s): `act`
waits for nothing longer.

## No tools

The model answers with JSON and nothing else: there is no working directory for it, no
`read_file`, no `write_file`. Everything it can do is a step. A procedure that needs files read
hands their text in its state (`build_procedure`'s `prepare` reads the documents; `compile`
hands back the folder as it is); one that needs files written has an `Execute` that writes what
the model answered (`build_procedure`'s `draft` answers `drafted: {path: text}` and `write`
writes it; `fix` answers `repairs` and `apply` writes them; `edit_procedure` likewise). Its
`ask_user` stays a plain `Task_Agent`: under `aip agent` the model answers it from the brief, and
a person driving the run answers it themselves.
