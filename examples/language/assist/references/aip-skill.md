# The verbs assist has

Answer with `verb`, one of the six below, and `args`, a JSON object of its arguments. The step
after yours (`act`) carries it out through the aip client and shows you the outcome, a JSON
object whose `status` says what came of it. A verb it cannot carry out comes back as
`"status": "refused"` with a `message` saying why; nothing changed, and you choose again.

## search

`{"query": "what the procedure should do", "limit": 8}` (limit optional)

Searches the published catalog. Answers `{"status": "found", "hits": [...]}`: each hit is a
procedure's name (with its revision), what it does, when to use it, and its inputs with their
types.

## runs

`{}`, or `{"run_id": "..."}`

With no arguments, this session's runs: `{"status": "listed", "runs": [{"run_id", "procedure",
"status"}]}`, newest first. With a `run_id`, that run's record: its `status`, and its `result`,
`pause` or `error`.

## run

`{"procedure": "name", "inputs": {...}}`

Starts a procedure: a published name (`name`, or `name@revision`), or a folder under the working
directory holding a `procedure.aip`. `inputs` is the object of its Start inputs: every input the
catalog lists for it, each of its type, nothing else (an input with nothing to give is `""`).
Answers where the run stopped:

- `{"status": "done", "run_id", "procedure", "result": {...}}`: the run reached its end.
- `{"status": "paused", "run_id", "procedure", "step", "hint", "tasks": [...]}`: the run waits
  for an answer. Each task has its `index`, the `prompt` to do, the `state` it reads, its
  `references` with their `text`, `answer_with` (the keys and their types) and `labels` (the
  values a `choice` key may take). Answer it with `resume`.
- `{"status": "failed", "run_id", "error", "step", "message", "resumable"}`: the run stopped on
  an error.

`assist` itself is refused.

## resume

`{"run_id": "...", "answers": {...}}`

Answers a paused run, every task of the pause at once: for one task, the answer object itself,
with exactly the keys of its `answer_with` (`{"answers": {"reply": "..."}}`); for several, an
object keyed by task index (`{"answers": {"0": {...}, "1": {...}}}`). A `true_or_false` key is
`true` or `false`, a `choice` key one of its labels, an `object` key a JSON object, a `list` key a
JSON array. Answers as `run` does. An answer that does not fit comes back as `"status":
"refused"` naming what is wrong, and the pause stands: correct it and resume again.

With no `answers`, retries the step a failed run stopped at, when its error is `resumable`.

## publish

`{"path": "folder"}`, or `{"path": "folder", "draft": true}`

Publishes a procedure folder under the working directory (one `build_procedure` wrote) to the
catalog under the name in its `procedure.aip`, so `search` finds it and `run` takes the name.
Answers `{"status": "published", "name", "revision", "run_it_as"}`. A name the catalog already
has is refused: assist never publishes over one. Then publish it as a draft (`"draft": true`),
which keeps it out of the catalog, and run it by its folder (`run_it_as`).

## finish

`{}`

Ends assist, with `done` true and `note` the result or the question for the person.
