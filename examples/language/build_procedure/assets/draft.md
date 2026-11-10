# Write the procedure

Write the AIP program folder of the procedure `{name}` at `{out}` (relative to the working
directory), with `write_file`.

The brief:

{brief}

The rules it follows:

{rules}

The person's latest answers (the rules already reflect the earlier ones):

{answers}

What the documents say:

{notes}

## What to write

- `{out}/procedure.aip`, starting `Procedure {name}` with a one-sentence description and
  `Use_When` lines an agent searching a catalog would recognise the task by. The language page
  in your instructions is the law; follow its rules and its example's shape.
- One step per thing done, each done by whoever the rules say: a script (`Execute`) for anything
  exact or repeatable (a limit checked against a number, a lookup, a ticket opened), the agent
  (`Task_Agent`) for reading, writing and judgement, a `Route` on an answer for each decision.
  An agent's or a script's decision is an answer type (`true_or_false`, `choice [...]`); no
  `Decide`, so the procedure runs where no decision model is configured.
- Something done for each item of a list is a `For`; a check and its fix is a `Loop ... Until`
  with the check inside it. Every loop has a cap.
- `{out}/scripts/<name>.py` for each `Execute`: real Python that reads the JSON object on stdin
  (`{"state": {...}, "assets": {...}, "expects": {...}}`) and prints exactly its `Produce`
  keys as one JSON object. Put `Requires python 3.10` in the header. A script that would talk to
  a system you do not have says in its output that it is a stub; it never pretends.
- `{out}/assets/` for prompts longer than a sentence and for any policy a step is handed whole.

Run `compile` on `{out}` when you have written it and fix what it reports before you answer.

Answer with `path`: `{out}`.
