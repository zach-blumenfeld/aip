"""The AIP procedure language: the parser, the syntax tree and the formatter for `procedure.aip`
(`docs/language/spec.md`), and the bundled example programs. No dependencies.

    from aip_spec import parse, format_program, ParseError
    program = parse(Path("procedure.aip").read_text())   # syntax.Program, or ParseError with line and column
    text = format_program(program)                        # canonical text; parse(text) == program

The checker, the graph and the bundle (the plan's L2 and L3) build on the tree in `aip_spec.syntax`.
Running a procedure is the `aip` package, which depends on this one."""

from aip_spec.errors import ParseError
from aip_spec.formatter import format_program, format_source
from aip_spec.parser import parse
from aip_spec.resources import example_dir, example_names

# The language version: the package's major.minor at the last release that changed the language.
LANGUAGE_VERSION = "0.9"

__all__ = ["LANGUAGE_VERSION", "ParseError", "parse", "format_program", "format_source", "example_dir", "example_names"]
