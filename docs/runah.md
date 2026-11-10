# runah: run ahead

A run pauses at every `Task_Agent` step for whoever runs it: an agent reads the task, does it,
and answers with `aip resume`. `aip runah` is the runtime taking those turns itself: each task
becomes one short chat with a model that has a few tools, its last message is the answer, and
the run carries on. The procedure is the plan, and the run is the memory between chats. There
is no agent framework and no MCP inside; outside agents still reach `aip` over MCP
(`docs/mcp.md`) and answer their own pauses with `run` and `resume`.

"runah" reads as *run ahead*. It reads as other things too (run as host, run as harness, run as
human, run and halt, run until a human, run unattended and ask humans), and each says part of
it; either way, this is what it does.

```
aip config runah --model-key KEY                  # Anthropic's endpoint and claude-opus-5-5 by default
aip runah build_procedure -i '{"brief": "...", "documents": "docs", "out": "refund-handling", "title": ""}' \
    --human ask_user
aip runah <run_id> --answers '{"answers": "1. ..."}'
```

aip calls no chat model anywhere else. `aip run` and `aip resume` pause at every `Task_Agent`,
and a `Decide` asks the decision model, as always.

## What it does

1. Before anything runs, it refuses when no model key is configured, naming the config line.
2. Scripts, `Decide`, routes and loops run exactly as `aip run` runs them.
3. At a `Task_Agent` pause: a step named in `--human` stops it, and it prints the `paused`
   object. Otherwise each task of the pause is one chat; the model answers with the five tools
   below, confined to the working directory; the answer is checked as `aip resume` checks one;
   a refusal goes back to the model, up to three times; then the answers go in and the run
   carries on.
4. It stops and prints at a human step, at the end, at an error, or when the model gives up,
   with the reason, in the same `paused`, `done` and `error` objects as `aip run`
   (`docs/cli-json.md`). A pause it did not answer carries `answerer: {"answered": false,
   "step", "reason", ...}`.
5. `run`, `resume` and `runah` mix on one run: `aip run` a procedure, answer its first pause
   yourself with `aip resume`, then `aip runah <run_id>` to have the model carry on, or the
   other way round.

```
aip runah <folder | bundle.rl | name[@rev]> [-i JSON] [--human STEP,STEP] [--progress] [--agent A] [--session S] [--workdir DIR]
aip runah <run_id> [--answers JSON] [--human STEP,STEP] [--progress]
```

Given a run id, `--answers` go into its standing pause first; with none, the model answers the
pause that stands (a human step's too: you asked it to carry on), or a failed step is retried.
`--agent` and `--session` are who launched the run, as on `aip run`: the run's identity stays
`cli`, `studio` or whoever it is, and each task the model answers says `runah` answered it.

The SDK is `Client.runah(target_or_run_id, inputs=..., answers=..., human=[...])` and the MCP
tool is `runah` (`docs/sdk.md`, `docs/mcp.md`). The console's Studio runs `build_procedure` and
`edit_procedure` through this verb with `--human ask_user`.

## The model

One shape, no vendor: an endpoint that serves OpenAI Chat Completions with function calling
(`POST {URL}/chat/completions`). OpenAI, Anthropic (`https://api.anthropic.com/v1`), Gemini
(`https://generativelanguage.googleapis.com/v1beta/openai`), Azure's v1 surface, Groq, Mistral,
OpenRouter, Ollama and vLLM all serve it. The default is **Anthropic's endpoint with
`claude-opus-5-5`**, so the first run needs only the key. The name is pinned, not a floating
alias, so two runs never record one name for two models.

| Setting | `aip config runah` | Environment | Default |
|---|---|---|---|
| endpoint | `--model-uri URL` | `AIP_RUNAH_MODEL_URI` | `https://api.anthropic.com/v1` |
| model | `--model-name NAME` | `AIP_RUNAH_MODEL_NAME` | `claude-opus-5-5` |
| key | `--model-key KEY` (`""` forgets it) | `AIP_RUNAH_MODEL_KEY` | none: `aip runah` is refused until one is set |
| tool calls per task | `--max-tool-calls-per-task N` | | 40 |
| tokens per task | `--max-tokens-per-task N` | | 500000 (prompt and completion, over every call of the chat) |

The environment wins over the file, and the file over the default. Human steps are per
procedure, so there is no config or environment for them: `--human` on the command only.
`aip config` and `aip config runah` print the block, with the key masked:

```
runah:  (from /Users/you/.config/aip/config.json)
  model uri:   https://api.anthropic.com/v1
  model name:  claude-opus-5-5
  model key:   set
  per task:    at most 40 tool calls, 500000 tokens
```

The client is one module (`src/aip/model/answerer/chat.py`, httpx): no provider SDK, no
streaming. A 429 or a 5xx is tried again three times, with a pause that doubles.

The caps here bound the model's turns. Scripts are bounded on their own, wherever they run, by
`aip config --script-timeout N` (`AIP_SCRIPT_TIMEOUT`, 300 seconds by default).

## One task, one chat

- **System prompt**: the rules of the loop (do this task only, the tools and where they reach,
  answer with one JSON object of the `Produce` keys, a refusal will say why), then the language
  on one page (`skills/aip/references/language.md`), since the tasks that most need a model are
  the ones that read and write procedures.
- **User message**: the task as the pause carries it: the step, the loop pass, the prompt, the
  state it reads as JSON, its references (as `bundle:` paths), and the answer's shape
  (`answer_with`, `labels`, and the pause's one-line hint).
- **Tools**, run by `aip`, confined to the run's working directory (`--workdir`): `read_file`,
  `list_files`, `search` (a regular expression over file contents), `write_file`, and
  `compile` (`aip compile --check --json` of a folder, in process). A path that resolves outside
  the working directory, `..` and symbolic links included, is refused. The procedure's own
  files, its assets and references, are readable as `bundle:<path>` and are never written. A tool
  that cannot do what it is asked answers `error: ...`, which goes back to the model as its
  result. No tool runs a command.
- **The answer** is the first reply with no tool call: one JSON object (a fenced block, or one
  object inside prose, is taken too). It is checked exactly as `aip resume` checks an answer. A
  refusal goes back to the model with the reasons, up to three times; a fourth bad answer gives
  the task up.
- **Caps**: the tool calls and the tokens above. Reaching either gives the task up, as does an
  endpoint that keeps failing.

A pause with several tasks (a batched `For`) is answered in task order, each its own chat, and
the answers go in as one resume. A task given up leaves the whole pause standing: a resume
answers every task at once, so the answers made before it are not kept.

A marker for human steps in the language itself (`Task_Human`, or a word on `Task_Agent`) is
plan open item 17, undecided: until then a human step is a `Task_Agent` whose description says
so, named by `--human`.

## The record

A task the model answered is recorded like any other, with `answered_by: {"agent": "runah",
"model": ID}`, where `ID` is the model the endpoint says answered (the reply's `model`), not the
name that was asked for, and with what answering took, marked `work: "observed"`: `tool_calls`
(each `name`, an `args` summary that names the path or the pattern and never a written file's
content, and `seconds`), `tokens` (`prompt`, `completion`, `total`), `model_seconds` (the calls
alone) and `refusals`. The entry's `seconds` is the whole chat, tools included. `aip runs <id>`
prints `answered by runah (ID), observed: 3 tool calls (read_file 2, compile 1), 18200 tokens`;
the server stores `work`, the count of tool calls and the total tokens on the `Entry` node
(`docs/server-design.md`); and `--progress` prints a line per tool call as it happens
(`{"event": "tool", "step", "task", "tool", "args", "seconds"}`) and one per refused answer, so
a console can show "reading policy.md" while the model works.

An outside agent can say what its own answers took: `aip resume <run> --answers JSON --work
'{"model": "...", "tool_calls": 3, "tokens": 12000, "seconds": 40}'` (SDK `work=`, MCP `resume`'s
`work`). The entry keeps it marked `work: "reported"`, beside runah's `observed`: aip saw the one
and was told the other. `aip runs <id>` and the audit query `agent-work` read both and say which.

## The two procedures it was made for

Both ship as built-ins beside `make_procedure` (every server publishes them on its first start;
`aip upgrade` publishes them to one that has not) and are in `examples/language/`.

- **`build_procedure`** (`brief`, `documents`, `out`, `title`): a script lists the documents
  and tidies the name the requester gave; the model reads the documents into notes; a `clarify`
  loop has the model extract the rules and the questions they leave open, and a person
  (`ask_user`, run with `--human ask_user`) answer them, at most two rounds; the model names the
  procedure (from `title`, or from the brief's subject when `title` is empty), drafts the folder
  at `out` and checks it with `compile`; the compile-and-fix loop runs until it compiles; a
  trial runs the new procedure once on example inputs, answering nothing and **running none of
  its scripts**; the model reviews it against the rules and says, per script, what it touches
  outside the working directory and which credentials it uses. The result is the folder, the
  procedure's name, its bundle id, the trial's report and the review. No decision model is needed.
- **`edit_procedure`** (`folder`, `instruction`, `documents`): a script keeps the folder as it
  is; the model rewrites it; the compile-and-fix loop; a script writes the unified diff. The
  result is the diff, the bundle id and what the model says it changed, with what each script it
  wrote or changed touches outside the working directory.

### A trial runs no script

The scripts in a drafted procedure were written by a model, and nobody has read them yet. The
trial is `Client.run(..., scripts=False)`: `Decide`, routes and loops run and a `Task_Agent`
pauses as usual, but the run stops at the first `Execute`, before its script starts, with
`{"error": "script_not_run", "step": ..., "script": ..., "message": "<step> would run
scripts/<file>; this run executes no script"}`. Such a run is not recorded and cannot be
resumed. There is no CLI flag for it until someone asks. The trial gives up after 30 seconds
of its own, and its report names where it stopped and lists every script the draft carries with
what each says it does, so the person who reads the review knows what would run before
anything does.

## Not here

A Claude Code or Codex backend (they use `run` and `resume` themselves; a `run-as X` form can be
added later), streaming, images.
