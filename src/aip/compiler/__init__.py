"""The AIP procedure language: the parser, the syntax tree, the checker, the formatter and the
compiler for `procedure.aip` (`docs/language/spec.md`), and the bundled example programs.

    from aip.compiler import parse, check, format_program, compile_folder, ParseError
    program = parse(Path("procedure.aip").read_text())   # syntax.Program, or ParseError with line and column
    diagnostics = check(program, folder)                  # every finding of spec 2.2 to 2.5, with positions
    text = format_program(program)                        # canonical text; parse(text) == program
    bundle, diagnostics = compile_folder(folder)          # the graph, the files and the id (spec 3), or None on errors

`check_path(folder)` parses and checks together and turns a syntax error into a diagnostic;
`aip compile <folder> --check --json` prints them. `write_bundle`, `read_bundle` and
`export_bundle` move a bundle to and from its `.rl` file, which needs Relate installed
(`aip.compiler.relate`); nothing else does. Running a procedure is `aip.model`, which reads the
bundle this package writes. Until 0.9 this was the separate `aip-spec` package (plan L5)."""

from aip.compiler.bundle import (
    Bundle, BundleError, bundle_id, compile_folder, compile_source, export_bundle, read_bundle, read_graph, write_bundle,
    write_graph,
)
from aip.compiler.checker import CODES, Diagnostic, check, check_path, check_source, has_errors
from aip.compiler.errors import ParseError
from aip.compiler.formatter import format_program, format_source
from aip.compiler.graph import FileEntry, Graph, build_graph
from aip.compiler.language import LANGUAGE_VERSION
from aip.compiler.parser import parse
from aip.compiler.resources import example_dir, example_names

__all__ = ["LANGUAGE_VERSION", "ParseError", "Diagnostic", "CODES", "parse", "check", "check_source", "check_path", "has_errors",
           "format_program", "format_source", "example_dir", "example_names",
           "Bundle", "BundleError", "FileEntry", "Graph", "build_graph", "bundle_id", "compile_folder", "compile_source",
           "write_bundle", "read_bundle", "export_bundle", "write_graph", "read_graph"]
