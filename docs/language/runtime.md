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
  `passed: true_or_false`, the label for a `choice` or a `score`), and the runtime stores
  it as `{"value": ...}`, which is also what the record keeps.
- A key is rebound when a loop pass writes it; every earlier value stays in the record.
- A decision writes its one key with one answer object per question, in the shape of 2.4. An
  answer an agent produced in a `Task_Agent` has `value` and nothing else; a script's has `value`
  and whatever confidence and probabilities the script supplied.
- The runtime's own keys (spec 2.6): each loop's name is a key holding an object, `<loop>.index`
  the pass's number, from 0, while the loop runs, and `<loop>.iterations` how many passes ran, a
  pass ended by `Until` included, once it has exited. The bare `index` is the innermost running
  loop's and the bare `iterations` the last exited loop's; when a nested loop exits, `index` is
  the enclosing pass's again. A step reads them like any key, but they are the runtime's and
  are kept beside the state, not in it: no saved state of a run holds one, and a run that is
  over (done, or failed at a cap) keeps none at all. The reference runtime's run file has them
  under `loops` while the run is under way, since a resumed run needs them.

## Steps

- `Start`: the client supplies the inputs; the runtime checks them against the declared types.
- `Decide`: the runtime renders each question's instruction (`{key}` from the state), sends the
  step's `Read` keys as the thing to judge and the rendered questions to the decision model, and
  records the model's answers whole. An interpolated key is not sent as data unless `Read` names it. The decision model is an endpoint with the
  TypeSafe API shape (questions in, answer objects with their confidence and probabilities
  out), configured by URL and key on the machine that runs; TypeSafe's URL is the default and
  any endpoint with that shape serves. With no model configured the step fails the run
  (`no_decision_model`), and so does a model that fails (`decision_model_failed`, naming the
  endpoint); a retry asks again. A decision is never answered by hand (spec 2.4, revised
  2026-11-09: `Agent_Fallback` is gone; an agent decides in a `Task_Agent`).
- `Route`: the runtime reads one answer. With a `Confidence_Below` check, it reads the answer's
  `confidence` first and takes the check's branch when the confidence is below the bound
  (`reason: below`) or absent (`reason: absent`, a script's answer written without one); the
  compiler allows the check only on a decision's or a script's answer. Otherwise it takes the branch for `value`: `true` or `false` for a `true_or_false`,
  the label for a `choice` or a `score` (a score's value is its level's label, spec 2.4; the
  labels are the question's, or the key's own when a script or an agent produced it under
  labels). A value with no branch fails the step.
- `Aggregate`: for each aggregation, the runtime tests each answer in its source against the
  line's condition (`== value`, `!= value`, or `== true` for a bare `true_or_false`), takes the
  probability the model put on that condition from the answer's probabilities, and, when the
  line has `With Confidence_Above` and that probability is not strictly above it, or absent, counts the
  answer as the value that fails the aggregation; then applies `All`, `Any` or `None`, and writes the one key
  with one answer per aggregation, each `{value}` and nothing else. It records each answer's
  resolution.
- `Execute`: the runtime checks the machine has what `Requires` names before the first
  `Execute` of a run, launches the script from the cache with one JSON object on stdin (the
  `Read` keys as `state`, the `Use` assets by stem, its own `Produce` keys with their types as `expects`),
  and takes the JSON object on stdout as the step's `Produce` keys. A non-zero exit fails the
  step. An answer-typed key among them is the bare value or an object with `value` and, when the
  script measured them, the `confidence` and `probabilities` a model's answer carries (spec 2.4);
  the value must be among the key's labels, and anything else on the answer fails the step
  (`invalid_output`). The runtime never performs a script's work by hand. A runtime bounds how
  long one script may run and fails the step past it (`timeout`, which a retry runs again); this
  one's cap is `aip config --script-timeout`, 300 seconds by default. A runtime may also run a
  procedure without executing any script, as a trial of a procedure nobody has read yet: such a
  run stops at the first `Execute`, before its script starts (`script_not_run`), is not
  recorded, and is over.
- `Task_Agent`: the runtime renders the prompt (`{key}` from `Read`, `{assets[stem]}` for
  `Use`) and hands the task to the agent, which produces the `Produce` keys; an answer-typed key
  among them is written as the bare value or `{"value": ...}` and stored as the latter, its value
  among the key's labels and nothing else on it; an answer that breaks either rule is refused and
  the pause stands.

### Pauses

A pause is the runtime stopping for the agent, and only a `Task_Agent` pauses. One pause carries
one step and a list of tasks, one per `For` pass waiting at that step (one task outside a
`For`): `{"kind": "task", "step", "tasks": [{"index", "pass", "passes", ...}]}`. A task's
`index` is its position in the list, from 0, and is what the answer is keyed by; `pass` is the
innermost loop's pass number and `passes` every enclosing loop's, outermost first (`[{"loop":
"each_ticket", "pass": 2}, {"loop": "revise", "pass": 0}]`). A task carries `prompt`, `state`
(the `Read` keys), `references` (path and description), `answer_with` (the `Produce` keys and
their types) and `labels` (for each `choice` or `score` among them, the values it may take, so
the agent knows what to answer). A task whose innermost loop is a `Loop` with a cap also says
`pass_of`, the cap, and `last_pass`, whether this pass is the last the cap allows, so an agent
asked to fix something on the last pass knows no pass follows it. The agent answers every task
of the pause at once, with one object per task keyed by the task's index, or with the one
object when there is one task. Answers are as strict as inputs: a key missing, a key or a task
the pause did not ask for, a task left out, a value outside the labels, or a field on an answer
beside its value, and the answers are refused whole, the refusal naming each such key and task;
nothing is applied, and the pause stands with the same tasks, to be answered again. The step's
history entry is written when the answer is accepted, and says who answered and how long the
run waited.
- `End`: the result is the `Read` keys the path taken produced; a key named there but produced
  only on another path is left out, so a run reports what it did (a ticket, or a reply).

## Loops

- The cap (`At_Most`, `Times`) is enforced before the first pass for a `For` and for a fold (the
  list may not be longer than the cap; `loop_cap` fails the run before any pass) and at the head
  of each pass for a `Loop`. `Else_Fail` fails the run at the cap (`loop_cap`, naming the loop,
  the cap and the count, and no step or pass, since none was under way); `Else_Exit` leaves the
  loop; a `Times` loop simply ends. A run failed by `loop_cap`, in either form, is over: a retry
  would fail the same way, so the runtime does not offer one (`resumable: false`), and the
  loop's exit entry is in the history with `cap` as its reason.
- `For` passes are independent: each sees the item, its index, the state as it was before the
  loop, and the record as it was before the loop, and nothing from another pass. `Collect`
  builds its list in input order whatever order the passes ran in; every other key a pass wrote
  is gone after the loop.
- `Loop` passes run in order; each sees the previous pass's state. With `Until`, the runtime
  tests the condition on its answer at the head of each pass and again the moment a step of the
  body produces the answer, or a loop in the body exits having produced it; when it holds the
  loop ends at that point, the pass counts, and the rest of the pass does not run. An absent
  answer does not hold, and with `With Confidence_Above` neither does one whose probability on the
  condition is not strictly above the bar, or missing. The head test comes before the first pass
  too: a loop whose answer already holds when it is reached runs no pass and exits with
  `iterations` 0.
- A pass ends at `Continue` and nowhere else: the flow goes to the loop node, the count moves,
  and the head decides. Nothing leads from a body back to a step outside it, so every cycle a
  run makes is through a loop node, and a pass's entries are exactly the steps of the body it
  ran. A loop that checks and then fixes reaches its cap after a fix: that fix is not checked,
  and the task for it says so (`last_pass`, under Pauses above).
- A loop writes one history entry when it exits (below). The loop's frame, the pass count and the
  passes in flight are part of the saved run, so a paused run resumes mid-loop.

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
  it fails, and a retry makes one call again.
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
  results at different batch sizes is a bug in the runtime. The history is the same too: a
  pass's entries are appended when its batch completes, pass by pass in input order, so it
  reads as if the passes had run one at a time. Only the timings differ, and the mark on a
  decision that went out with others in one call (below). A runtime that reports progress
  reports each entry as it is written, which inside a batch is the order things happened in,
  not the history's.
- A run that stops inside a batch (a pass waits for the agent, or failed) shows the work of its
  open passes in its record: the entries they have written, pass by pass in input order, where
  the history will hold them once the batch completes. Whoever reads a paused run to decide how
  to answer sees what the loop has done, not a run that seems to have stopped at the step before
  the loop. Until the batch completes, a pass that goes on writes its next entries after its
  own earlier ones, so before those of the passes after it: within an open batch an entry's
  position is not final. No entry is changed or dropped.
- A failing pass fails the run. The passes of its batch that finished are recorded, a pass
  waiting for the agent stays where it is, and no further pass starts; a retry runs the failed
  pass's step again and the batch goes on.
- `Loop` passes are never batched, since each depends on the last.

## The record

The record is the whole run; its **history** is the list of entries, one per step run. The
reference runtime's field names are in `docs/cli-json.md`, The run file.

- The run carries the bundle id, once, so a question about a run can name the exact program that
  ran; when it started and when it finished; and who ran it: `agent` (the framework or tool,
  from the MCP client or `--agent` / `AIP_AGENT`), `session` (a caller-supplied id grouping
  runs, `--session` / `AIP_SESSION`) and `user` (the server token's name). Claimed, not verified.
  A caller with a version of its own may give it (`agent_version`; the MCP client's); it is
  kept beside `agent` and runs are found by `agent` alone.
- Every step's outputs are in the history, including every pass of a loop, with the pass number:
  one entry per step run, with the time it was written, the keys the step read (`input`, each
  under the name the step reads it by) and what it produced (`result`), `pass` (the innermost
  loop's pass number, from 0; none outside loops) and `passes` (every enclosing loop's name and
  pass number, outermost first).
- Every step's entry says how long the step took (`seconds`, its own wall time, waiting for an
  agent not counted), so where a run's time went can be read off the history.
- A loop writes one entry when it exits, under its name and kind (`For` or `Loop`): what it ran
  over, `iterations` and the collected list as its result, and `exit`: why it ended (`until`,
  `items`, `times`, `cap`), where (`head`, or the body step or loop that produced the `Until`
  answer) and that answer's resolution. A loop that fails the run at its cap writes it too. The
  test of `Until` at the head of a pass that then ran is written as well, on the first entry
  the pass writes at the loop's level (`until`: that it did not hold, and the answer's
  resolution, or none when the answer was absent), so the history shows why each pass ran.
- A decision's entry says which model answered and at which endpoint, how long the call alone
  took (`model_seconds`), whether the history was sent, whether it went out with other passes
  in one call and how many (`batched`, `batch_size`), and keeps the model's full answer objects.
  A route's entry says what it read (the dotted key, for lineage), whether its confidence
  check fired and why (below the bound, absent), and where it went, once. An aggregation's
  entry keeps every answer's resolution (its value, the probability on the condition, which is
  the number a bar reads, whether it held, whether a bar turned it). A script's entry keeps the
  script and what it was given on stdin. An agent task's entry keeps the prompt and references
  it was given, who answered (`agent`, `session`) and how long the run waited for the answer
  (`waited_seconds`). A runtime that has a model answer the task (`aip runah`,
  `docs/runah.md`) says so in `answered_by` (`{"agent": "runah", "model": <the id the model's
  endpoint reported>}`) and keeps what answering took, marked `work: "observed"`: the tool calls
  (`name`, a summary of the arguments, `seconds`), the tokens (`prompt`, `completion`, `total`),
  `model_seconds` and how many answers were refused before one held (`refusals`). An agent that
  reports what its own answer took (`aip resume --work`) has it kept marked `work: "reported"`,
  so the record says which numbers the runtime saw and which it was told. The answer itself is
  checked as any agent's is.
- The history is appended, never rewritten (the entries of a batch still open are the one case
  where an entry may yet move, above). A run that fails keeps everything up to the failure
  and the error beside it; the failed step runs again on a retry, from the state before it.

## What a runtime may add

A server that stores bundles and runs, a projection of both into a graph database for
governance queries, and a console that shows them are all built on top of the above. They
belong to the runtime's own documentation. The requirement here is only that nothing in them
changes what a procedure means or what a run records.
