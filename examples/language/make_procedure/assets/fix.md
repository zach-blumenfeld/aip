# Fix what the compiler reported

The program folder at `{path}` does not compile yet. The compiler's diagnostics, errors first,
each with its line and column in `procedure.aip`:

{diagnostics}

Fix the folder so it compiles: edit `procedure.aip`, and write any script, prompt or asset the
diagnostics say is missing. Fix what each error says rather than removing the step it names, and
keep the procedure doing what it was written to do. Start with the first error; a later one is
often its consequence. `aip compile --check {path}` shows you the same diagnostics as you work.

## The language

{assets[language]}

## Answer

Answer with `path`: the absolute path of the folder, the same one unless you moved it.
