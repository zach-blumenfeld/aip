"""Tests for the procedure format: spec models, generated schema, skill validation, and the
`aip-spec` CLI. The loader that builds the executable Procedure is tested in the `aip` repo.

Run with: uv run pytest -q
"""

import contextlib
import copy
import io
import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml
from pydantic import ValidationError
from aip_spec import FORMAT_VERSION, ProcedureSpec, check_graph, example_dir, json_schema, parse_skill_md, runtime_text, skill_dir, validate_skill
from aip_spec.cli import main, validate_command
from aip_spec.models import LEGACY_VERSIONS, SCHEMA_ID, SPEC_URL, DecisionStep, ProcedureSpec as Spec, Strict
from aip_spec.skill import UPGRADES, check_frontmatter

REPO = Path(__file__).parent.parent
EXAMPLE = example_dir("billing-support")
SCHEMA_FILE = REPO / "assets" / "procedure.schema.json"
DIALOGUE = Path(__file__).parent / "fixtures" / "dialogue-graph.yaml"


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
                         "assets/procedure.schema.json is stale; run `uv run aip-spec schema --write assets/procedure.schema.json`")

    def test_schema_metadata(self):
        schema = json_schema()
        self.assertEqual(schema["title"], "Procedure")
        self.assertEqual(schema["aip"]["version"], FORMAT_VERSION)
        self.assertIn(FORMAT_VERSION, schema["$id"])
        self.assertEqual((schema["$id"], schema["aip"]["spec"]), (SCHEMA_ID, SPEC_URL))
        self.assertIn("github.com/zach-blumenfeld/aip-spec", SPEC_URL)
        self.assertFalse(schema["additionalProperties"])

    def test_every_field_is_described(self):
        missing = []
        seen = set()

        def walk(model):
            if model in seen:
                return
            seen.add(model)
            for name, field in model.model_fields.items():
                if not field.description and name not in ("name", "inputs", "outputs"):  # described on the shared alias
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


class RuntimeBlock(unittest.TestCase):
    def test_runtime_carries_the_format_version(self):
        self.assertIn(FORMAT_VERSION, runtime_text().splitlines()[0])

    def test_runtime_block_appears_verbatim_in_skill_md(self):
        """The block an authoring agent copies from the aip SKILL.md must be exactly what the validator enforces."""
        skill_md = (REPO / "SKILL.md").read_text()
        self.assertIn(runtime_text().strip(), skill_md,
                      "the runtime block in SKILL.md and src/aip_spec/runtime.md have drifted")


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

    def test_decision_history_is_opt_in(self):
        body = example_yaml()
        self.assertFalse(ProcedureSpec.model_validate(body).start.history)
        body["steps"][0]["history"] = True
        self.assertTrue(ProcedureSpec.model_validate(body).start.history)

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

    def test_router_branch_keys_must_match_the_question(self):
        self.step("by-tone")["branches"] = {"angry": "escalate", "furious": "reply"}
        issues = check_graph(self.spec(), "x")
        self.assertIn("unknown_branch_value", kinds(issues))
        self.assertIn("furious", next(i for i in issues if i.kind == "unknown_branch_value").message)

    def test_router_on_score_expects_level_numbers_as_strings(self):
        triage = self.step("triage")
        triage["questions"]["severity"] = {"type": "score", "instructions": "How bad?",
                                           "criteria": ["cosmetic", "degraded", "unusable"]}
        self.step("by-tone")["branch_on"] = "severity"
        self.step("by-tone")["branches"] = {"0": "reply", "1": "reply", "2": "escalate"}
        self.assertEqual([i.kind for i in check_graph(self.spec(), "x")], [])
        self.step("by-tone")["branches"] = {"low": "reply", "high": "escalate"}
        self.assertEqual(kinds(check_graph(self.spec(), "x")), ["unknown_branch_value", "unknown_branch_value"])

    def test_example_declares_outputs(self):
        spec = self.spec()
        self.assertEqual([o.name for o in spec.step("escalate").outputs], ["ticket_id", "queue"])
        self.assertEqual([o.name for o in spec.step("reply").outputs], ["reply"])

    def test_rule_1_consumed_key_needs_a_producer_on_every_path(self):
        self.step("end")["inputs"].append({"name": "reply", "type": "string"})  # the angry path never drafts one
        issues = check_graph(self.spec(), "x")
        self.assertEqual(kinds(issues), ["unproduced_input"])
        self.assertIn("step `end` consumes `reply`", issues[0].message)
        self.assertIn("start step `triage`", issues[0].message)
        self.step("end")["inputs"].pop()
        self.step("escalate")["inputs"].append({"name": "account_id", "type": "string"})
        self.assertEqual(kinds(check_graph(self.spec(), "x")), ["unproduced_input"])
        self.step("triage")["inputs"].append({"name": "account_id", "type": "string"})  # the client supplies it
        self.assertEqual(check_graph(self.spec(), "x"), [])

    def test_rule_1_router_consumes_its_branch_key(self):
        self.step("by-tone")["branch_on"] = "mood"
        self.step("by-tone")["branches"] = {"angry": "escalate", "calm": "reply"}
        self.assertIn("step `by-tone` consumes `mood`", check_graph(self.spec(), "x")[0].message)

    def test_rule_2_two_steps_producing_tone(self):
        self.step("reply")["outputs"].append({"name": "tone", "type": "string"})
        issues = check_graph(self.spec(), "x")
        self.assertEqual(kinds(issues), ["duplicate_producer"])
        self.assertIn("key `tone` is produced by `triage`, `reply`", issues[0].message)

    def test_rule_2_no_step_overwrites_a_start_input(self):
        self.step("escalate")["outputs"].append({"name": "message", "type": "string"})
        issues = check_graph(self.spec(), "x")
        self.assertEqual(kinds(issues), ["duplicate_producer"])
        self.assertIn("`message` is a start input", issues[0].message)

    def test_rule_4_consumer_type_matches_producer_type(self):
        self.step("end")["inputs"][0]["type"] = "object"           # `message` is a string start input
        issues = check_graph(self.spec(), "x")
        self.assertEqual(kinds(issues), ["type_mismatch"])
        self.assertIn("declares input `message` as `object`, but it is `string` (start input on `triage`)", issues[0].message)
        self.assertEqual(issues[0].location, "body:$.steps[4].inputs[0].type")
        self.step("end")["inputs"][0]["type"] = "string"
        self.step("reply")["inputs"][1]["type"] = "integer"        # `tone` is a choice question: a string
        issues = check_graph(self.spec(), "x")
        self.assertEqual(kinds(issues), ["type_mismatch"])
        self.assertIn("a choice question in `triage`", issues[0].message)
        self.step("reply")["inputs"][1]["type"] = "string"
        self.step("end")["inputs"].append({"name": "ticket_id", "type": "string"})   # escalate outputs an integer
        self.step("reply")["outputs"].append({"name": "ticket_id", "type": "integer"})   # so every path has it
        issues = check_graph(self.spec(), "x")
        self.assertEqual(sorted(kinds(issues)), ["duplicate_producer", "type_mismatch"])
        self.assertIn("output of `escalate`", next(i for i in issues if i.kind == "type_mismatch").message)

    def test_rule_3_client_task_must_declare_outputs(self):
        del self.step("reply")["outputs"]
        issues = check_graph(self.spec(), "x")
        self.assertEqual(kinds(issues), ["missing_outputs"])
        self.assertIn("client_task `reply`", issues[0].message)

    def test_duplicate_output_name(self):
        self.step("escalate")["outputs"].append({"name": "queue", "type": "string"})
        self.assertIn("duplicate_output_name", kinds(check_graph(self.spec(), "x")))

    def test_dialogue_parser_skill_fails_rule_1(self):
        """aip-skillbench's dialogue-parser skill reads four paths no step supplies. With outputs
        added where its scripts and tasks plainly produce them, rule 1 is all that remains."""
        body = yaml.safe_load(DIALOGUE.read_text())
        steps = {s["name"]: s for s in body["steps"]}
        self.assertEqual(kinds(check_graph(ProcedureSpec.model_validate(body), "x")).count("missing_outputs"), 2)  # repair, deliver
        delivered = [i for i in steps["deliver"]["inputs"] if i["name"] not in ("task_instructions", "script_path")]
        steps["build"]["outputs"] = [*delivered, {"name": "errors", "type": "list[*]"}, {"name": "warnings", "type": "list[*]"}]
        steps["repair"]["outputs"] = [{"name": "repair_notes", "type": "string"}]
        steps["deliver"]["outputs"] = [{"name": "deliverables", "type": "list[*]"}, {"name": "summary", "type": "string"}]
        body["requires"] = {"interpreter": {"name": "python", "version": "3.10"}}  # B2, not under test here
        issues = check_graph(ProcedureSpec.model_validate(body), "x")
        self.assertEqual(set(kinds(issues)), {"unproduced_input"})
        build = next(i for i in issues if "step `build`" in i.message)
        self.assertIn("consumes `script_path`, `output_json`, `dot_path`, `image_path`, which no step produces", build.message)

    def test_scripts_need_requires(self):
        del self.body["requires"]
        issues = check_graph(self.spec(), "x")
        self.assertEqual(kinds(issues), ["missing_requires"])
        self.assertIn("runs scripts (`escalate`) but declares no `requires`", issues[0].message)
        self.body["steps"] = [s for s in self.body["steps"] if s["kind"] != "execution"]
        self.step("by-tone")["branches"]["angry"] = "reply"
        self.assertEqual(check_graph(self.spec(), "x"), [])  # no scripts, nothing to require

    def test_requires_shape(self):
        self.assertEqual(self.spec().requires.interpreter.version, "3.10")
        self.body["requires"] = {"interpreter": {"name": "python", "version": "3.10"},
                                 "packages": ["numpy", "scikit-learn>=1.3"], "tools": ["git"]}
        self.assertEqual(self.spec().requires.packages, ["numpy", "scikit-learn>=1.3"])
        for bad in ({"packages": ["numpy"]},                                    # no interpreter
                    {"interpreter": {"name": "python", "version": "3.x"}},
                    {"interpreter": {"name": "python"}, "packages": ["numpy==1.0"]},
                    {"interpreter": {"name": "python"}, "gpu": True}):
            self.body["requires"] = bad
            with self.assertRaises(ValidationError, msg=bad):
                self.spec()

    def test_command_launcher_must_be_declared(self):
        self.step("escalate")["command"] = ["bash", "escalate.sh"]
        issues = check_graph(self.spec(), "x")
        self.assertEqual(kinds(issues), ["undeclared_launcher"])
        self.assertIn("`escalate` is launched with `bash`", issues[0].message)
        self.body["requires"]["tools"] = ["bash"]
        self.assertEqual(check_graph(self.spec(), "x"), [])
        del self.step("escalate")["command"]
        self.body["requires"]["interpreter"] = {"name": "bash"}
        self.assertIn("has no `command`, so it is launched with `python`", check_graph(self.spec(), "x")[0].message)
        self.step("escalate")["command"] = []
        with self.assertRaises(ValidationError):
            self.spec()

    def test_missing_resource_only_with_skill_dir(self):
        self.step("escalate")["assets"] = ["assets/nope.json"]
        self.assertEqual(check_graph(self.spec(), "x"), [])
        self.assertEqual(kinds(check_graph(self.spec(), "x", EXAMPLE)), ["missing_resource"])


class SkillFolder(unittest.TestCase):
    def test_example_is_valid(self):
        loaded, issues = validate_skill(EXAMPLE)
        self.assertEqual(issues, [])
        self.assertEqual(loaded.frontmatter["name"], "billing-support")

    def test_body_is_runtime_block_then_one_yaml_block(self):
        block = runtime_text().strip()
        cases = {
            "prose after": (lambda t: t + "\ntrailing prose\n", "invalid_body_format"),
            "prose between": (lambda t: t.replace(block + "\n\n```yaml", block + "\n\nSome intro.\n\n```yaml"), "invalid_body_format"),
            "block missing": (lambda t: t.replace(block + "\n\n", ""), "missing_runtime_block"),
            "block edited": (lambda t: t.replace("Critical terminology:", "Terminology:"), "missing_runtime_block"),
        }
        for label, (mutate, expected) in cases.items():
            with self.subTest(label), tempfile.TemporaryDirectory() as tmp:
                skill = copy_example(tmp)
                md = skill / "SKILL.md"
                text = md.read_text()
                mutated = mutate(text)
                self.assertNotEqual(mutated, text, label)
                md.write_text(mutated)
                loaded, issues = validate_skill(skill)
                self.assertIsNone(loaded)
                self.assertEqual(kinds(issues), [expected])

    def test_frontmatter_rules(self):
        cases = {
            "name_mismatch": ("name: billing-support", "name: other-name"),
            "invalid_name": ("name: billing-support", "name: Billing--Support"),
            "missing_required_frontmatter": ("description: Triage", "descriptionx: Triage"),
            "missing_aip_version": (f'aip-version: "{FORMAT_VERSION}"', 'other: "x"'),
            "aip_version_mismatch": (f'aip-version: "{FORMAT_VERSION}"', 'aip-version: "0.3a3"'),
            "invalid_metadata": (f'aip-version: "{FORMAT_VERSION}"', f'aip-version: "{FORMAT_VERSION}"\n  nested:\n    a: b'),
        }
        for expected, (old, new) in cases.items():
            with self.subTest(expected), tempfile.TemporaryDirectory() as tmp:
                skill = copy_example(tmp)
                rewrite(skill, old, new)
                _, issues = validate_skill(skill)
                self.assertIn(expected, kinds(issues))

    def test_accepted_earlier_format_loads_with_a_warning(self):
        """0.6a1 is not breaking: a skill still carrying the 0.6a0 block and version loads, with
        `runtime_block_outdated` as one warning, and the CLI exits 0."""
        with tempfile.TemporaryDirectory() as tmp:
            skill = copy_example(tmp)
            rewrite(skill, runtime_text().strip(), runtime_text("0.6a0").strip())
            rewrite(skill, f'aip-version: "{FORMAT_VERSION}"', 'aip-version: "0.6a0"')
            loaded, issues = validate_skill(skill)
            self.assertIsNotNone(loaded)
            self.assertEqual([(i.kind, i.severity) for i in issues], [("runtime_block_outdated", "warning")])
            self.assertTrue(issues[0].message.startswith("0.6a0 skill: regenerate the runtime block"), issues[0].message)
            with mock.patch("sys.stdout", new=io.StringIO()), mock.patch("sys.stderr", new=io.StringIO()):
                self.assertEqual(main(["validate", str(skill)]), 0)

    def test_previous_format_is_rejected_as_outdated(self):
        """0.6a0 is breaking: a skill still carrying the 0.5a1 block and version is recognised and
        rejected with `runtime_block_outdated`, said once; the CLI exits 1."""
        with tempfile.TemporaryDirectory() as tmp:
            skill = copy_example(tmp)
            rewrite(skill, runtime_text().strip(), runtime_text("0.5a1").strip())
            rewrite(skill, f'aip-version: "{FORMAT_VERSION}"', 'aip-version: "0.5a1"')
            loaded, issues = validate_skill(skill)
            self.assertIsNone(loaded)
            self.assertEqual([(i.kind, i.severity) for i in issues], [("runtime_block_outdated", "error")])
            self.assertTrue(issues[0].message.startswith(
                "0.5a1 skill: add outputs to each execution and client_task step, a requires block, and "
                "regenerate the runtime block"), issues[0].message)
            with mock.patch("sys.stdout", new=io.StringIO()), mock.patch("sys.stderr", new=io.StringIO()):
                self.assertEqual(main(["validate", str(skill)]), 1)
            # the block alone, or the version alone, is the same issue
            rewrite(skill, 'aip-version: "0.5a1"', f'aip-version: "{FORMAT_VERSION}"')
            self.assertEqual(kinds(validate_skill(skill)[1]), ["runtime_block_outdated"])
        with tempfile.TemporaryDirectory() as tmp:
            skill = copy_example(tmp)
            rewrite(skill, f'aip-version: "{FORMAT_VERSION}"', 'aip-version: "0.5a1"')
            self.assertEqual(kinds(validate_skill(skill)[1]), ["runtime_block_outdated"])

    def test_previous_format_reads_as_an_upgrade(self):
        """The 0.5a1 billing-support (no outputs, no requires, the old block) leads with the upgrade
        note, then the steps it names; every recognised earlier format has an upgrade note."""
        self.assertEqual(set(UPGRADES), set(LEGACY_VERSIONS))
        with tempfile.TemporaryDirectory() as tmp:
            skill = copy_example(tmp)
            rewrite(skill, runtime_text().strip(), runtime_text("0.5a1").strip())
            rewrite(skill, f'aip-version: "{FORMAT_VERSION}"', 'aip-version: "0.5a1"')
            text = (skill / "SKILL.md").read_text()
            text = re.sub(r"requires:\n(  .*\n)+\n", "", text)
            text = re.sub(r"    outputs:\n(      .*\n)+", "", text)
            (skill / "SKILL.md").write_text(text)
            issues = validate_skill(skill)[1]
            self.assertEqual(kinds(issues), ["runtime_block_outdated", "missing_outputs", "missing_requires"])
            self.assertIn("0.5a1 skill: add outputs", issues[0].message)

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



class Cli(unittest.TestCase):
    def run_cli(self, *argv) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_version_and_help(self):
        self.assertEqual(self.run_cli("--version"), (0, FORMAT_VERSION + "\n", ""))
        code, out, _ = self.run_cli()
        self.assertEqual(code, 0)
        for command in ("validate", "schema", "runtime", "skill", "example"):
            self.assertIn(command, out)
        self.assertEqual(self.run_cli("bogus")[0], 2)

    def test_schema_and_runtime_print_the_package_contents(self):
        code, out, _ = self.run_cli("schema")
        self.assertEqual((code, json.loads(out)), (0, json_schema()))
        code, out, _ = self.run_cli("runtime")
        self.assertEqual((code, out), (0, runtime_text()))

    def test_example_copies_the_bundled_skill_out(self):
        code, out, _ = self.run_cli("example")
        self.assertEqual((code, out), (0, "billing-support\n"))
        with tempfile.TemporaryDirectory() as tmp:
            code, out, _ = self.run_cli("example", "billing-support", "--out", tmp)
            self.assertEqual(code, 0, out)
            copied = Path(tmp) / "billing-support"
            self.assertEqual(sorted(p.relative_to(copied) for p in copied.rglob("*") if p.is_file()),
                             sorted(p.relative_to(EXAMPLE) for p in EXAMPLE.rglob("*") if p.is_file() and "__pycache__" not in p.parts))
            self.assertEqual(validate_skill(copied)[1], [])
            self.assertEqual(self.run_cli("example", "billing-support", "--out", tmp)[0], 1, "refuses to overwrite")
        self.assertEqual(self.run_cli("example", "nope", "--out", "/tmp")[0], 1)


class SkillInstall(unittest.TestCase):
    """`aip-spec skill install` writes the authoring skill as an Agent Skill folder."""

    def run_cli(self, *argv) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def assert_installed_skill(self, folder: Path):
        self.assertTrue((folder / "SKILL.md").is_file())
        self.assertTrue((folder / "references" / "skill-creation-best-practices.md").is_file())
        self.assertTrue((folder / "assets" / "procedure.schema.json").is_file())
        self.assertEqual((folder / "SKILL.md").read_text(), (skill_dir() / "SKILL.md").read_text())
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ["SKILL.md", "assets", "references"],
                         "the three bundled entries, never the checkout's src/ or scripts/")
        doc, _ = parse_skill_md(folder / "SKILL.md")  # the authoring skill is not an AIP procedure, but
        frontmatter = yaml.safe_load((folder / "SKILL.md").read_text().split("---")[1])  # its frontmatter passes
        issues = list(check_frontmatter(frontmatter, folder))
        self.assertEqual(issues, [], [i.to_record() for i in issues])
        self.assertEqual(frontmatter["name"], "aip")
        self.assertEqual(frontmatter["metadata"]["aip-version"], FORMAT_VERSION)

    def test_install_with_path_writes_the_skill_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, err = self.run_cli("skill", "install", "--path", tmp)
            self.assertEqual((code, err), (0, ""), out)
            self.assert_installed_skill(Path(tmp) / "aip")
            self.assertEqual(self.run_cli("skill", "install", "--path", tmp)[0], 0, "idempotent")
            code, out, _ = self.run_cli("skill", "remove", "--path", tmp)
            self.assertEqual(code, 0)
            self.assertFalse((Path(tmp) / "aip").exists())

    def test_install_into_detected_agents(self):
        with tempfile.TemporaryDirectory() as home, mock.patch.dict(os.environ, {"HOME": home, "XDG_CONFIG_HOME": f"{home}/.config"}):
            code, _, err = self.run_cli("skill", "install")
            self.assertEqual(code, 1)
            self.assertIn("no supported agent detected", err)
            (Path(home) / ".claude").mkdir()
            (Path(home) / ".cursor").mkdir()
            code, out, err = self.run_cli("skill", "install")
            self.assertEqual((code, err), (0, ""), out)
            for agent in (".claude", ".cursor"):
                self.assert_installed_skill(Path(home) / agent / "skills" / "aip")
            code, out, _ = self.run_cli("skill", "list")
            rows = {line.split()[0]: line.split()[1:3] for line in out.splitlines()[1:]}
            self.assertEqual((rows["claude-code"], rows["cursor"], rows["codex"]), (["yes", "aip"], ["yes", "aip"], ["no", "-"]))
            code, out, _ = self.run_cli("skill", "remove", "cursor")
            self.assertEqual(code, 0)
            self.assertFalse((Path(home) / ".cursor" / "skills" / "aip").exists())
            self.assertTrue((Path(home) / ".claude" / "skills" / "aip").exists())
            self.assertEqual(self.run_cli("skill", "remove")[0], 0)
            self.assertFalse((Path(home) / ".claude" / "skills" / "aip").exists())
            self.assertEqual(self.run_cli("skill", "install", "emacs")[0], 1)


if __name__ == "__main__":
    unittest.main()
