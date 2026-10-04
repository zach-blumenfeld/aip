"""Tests for the `aip-runtime` meta-skill (M5): the one page an agent reads to run published
procedures through the client. It is a plain Agent Skill, so its frontmatter must pass the
Agent Skills rules; every `aip <command>` it names must exist; the copy shipped in the
package must match the one in the repo; and `aip runtime --skill` must write it out."""

import io
import re
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from aip.client.cli import COMMANDS, main
from aip.spec import FORMAT_VERSION, runtime_skill_text
from aip.spec.skill import check_frontmatter, parse_skill_md

REPO = Path(__file__).parent.parent
SKILL_DIR = REPO / "skills" / "aip-runtime"
SKILL_MD = SKILL_DIR / "SKILL.md"
FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)
COMMAND_REF = re.compile(r"\baip (?:--)?([a-z][a-z-]*)")
MAX_LINES = 120


def frontmatter_and_body() -> tuple[dict, str]:
    import yaml

    match = FRONTMATTER.match(SKILL_MD.read_text())
    assert match, "SKILL.md must begin with YAML frontmatter"
    return yaml.safe_load(match.group(1)), match.group(2)


class TestRuntimeSkill(unittest.TestCase):
    def test_frontmatter_passes_agent_skills_rules(self):
        frontmatter, _ = frontmatter_and_body()
        issues = list(check_frontmatter(frontmatter, SKILL_DIR))
        self.assertEqual(issues, [], [i.to_record() for i in issues])
        self.assertEqual(frontmatter["name"], "aip-runtime")
        self.assertEqual(frontmatter["metadata"]["aip-version"], FORMAT_VERSION, "the meta-skill is versioned with the format")

    def test_description_triggers_on_the_design_words(self):
        frontmatter, _ = frontmatter_and_body()
        description = frontmatter["description"].lower()
        for word in ("procedure", "runbook", "workflow", "aip"):
            self.assertIn(word, description)

    def test_is_not_an_aip_procedure(self):
        """A plain Agent Skill: no runtime block, no YAML procedure. The procedure parser rejects it."""
        doc, issues = parse_skill_md(SKILL_MD)
        self.assertIsNone(doc)
        self.assertEqual([i.kind for i in issues], ["missing_runtime_block"])

    def test_every_named_command_exists(self):
        _, body = frontmatter_and_body()
        named = set(COMMAND_REF.findall(body))
        self.assertTrue(named, "the skill should name at least one aip command")
        unknown = {c for c in named if c not in COMMANDS and c != "help"}
        self.assertEqual(unknown, set(), f"commands named in the skill that `aip` does not have: {sorted(unknown)}")
        for required in ("search", "info", "run", "resume", "config"):
            self.assertIn(required, named, f"the loop needs `aip {required}`")

    def test_under_the_line_budget(self):
        lines = SKILL_MD.read_text().count("\n")
        self.assertLess(lines, MAX_LINES, f"skills/aip-runtime/SKILL.md is {lines} lines; the design says under {MAX_LINES}")

    def test_package_copy_matches_repo_copy(self):
        self.assertEqual(runtime_skill_text(), SKILL_MD.read_text(),
                         "src/aip/spec/aip-runtime/SKILL.md and skills/aip-runtime/SKILL.md have drifted; copy one over the other")

    def test_runtime_skill_prints_it(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["runtime", "--skill"])
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue(), SKILL_MD.read_text())

    def test_runtime_skill_out_writes_a_skills_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with redirect_stdout(out):
                code = main(["runtime", "--skill", "--out", tmp])
            self.assertEqual(code, 0)
            written = Path(tmp) / "aip-runtime" / "SKILL.md"
            self.assertTrue(written.is_file())
            self.assertEqual(written.read_text(), SKILL_MD.read_text())
            self.assertIn(str(written), out.getvalue())
            # The written copy is itself a valid Agent Skill folder: name matches its folder.
            frontmatter, _ = frontmatter_and_body()
            self.assertEqual(list(check_frontmatter(frontmatter, written.parent)), [])

    def test_out_requires_skill(self):
        with tempfile.TemporaryDirectory() as tmp, redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as ctx:
            main(["runtime", "--out", tmp])
        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
