# aip-spec

The Agent Instruction Protocol procedure language as a Python package: the parser that turns a
`procedure.aip` into a syntax tree with a line and column on every node, the checker that reports
every rule of the spec against those lines (`aip-spec compile --check`, also `aip compile`; `--json`
for an editor), the formatter that writes the tree back in canonical form (`aip-spec fmt`, also
`aip fmt`), and the bundled example programs. The bundle writer is being added on top.

**The language is specified in [`docs/language/spec.md`](../../docs/language/spec.md)** at the
repository root: the source language and its glossary of keywords, the state rules, the answer
types, aggregation, and compilation. The example programs are under
[`examples/language/`](../../examples/language/).

This is a workspace member of [zach-blumenfeld/aip](https://github.com/zach-blumenfeld/aip);
the repository's [README](../../README.md) covers installation and the walkthrough.

`aip_spec` has no dependencies:

```python
from aip_spec import parse, check, format_program, ParseError

program = parse(open("procedure.aip").read())   # aip_spec.syntax.Program, or ParseError with line and column
diagnostics = check(program, "the-folder/")      # every finding of spec 2.2 to 2.5, with code, severity and span
text = format_program(program)                   # canonical text; parse(text) == program
```

Tests run from the repository root with `uv run pytest -q`, which covers both packages.
