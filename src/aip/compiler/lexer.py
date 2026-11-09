"""Tokens of a `procedure.aip` file.

The lexer is deliberately small: words, strings, a handful of punctuation marks, and comments.
A word is anything a name, a keyword, a number, a version or a path can be (`triage`,
`Next_Step`, `0.6`, `3.10`, `scripts/escalate.py`, `w/`); the parser decides which it is from
its position. Newlines are not tokens: the grammar is read from the tokens themselves, so a
clause may wrap and a description may sit on the line after `Procedure <name>`.

Comments ride on the next token (`Token.comments`), so the parser can keep them with the node
they belong to and the formatter can write them back."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from aip.compiler.errors import ParseError

WORD = "word"
STRING = "string"
PUNCT = "punct"
EOF = "eof"

# A word may hold letters, digits, `_`, `.`, `/` and `-`; a `-` that starts `->` ends it.
_WORD = re.compile(r"[A-Za-z0-9_.](?:[A-Za-z0-9_./]|-(?!>))*")
_PUNCT = ("->", "==", "!=", "{", "}", "[", "]", ",", ":", "=")
_ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}


@dataclass(frozen=True)
class Comment:
    text: str  # from the `#` to the end of the line, as written
    line: int
    column: int


@dataclass
class Token:
    kind: str  # WORD, STRING, PUNCT or EOF
    text: str  # the lexeme as written; for a string, including its quotes
    line: int
    column: int
    end_line: int
    end_column: int  # the column after the last character
    value: str = ""  # the decoded value of a string
    comments: list[Comment] = field(default_factory=list)  # comments between the previous token and this one

    def describe(self) -> str:
        if self.kind == EOF:
            return "the end of the file"
        if self.kind == STRING:
            return "a string"
        return repr(self.text)


def tokenize(source: str) -> list[Token]:
    """The tokens of `source`, ending in an EOF token. Raises ParseError on a stray character or
    an unterminated string."""
    tokens: list[Token] = []
    pending: list[Comment] = []
    line, column = 1, 1
    i, n = 0, len(source)

    def advance(text: str) -> None:
        nonlocal line, column
        newlines = text.count("\n")
        if newlines:
            line += newlines
            column = len(text) - text.rfind("\n")
        else:
            column += len(text)

    while i < n:
        ch = source[i]
        if ch in " \t\r\n":
            advance(ch)
            i += 1
            continue
        if ch == "#":
            end = source.find("\n", i)
            end = n if end < 0 else end
            text = source[i:end].rstrip("\r")
            pending.append(Comment(text, line, column))
            advance(source[i:end])
            i = end
            continue
        start_line, start_column = line, column
        if ch == '"':
            triple = source.startswith('"""', i)
            quote = '"""' if triple else '"'
            j = i + len(quote)
            value: list[str] = []
            while True:
                if j >= n:
                    raise ParseError("unterminated string", start_line, start_column, expected="a closing quote")
                if source.startswith(quote, j):
                    break
                c = source[j]
                if c == "\\" and not triple and j + 1 < n and source[j + 1] in _ESCAPES:
                    value.append(_ESCAPES[source[j + 1]])
                    j += 2
                    continue
                value.append(c)
                j += 1
            j += len(quote)
            text = source[i:j]
            advance(text)
            tokens.append(Token(STRING, text, start_line, start_column, line, column, "".join(value), pending))
            pending = []
            i = j
            continue
        for mark in _PUNCT:
            if source.startswith(mark, i):
                advance(mark)
                tokens.append(Token(PUNCT, mark, start_line, start_column, line, column, comments=pending))
                pending = []
                i += len(mark)
                break
        else:
            m = _WORD.match(source, i)
            if not m:
                raise ParseError(f"unexpected character {ch!r}", line, column)
            text = m.group(0)
            advance(text)
            tokens.append(Token(WORD, text, start_line, start_column, line, column, comments=pending))
            pending = []
            i = m.end()
    tokens.append(Token(EOF, "", line, column, line, column, comments=pending))
    return tokens
