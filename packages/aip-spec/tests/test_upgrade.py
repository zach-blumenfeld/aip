"""`aip-spec upgrade`: a skill in an earlier format becomes a format-0.8 skill that validates,
with the layout and comments it had, and the command says what it did and what is left by hand.

Run with: uv run pytest -q
"""

import copy
import io
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml
from aip_spec import FORMAT_VERSION, example_dir, parse_skill_md, runtime_text, validate_skill
from aip_spec.cli import main
from aip_spec.upgrade import CannotUpgrade, upgrade_procedure, upgrade_skill_md, upgraded

EXAMPLE = example_dir("billing-support")
FIXTURES = Path(__file__).parent / "fixtures"
# The example and the dialogue-parser fixture as they were in 0.6a1 (the `v0.7.0` tag), verbatim.
OLD_EXAMPLE = FIXTURES / "billing-support-0.6a1.md"
OLD_DIALOGUE = FIXTURES / "dialogue-graph-0.6a1.yaml"
DIALOGUE = FIXTURES / "dialogue-graph.yaml"


def old_example(tmp: str) -> Path:
    """A copy of the example folder (its scripts, assets, source) with the 0.6a1 SKILL.md."""
    skill = Path(tmp) / "billing-support"
    shutil.copytree(EXAMPLE, skill)
    (skill / "SKILL.md").write_text(OLD_EXAMPLE.read_text())
    return skill


def shape(body: dict) -> dict:
    """A procedure with its input descriptions dropped: the upgrade copies the first step's inputs
    to the start step, descriptions included, where the hand migration moved them."""
    body = copy.deepcopy(body)
    for step in body["steps"]:
        if step["kind"] == "start":
            step.pop("description", None)
        for key in step.get("inputs") or []:
            key.pop("description", None)
    return body


def run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with mock.patch("sys.stdout", new=out), mock.patch("sys.stderr", new=err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


class TheExample(unittest.TestCase):
    def test_round_trip(self):
        """The 0.6a1 example upgraded is the 0.8 example as migrated by hand (up to where the
        input descriptions sit), validates with the one warning the shipped example has, and the
        command lists each change and what is left by hand."""
        with tempfile.TemporaryDirectory() as tmp:
            skill = old_example(tmp)
            code, out, err = run(["upgrade", str(skill)])
            self.assertEqual(code, 0, err)
            text = (skill / "SKILL.md").read_text()
            doc, issues = parse_skill_md(skill / "SKILL.md")
            self.assertEqual(issues, [])
            self.assertEqual(doc.frontmatter["metadata"]["aip-version"], FORMAT_VERSION)
            self.assertIn(runtime_text().strip(), text)
            self.assertNotIn(runtime_text("0.6a1").strip(), text)
            self.assertNotIn("thresholds", text)

            upgraded_body = yaml.safe_load(doc.yaml_text)
            current = yaml.safe_load(parse_skill_md(EXAMPLE / "SKILL.md")[0].yaml_text)
            self.assertEqual(shape(upgraded_body), shape(current))
            old_body = yaml.safe_load(parse_skill_md(OLD_EXAMPLE)[0].yaml_text)
            self.assertEqual(upgraded_body, upgraded(old_body, "start"))
            self.assertEqual(upgraded_body["steps"][0], {
                "name": "start", "kind": "start", "inputs_to": "triage",
                "inputs": [{"name": "message", "type": "string", "description": "The customer's message, verbatim."}]})
            self.assertEqual(upgraded_body["steps"][1]["inputs"], upgraded_body["steps"][0]["inputs"], "the old first step keeps its inputs")

            loaded, issues = validate_skill(skill)
            self.assertIsNotNone(loaded)
            self.assertEqual([(i.kind, i.severity) for i in issues], [("unmeasured_route", "warning")])
            for line in ("0.6a1 -> 0.8", "replaced the 0.6a1 runtime block with the 0.8 block", 'set `metadata.aip-version` to "0.8"',
                         "inserted a `start` step named `start` before `triage`, carrying its 1 input and pointing at it",
                         "`triage`: dropped `thresholds` (billing: 0.15, tone: 0.6)", "`triage`: set `fallback: true`",
                         "by hand:", "add `confidence: [billing, tone]` to the decision",
                         "set `fallback: false` where a decision model is required", "wrote", "VALID (name: billing-support) (1 warning(s)"):
                self.assertIn(line, out)
            self.assertIn('"kind": "unmeasured_route"', err)

    def test_check_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = old_example(tmp)
            code, out, err = run(["upgrade", "--check", str(skill)])
            self.assertEqual(code, 0, err)
            self.assertEqual((skill / "SKILL.md").read_text(), OLD_EXAMPLE.read_text())
            self.assertIn("would write", out)
            self.assertIn("VALID (name: billing-support)", out)
            self.assertNotIn("wrote", out)

    def test_a_current_skill_is_left_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp) / "billing-support"
            shutil.copytree(EXAMPLE, skill)
            before = (skill / "SKILL.md").read_text()
            code, out, _ = run(["upgrade", str(skill)])
            self.assertEqual(code, 0)
            self.assertIn(f"already format {FORMAT_VERSION}; nothing to do", out)
            self.assertIn("unchanged", out)
            self.assertEqual((skill / "SKILL.md").read_text(), before)

    def test_a_result_that_still_fails_is_written_and_reported(self):
        """What the upgrade cannot fix, the validator names; the skill is still rewritten."""
        with tempfile.TemporaryDirectory() as tmp:
            skill = old_example(tmp)
            (skill / "scripts" / "escalate.py").unlink()
            code, out, err = run(["upgrade", str(skill)])
            self.assertEqual(code, 1)
            self.assertIn("INVALID: 1 error(s)", out)
            self.assertIn("the rest is by hand", out)
            self.assertIn('"kind": "missing_resource"', err)
            self.assertIn(runtime_text().strip(), (skill / "SKILL.md").read_text())

    def test_an_unrecognised_skill_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = old_example(tmp)
            text = (skill / "SKILL.md").read_text().replace("# AIP runtime — format 0.6a1", "# Some other block")
            (skill / "SKILL.md").write_text(text)
            code, out, err = run(["upgrade", str(skill)])
            self.assertEqual(code, 2)
            self.assertIn("does not begin with a runtime block this version recognises", err)
            self.assertIn("nothing written", err)
            self.assertEqual((skill / "SKILL.md").read_text(), text)
            self.assertEqual(run(["upgrade", str(Path(tmp) / "nowhere")])[0], 2)

    def test_the_0_5a1_block_is_upgraded_too_and_says_what_that_format_lacked(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = old_example(tmp)
            text = (skill / "SKILL.md").read_text()
            text = text.replace(runtime_text("0.6a1").strip(), runtime_text("0.5a1").strip()).replace('aip-version: "0.6a1"', 'aip-version: "0.5a1"')
            result = upgrade_skill_md(text)
            self.assertEqual(result.version, "0.5a1")
            self.assertIn("replaced the 0.5a1 runtime block with the 0.8 block", result.changes)
            self.assertTrue(any("no `outputs`" in note and "no `requires`" in note for note in result.by_hand), result.by_hand)


class TheProcedure(unittest.TestCase):
    def test_dialogue_fixture_round_trip(self):
        """The fixture as authored (0.5a1, upgraded by hand to 0.8 in S2) and as the upgrade
        rewrites it are the same procedure, and the header comment survives."""
        text, changes, by_hand = upgrade_procedure(OLD_DIALOGUE.read_text())
        self.assertEqual(shape(yaml.safe_load(text)), shape(yaml.safe_load(DIALOGUE.read_text())))
        self.assertTrue(text.startswith("# The procedure block of aip-skillbench's dialogue-parser skill"))
        self.assertEqual(changes, [
            "inserted a `start` step named `start` before `conventions`, carrying its 1 input and pointing at it",
            "`conventions`: dropped `thresholds` (end_node: 0.7, choice_text: 0.7)",
            "`conventions`: set `fallback: true`"])
        self.assertEqual(len(by_hand), 2)
        self.assertNotIn("thresholds", text)

    def test_the_start_name_avoids_a_taken_one_and_fallback_goes_before_inputs_to(self):
        text, changes, _ = upgrade_procedure(
            "steps:\n"
            "  - name: start\n    kind: decision\n    inputs: [{name: x, type: string}]\n"
            "    questions:\n      q:\n        type: noul\n        instructions: Is it?\n"
            "    inputs_to: end  # on to the end\n"
            "  - name: end\n    kind: end\n    inputs: [{name: q, type: boolean}]\n")
        self.assertEqual(changes[0], "inserted a `start` step named `begin` before `start`, carrying its 1 input and pointing at it")
        self.assertIn("    fallback: true\n    inputs_to: end  # on to the end\n", text)
        self.assertEqual(yaml.safe_load(text)["steps"][0], {"name": "begin", "kind": "start", "inputs": [{"name": "x", "type": "string"}], "inputs_to": "start"})

    def test_a_first_step_with_no_inputs_gives_an_empty_start(self):
        text, _, _ = upgrade_procedure("steps:\n  - name: go\n    kind: client_task\n    template: assets/t.md\n    inputs_to: end\n  - name: end\n    kind: end\n    inputs: []\n")
        self.assertEqual(yaml.safe_load(text)["steps"][0], {"name": "start", "kind": "start", "inputs": [], "inputs_to": "go"})

    def test_a_layout_the_line_edits_cannot_follow_is_refused(self):
        for yaml_text, reason in (
            ("steps: [{name: a, kind: end, inputs: []}]\n", "`steps:` is not a block list"),
            ("purpose: x\n", "no `steps` list"),
            ("steps:\n  - {name: a, kind: decision, thresholds: {q: 0.5}, inputs_to: b}\n  - name: b\n    kind: end\n    inputs: []\n",
             "not written as a field of its own line"),
            ("steps:\n  - name: start\n    kind: end\n    inputs: []\n  - name: begin\n    kind: end\n    inputs: []\n", "rename one"),
        ):
            with self.assertRaises(CannotUpgrade, msg=yaml_text) as caught:
                upgrade_procedure(yaml_text)
            self.assertIn(reason, str(caught.exception))
