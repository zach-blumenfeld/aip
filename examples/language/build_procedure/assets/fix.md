# Fix what the compiler reported

The program folder at `{path}` (relative to the working directory) does not compile yet. The
compiler's diagnostics, errors first, each with its line and column in `procedure.aip`:

{diagnostics}

The folder as it is now, every file by its path in the folder:

{contents}

The rules the procedure follows:

{rules}

Fix the folder so it compiles: rewrite `procedure.aip`, and write any script or asset the
diagnostics say is missing. Fix what each error says rather than removing the step it names, and
keep the procedure following the rules. Start with the first error; a later one is often its
consequence. The language page (the reference `references/language.md`) is the law.

Answer with `repairs`: the files to replace, as one JSON object, each key a path inside the
folder and its value the file's whole new text. Leave out the files that do not change.
