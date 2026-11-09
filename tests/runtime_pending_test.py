"""The 0.8 server tests and the runtime-skill test wait for the milestones that rewrite those
layers (S1, K1); see `conftest.py`. The engine's tests are `test_engine.py`, the CLI's and the
SDK's `test_cli_json.py` and `test_sdk.py`. The language's commands under `aip` are checked
here so the command stays importable even where Relate is missing."""

import contextlib
import io
import unittest

import pytest

from aip.client.cli import main


@pytest.mark.skip(reason="the 0.8 server tests (tests/server) and the runtime-skill test are not collected: they drive the 0.8 "
                         "server and skill, which S1 and K1 replace (plan aip-dev#1)")
def test_server_and_skill_pending():
    pass


class AipLanguageCommands(unittest.TestCase):
    def test_aip_compile_checks_every_example_clean(self):
        from aip.compiler import example_dir, example_names

        for name in example_names():
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main(["compile", "--check", str(example_dir(name))])
            self.assertEqual(code, 0, err.getvalue())
            self.assertTrue(out.getvalue().startswith("ok "), out.getvalue())
            self.assertNotIn("error", err.getvalue())

    def test_aip_fmt_checks_the_examples(self):
        from aip.compiler import example_dir, example_names

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["fmt", "--check", *(str(example_dir(n)) for n in example_names())])
        self.assertIn(code, (0, 1), out.getvalue())
        self.assertEqual(out.getvalue().count("\n"), len(example_names()), "one line per example")

    def test_version_names_the_language(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["--version"]), 0)
        self.assertRegex(out.getvalue(), r"^aip \d+\.\d+\.\d+ language 0\.9\n$")

    def test_help_and_unknown_command(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main([]), 0)
        self.assertIn("run", out.getvalue())
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(main(["validate", "x"]), 2)
        self.assertIn("unknown command", err.getvalue())
