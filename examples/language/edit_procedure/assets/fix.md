# Fix what the compiler reported

The procedure at `{path}` (relative to the working directory) was changed as this instruction
says, and does not compile yet:

{instruction}

The compiler's diagnostics, errors first, each with its line and column in `procedure.aip`:

{diagnostics}

Fix the folder so it compiles: read `procedure.aip`, then rewrite it, and write any script or
asset the diagnostics say is missing. Keep the change the instruction asked for; fix what each
error says rather than removing the step it names. Start with the first error; a later one is
often its consequence. Run `compile` on the folder before you answer.

Answer with `fixed`: what you fixed, in a line or two.
