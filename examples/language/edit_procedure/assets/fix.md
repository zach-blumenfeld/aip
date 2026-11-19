# Fix what the compiler reported

The procedure at `{path}` (relative to the working directory) was changed as this instruction
says, and does not compile yet:

{instruction}

The compiler's diagnostics, errors first, each with its line and column in `procedure.aip`:

{diagnostics}

The folder as it is now, every file by its path in the folder:

{contents}

Fix the folder so it compiles: rewrite `procedure.aip`, and write any script or asset the
diagnostics say is missing. Keep the change the instruction asked for; fix what each error says
rather than removing the step it names. Start with the first error; a later one is often its
consequence. The language page (the reference `references/language.md`) is the law.

Answer with `repairs`: the files to replace, as one JSON object, each key a path inside the
folder and its value the file's whole new text; leave out the files that do not change. And
`fixed`: what you fixed, in a line or two.
