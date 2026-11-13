# Write the procedure

Write an AIP program folder. The next step writes it at `{out}` (relative to the working
directory) from your answer, then compiles it and hands any errors back to you.

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

- `procedure.aip`, starting `Procedure <its name>` with a one-sentence description and
  `Use_When` lines an agent searching a catalog would recognise the task by. The language page
  (the reference `references/language.md`) is the law; follow its rules and its example's shape.
- One step per thing done, each done by whoever the rules say: a script (`Execute`) for anything
  exact or repeatable (a limit checked against a number, a lookup, a file read, a ticket opened),
  the agent (`Task_Agent`) for reading, writing and judgement, a `Route` on an answer for each
  decision. An agent's or a script's decision is an answer type (`true_or_false`, `choice
  [...]`); no `Decide`, so the procedure runs where no decision model is configured.
- A step the rules give to a person (an approval, a sign-off, a judgement the documents reserve
  for someone) is a `Task_Agent` whose prompt says what the person decides; whoever runs the
  procedure takes it to them.
- Something done for each item of a list is a `For`; a check and its fix is a `Loop ... Until`
  with the check inside it. Every loop has a cap.
- `scripts/<name>.py` for each `Execute`: real Python that reads the JSON object on stdin
  (`{"state": {...}, "assets": {...}, "expects": {...}}`) and prints exactly its `Produce`
  keys as one JSON object. A script starts in the run's working directory, so a path the
  procedure is given is opened as it is. Put `Requires python 3.10` in the header. Open each
  script with a docstring saying what it does and which outside systems, files outside the
  working directory and credentials (tokens, logins, keys) it touches: a person reads that
  before it ever runs. A script that would talk to a system you do not have says in its output
  that it is a stub; it never pretends.
- `assets/` for prompts longer than a sentence and for any policy a step is handed whole.

Answer with `procedure`: the name in its header, and `drafted`: every file of the folder as one
JSON object, each key a path inside the folder (`procedure.aip`, `scripts/count.py`,
`assets/reply.md`) and its value the file's whole text.
