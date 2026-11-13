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
- One step per thing done, each done by whoever the rules say:
  - A rule a person would read and judge (is this receipt for alcohol, does it support the
    claim) is a `Decide`: one question, answered with a confidence.
  - A policy with several rules is a `For` over the rules (a list in an asset, or an input) with
    one `Decide` per rule inside it, `Collect`ing the verdicts, then an `Aggregate` with a
    confidence bar (`All verdicts.follows With Confidence_Above 0.8`) and a `Route` on it; so a
    rule added to the policy is covered without editing the steps. Never one script or one
    agent step that checks every rule in turn.
  - A `Task_Agent` is for reading or writing prose (a receipt's text, a rationale, a reply) and
    for acting in the world, never for a judgment a `Decide` can make.
  - Anything exact (a number against a limit, a date difference, a lookup, a file read,
    recording a line in a file, a ticket opened) is a script (`Execute`).
  - A `Route` on an answer for each decision.
- A step the rules give to a person (an approval, a sign-off, a judgement the documents reserve
  for someone) is a `Task_Agent` whose prompt says what the person decides; whoever runs the
  procedure takes it to them.
- A procedure with a `Decide` needs a decision model configured on the machine that runs it;
  the review says so.
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
