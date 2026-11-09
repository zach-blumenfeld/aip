"""The 0.8 runtime's tests wait for the 0.9 runtime; see `conftest.py`. What already works is
the language's `fmt` under the `aip` command, tested here so the command stays importable."""

import contextlib
import io
import unittest

import pytest

from aip.client.cli import main


@pytest.mark.skip(reason="the 0.8 runtime does not load since aip_spec dropped the 0.8 format (plan L1); "
                         "R1 replaces src/aip/model and src/aip/spec and brings tests/ back")
def test_runtime_pending():
    pass


class AipFmt(unittest.TestCase):
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
