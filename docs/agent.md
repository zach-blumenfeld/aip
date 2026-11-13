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

All of it is `src/aip/agent.py`, and this is the whole file:

```python
"""aip agent: a chat model outside the run, answering the pauses of assist. This is all of it."""
from aip.chat import ChatError, continuation, message_for, parse, reason, refused, work_of
from aip.sdk import Paused, RunError

AGENT, ASSIST, MAX_REFUSALS = "agent", "assist", 3


def agent(client, chat, text, session, on_step=None, procedure=ASSIST):
    r = client.run(procedure, inputs(client, session, text), agent=AGENT, session=session, on_step=on_step)
    while isinstance(r, Paused):
        r, gave_up = answer(client, chat, r, AGENT, session, on_step)
        if gave_up:
            break                                                    # left paused, for whoever answers next
    return r


def answer(client, chat, paused, agent, session, on_step=None):
    """One pause: the model's answer resumes the run, a refused one goes back to it; (result, why it gave up)."""
    msg = message_for(client, paused)
    for _ in range(MAX_REFUSALS + 1):
        try:
            reply = chat(msg)
            return client.resume(paused, parse(reply), agent=agent, session=session, on_step=on_step,
                                 work=work_of(reply, paused)), None
        except ChatError as e:
            return paused, f"the model's endpoint failed: {e}"
        except (ValueError, RunError) as e:
            if getattr(e, "stopped", False):
                raise                                                # the answer went in; a later step failed the run
            msg, why = msg + refused(reply, e), reason(e)
    return paused, f"the model's answer at {paused.step} was refused {MAX_REFUSALS + 1} times; the last time: {why}"


def inputs(client, session, text):
    """What it asked last time and the person's reply, from the session's newest assist run in the record."""
    last = client.runs(name=ASSIST, session=session, limit=1)
    return continuation(client.run_record(last[0].run_id) if last else None, text)
```

`agent` runs `assist` and answers its pauses until it is done; `answer` is one pause; `inputs` is
the session, read from the record. Each pause is one call to `chat`, no tools. The plumbing is in
`aip.chat`, beside the chat client, one function each: `message_for` (the pause as it comes: each
task's prompt, the state it reads, the text of every file it references from the run's bundle,
the keys to answer with and their labels, after the system text), `parse` (the JSON object the
reply holds), `refused` (the reply and the correction that goes back with the reason), `reason`,
`work_of` (the model's id, its tokens and the seconds the call took, kept on the task's entry as
`work: "reported"`, as `aip resume --work` keeps an agent's own account) and `continuation`. The
answer goes in through `resume`, which checks it as it checks anyone's; a refusal goes back to the
model, up to three times, then the run is left paused as it is, for whoever answers next.

```
aip config agent --model-key KEY          # Anthropic's endpoint and claude-opus-5-5 by default
aip agent "count the lines mentioning refund in each .txt file in ./notes"
#   aip: session: agent-20261112-101500-3f2a (`export AIP_SESSION=agent-20261112-101500-3f2a` to continue it)
aip agent --session agent-20261112-101500-3f2a "the notes are in ./meeting-notes"   # your reply to its question
```

The command prints where `assist`'s run stopped as `aip run` prints it (`done` with its `result`,
whose `note` is the answer or the question; `paused` when an answer would not hold or the endpoint
failed; or the error object), with `session` added, and exits as `aip run` does. The session line
goes to stderr first. `--progress` prints the run's own step lines as they are written; the agent
adds none of its own. The model, endpoint and key come from `aip config agent` (`--model-uri`,
`--model-name`, `--model-key`; `AIP_AGENT_MODEL_URI`, `AIP_AGENT_MODEL_NAME`,
`AIP_AGENT_MODEL_KEY`); any endpoint with the OpenAI Chat Completions shape works.

The SDK's call is `Client.ask(text, session=None, on_step=None)`, which returns what `agent`
returns (`Done` or `Paused`; a run that fails raises `RunError`); `Client.chat()` is the configured
model, or `agent_chat` when the client was given one. The MCP server's tool is `agent`
(`{task, session?}`), for a caller that wants the whole task done by this machine's model rather
than answering each pause itself; it answers with the same object and the `session`.

## One pause of any run

`aip agent --answer RUN [--session ID] [--progress]` is the loop's body on its own, `answer`: the
model answers the pause run `RUN` waits at, with the same message and the same three retries, and
the run is resumed with it. It works on a run of any procedure, and prints what `aip resume`
prints (exit 0 for paused or done, 1 for an error); when no answer would hold, or the endpoint
failed, the run is left as it was and the paused object comes back with `gave_up`, the reason
(exit 1). With `--progress`, the model's calls are lines of their own, `{"event": "answer",
"step", "run_id", "tokens", "seconds"}`, then `refused` or `gave_up` with a `reason`, among the
run's step lines (`aip.chat.observed` wraps `chat` to say them). The answer is recorded as
`AIP_AGENT`'s (default `cli`) in `--session` or `AIP_SESSION`, with the model and what it spent.
The SDK's call is `Client.answer(run, agent=None, session=None)`, which returns the result the
resume came to and None, or the run's `Paused` and the reason.

This is how the console drives a run (its plan milestone C6): it runs `aip run`, and at every
pause but those at the steps a person was given, `aip agent --answer`; the Studio's person answers
`build_procedure`'s `ask_user`, and in the run console the user ticks the steps that are theirs.

## Sessions

A session is a conversation with the person, and the record is its memory: nothing is kept
anywhere else. The session id is `--session ID`, else `AIP_SESSION`, else a new one, which the
command prints with the line to export. `inputs` asks the record for the session's newest
`assist` run (`client.runs(name="assist", session=...)`): with none, `assist` starts on the text
as its task; with one, it starts again on that run's task, with `outcome` saying "You asked: <that
run's note>. The person answered: <the text>", so the model has its own question and the reply.

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
