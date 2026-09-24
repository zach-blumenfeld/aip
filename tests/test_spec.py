"""Tests for the procedure format: spec models, generated schema, skill validation, loader.

Run with: uv run python -m unittest tests.test_spec
"""

import contextlib
import copy
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml
from pydantic import ValidationError
from typesafe_sdk import SystemOneResponse

from aip.client.cli import validate_command
from aip.spec import FORMAT_VERSION, ProcedureSpec, check_graph, json_schema, parse_skill_md, validate_skill
from aip.spec.loader import load_procedure
from aip.spec.models import DecisionStep, ProcedureSpec as Spec, Strict

REPO = Path(__file__).parent.parent
EXAMPLE = REPO / "examples" / "billing-support"
SCHEMA_FILE = REPO / "assets" / "procedure.schema.json"


def example_yaml() -> dict:
    doc, issues = parse_skill_md(EXAMPLE / "SKILL.md")
    assert not issues, issues
    return yaml.safe_load(doc.yaml_text)


def kinds(issues) -> list[str]:
    return [i.kind for i in issues]


def copy_example(tmp: str) -> Path:
    skill = Path(tmp) / "billing-support"
    shutil.copytree(EXAMPLE, skill)
    return skill


def rewrite(skill: Path, old: str, new: str) -> None:
    md = skill / "SKILL.md"
    text = md.read_text()
    assert old in text, old
    md.write_text(text.replace(old, new))


class GeneratedSchema(unittest.TestCase):
    def test_committed_schema_is_in_sync_with_models(self):
        self.assertEqual(json.loads(SCHEMA_FILE.read_text()), json_schema(),
                         "assets/procedure.schema.json is stale; run `uv run aip schema --write assets/procedure.schema.json`")

    def test_schema_metadata(self):
        schema = json_schema()
        self.assertEqual(schema["title"], "Procedure")
        self.assertEqual(schema["aip"]["version"], FORMAT_VERSION)
        self.assertIn(FORMAT_VERSION, schema["$id"])
        self.assertFalse(schema["additionalProperties"])

    def test_every_field_is_described(self):
        missing = []
        seen = set()

        def walk(model):
            if model in seen:
                return
            seen.add(model)
            for name, field in model.model_fields.items():
                if not field.description and name not in ("name", "inputs"):  # described on the shared alias
                    missing.append(f"{model.__name__}.{name}")
                for sub in Strict.__subclasses__():
                    walk(sub)

        walk(Spec)
        self.assertEqual(missing, [])

    def test_every_object_is_closed(self):
        schema = json_schema()
        for name, definition in schema["$defs"].items():
            if definition.get("type") == "object" or "properties" in definition:
                self.assertIs(definition.get("additionalProperties"), False, name)


class SpecModels(unittest.TestCase):
    def test_example_parses(self):
        spec = ProcedureSpec.model_validate(example_yaml())
        self.assertEqual([s.kind for s in spec.steps], ["decision", "router", "execution", "client_task", "end"])
        self.assertIsInstance(spec.start, DecisionStep)
        self.assertEqual(spec.step("by-tone").branches, {"angry": "escalate", "calm": "reply"})

    def test_unknown_kind_rejected(self):
        body = example_yaml()
        body["steps"][0]["kind"] = "magic"
        with self.assertRaises(ValidationError):
            ProcedureSpec.model_validate(body)

    def test_unknown_key_rejected(self):
        body = example_yaml()
        body["steps"][0]["depends_on"] = ["x"]
        with self.assertRaises(ValidationError):
            ProcedureSpec.model_validate(body)

    def test_resource_prefix_enforced(self):
        body = example_yaml()
        body["steps"][2]["script"] = "escalate.py"
        with self.assertRaises(ValidationError):
            ProcedureSpec.model_validate(body)

    def test_noul_criteria_accepts_bare_yaml_booleans(self):
        step = yaml.safe_load("""
name: t
kind: decision
description: d
inputs: []
questions:
  has_pii:
    type: noul
    instructions: Does the message contain personal data?
    criteria:
      true: Identifiers appear.
      false: None appear.
inputs_to: end
""")
        parsed = DecisionStep.model_validate(step)
        self.assertEqual(parsed.questions["has_pii"].criteria.true, "Identifiers appear.")
        self.assertEqual(parsed.questions["has_pii"].criteria.false, "None appear.")

    def test_router_needs_two_branches(self):
        body = example_yaml()
        body["steps"][1]["branches"] = {"angry": "escalate"}
        with self.assertRaises(ValidationError):
            ProcedureSpec.model_validate(body)


class GraphChecks(unittest.TestCase):
    def setUp(self):
        self.body = example_yaml()

    def spec(self) -> ProcedureSpec:
        return ProcedureSpec.model_validate(self.body)

    def step(self, name: str) -> dict:
        return next(s for s in self.body["steps"] if s["name"] == name)

    def test_example_is_clean(self):
        self.assertEqual(check_graph(self.spec(), "x", EXAMPLE), [])

    def test_duplicate_step_name(self):
        self.body["steps"].append(copy.deepcopy(self.step("reply")))
        self.assertIn("duplicate_step_name", kinds(check_graph(self.spec(), "x")))

    def test_start_must_be_runnable(self):
        steps = self.body["steps"]
        steps.insert(0, steps.pop(1))
        self.assertIn("invalid_start_step", kinds(check_graph(self.spec(), "x")))

    def test_missing_end(self):
        self.body["steps"] = [s for s in self.body["steps"] if s["kind"] != "end"]
        found = kinds(check_graph(self.spec(), "x"))
        self.assertIn("missing_end_step", found)
        self.assertIn("unknown_step_reference", found)

    def test_multiple_ends(self):
        self.body["steps"].append({"name": "end-2", "kind": "end", "inputs": []})
        self.assertIn("multiple_end_steps", kinds(check_graph(self.spec(), "x")))

    def test_unknown_router_target(self):
        self.step("by-tone")["branches"]["angry"] = "nowhere"
        issues = check_graph(self.spec(), "x")
        self.assertIn("unknown_step_reference", kinds(issues))
        self.assertIn("unreachable_step", kinds(issues))  # escalate is now orphaned

    def test_no_path_to_end(self):
        self.step("escalate")["inputs_to"] = "escalate"
        self.assertIn("no_path_to_end", kinds(check_graph(self.spec(), "x")))

    def test_duplicate_input_name(self):
        self.step("triage")["inputs"].append({"name": "message", "type": "string"})
        self.assertIn("duplicate_input_name", kinds(check_graph(self.spec(), "x")))

    def test_threshold_must_name_a_question(self):
        self.step("triage")["thresholds"]["mood"] = 0.5
        self.assertIn("unknown_threshold_question", kinds(check_graph(self.spec(), "x")))

    def test_missing_resource_only_with_skill_dir(self):
        self.step("escalate")["assets"] = ["assets/nope.json"]
        self.assertEqual(check_graph(self.spec(), "x"), [])
        self.assertEqual(kinds(check_graph(self.spec(), "x", EXAMPLE)), ["missing_resource"])


class SkillFolder(unittest.TestCase):
    def test_example_is_valid(self):
        loaded, issues = validate_skill(EXAMPLE)
        self.assertEqual(issues, [])
        self.assertEqual(loaded.frontmatter["name"], "billing-support")

    def test_no_prose_around_the_block(self):
        for label, mutate in {
            "after": lambda t: t + "\ntrailing prose\n",
            "before": lambda t: t.replace("---\n\n```yaml", "---\n\nSome intro.\n\n```yaml"),
        }.items():
            with self.subTest(label), tempfile.TemporaryDirectory() as tmp:
                skill = copy_example(tmp)
                md = skill / "SKILL.md"
                md.write_text(mutate(md.read_text()))
                loaded, issues = validate_skill(skill)
                self.assertIsNone(loaded)
                self.assertEqual(kinds(issues), ["invalid_body_format"])

    def test_frontmatter_rules(self):
        cases = {
            "name_mismatch": ("name: billing-support", "name: other-name"),
            "invalid_name": ("name: billing-support", "name: Billing--Support"),
            "missing_required_frontmatter": ("description: Triage", "descriptionx: Triage"),
            "missing_aip_version": ('aip-version: "0.4a0"', 'other: "x"'),
            "aip_version_mismatch": ('aip-version: "0.4a0"', 'aip-version: "0.3a3"'),
            "invalid_metadata": ('aip-version: "0.4a0"', 'aip-version: "0.4a0"\n  nested:\n    a: b'),
        }
        for expected, (old, new) in cases.items():
            with self.subTest(expected), tempfile.TemporaryDirectory() as tmp:
                skill = copy_example(tmp)
                rewrite(skill, old, new)
                _, issues = validate_skill(skill)
                self.assertIn(expected, kinds(issues))

    def test_source_dir_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = copy_example(tmp)
            shutil.rmtree(skill / "source")
            _, issues = validate_skill(skill)
            self.assertIn("missing_source_dir", kinds(issues))

    def test_schema_violation_is_path_addressed(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = copy_example(tmp)
            rewrite(skill, "    branch_on: tone\n", "    on: tone\n")
            _, issues = validate_skill(skill)
            self.assertEqual(kinds(issues), ["schema_violation", "schema_violation"])
            self.assertTrue(all(i.location.startswith("body:$.steps[1]") for i in issues), [i.location for i in issues])

    def test_cli_validate_output_contract(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = validate_command([str(EXAMPLE)])
        self.assertEqual((code, err.getvalue()), (0, ""))
        self.assertTrue(out.getvalue().startswith("VALID: "))

        with tempfile.TemporaryDirectory() as tmp:
            skill = copy_example(tmp)
            rewrite(skill, "angry: escalate", "angry: nowhere")
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = validate_command([str(skill)])
            self.assertEqual(code, 1)
            records = [json.loads(line) for line in err.getvalue().splitlines()]
            self.assertEqual({r["kind"] for r in records}, {"unknown_step_reference", "unreachable_step"})
            self.assertTrue(out.getvalue().startswith("INVALID: 2 error(s)"))


class FakeJev:
    def system_one(self, state, questions, **_):
        self.questions = questions
        return SystemOneResponse.model_validate_json(json.dumps({
            "model": "jev-1", "usage": {"input_tokens": 1, "output_tokens": 1},
            "answers": {
                "billing": {"type": "noul", "noul": 0.97},
                "tone": {"type": "choice", "choice": "angry", "confidence": 0.9,
                         "probabilities": {"angry": 0.9, "calm": 0.1}},
            }}))


class LoaderEndToEnd(unittest.TestCase):
    def test_example_loads_and_runs_through_the_server_path(self):
        jev = FakeJev()
        proc = load_procedure(EXAMPLE, client=jev)
        self.assertEqual(proc.describe()["steps"],
                         {"triage": "decision", "by-tone": "router", "escalate": "execution", "end": "end", "reply": "client_task"})
        self.assertEqual(proc.meta.name, "billing-support")

        r1 = proc.run(None, {"message": "I was charged twice!"})
        self.assertEqual(set(jev.questions), {"billing", "tone"})
        self.assertEqual(jev.questions["tone"].criteria["angry"], "Frustrated, demanding, or threatening to leave.")
        self.assertEqual(r1.suggested["tone"], "angry")
        self.assertEqual(r1.review, [])
        self.assertEqual(r1.next["branch_on"], "tone")

        r2 = proc.run(r1.ran, r1.suggested, r1.history)  # server routes to escalate and runs the real script
        self.assertEqual((r2.ran, r2.result["queue"]), ("escalate", "tier2"))
        self.assertIn("ticket_id", r2.result)

        r3 = proc.run(r1.ran, {**r1.suggested, "tone": "calm"}, r1.history)  # override -> client task
        self.assertEqual(r3.kind, "client_task")
        self.assertIn("Duplicate charges are refunded in full", r3.result["task"])
        self.assertIn('pertaining to "', r3.result["task"])
        self.assertEqual(r3.result["references"][0]["uri"], "billing-support/references/help.md")

        r4 = proc.run(r2.ran, r2.suggested, r2.history)
        self.assertEqual((r4.ran, r4.next), ("end", None))
        self.assertEqual([h["step"] for h in r4.history], ["triage", "by-tone", "escalate", "end"])

    def test_invalid_skill_raises_with_issues(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = copy_example(tmp)
            rewrite(skill, "angry: escalate", "angry: nowhere")
            with self.assertRaises(ValueError) as ctx:
                load_procedure(skill)
            self.assertIn("unknown_step_reference", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
