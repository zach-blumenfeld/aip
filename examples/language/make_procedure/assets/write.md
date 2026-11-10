# Write an AIP procedure

Write the program folder of a procedure called `{name}`. What it should do, in the requester's
words:

{description}

Source material to read first (a file or a folder; empty when there is none): {materials}

## What to write

Make the folder `{name}` in the directory this run was started in, unless the requester named
another place, and write into it:

- `procedure.aip`, starting with `Procedure {name}` and a one-sentence description, then
  `Use_When` lines an agent searching a catalog would recognise the task by.
- `assets/`: one prompt template per `Task_Agent` step whose prompt is longer than a sentence,
  and any file a step is handed whole (a policy, a config).
- `scripts/`: one script per `Execute` step, with `Requires python 3.10` in the header. A script
  does real work or is honest that it is a stub; it never pretends.
- `references/`: only for long material an agent should load when a prompt calls for it.

How to shape it:

1. Start from the result: what `End` returns, then the inputs `Start` needs to get there.
2. One step per thing done. Name who does each: a decision model (`Decide`: a judgement that
   should carry a confidence), the agent running the procedure (`Task_Agent`: writing, reading,
   anything needing judgement and tools), a script (`Execute`: anything exact or repeatable), the
   runtime (`Route`, `Aggregate`).
3. Something done once per item of a list is a `For`. Work that is checked and revised until it
   passes is a `Loop ... Until`. Give every loop a cap that fits the task.
4. A `Decide` needs a decision model on the machine that runs the procedure. Use one where the
   requester wants a measured judgement (a policy check, a classification with a confidence
   check on its route); where the agent should judge, use a `Task_Agent` that produces an answer
   type instead. If you write a `Decide`, tell the requester when you report: the procedure
   runs only where a decision model is configured (`aip config` shows whether one is).
5. Keep what the requester asked for and add nothing they did not: no extra inputs, no extra
   steps for their own sake.

You may run `aip compile --check <folder>` yourself while you write; the next step of this
procedure runs the compiler either way and hands you back whatever it reports.

## The language

{assets[language]}

## Answer

Answer with `path`: the absolute path of the folder you wrote.
