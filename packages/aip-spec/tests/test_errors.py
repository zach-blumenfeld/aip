"""Syntax errors: each names its line, its column and what was expected."""

import unittest

from aip_spec import ParseError, parse

PREFIX = 'Procedure p "x"\n'  # line 1 of every case below

# (name, source after the Procedure line, line, column, a fragment of the message)
CASES = [
    ("no procedure", 'Start "s" { Next_Step end }\n', 1, 1, "expected 'Procedure <name>' to open the file"),
    ("procedure name", 'Procedure "x"\n', 1, 11, "the procedure's name"),
    ("procedure description", "Procedure p\nStart \"s\" {}\n", 2, 1, "the procedure's description, a string"),
    ("header string", 'Use_When\nStart "s" {}\n', 3, 1, "expected a string after 'Use_When', got 'Start'"),
    ("requires version", "Requires python\nStart \"s\" {}\n", 3, 1, "expected a version after 'Requires python', got 'Start'"),
    ("named string not a string", "a = b\n", 2, 5, "a string for a (a name holds a string and nothing else)"),
    ("named string needs =", "a \"b\"\n", 2, 3, "expected '=' after the name a (a named string is written a = \"...\"), got a string"),
    ("clause outside a step", "m: string\n", 2, 1, "a clause (m: ...) outside a step"),
    ("unknown item", "Fetch f \"x\" {}\n", 2, 1, "expected a step (Start, Decide, Route, Aggregate, Execute, Task_Agent, End), a loop (For, Loop) or a named string, got 'Fetch'"),
    ("step name", 'Decide "d" {}\n', 2, 8, "expected a name for the Decide step, got a string"),
    ("step name is a keyword case", "Decide Read \"d\" {}\n", 2, 8, "expected a name for the Decide step, got 'Read'"),
    ("start has no name", 'Start s "x" {}\n', 2, 7, "Start has no name"),
    ("end named end", 'Decide end "x" {}\n', 2, 8, "'end' names the End step"),
    ("step description", "Decide d {}\n", 2, 10, "expected the description of d, a string, got '{'"),
    ("open brace", 'Decide d "x"\n  Read m\n', 3, 3, "expected '{' to open the step's block, got 'Read'"),
    ("close brace", 'Decide d "x" {\n  Read m\n', 4, 1, "expected '}' to close d, got the end of the file"),
    ("unknown clause", 'Decide d "x" {\n  Fetch m\n}\n', 3, 3, "expected a clause of Decide (Read, Answer_Questions, Agent_Fallback, History, Produce, Next_Step, Continue, Again), got 'Fetch'"),
    ("clause of another kind", 'Decide d "x" {\n  Run_Script s.py\n}\n', 3, 3, "'Run_Script' is not a clause of Decide; Decide takes Read, Answer_Questions"),
    ("end has no next step", 'End "x" {\n  Read m\n  Next_Step a\n}\n', 4, 3, "'Next_Step' is not a clause of End; End takes Read"),
    ("clause order", 'Decide d "x" {\n  Produce dec\n  Read m\n}\n', 4, 3, "'Read' comes before 'Produce' in a step: Read, the lines of its kind, Produce, then where it goes"),
    ("flow before produce", 'Execute e "x" {\n  Next_Step a\n  Produce o: string\n}\n', 4, 3, "'Produce' comes before 'Next_Step'"),
    ("start input bare key", 'Start "s" {\n  m\n  Next_Step a\n}\n', 3, 3, "expected a clause of Start (<key>: <type>, Next_Step), got 'm'"),
    ("start input needs type", 'Start "s" {\n  Input m\n  Next_Step a\n}\n', 4, 3, "expected ':' and a type for the input m, got 'Next_Step'"),
    ("unknown type", 'Start "s" {\n  m: text\n}\n', 3, 6, "expected a type (string, integer, float, boolean, list, object, true_or_false, choice, score, decision, aggregation), got 'text'"),
    ("produce needs a key", 'Execute e "x" {\n  Produce 3x: string\n}\n', 3, 11, "expected a key (lowercase letters, digits and underscores), got '3x'"),
    ("produce not a field", 'Execute e "x" {\n  Produce a.b: string\n}\n', 3, 11, "a key, not a field: 'a.b' can be read but not produced"),
    ("decide produce typed", 'Decide d "x" {\n  Produce dec: decision\n}\n', 3, 14, "Decide's Produce names one key and no type; the key's fields are its questions"),
    ("aggregate produce typed", 'Aggregate a "x" {\n  Produce s: aggregation\n}\n', 3, 12, "Aggregate's Produce names one key and no type; the key's fields are its aggregations"),
    ("next step target", 'Execute e "x" {\n  Next_Step\n}\n', 4, 1, "expected a step name after 'Next_Step', got '}'"),
    ("again target", 'Execute e "x" {\n  Again 7\n}\n', 3, 9, "expected a step name after 'Again', got '7'"),
    ("flag value", 'Decide d "x" {\n  Agent_Fallback yes\n}\n', 3, 18, "expected 'true' or 'false' after 'Agent_Fallback', got 'yes'"),
    ("questions brace", 'Decide d "x" {\n  Answer_Questions\n    q: noul "?"\n}\n', 4, 5, "expected '{' to open the questions, got 'q'"),
    ("questions unclosed", 'Decide d "x" {\n  Answer_Questions {\n    q: noul "?"\n', 5, 1, "expected '}' to close the questions, got the end of the file"),
    ("question name", 'Decide d "x" {\n  Answer_Questions {\n    Q: noul "?"\n  }\n}\n', 4, 5, "expected a question name (lowercase letters, digits and underscores), got 'Q'"),
    ("question colon", 'Decide d "x" {\n  Answer_Questions {\n    q noul "?"\n  }\n}\n', 4, 7, "expected ':' after the question name q, got 'noul'"),
    ("question type", 'Decide d "x" {\n  Answer_Questions {\n    q: string "?"\n  }\n}\n', 4, 8, "expected an answer type (true_or_false, choice or score), got 'string'"),
    ("question labels", 'Decide d "x" {\n  Answer_Questions {\n    q: choice [a b] "?"\n  }\n}\n', 4, 18, "expected ']' to close the labels, got 'b'"),
    ("question label case", 'Decide d "x" {\n  Answer_Questions {\n    q: choice [A] "?"\n  }\n}\n', 4, 16, "expected a label (lowercase letters, digits and underscores), got 'A'"),
    ("question instruction", 'Decide d "x" {\n  Answer_Questions {\n    q: choice [a, b]\n  }\n}\n', 5, 3, "expected the instruction for q, a string, got '}'"),
    ("criterion text", 'Decide d "x" {\n  Answer_Questions {\n    q: choice [a, b] "?"\n      a: 5\n  }\n}\n', 5, 10, "expected the criterion for a, a string, got '5'"),
    ("route branch value", 'Route r "x" {\n  Read d.q\n  -> a\n}\n', 4, 3, "expected a clause of Route (Read, Confidence_Below, <value> -> <step>), got '->'"),
    ("route branch arrow", 'Route r "x" {\n  Read d.q\n  When a b\n}\n', 4, 10, "expected '->' after the value a, got 'b'"),
    ("route target", 'Route r "x" {\n  Read d.q\n  a -> 7\n}\n', 4, 8, "expected a step name or 'Continue' after '->', got '7'"),
    ("confidence bound", 'Route r "x" {\n  Read d.q\n  Confidence_Below -> a\n}\n', 4, 20, "expected a confidence bound after 'Confidence_Below', such as 0.6, got '->'"),
    ("route has no produce", 'Route r "x" {\n  Read d.q\n  Produce z: string\n}\n', 4, 3, "'Produce' is not a clause of Route; Route takes Read, Confidence_Below, <value> -> <step>"),
    ("aggregation mode", 'Aggregate a "x" {\n  Aggregations {\n    all: Every d.q\n  }\n}\n', 4, 10, "expected 'All', 'Any' or 'None', got 'Every'"),
    ("aggregation source", 'Aggregate a "x" {\n  Aggregations {\n    all: All == true\n  }\n}\n', 4, 14, "expected the answers to aggregate, got '=='"),
    ("condition value", 'Aggregate a "x" {\n  Aggregations {\n    all: All d.q == \n  }\n}\n', 5, 3, "expected a value (a label, a level, true or false) after '==', got '}'"),
    ("condition confidence", 'Aggregate a "x" {\n  Aggregations {\n    all: All d.q With 0.7\n  }\n}\n', 4, 23, "expected 'Confidence_Above' after 'With', got '0.7'"),
    ("condition probability", 'Aggregate a "x" {\n  Aggregations {\n    all: All d.q With Confidence_Above high\n  }\n}\n', 4, 40, "expected a probability after 'Confidence_Above', such as 0.7, got 'high'"),
    ("script path", 'Execute e "x" {\n  Run_Script\n  Produce o: string\n}\n', 4, 3, "expected the script's path after 'Run_Script', got 'Produce'"),
    ("use path", 'Execute e "x" {\n  Use\n}\n', 4, 1, "expected a file path after 'Use', got '}'"),
    # `python` stands where a string may: a named string. The stray word after it is the error.
    ("command string", 'Execute e "x" {\n  Command python x.py\n}\n', 3, 18, "expected a clause of Execute (Read, Run_Script, Command, Use, Produce, Next_Step, Continue, Again), got 'x.py'"),
    ("command missing", 'Execute e "x" {\n  Command\n}\n', 4, 1, "expected the command, a string, got '}'"),
    ("for over", "For f items As item {\n}\n", 2, 7, "expected 'Over' after 'For f', got 'items'"),
    ("for as", "For f Over items item {\n}\n", 2, 18, "expected 'As' to name the item, got 'item'"),
    ("for option", "For f Over items As item, Until x {\n}\n", 2, 27, "expected '{' to open the loop, or one of At_Most, Collect, got 'Until'"),
    ("collect into", "For f Over items As item, Collect out {\n}\n", 2, 39, "expected 'Into' after 'Collect out', got '{'"),
    ("at most number", "For f Over items As item, At_Most many {\n}\n", 2, 35, "expected a whole number after 'At_Most', got 'many'"),
    ("loop mode", "Loop l {\n}\n", 2, 8, "expected 'Until <condition>', 'Over <list> As <item>' or '<n> Times' after 'Loop l', got '{'"),
    ("loop times", "Loop l 3 {\n}\n", 2, 10, "expected 'Times' after the number of passes, got '{'"),
    ("loop option", "Loop l 3 Times, Else_Fail {\n}\n", 2, 17, "expected '{' to open the loop, or one of At_Most, got 'Else_Fail'"),
    ("loop body item", "Loop l 3 Times {\n  x = \"y\"\n}\n", 3, 3, "expected a step, a loop, or the loop's exit ('Next_Step <step>' or 'Continue'), got 'x'"),
    ("loop exit last", "Loop l 3 Times {\n  Next_Step a\n  Task_Agent t \"x\" { Read m  Produce o: string  Continue }\n}\n", 4, 3, "expected '}': the loop's exit is the last line of its block, got 'Task_Agent'"),
    ("loop unclosed", "Loop l 3 Times {\n", 3, 1, "expected '}' to close the loop l, got the end of the file"),
    ("unterminated string", 'a = "never closed\n', 2, 5, "unterminated string"),
    ("stray character", "Start \"s\" { m: string @ }\n", 2, 23, "unexpected character '@'"),
]


class SyntaxErrors(unittest.TestCase):
    def test_each_error_names_its_position_and_what_was_expected(self):
        for name, body, line, column, fragment in CASES:
            with self.subTest(name):
                text = body if name == "no procedure" or name.startswith("procedure") else PREFIX + body
                with self.assertRaises(ParseError) as caught:
                    parse(text, "procedure.aip")
                error = caught.exception
                self.assertEqual((error.line, error.column), (line, column), f"{name}: {error}")
                self.assertIn(fragment, error.message, name)
                self.assertTrue(str(error).startswith(f"procedure.aip:{line}:{column}: "), str(error))

    def test_diagnostic_shape(self):
        with self.assertRaises(ParseError) as caught:
            parse('Procedure p "x"\nDecide d {}\n', "p/procedure.aip")
        diagnostic = caught.exception.to_diagnostic()
        self.assertEqual(set(diagnostic), {"code", "severity", "message", "file", "line", "column", "end_line", "end_column", "step"})
        self.assertEqual((diagnostic["code"], diagnostic["severity"], diagnostic["file"], diagnostic["line"], diagnostic["column"]),
                         ("syntax_error", "error", "p/procedure.aip", 2, 10))
        self.assertEqual((diagnostic["end_line"], diagnostic["end_column"]), (2, 11), "the span covers the offending token")

    def test_without_a_file_the_message_starts_with_the_position(self):
        with self.assertRaises(ParseError) as caught:
            parse("")
        self.assertEqual(str(caught.exception), "1:1: expected 'Procedure <name>' to open the file, got the end of the file")


if __name__ == "__main__":
    unittest.main()
