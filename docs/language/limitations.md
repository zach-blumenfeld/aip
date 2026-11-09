# Known limitations

Things the language does not do yet, with the workaround each example uses and what would
change. Each is a deliberate boundary for now, not an oversight; when one starts to hurt, it
moves to the spec's open items with a design.

## One model call per item in a `For` loop, unless batched

A decision's questions are fixed in the file. Checking a list of policies that arrives at run
time therefore runs a `For` loop whose body is one `Decide` with one question, reading the item
(`examples/language/dynamic-policy`; `fixed-policy` has its policies in the file and asks them in one call). Run one pass at a time, that is one model
call per policy, though the decision model can answer many questions in one call.

Nothing in the language changes to fix it. `For` passes are independent by definition, so a
runtime batches them: `aip run --batch N` (default 10) turns a batch of single-`Decide` passes
into **one** model call carrying one question per item, the keys made distinct by the runtime
and mapped back, same answers, same record, fewer calls. The author writes a loop; the runtime
writes the multi-question request. The
requirement is written in `docs/language/runtime.md` under "Batching `For` passes". The limitation that
remains is that a body with more than one step in it runs its passes concurrently rather than
as one call.

## Loading data saved with the procedure into the state

An asset reaches a step as a file, not as a state key. Fixed data that a question needs can
be written into the procedure as named strings, which is what `fixed-policy` does with its
policies. Data that must be a state key, a list to loop over for instance, has to come in at
`Start` or be produced by an `Execute` step whose script reads the asset. A `Load <path> As
<key>` clause on `Start` would remove that script; it is not in the language because nothing
needs it yet.

## Questions are written at compile time

A `Decide` cannot generate questions from data. "One question per policy" is written as one
fixed question asked once per policy in a loop, with the policy written into the question text
by interpolation, so the model judges the work against a question that carries the policy. A procedure whose questions themselves arrive at run time is out of scope.

## No expressions

By design and not changing: no arithmetic, no comparisons beyond the confidence check, no
logical operators, no string building beyond `{key}` interpolation in prompts and questions, no
function calls. Computation is an `Execute` step. The reasoning, including why a limited
logical grammar with per-atom confidence was designed and rejected, is in
`docs/language/no-expressions.md`.
