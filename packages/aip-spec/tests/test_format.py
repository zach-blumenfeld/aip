"""The formatter and `aip-spec fmt`: canonical spelling and layout, idempotence, the exit codes."""

import contextlib
import io
import unittest
from pathlib import Path

from aip_spec import format_program, format_source, parse
from aip_spec.cli import main

EXAMPLES = Path(__file__).resolve().parents[3] / "examples" / "language"

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
questions {   yes:  noul q
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

    def test_examples_are_canonical_or_nearly(self):
        """Formatting an example changes alignment, blank lines, the layout of a `Produce` list
        and the spelling of an alias; every word survives in order."""
        for file in sorted(EXAMPLES.glob("*/procedure.aip")):
            with self.subTest(file.parent.name):
                before = file.read_text(encoding="utf-8")
                after = format_source(before)
                words = lambda text: text.replace(",", " ").replace("Task draft", "Task_Agent draft").split()
                self.assertEqual(words(before), words(after))

    def test_route_branches_align_and_check_comes_as_written(self):
        text = format_source('Procedure p "x"\nRoute r "x" {\nRead d.tone\nConfidence_Below 0.6 -> a\nangry -> a\ncalm -> b\n}\n')
        self.assertIn("  Confidence_Below 0.6 -> a\n  angry -> a\n  calm  -> b\n", text)

    def test_produce_continues_aligned_under_the_first_key(self):
        text = format_source('Procedure p "x"\nExecute e "x" {\nRead m\nRun_Script s.py\nProduce a: string "A", b: integer\nNext_Step end\n}\n')
        self.assertIn('  Produce a: string "A"\n          b: integer\n', text)

    def test_a_labelled_produce_round_trips(self):
        source = ('Procedure p "x"\nTask t "x" {\nRead m\nProduce tone: choice [angry,calm] "T", level: score [low, high]\nNext_Step end\n}\n'
                  'Start "s" { kind: choice [a, b] "K"  Next_Step t }\n')
        text = format_source(source)
        self.assertIn('  Produce tone: choice [angry, calm] "T"\n          level: score [low, high]\n', text)
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

    def test_missing_path(self):
        code, _, err = self.run_cli("fmt", "/nonexistent/folder")
        self.assertEqual(code, 2)
        self.assertIn("not found", err)

    def test_version_and_help(self):
        self.assertEqual(self.run_cli("--version"), (0, "0.9\n", ""))
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
