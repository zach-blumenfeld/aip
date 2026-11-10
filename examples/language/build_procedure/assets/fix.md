# Fix what the compiler reported

The program folder at `{path}` (relative to the working directory) does not compile yet. The
compiler's diagnostics, errors first, each with its line and column in `procedure.aip`:

{diagnostics}

The rules the procedure follows:

{rules}

Fix the folder so it compiles: read `procedure.aip`, then rewrite it, and write any script or
asset the diagnostics say is missing. Fix what each error says rather than removing the step it
names, and keep the procedure following the rules. Start with the first error; a later one is
often its consequence. Run `compile` on the folder before you answer.

Answer with `path`: `{path}`.
