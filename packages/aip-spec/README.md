# aip-spec

The Agent Instruction Protocol procedure language as a Python package: the parser that turns a
`procedure.aip` into a syntax tree with a line and column on every node, the checker that reports
every rule of the spec against those lines (`aip-spec compile --check`, also `aip compile`; `--json`
for an editor), the compiler that writes the bundle, one `.rl` file holding the source, the files
and the derived graph (`aip-spec compile`, `aip-spec export`), the formatter that writes the tree
back in canonical form (`aip-spec fmt`, also `aip fmt`), and the bundled example programs.

**The language is specified in [`docs/language/spec.md`](../../docs/language/spec.md)** at the
repository root: the source language and its glossary of keywords, the state rules, the answer
types, aggregation, and compilation; the bundle's graph is in
[`docs/language/bundle.md`](../../docs/language/bundle.md). The example programs are under
[`examples/language/`](../../examples/language/).

This is a workspace member of [zach-blumenfeld/aip](https://github.com/zach-blumenfeld/aip);
the repository's [README](../../README.md) covers installation and the walkthrough.

`aip_spec` has no dependencies for parsing, checking and formatting; writing or reading a bundle
needs Relate, the embedded graph engine, installed (`scripts/install-relate.sh` at the
repository root):

```python
from aip_spec import parse, check, format_program, compile_folder, write_bundle, ParseError

program = parse(open("procedure.aip").read())   # aip_spec.syntax.Program, or ParseError with line and column
diagnostics = check(program, "the-folder/")      # every finding of spec 2.2 to 2.5, with code, severity and span
text = format_program(program)                   # canonical text; parse(text) == program
bundle, diagnostics = compile_folder("the-folder/")   # the graph, the files and the id, or None on errors
write_bundle(bundle, "the_procedure.rl")         # one Relate file; read_bundle verifies it, export_bundle writes the folder back
```

Tests run from the repository root with `uv run pytest -q`, which covers both packages.
