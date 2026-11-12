# Write the procedure

Write an AIP program folder at `{out}` (relative to the working directory), with `write_file`.

Its name: `{name}`. When that is empty, the requester gave none: name it from the brief's
subject, the thing the procedure handles, in two to four lowercase words joined by underscores
(`refund_requests`, `github_activity_feed`), never from the brief's opening words.

The brief:

{brief}

The rules it follows:

{rules}

The person's latest answers (the rules already reflect the earlier ones):

{answers}

What the documents say:

{notes}

## What to write

- `{out}/procedure.aip`, starting `Procedure <its name>` with a one-sentence description and
  `Use_When` lines an agent searching a catalog would recognise the task by. The language page
  in your instructions is the law; follow its rules and its example's shape.
- One step per thing done, each done by whoever the rules say: a script (`Execute`) for anything
  exact or repeatable (a limit checked against a number, a lookup, a ticket opened), the agent
  (`Task_Agent`) for reading, writing and judgement, a `Route` on an answer for each decision.
  An agent's or a script's decision is an answer type (`true_or_false`, `choice [...]`); no
  `Decide`, so the procedure runs where no decision model is configured.
- A step the rules give to a person (an approval, a sign-off, a judgement the documents reserve
  for someone) is a `Task_Agent` whose prompt begins `This is a task for a person, not for
  you:` and then says what the person decides; the agent running it takes it to them.
- Something done for each item of a list is a `For`; a check and its fix is a `Loop ... Until`
  with the check inside it. Every loop has a cap.
- `{out}/scripts/<name>.py` for each `Execute`: real Python that reads the JSON object on stdin
  (`{"state": {...}, "assets": {...}, "expects": {...}}`) and prints exactly its `Produce`
  keys as one JSON object. Put `Requires python 3.10` in the header. Open each script with a
  docstring saying what it does and which outside systems, files outside the working directory
  and credentials (tokens, logins, keys) it touches: a person reads that before it ever runs. A
  script that would talk to a system you do not have says in its output that it is a stub; it
  never pretends.
- `{out}/assets/` for prompts longer than a sentence and for any policy a step is handed whole.

Run `compile` on `{out}` when you have written it and fix what it reports before you answer.

Answer with `path`: `{out}`, and `procedure`: the name in its header.
