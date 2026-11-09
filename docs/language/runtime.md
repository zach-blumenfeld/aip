# Runtime requirements

What a runtime must do to run a bundle, stated as requirements on the runtime rather than as
a description of any one implementation. The language spec (`docs/language/spec.md`) says what a
procedure means; this page says what running one entails.

## Loading

- A runtime accepts a program directory or a bundle. A directory is compiled in memory first,
  and a compile error stops the run before any step. A bundle is opened, its id and language
  version checked, and never written to.
- The bundle is loaded into an in-memory Relate database once, from a path or a URL, and each
  step is read with a Cypher query as the run reaches it. The same queries run against a
  server's graph, so a server can run a procedure from its own store.
- Scripts and assets are unpacked once per bundle id into a cache and executions launch from
  there, so the same bundle on the same machine does not unpack twice. The reference runtime
  keeps them under `~/.aip/cache/<bundle id>/` (`AIP_HOME` moves it), written whole and moved
  into place, so the directory is complete or absent.

## The state

- One state per run: a set of named, typed keys, as the spec's section 2.3 defines it. A step
  sees only the keys its `Read` names, with the declared types checked before it runs.
- A step's `Produce` keys are checked on its result and added to the state. A missing key or
  a wrong type fails the step; the runtime does not fill in a value. One normalisation is
  allowed: a script or an agent may write an answer-typed key as the bare value (`true` for
  `passed: true_or_false`, a label for a `choice`, a level for a `score`), and the runtime stores
  it as `{"value": ...}`, which is also what the record keeps.
- A key is rebound when a loop pass writes it; every earlier value stays in the record.
- A decision writes its one key with one answer object per question, in the shape of 2.4. An
  answer given by hand has `value` and nothing else.
- The runtime's own keys: inside a body `index` is the pass's number, from 0, and after a loop
  `iterations` is how many passes ran, a pass ended by `Until` included. When a nested loop
  exits, `index` is the enclosing pass's again.

## Steps

- `Start`: the client supplies the inputs; the runtime checks them against the declared types.
- `Decide`: the runtime renders each question's instruction (`{key}` from the state), sends the
  step's `Read` keys as the thing to judge and the rendered questions to the decision model, and
  records the model's answers whole. An interpolated key is not sent as data unless `Read` names it. With no model configured, the step stops the run
  unless `Agent_Fallback true`, in which case the agent answers and the record says so.
- `Route`: the runtime reads one answer. With a `Confidence_Below` check, it reads the answer's
  `confidence` first and takes the check's branch when the confidence is below the bound. An
  answer with no confidence is let through when it was given by hand, by the agent under
  `Agent_Fallback` or in a `Task_Agent` (the record says `reason: hand`), and fires the check when
  it came from a script or an input (`reason: absent`); otherwise it takes the branch for `value`: `true` or `false` for a `true_or_false`,
  the label for a `choice`, and for a `score` the label of the level the value names (the
  branch lines are written with the question's labels, the value is the level's number). A
  value with no branch fails the step.
- `Aggregate`: for each aggregation, the runtime tests each answer in its source against the
  line's condition (`== value`, `!= value`, or `== true` for a bare `true_or_false`), takes the
  probability the model put on that condition from the answer's probabilities, and, when the
  line has `With Confidence_Above` and that probability is below it or absent, counts the
  answer as the value that fails the aggregation; then applies `All`, `Any` or `None`, and writes the one key
  with one answer per aggregation, each `{value}` and nothing else. It records each answer's
  resolution.
- `Execute`: the runtime checks the machine has what `Requires` names before the first
  `Execute` of a run, launches the script from the cache with one JSON object on stdin (the
  `Read` keys as `state`, the `Use` assets by stem, the next step's `Read` keys as `expects`),
  and takes the JSON object on stdout as the step's `Produce` keys. A non-zero exit fails the
  step. The runtime never performs a script's work by hand.
- `Task_Agent`: the runtime renders the prompt (`{key}` from `Read`, `{assets[stem]}` for
  `Use`) and hands the task to the agent, which produces the `Produce` keys. A `Decide` with no
  model, or whose model failed, and `Agent_Fallback true` is handed to the agent the same way,
  with its rendered questions; the agent answers each with a value, stored as `{"value": ...}`.

### Pauses

A pause is the runtime stopping for the agent. One pause carries one step and a list of tasks,
one per `For` pass waiting at that step (one task outside a `For`): `{"kind": "task" |
"decision", "step", "tasks": [{"index", "pass", "passes", ...}]}`. A task's `index` is its
position in the list, from 0, and is what the answer is keyed by; `pass` is the innermost
loop's pass number and `passes` every enclosing loop's, outermost first (`[{"loop":
"each_ticket", "pass": 2}, {"loop": "revise", "pass": 0}]`). A task of a `Task_Agent` step
carries `prompt`, `state` (the `Read` keys), `references` (path and description) and
`answer_with` (the `Produce` keys and their types); a task of a `Decide` step carries
`questions` (name, type, labels, the rendered instruction, criteria), `state` and `answer_with`
(the question names and types), and the pause says why the agent is asked (`reason`: no model,
or how the model failed). The agent answers with one object per task, keyed by the task's
index, or with the one object when there is one task; an answer that does not fit the step's
keys is refused, nothing is applied, and the pause stands; a task left unanswered fails its
pass (and so the run), and a retry asks for it again. The step's record entry is written when
the answer is accepted.
- `End`: the state must hold the `Read` keys; they are the result.

## Loops

- The cap (`At_Most`, `Times`) is enforced before the first pass for a `For` and for a fold (the
  list may not be longer than the cap; `loop_cap` fails the run before any pass) and at the head
  of each pass for a `Loop`. `Else_Fail` fails the run at the cap (`loop_cap`, with the loop,
  the cap and the count; a retry arrives at the head again and fails the same way); `Else_Exit`
  leaves the loop; a `Times` loop simply ends.
- `For` passes are independent: each sees the item, its index, the state as it was before the
  loop, and the record as it was before the loop, and nothing from another pass. `Collect`
  builds its list in input order whatever order the passes ran in; every other key a pass wrote
  is gone after the loop.
- `Loop` passes run in order; each sees the previous pass's state. With `Until`, the runtime
  tests the condition on its answer at the head of each pass and again the moment a step of the
  body produces the answer, or a loop in the body exits having produced it; when it holds the
  loop ends at that point, the pass counts, and the rest of the pass does not run. An absent
  answer does not hold, and with `With Confidence_Above` neither does one whose probability on the
  condition is below the bar or missing.
- `Again <step>` re-enters the procedure at that step and follows the flow until the enclosing
  loop is reached again; everything on that path runs, recorded under the pass that asked for
  it, and the head's `Until` test is what sees the fresh answer.
- A loop writes one record entry when it exits (below). The loop's frame, the pass count and the
  passes in flight are part of the run's saved state, so a paused run resumes mid-loop.

### Batching `For` passes

Because `For` passes are independent, a runtime may run them in batches. The batch size is an
operator setting, not something the procedure says:

- `aip run ... --batch N`, default **10**; `--batch 1` runs passes one at a time. The default
  is also settable in the runtime's configuration, and the flag overrides it for one run.
- A batch of passes whose body is a single `Decide` that ends the pass, and whose `Read` keys
  are the same on every pass, becomes **one call to the decision model**, not one call per
  pass. The item reaches the question by interpolation (`{policy}` in `dynamic-policy`), so the
  call carries the `Read` keys once and one copy of each question per pass, rendered with that
  pass's item. The model wants distinct question keys, so the runtime suffixes the author's key
  with the pass index on the way out, `follows__0` ... `follows__9`, and strips it on the way
  back: the answer under `follows__3` becomes `verdict.follows` for pass 3. The author never
  writes the suffixed keys and the record never shows them: the answers are recorded as if each
  pass had made its own call, one decision key per pass, one entry per pass, in input order. A
  `Decide` that `Read`s the item (or `index`) judges something different on every pass, so its
  passes call one at a time; they still run as a batch. When the one call fails, every pass of
  it is handed to the agent (`Agent_Fallback true`) or fails, and a retry makes one call again.
- The suffix scheme is the runtime's and is not part of the language. A procedure cannot name
  a suffixed key, and a compiler never sees one. Any other way of making the keys distinct is
  equally correct provided the mapping back is exact.
- A batch of passes with any other body runs the passes together, up to N in flight, each with
  its own copy of the state: each pass is driven until it finishes or waits for the agent, and
  the passes waiting at the same step go out as one pause (the passes waiting at another step
  follow in the next pause). Scripts run as separate processes. The reference runtime drives
  the passes of a batch one after another; running them on several threads is allowed so long
  as the rest of this section holds.
- Batching never changes a result. Anything a pass could observe is the same at every batch
  size, which is what the independence rule guarantees, and a procedure that gives different
  results at different batch sizes is a bug in the runtime. The record is the same too: a
  pass's entries are appended when its batch completes, pass by pass in input order, so the
  record reads as if the passes had run one at a time.
- A failing pass fails the run. The passes of its batch that finished are recorded, a pass
  waiting for the agent stays where it is, and no further pass starts; a retry runs the failed
  pass's step again and the batch goes on.
- `Loop` passes are never batched, since each depends on the last.

## The record

- Every run entry carries the bundle id, so a question about a run can name the exact program
  that ran, and the time it was written.
- Every step's outputs are recorded, including every pass of a loop, with the pass number: one
  entry per step run, with the keys the step read (`input`) and what it produced (`result`),
  `pass` (the innermost loop's pass number, from 0; none outside loops) and `passes` (every
  enclosing loop's name and pass number, outermost first).
- A loop writes one entry when it exits, under its name and kind (`For` or `Loop`): what it ran
  over, `iterations` and the collected list as its result, and `exit`: why it ended (`until`,
  `items`, `times`, `cap`), where (`head`, or the body step or loop that produced the `Until`
  answer) and that answer's resolution.
- The run carries who ran it: `agent` (the framework or tool, from the MCP client or
  `--agent` / `AIP_AGENT`), `session` (a caller-supplied id grouping runs, `--session` /
  `AIP_SESSION`) and `user` (the server token's name). Claimed, not verified.
- A decision's record says who answered (the model, by name, or the agent), whether the history
  was sent, and keeps the model's full answer objects. A route's record says what it read,
  whether its confidence check fired and why (below the bound, absent), or let a hand answer through (`hand`), and where it went. An
  aggregation's record keeps every answer's resolution (its value, the probability on the
  condition, whether it held, whether a bar turned it). A script's record keeps the script, what
  it was given on stdin and how long it took. An agent task's record keeps the prompt and
  references it was given.
- The record is appended, never rewritten. A run that fails keeps everything up to the failure
  and the error beside it; the failed step runs again on a retry, from the state before it.

## What a runtime may add

A server that stores bundles and runs, a projection of both into a graph database for
governance queries, and a console that shows them are all built on top of the above. They
belong to the runtime's own documentation. The requirement here is only that nothing in them
changes what a procedure means or what a run records.
