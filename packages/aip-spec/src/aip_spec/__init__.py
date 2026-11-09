"""The AIP procedure language: the parser, the syntax tree, the checker and the formatter for
`procedure.aip` (`docs/language/spec.md`), and the bundled example programs. No dependencies.

    from aip_spec import parse, check, format_program, ParseError
    program = parse(Path("procedure.aip").read_text())   # syntax.Program, or ParseError with line and column
    diagnostics = check(program, folder)                  # every finding of spec 2.2 to 2.5, with positions
    text = format_program(program)                        # canonical text; parse(text) == program

`check_path(folder)` does the first two together and turns a syntax error into a diagnostic;
`aip-spec compile <folder> --check --json` prints them. The graph and the bundle (the plan's L3)
build on the checked tree. Running a procedure is the `aip` package, which depends on this one."""

from aip_spec.checker import CODES, Diagnostic, check, check_path, check_source, has_errors
from aip_spec.errors import ParseError
from aip_spec.formatter import format_program, format_source
from aip_spec.parser import parse
from aip_spec.resources import example_dir, example_names

# The language version: the package's major.minor at the last release that changed the language.
LANGUAGE_VERSION = "0.9"

__all__ = ["LANGUAGE_VERSION", "ParseError", "Diagnostic", "CODES", "parse", "check", "check_source", "check_path", "has_errors",
           "format_program", "format_source", "example_dir", "example_names"]
