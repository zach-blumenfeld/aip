"""The 0.8 CLI, SDK and server tests wait for the milestones that rewrite those layers; see
`conftest.py`. The engine's tests are `test_engine.py`. What already works under the `aip`
command is the language's `compile` and `fmt`, tested here so the command stays importable."""

import contextlib
import io
import unittest

import pytest

from aip.client.cli import main


@pytest.mark.skip(reason="the 0.8 CLI, SDK, runner and server tests are not collected: they drive the 0.8 commands over the "
                         "0.8 model, which R1 replaced; R3 and S1 rewrite them (plan aip-dev#1)")
def test_cli_and_server_pending():
    pass


class AipLanguageCommands(unittest.TestCase):
    def test_aip_compile_checks_every_example_clean(self):
        from aip_spec import example_dir, example_names

        for name in example_names():
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main(["compile", "--check", str(example_dir(name))])
            self.assertEqual(code, 0, err.getvalue())
            self.assertTrue(out.getvalue().startswith("ok "), out.getvalue())
            self.assertNotIn("error", err.getvalue())

    def test_aip_fmt_checks_the_examples(self):
        from aip_spec import example_dir, example_names

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["fmt", "--check", *(str(example_dir(n)) for n in example_names())])
        self.assertIn(code, (0, 1), out.getvalue())
        self.assertEqual(out.getvalue().count("\n"), 4)

    def test_version_names_the_language(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["--version"]), 0)
        self.assertRegex(out.getvalue(), r"^aip \d+\.\d+\.\d+ language 0\.9\n$")
