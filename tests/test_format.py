"""The formatter and `aip fmt`: canonical spelling and layout, idempotence, the exit codes."""

import contextlib
import io
import unittest
from pathlib import Path

from aip.compiler import format_program, format_source, parse
from aip.client.cli import main

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "language"

MESSY = """# a comment
procedure   messy   "A messy file."
    trigger_when "one"   "two"
    requires python 3.12
q = "Is it?"
start "s" {
    input item: array "the items"
        n:   integer
    next   each }
for_each each over item as it max 3 collect verdict into verdicts {
decide d "d" { reads it
questions {   yes:  true_or_false q
   true: "it is"
   maybe_longer: choice [a,b] "which"  }
history true  produces verdict  next_pass }
    next end
}
End "e" { read verdicts  }
"""

CANONICAL = """# a comment
Procedure messy
  "A messy file."

  Use_When
    "one"
    "two"
  Requires python 3.12

q = "Is it?"

Start "s" {
  item: list "the items"
  n: integer
  Next_Step each
}

For each Over item As it, At_Most 3, Collect verdict Into verdicts {
  Decide d "d" {
    Read it
    Answer_Questions {
      yes:          true_or_false q
        true: "it is"
      maybe_longer: choice [a, b] "which"
    }
    History true
    Produce verdict
    Continue
  }

  Next_Step end
}

End "e" {
  Read verdicts
}
"""


class Canonical(unittest.TestCase):
    def test_messy_input_becomes_canonical(self):
        self.assertEqual(format_source(MESSY), CANONICAL)
        self.assertEqual(parse(CANONICAL), parse(MESSY))
        self.assertEqual(format_source(CANONICAL), CANONICAL)

    def test_the_examples_are_canonical(self):
        """The shipped examples are in the formatter's form, so `aip fmt --check` on them passes
        (CI runs it) and formatting one never changes its bundle id."""
        files = sorted(EXAMPLES.glob("*/procedure.aip"))
        self.assertEqual(len(files), 9)
        for file in files:
            with self.subTest(file.parent.name):
                before = file.read_text(encoding="utf-8")
                self.assertEqual(format_source(before), before)

    def test_route_branches_align_and_check_comes_as_written(self):
        text = format_source('Procedure p "x"\nRoute r "x" {\nRead d.tone\nConfidence_Below 0.6 -> a\nangry -> a\ncalm -> b\n}\n')
        self.assertIn("  Confidence_Below 0.6 -> a\n  angry -> a\n  calm  -> b\n", text)

    def test_produce_continues_aligned_under_the_first_key(self):
        text = format_source('Procedure p "x"\nExecute e "x" {\nRead m\nRun_Script s.py\nProduce a: string "A", b: integer\nNext_Step end\n}\n')
        self.assertIn('  Produce a: string "A"\n          b: integer\n', text)
        nested = format_source('Procedure p "x"\nLoop l 2 Times {\nExecute e "x" {\nRun_Script s.py\nProduce reply: string, queue: string\nContinue\n}\nNext_Step end\n}\n')
        self.assertIn('    Produce reply: string\n            queue: string\n', nested, "under the first key at any depth")
        columns = format_source('Procedure p "x"\nExecute e "x" {\nRun_Script s.py\nProduce ticket_id: integer "The ticket.", queue: string "The queue."\nNext_Step end\n}\n')
        self.assertIn('  Produce ticket_id: integer "The ticket."\n          queue:     string  "The queue."\n', columns,
                      "the types line up, and the descriptions")

    def test_named_strings_may_open_the_file_and_stay_there(self):
        above = ('q = "Is it about a charge?"\nlonger_name = "Angry means threats or demands."\n\n'
                 '# the procedure\nProcedure p\n  "x"\n\nStart "s" {\n  m: string\n  Next_Step d\n}\n\n'
                 'Decide d "d" {\n  Read m\n  Answer_Questions {\n    billing: true_or_false q\n    tone: choice [angry, calm] longer_name\n  }\n'
                 '  Produce dec\n  Next_Step end\n}\n\nEnd "e" {\n  Read dec\n}\n')
        program = parse(above)
        self.assertEqual(sorted(program.named_strings), ["longer_name", "q"])
        self.assertTrue(all(ns.before_header for ns in program.named_strings.values()))
        formatted = format_program(program)
        self.assertTrue(formatted.startswith('q           = "Is it about a charge?"\nlonger_name = "Angry means threats or demands."\n\n# the procedure\nProcedure p'), formatted)
        self.assertEqual(format_program(parse(formatted)), formatted)
        below = parse(formatted.split("\n\n", 1)[1] + "\n" + formatted.split("\n\n", 1)[0] + "\n")
        self.assertFalse(any(ns.before_header for ns in below.named_strings.values()), "below the header they stay below")

    def test_a_labelled_produce_round_trips(self):
        source = ('Procedure p "x"\nTask t "x" {\nRead m\nProduce tone: choice [angry,calm] "T", level: score [low, high]\nNext_Step end\n}\n'
                  'Start "s" { kind: choice [a, b] "K"  Next_Step t }\n')
        text = format_source(source)
        self.assertIn('  Produce tone:  choice [angry, calm] "T"\n          level: score [low, high]\n', text,
                      "continuation lines sit under the first key, the types under each other")
        self.assertIn('  kind: choice [a, b] "K"\n', text)
        self.assertEqual(parse(text), parse(source))
        self.assertEqual(format_source(text), text)

    def test_named_strings_group_and_align(self):
        text = format_source('Procedure p "x"\nshort = "a"\nmuch_longer = "b"\n\nStart "s" { m: string  Next_Step end }\nlast = "c"\n')
        self.assertIn('short       = "a"\nmuch_longer = "b"\n\nStart "s"', text)
        self.assertTrue(text.endswith('}\n\nlast = "c"\n'))

    def test_strings_are_written_as_the_author_wrote_them(self):
        text = format_source('Procedure p "x"\na = """multi\nline"""\nb = "with \\"escapes\\""\n')
        self.assertIn('a = """multi\nline"""\n', text)
        self.assertIn('b = "with \\"escapes\\""\n', text)

    def test_a_path_with_spaces_is_quoted(self):
        text = format_source('Procedure p "x"\nExecute e "x" {\nRead m\nRun_Script "my scripts/run.py"\nNext_Step end\n}\n')
        self.assertIn('Run_Script "my scripts/run.py"', text)

    def test_particle_is_kept(self):
        text = format_source('Procedure p "x"\nTask w/ t "x" {\nRead m\nProduce o: string\nNext_Step end\n}\nRoute on r "x" {\nRead o\ntrue -> end\n}\n')
        self.assertIn("Task_Agent With t", text)
        self.assertIn("Route On r", text)


@contextlib.contextmanager
def _stdin(text):
    import sys

    saved, sys.stdin = sys.stdin, io.StringIO(text)
    try:
        yield
    finally:
        sys.stdin = saved


class FmtCommand(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_check_then_write(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "messy"
            folder.mkdir()
            (folder / "procedure.aip").write_text(MESSY, encoding="utf-8")
            code, out, _ = self.run_cli("fmt", "--check", str(folder))
            self.assertEqual((code, out), (1, f"would reformat {folder / 'procedure.aip'}\n"))
            self.assertEqual((folder / "procedure.aip").read_text(encoding="utf-8"), MESSY, "--check writes nothing")
            code, out, _ = self.run_cli("fmt", str(folder))
            self.assertEqual((code, out), (0, f"formatted {folder / 'procedure.aip'}\n"))
            self.assertEqual((folder / "procedure.aip").read_text(encoding="utf-8"), CANONICAL)
            code, out, _ = self.run_cli("fmt", "--check", str(folder / "procedure.aip"))
            self.assertEqual((code, out), (0, f"unchanged {folder / 'procedure.aip'}\n"))

    def test_parse_error_names_the_position(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "procedure.aip"
            file.write_text('Procedure p "x"\nDecide d {}\n', encoding="utf-8")
            code, out, err = self.run_cli("fmt", str(file))
            self.assertEqual(code, 1)
            self.assertIn(f"{file}:2:10: expected the description of d, a string, got '{{'", err)
            self.assertIn("1 file(s) did not parse", err)

    def test_stdin_prints_the_canonical_form(self):
        """An editor formats a buffer it holds (the console's Studio, plan C2): the text in, the
        canonical form out, the file untouched; a buffer that does not parse prints nothing."""
        with _stdin(MESSY):
            code, out, err = self.run_cli("fmt", "--stdin")
        self.assertEqual((code, out, err), (0, CANONICAL, ""))
        with _stdin('Procedure p "x"\nDecide d {}\n'):
            code, out, err = self.run_cli("fmt", "--stdin")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("2:10: expected the description of d, a string", err)
        with self.assertRaises(SystemExit) as raised, contextlib.redirect_stderr(io.StringIO()):
            self.run_cli("fmt")
        self.assertEqual(raised.exception.code, 2, "a PATH or --stdin")

    def test_a_directory_of_programs_is_every_program_in_it(self):
        code, out, _ = self.run_cli("fmt", "--check", str(EXAMPLES))
        self.assertEqual(code, 0, out)
        self.assertEqual(out.count("unchanged "), 9,"aip fmt --check examples/language is what CI runs")

    def test_missing_path(self):
        code, _, err = self.run_cli("fmt", "/nonexistent/folder")
        self.assertEqual(code, 2)
        self.assertIn("not found", err)

    def test_version_and_help(self):
        from importlib.metadata import version

        code, out, err = self.run_cli("--version")
        self.assertEqual((code, out, err), (0, f"aip {version('agent-instruction-protocol')} language 0.9\n", ""),
                         "one package, one version line")
        code, out, _ = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("fmt", out)
        self.assertEqual(self.run_cli("nope")[0], 2)

    def test_examples_round_trip_through_the_command(self):
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            for example in sorted(EXAMPLES.iterdir()):
                shutil.copytree(example, Path(tmp) / example.name)
            code, out, _ = self.run_cli("fmt", *(str(Path(tmp) / e.name) for e in sorted(EXAMPLES.iterdir())))
            self.assertEqual(code, 0, out)
            for example in sorted(EXAMPLES.iterdir()):
                before = (example / "procedure.aip").read_text(encoding="utf-8")
                after = (Path(tmp) / example.name / "procedure.aip").read_text(encoding="utf-8")
                self.assertEqual(parse(after), parse(before), example.name)
                self.assertEqual(format_program(parse(after)), after, "the second format changes nothing")


if __name__ == "__main__":
    unittest.main()
