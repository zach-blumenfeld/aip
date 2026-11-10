# The answerer: an agent made of Chat Completions and AIP

A run pauses at every `Task_Agent` step for whoever runs it: an agent reads the task, does it,
and answers with `aip resume`. The answerer is the runtime doing that itself: with
`--answer-with model`, each task becomes one short chat with a model that has a few tools, and
its last message is the answer. The procedure is the plan, and the run is the memory between
chats. There is no agent framework and no MCP inside; outside agents still reach `aip` over MCP
(`docs/mcp.md`).

```
aip config --agent-model-key KEY                  # Anthropic's endpoint and claude-opus-5-5 by default
aip run build_procedure -i '{"brief": "...", "documents": "docs", "out": "refund-handling"}' \
    --answer-with model --human ask_user
aip resume <run_id> --answers '{"answers": "1. ..."}' --answer-with model
```

## The model

One shape, no vendor: an endpoint that serves OpenAI Chat Completions with function calling
(`POST {URL}/chat/completions`). OpenAI, Anthropic (`https://api.anthropic.com/v1`), Gemini
(`https://generativelanguage.googleapis.com/v1beta/openai`), Azure's v1 surface, Groq, Mistral,
OpenRouter, Ollama and vLLM all serve it. The default is **Anthropic's endpoint with
`claude-opus-5-5`**, so the first run needs only the key:

| Setting | `aip config` | Environment | Default |
|---|---|---|---|
| endpoint | `--agent-model URL` | `AIP_AGENT_MODEL` | `https://api.anthropic.com/v1` |
| key | `--agent-model-key KEY` | `AIP_AGENT_MODEL_KEY` | none: `--answer-with model` is refused until one is set |
| model | `--agent-model-name NAME` | `AIP_AGENT_MODEL_NAME` | `claude-opus-5-5` |
| tool calls per task | `--agent-model-max-tool-calls N` | | 40 |
| tokens per task | `--agent-model-max-tokens N` | | 500000 (prompt and completion, over every call of the chat) |

`aip config` prints the endpoint, the model, whether a key is set (never the key) and the caps.
The client is one module (`src/aip/model/answerer/chat.py`, httpx): no provider SDK, no
streaming. A 429 or a 5xx is tried again three times, with a pause that doubles.

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
  result.
- **The answer** is the first reply with no tool call: one JSON object (a fenced block, or one
  object inside prose, is taken too). It is checked exactly as `aip resume` checks an answer. A
  refusal goes back to the model with the reasons, up to three times; a fourth bad answer gives
  the task up.
- **Caps**: the tool calls and the tokens above. Reaching either gives the task up, as does an
  endpoint that keeps failing.

A pause with several tasks (a batched `For`) is answered in task order, each its own chat, and
the answers go in as one resume. A task given up leaves the whole pause standing: a resume
answers every task at once, so the answers made before it are not kept.

## Who answers what

The answerer answers every `Task_Agent` except the steps named by `--human STEP[,STEP]`
(`AIP_HUMAN_STEPS`), which pause as before; the run file keeps them, so a resume does not have
to repeat them. A pause the model did not answer, at a human step or after giving up, carries
`answerer: {"answered": false, "step", "reason", ...}` in the CLI's paused object
(`docs/cli-json.md`). Answer it with `aip resume <run> --answers JSON` as always; add
`--answer-with model` to have the model answer the pauses after it, or give `--answer-with model`
and no answers to have it try the standing pause again. `--answer-with` is per command
(`AIP_ANSWER_WITH`), and `--answer-with none` turns it off.

A marker for human steps in the language itself (`Task_Human`, or a word on `Task_Agent`) is
plan open item 17, undecided: until then a human step is a `Task_Agent` whose description says
so, named by `--human`.

## The record

A task the model answered is recorded like any other, with `answered_by: {"agent": "model",
"model": NAME}` and what answering took: `tool_calls` (each `name`, an `args` summary that names
the path or the pattern and never a written file's content, and `seconds`), `tokens` (`prompt`,
`completion`, `total`), `model_seconds` (the calls alone) and `refusals`. The entry's `seconds`
is the whole chat, tools included. `aip runs <id>` says `answered by model`, the server stores
the count of tool calls and the total tokens on the `Entry` node (`docs/server-design.md`), and
`--progress` prints a line per tool call as it happens (`{"event": "tool", "step", "task",
"tool", "args", "seconds"}`) and one per refused answer, so a console can show "reading
policy.md" while the model works.

## The two procedures it was made for

Both ship as built-ins beside `make_procedure` (every server publishes them on its first start;
`aip upgrade` publishes them to one that has not) and are in `examples/language/`.

- **`build_procedure`** (`brief`, `documents`, `out`): a script lists the documents; the model
  reads them into notes; a `clarify` loop has the model extract the rules and the questions they
  leave open, and a person (`ask_user`, run with `--human ask_user`) answer them, at most two
  rounds; the model drafts the folder and checks it with `compile`; the compile-and-fix loop
  runs until it compiles; a script runs the new procedure once on example inputs, answering
  nothing; the model reviews it against the rules. The result is the folder, its bundle id, the
  trial's report and the review. No decision model is needed.
- **`edit_procedure`** (`folder`, `instruction`, `documents`): a script keeps the folder as it
  is; the model rewrites it; the compile-and-fix loop; a script writes the unified diff. The
  result is the diff, the bundle id and what the model says it changed.

## Not here

The console's chat pane (C4 builds on this), a Claude Code backend (Claude Code drives
`make_procedure` by itself, D1), streaming, images.
