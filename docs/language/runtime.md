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
  there, so the same bundle on the same machine does not unpack twice.

## The state

- One state per run: a set of named, typed keys, as the spec's section 2.3 defines it. A step
  sees only the keys its `Read` names, with the declared types checked before it runs.
- A step's `Produce` keys are checked on its result and added to the state. A missing key or
  a wrong type fails the step; the runtime does not fill in a value.
- A key is rebound when a loop pass writes it; every earlier value stays in the record.
- A decision writes its one key with one answer object per question, in the shape of 2.4. An
  answer given by hand has `value` and nothing else.

## Steps

- `Start`: the client supplies the inputs; the runtime checks them against the declared types.
- `Decide`: the runtime renders each question's instruction (`{key}` from the state), sends the
  step's `Read` keys as the thing to judge and the rendered questions to the decision model, and
  records the model's answers whole. An interpolated key is not sent as data unless `Read` names it. With no model configured, the step stops the run
  unless `Agent_Fallback true`, in which case the agent answers and the record says so.
- `Route`: the runtime reads one answer. With a `Confidence_Below` check, it reads the answer's
  `confidence` first and takes the check's branch when the confidence is below the bound or
  absent; otherwise it takes the branch for `value`. A value with no branch fails the step.
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
  `Use`) and hands the task to the agent, which produces the `Produce` keys.
- `End`: the state must hold the `Read` keys; they are the result.

## Loops

- The cap (`At_Most`, `Times`) is enforced before the first pass for a `For` (the list may not
  be longer than the cap) and at the head of each pass for a `Loop`. `Else_Fail` fails the run
  at the cap; `Else_Exit` leaves the loop.
- `For` passes are independent: each sees the item, its index, and the state as it was before
  the loop, and nothing from another pass. `Collect` builds its list in input order whatever
  order the passes ran in.
- `Loop` passes run in order; each sees the previous pass's state. With `Until`, the runtime
  tests the condition on its answer at the head of each pass and again after any body step that
  produces the answer; when it holds the loop ends at that point and the rest of the pass does
  not run. An absent answer does not hold, and with `With Confidence_Above` neither does one whose
  probability on the condition is below the bar or missing.
- `Again <step>` re-enters the procedure at that step and follows the flow until the enclosing
  loop is reached again; everything on that path runs.

### Batching `For` passes

Because `For` passes are independent, a runtime may run them in batches. The batch size is an
operator setting, not something the procedure says:

- `aip run ... --batch N`, default **10**; `--batch 1` runs passes one at a time. The default
  is also settable in the runtime's configuration, and the flag overrides it for one run.
- A batch of passes whose body is a single `Decide` reading the item becomes **one call to the
  decision model**, not one call per pass. The call carries the `Read` keys once (they are the
  same on every pass, since a `For` body may not read another pass's state) and one copy of
  each question per pass, rendered with that pass's item. The model wants distinct question
  keys, so the runtime suffixes the author's key with the pass index on the way out,
  `follows__0` ... `follows__9`, and strips it on the way back: the answer under `follows__3`
  becomes `verdict.follows` for pass 3. The author never writes the suffixed keys and the record
  never shows them: the answers are recorded as if each pass had made its own call, one
  decision key per pass, one entry per pass, in input order.
- The suffix scheme is the runtime's and is not part of the language. A procedure cannot name
  a suffixed key, and a compiler never sees one. Any other way of making the keys distinct is
  equally correct provided the mapping back is exact.
- A batch of passes with any other body runs the passes concurrently, up to N at once, each
  with its own copy of the state. Scripts in a batch run as separate processes.
- Batching never changes a result. Anything a pass could observe is the same at every batch
  size, which is what the independence rule guarantees, and a procedure that gives different
  results at different batch sizes is a bug in the runtime.
- A failing pass fails the run. The passes already started in its batch run to completion and
  are recorded; no further batch starts.
- `Loop` passes are never batched, since each depends on the last.

## The record

- Every run entry carries the bundle id, so a question about a run can name the exact program
  that ran.
- Every step's outputs are recorded, including every pass of a loop, with the pass number.
- A decision's record says who answered (the model, by name, or the agent) and keeps the
  model's full answer objects. A route's record says whether its confidence check fired and why
  (below the bound, absent).
- The record is appended, never rewritten. A run that fails keeps everything up to the failure.

## What a runtime may add

A server that stores bundles and runs, a projection of both into a graph database for
governance queries, and a console that shows them are all built on top of the above. They
belong to the runtime's own documentation. The requirement here is only that nothing in them
changes what a procedure means or what a run records.
