"""The one error the parser raises."""

from __future__ import annotations


class ParseError(Exception):
    """A syntax error: where it is (1-based line and column), what was expected, what was found.

    `str(error)` is `<file>:<line>:<column>: <message>` when `file` is set, else `<line>:<column>: <message>`.
    `to_diagnostic()` gives the shape every compiler diagnostic has (the plan's L2):
    `{code, severity, message, file, line, column, end_line, end_column, step}`."""

    code = "syntax_error"

    def __init__(self, message: str, line: int, column: int, *, expected: str | None = None, found: str | None = None,
                 end_line: int | None = None, end_column: int | None = None, file: str | None = None):
        super().__init__(message)
        self.message = message
        self.line = line
        self.column = column
        self.expected = expected
        self.found = found
        self.end_line = line if end_line is None else end_line
        self.end_column = column if end_column is None else end_column
        self.file = file

    def __str__(self) -> str:
        where = f"{self.line}:{self.column}"
        if self.file:
            where = f"{self.file}:{where}"
        return f"{where}: {self.message}"

    def to_diagnostic(self) -> dict:
        return {
            "code": self.code, "severity": "error", "message": self.message, "file": self.file,
            "line": self.line, "column": self.column, "end_line": self.end_line, "end_column": self.end_column,
            "step": None,
        }
