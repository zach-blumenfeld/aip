# Change the procedure

Change the AIP procedure in `{path}` (relative to the working directory) as this instruction
says:

{instruction}

Its `procedure.aip` as it is now:

```aip
{source}
```

Documents the change is based on (relative to the working directory; an empty list when there
are none): {files}

Read what you need first: the folder's prompts and scripts (`list_files {path}`) and the
documents. Then make the change with `write_file`: rewrite `procedure.aip` whole, and write any
new prompt, asset or script the change needs (a new `Execute` gets a real script under
`scripts/`; a new `Task_Agent` with a long prompt gets one under `assets/`). Change only what
the instruction asks for, and keep everything else as it is, comments included. A new step for
a person (an approval, a sign-off) is a `Task_Agent` whose prompt begins `This is a task for a
person, not for you:` and then says what the person decides. The language
page in your instructions is the law. Run `compile` on `{path}` and fix what it reports before
you answer.

A script you write or change opens with a docstring saying what it does and what it touches
outside the working directory: services and URLs it calls, files elsewhere, commands it runs,
and the credentials (tokens, logins, keys, environment variables) it uses. A person reads that
before it runs.

Answer with `changes`: what you changed and why, in a few lines; then, under a line `Scripts:`,
one line per script you wrote or changed, saying what it touches outside the working directory
and which credentials it uses, or that it touches nothing outside.
