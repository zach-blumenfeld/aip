# Change the procedure

Change the AIP procedure in `{path}` (relative to the working directory) as this instruction
says:

{instruction}

The folder as it is now, every file by its path in the folder:

{before}

Documents the change is based on (relative to the working directory; an empty list when there
are none): {files}

Their text:

{texts}

Make the change: rewrite `procedure.aip` whole, and write any new prompt, asset or script the
change needs (a new `Execute` gets a real script under `scripts/`; a new `Task_Agent` with a long
prompt gets one under `assets/`). Change only what the instruction asks for, and keep everything
else as it is, comments included. A new step for a person (an approval, a sign-off) is a
`Task_Agent` whose prompt says what the person decides; whoever runs the procedure takes it to
them. The language page (the reference `references/language.md`) is the law. The next steps
write your files, compile the folder and hand any errors back to you.

A script you write or change opens with a docstring saying what it does and what it touches
outside the working directory: services and URLs it calls, files elsewhere, commands it runs,
and the credentials (tokens, logins, keys, environment variables) it uses. A person reads that
before it runs.

Answer with `rewritten`: the files you write or change, as one JSON object, each key a path inside
the folder and its value the file's whole new text (`null` removes a file); leave out the files
that do not change. And `changes`: what you changed and why, in a few lines; then, under a line
`Scripts:`, one line per script you wrote or changed, saying what it touches outside the working
directory and which credentials it uses, or that it touches nothing outside.
