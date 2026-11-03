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
from aip_spec import FORMAT_VERSION, ProcedureSpec, check_graph, classify_sources, example_dir, json_schema, parse_skill_md, runtime_text, skill_dir, validate_skill
from aip_spec.cli import main, validate_command
from aip_spec.models import LEGACY_VERSIONS, SCHEMA_ID, SPEC_URL, DecisionStep, ProcedureSpec as Spec, StartStep, Strict
from aip_spec.skill import ACCEPTED_VERSIONS, UPGRADES, check_frontmatter

SKILL = skill_dir()  # the authoring skill: `skills/aip-compile/` in the checkout
EXAMPLE = example_dir("billing-support")
SCHEMA_FILE = SKILL / "assets" / "procedure.schema.json"
DIALOGUE = Path(__file__).parent / "fixtures" / "dialogue-graph.yaml"
# The shipped example lets its decision be answered by hand (`fallback: true`), so the quickstart
# runs without a decision model. That makes its one route unmeasured, which the validator says.
EXAMPLE_WARNING = ("confidence_on_unmeasured_source", "warning")   # the example checks a fallback decision's confidence
CHECK = {"key": "tone_confidence", "below": 0.6, "to": "escalate"}


def measured(body: dict) -> dict:
    """The example in its measured form: a decision model answers `tone` (no fallback), its
    confidence is emitted, and the router checks it. The validator has nothing to say about it."""
    step_of(body, "triage")["fallback"] = False
    step_of(body, "triage")["confidence"] = ["tone"]
    step_of(body, "by-tone")["confidence"] = dict(CHECK)
    return body


def example_yaml() -> dict:
    doc, issues = parse_skill_md(EXAMPLE / "SKILL.md")
    assert not issues, issues
    return yaml.safe_load(doc.yaml_text)


def step_of(body: dict, name: str) -> dict:
    return next(s for s in body["steps"] if s["name"] == name)


def kinds(issues) -> list[str]:
    return [i.kind for i in issues]


def copy_example(tmp: str, clean: bool = True) -> Path:
    """A copy of the example; by default in its measured form (see `measured`), so the copy is
    clean and a test's assertion names only what the test changed."""
    skill = Path(tmp) / "billing-support"
    shutil.copytree(EXAMPLE, skill)
    if clean:
        rewrite(skill, "    fallback: true\n", "    confidence: [tone]\n    fallback: false\n")
        rewrite(skill, "    branch_on: tone\n", "    branch_on: tone\n    confidence: {key: tone_confidence, below: 0.6, to: escalate}\n")
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
        self.assertIn("github.com/zach-blumenfeld/aip/", SPEC_URL)
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
        skill_md = (SKILL / "SKILL.md").read_text()
        self.assertIn(runtime_text().strip(), skill_md,
                      "the runtime block in SKILL.md and src/aip_spec/runtime.md have drifted")


class SpecModels(unittest.TestCase):
    def test_example_parses(self):
        spec = ProcedureSpec.model_validate(example_yaml())
        self.assertEqual([s.kind for s in spec.steps], ["start", "decision", "router", "execution", "client_task", "end"])
        self.assertIsInstance(spec.start, StartStep)
        self.assertEqual(([i.name for i in spec.start.inputs], spec.start.inputs_to), (["message"], "triage"))
        self.assertIsInstance(spec.step("triage"), DecisionStep)
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
        self.assertFalse(ProcedureSpec.model_validate(body).step("triage").history)
        step_of(body, "triage")["history"] = True
        self.assertTrue(ProcedureSpec.model_validate(body).step("triage").history)

    def test_decision_fallback_is_opt_in_and_thresholds_are_gone(self):
        body = example_yaml()
        self.assertTrue(ProcedureSpec.model_validate(body).step("triage").fallback, "the shipped example opts in")
        self.assertEqual(ProcedureSpec.model_validate(body).step("triage").confidence, ["tone"], "and emits `tone_confidence`")
        del step_of(body, "triage")["fallback"]
        del step_of(body, "triage")["confidence"]
        self.assertFalse(ProcedureSpec.model_validate(body).step("triage").fallback)
        self.assertEqual(ProcedureSpec.model_validate(body).step("triage").confidence, [])
        step_of(body, "triage")["thresholds"] = {"tone": 0.6}
        with self.assertRaises(ValidationError):
            ProcedureSpec.model_validate(body)

    def test_router_confidence_check_shape(self):
        body = example_yaml()
        step_of(body, "by-tone")["confidence"] = {"key": "tone_confidence", "below": 0.6, "to": "escalate"}
        check = ProcedureSpec.model_validate(body).step("by-tone").confidence
        self.assertEqual((check.key, check.below, check.to), ("tone_confidence", 0.6, "escalate"))
        for bad in ({"key": "tone_confidence", "below": 1.5, "to": "escalate"},
                    {"key": "tone_confidence", "to": "escalate"},
                    {"key": "tone_confidence", "below": 0.6}):
            step_of(body, "by-tone")["confidence"] = bad
            with self.assertRaises(ValidationError, msg=bad):
                ProcedureSpec.model_validate(body)

    def test_a_procedure_is_at_least_start_one_step_and_end(self):
        body = example_yaml()
        body["steps"] = body["steps"][:2]
        with self.assertRaises(ValidationError):
            ProcedureSpec.model_validate(body)

    def test_resource_prefix_enforced(self):
        body = example_yaml()
        step_of(body, "escalate")["script"] = "escalate.py"
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
        step_of(body, "by-tone")["branches"] = {"angry": "escalate"}
        with self.assertRaises(ValidationError):
            ProcedureSpec.model_validate(body)


class GraphChecks(unittest.TestCase):
    def setUp(self):
        # The shipped example opts into `fallback` for the quickstart, which makes its route
        # unmeasured. The graph tests start from the measured form; `RouteSources` covers the classes.
        self.body = measured(example_yaml())

    def spec(self) -> ProcedureSpec:
        return ProcedureSpec.model_validate(self.body)

    def step(self, name: str) -> dict:
        return step_of(self.body, name)

    def test_example_is_clean(self):
        self.assertEqual(check_graph(self.spec(), "x", EXAMPLE), [])

    def test_shipped_example_checks_an_unmeasured_source(self):
        """The example keeps `fallback: true` so the quickstart runs without a key; its router checks
        `tone_confidence` all the same, so the validator says the check reads an unmeasured source."""
        self.body = example_yaml()
        issues = check_graph(self.spec(), "x", EXAMPLE)
        self.assertEqual([(i.kind, i.severity) for i in issues], [EXAMPLE_WARNING])
        self.assertIn("decision `triage` answers `tone` with `fallback: true`", issues[0].message)

    def test_duplicate_step_name(self):
        self.body["steps"].append(copy.deepcopy(self.step("reply")))
        self.assertIn("duplicate_step_name", kinds(check_graph(self.spec(), "x")))

    def test_exactly_one_start_step(self):
        steps = self.body["steps"]
        start = steps.pop(0)
        self.assertEqual(kinds(check_graph(self.spec(), "x")), ["missing_start_step"])
        steps.append(start)  # any position: by convention first, not required to be
        self.assertEqual(check_graph(self.spec(), "x"), [])
        steps.append({**copy.deepcopy(start), "name": "again"})
        issues = check_graph(self.spec(), "x")
        self.assertEqual(kinds(issues), ["multiple_start_steps", "unreachable_step", "duplicate_producer"])
        self.assertIn("['start', 'again']", issues[0].message)

    def test_nothing_points_at_the_start(self):
        self.step("escalate")["inputs_to"] = "start"
        issues = check_graph(self.spec(), "x")
        self.assertEqual(kinds(issues), ["edge_into_start"])
        self.assertEqual(issues[0].location, "body:$.steps[3].inputs_to")
        self.step("escalate")["inputs_to"] = "end"
        self.step("by-tone")["branches"]["angry"] = "start"   # escalate stays reachable through the check
        issues = check_graph(self.spec(), "x")
        self.assertEqual(kinds(issues), ["edge_into_start"])
        self.assertEqual(issues[0].location, "body:$.steps[2].branches.angry")

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
        self.assertEqual(kinds(check_graph(self.spec(), "x")), ["unknown_step_reference"])  # the check still reaches escalate
        self.step("by-tone")["confidence"]["to"] = "reply"
        issues = check_graph(self.spec(), "x")
        self.assertIn("unknown_step_reference", kinds(issues))
        self.assertIn("unreachable_step", kinds(issues))  # escalate is now orphaned

    def test_the_confidence_check_target_is_an_edge(self):
        self.step("by-tone")["confidence"]["to"] = "nowhere"
        issues = check_graph(self.spec(), "x")
        self.assertEqual(kinds(issues), ["unknown_step_reference"])
        self.assertEqual(issues[0].location, "body:$.steps[2].confidence.to")
        # a step only the check reaches is reachable, and must reach the end like any other
        self.body["steps"].insert(4, {"name": "review", "kind": "client_task", "description": "d", "inputs": [],
                                      "template": "assets/reply.md", "outputs": [{"name": "notes", "type": "string"}], "inputs_to": "end"})
        self.step("by-tone")["confidence"]["to"] = "review"
        self.assertEqual(check_graph(self.spec(), "x"), [])

    def test_no_path_to_end(self):
        self.step("escalate")["inputs_to"] = "escalate"
        self.assertIn("no_path_to_end", kinds(check_graph(self.spec(), "x")))

    def test_duplicate_input_name(self):
        self.step("triage")["inputs"].append({"name": "message", "type": "string"})
        self.assertIn("duplicate_input_name", kinds(check_graph(self.spec(), "x")))

    def test_confidence_must_name_a_question(self):
        self.step("triage")["confidence"] = ["tone", "mood"]
        issues = check_graph(self.spec(), "x")
        self.assertEqual(kinds(issues), ["unknown_confidence_question"])
        self.assertIn("names `mood` in `confidence`", issues[0].message)
        self.assertEqual(issues[0].location, "body:$.steps[1].confidence[1]")

    def test_router_branch_keys_must_match_the_question(self):
        self.step("by-tone")["branches"] = {"angry": "escalate", "furious": "reply"}
        issues = check_graph(self.spec(), "x")
        self.assertIn("unknown_branch_value", kinds(issues))
        self.assertIn("furious", next(i for i in issues if i.kind == "unknown_branch_value").message)

    def test_router_on_score_expects_level_numbers_as_strings(self):
        triage = self.step("triage")
        triage["questions"]["severity"] = {"type": "score", "instructions": "How bad?",
                                           "criteria": ["cosmetic", "degraded", "unusable"]}
        triage["confidence"] = ["severity"]
        self.step("by-tone")["branch_on"] = "severity"
        self.step("by-tone")["confidence"]["key"] = "severity_confidence"
        self.step("by-tone")["branches"] = {"0": "reply", "1": "reply", "2": "escalate"}
        self.assertEqual([i.kind for i in check_graph(self.spec(), "x")], [])
        self.step("by-tone")["branches"] = {"low": "reply", "high": "escalate"}
        self.assertEqual(kinds(check_graph(self.spec(), "x")), ["unknown_branch_value", "unknown_branch_value"])

    def test_router_branches_on_a_boolean_string_or_integer(self):
        self.step("escalate")["outputs"].append({"name": "payload", "type": "object"})
        self.body["steps"].insert(4, {"name": "by-payload", "kind": "router", "description": "d", "branch_on": "payload",
                                      "branches": {"a": "end", "b": "end"}})
        self.step("escalate")["inputs_to"] = "by-payload"
        issues = check_graph(self.spec(), "x")
        self.assertEqual(kinds(issues), ["unbranchable_type"])
        self.assertIn("branches on `payload`, which is `object` (output of `escalate`)", issues[0].message)
        self.assertEqual(issues[0].location, "body:$.steps[4].branch_on")

    def test_example_declares_outputs(self):
        spec = self.spec()
        self.assertEqual([o.name for o in spec.step("escalate").outputs], ["ticket_id", "queue"])
        self.assertEqual([o.name for o in spec.step("reply").outputs], ["reply"])

    def test_rule_1_consumed_key_needs_a_producer_on_every_path(self):
        self.step("end")["inputs"].append({"name": "reply", "type": "string"})  # the angry path never drafts one
        issues = check_graph(self.spec(), "x")
        self.assertEqual(kinds(issues), ["unproduced_input"])
        self.assertIn("step `end` consumes `reply`", issues[0].message)
        self.assertIn("start step `start`", issues[0].message)
        self.step("end")["inputs"].pop()
        self.step("escalate")["inputs"].append({"name": "account_id", "type": "string"})
        self.assertEqual(kinds(check_graph(self.spec(), "x")), ["unproduced_input"])
        self.step("start")["inputs"].append({"name": "account_id", "type": "string"})  # the client supplies it
        self.assertEqual(check_graph(self.spec(), "x"), [])

    def test_rule_1_router_consumes_its_branch_key(self):
        self.step("by-tone")["branch_on"] = "mood"
        self.step("by-tone")["branches"] = {"angry": "escalate", "calm": "reply"}
        self.assertIn("step `by-tone` consumes `mood`", check_graph(self.spec(), "x")[0].message)

    def test_rule_1_a_confidence_key_is_declared_on_some_path(self):
        self.step("triage")["confidence"] = []   # nothing emits what the router checks
        issues = check_graph(self.spec(), "x")
        self.assertEqual(kinds(issues), ["unproduced_input", "confidence_on_unmeasured_source"])
        self.assertIn("router `by-tone` checks `tone_confidence`, which no step produces on any path to it", issues[0].message)
        self.assertEqual(issues[0].location, "body:$.steps[2].confidence.key")
        # declared on one path is enough: on a path where a script rewrote `tone` without a
        # confidence, the check fires as `absent`, and the script is a deterministic source
        self.step("escalate")["outputs"].append({"name": "tone", "type": "string"})
        self.body["steps"].insert(4, {"name": "by-tone-again", "kind": "router", "description": "d", "branch_on": "tone",
                                      "confidence": dict(CHECK, to="reply"), "branches": {"angry": "end", "calm": "reply"}})
        self.step("escalate")["inputs_to"] = "by-tone-again"
        self.step("end")["inputs"] = []
        self.step("triage")["confidence"] = ["tone"]
        self.assertEqual(kinds(check_graph(self.spec(), "x")), ["duplicate_producer"])
        self.assertEqual(classify_sources(self.spec()), {"by-tone": "measured", "by-tone-again": "measured"})

    def test_several_producers_are_information_not_a_fault(self):
        self.step("reply")["outputs"].append({"name": "tone", "type": "string"})
        issues = check_graph(self.spec(), "x")
        self.assertEqual([(i.kind, i.severity) for i in issues], [("duplicate_producer", "info")])
        self.assertIn("key `tone` has more than one producer: `triage`, `reply`", issues[0].message)
        self.assertEqual(issues[0].location, "body:$.steps[4]")
        self.assertEqual(issues[0].to_record()["severity"], "info")

    def test_a_start_input_may_be_overwritten(self):
        self.step("escalate")["outputs"].append({"name": "message", "type": "string"})
        issues = check_graph(self.spec(), "x")
        self.assertEqual([(i.kind, i.severity) for i in issues], [("duplicate_producer", "info")])
        self.assertIn("`start` (a start input), `escalate`", issues[0].message)
        self.step("escalate")["outputs"][-1]["type"] = "object"  # but every producer agrees on the type
        self.assertEqual(sorted(kinds(check_graph(self.spec(), "x"))), ["duplicate_producer", "type_mismatch"])

    def test_rule_4_every_declaration_of_a_key_agrees_on_its_type(self):
        self.step("end")["inputs"][0]["type"] = "object"           # `message` is a string start input
        issues = check_graph(self.spec(), "x")
        self.assertEqual(kinds(issues), ["type_mismatch"])
        self.assertIn("declares input `message` as `object`, but it is `string` (start input on `start`)", issues[0].message)
        self.assertEqual(issues[0].location, "body:$.steps[5].inputs[0].type")
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
        mismatch = next(i for i in issues if i.kind == "type_mismatch")
        self.assertIn("step `end` declares input `ticket_id` as `string`, but it is `integer` (output of `escalate`)", mismatch.message)

    def test_rule_4_the_first_declaration_in_step_order_is_the_reference(self):
        self.step("escalate")["outputs"][0]["type"] = "string"   # ticket_id: escalate (string) comes before reply (integer)
        self.step("reply")["outputs"].append({"name": "ticket_id", "type": "integer"})
        issues = check_graph(self.spec(), "x")
        mismatch = next(i for i in issues if i.kind == "type_mismatch")
        self.assertIn("step `reply` declares output `ticket_id` as `integer`, but it is `string` (output of `escalate`)", mismatch.message)
        self.assertEqual(mismatch.location, "body:$.steps[4].outputs[1].type")

    def test_rule_4_a_confidence_key_is_a_float(self):
        self.step("by-tone")["confidence"]["key"] = "tone"   # the answer, not its confidence
        issues = check_graph(self.spec(), "x")
        self.assertEqual(kinds(issues), ["type_mismatch", "confidence_on_unmeasured_source"])
        self.assertIn("router `by-tone` checks `tone` as a `float`, but it is `string` (a choice question in `triage`)", issues[0].message)
        self.assertEqual(issues[0].location, "body:$.steps[2].confidence.key")
        self.step("by-tone")["confidence"]["key"] = "tone_confidence"
        self.step("reply")["inputs"].append({"name": "tone_confidence", "type": "integer"})
        issues = check_graph(self.spec(), "x")
        self.assertEqual(kinds(issues), ["type_mismatch"])
        self.assertIn("but it is `float` (the confidence of `tone` in `triage`)", issues[0].message)

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
        self.assertEqual(classify_sources(ProcedureSpec.model_validate(body)), {"by-status": "deterministic"}, "a script's output routes it")

    def test_scripts_need_requires(self):
        del self.body["requires"]
        issues = check_graph(self.spec(), "x")
        self.assertEqual(kinds(issues), ["missing_requires"])
        self.assertIn("runs scripts (`escalate`) but declares no `requires`", issues[0].message)
        self.body["steps"] = [s for s in self.body["steps"] if s["kind"] != "execution"]
        self.step("by-tone")["branches"]["angry"] = "reply"
        self.step("by-tone")["confidence"]["to"] = "reply"
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


class RouteSources(unittest.TestCase):
    """What feeds a router is deterministic, measured or unmeasured; the worst producer wins.
    The two warnings and the one info follow from the class, and `classify_sources` exposes it."""

    def setUp(self):
        self.body = example_yaml()
        self.step("triage")["fallback"] = False
        self.step("triage").pop("confidence")        # the shipped example emits `tone_confidence` and checks it;
        self.step("by-tone").pop("confidence")       # every case below starts from neither

    def spec(self) -> ProcedureSpec:
        return ProcedureSpec.model_validate(self.body)

    def step(self, name: str) -> dict:
        return step_of(self.body, name)

    def check(self) -> list:
        return check_graph(self.spec(), "x")

    def add_check(self, key: str = "tone_confidence") -> None:
        self.step("by-tone")["confidence"] = {"key": key, "below": 0.6, "to": "escalate"}

    def test_measured_a_decision_model_with_the_check(self):
        self.step("triage")["confidence"] = ["tone"]
        self.add_check()
        self.assertEqual(self.check(), [])
        self.assertEqual(classify_sources(self.spec()), {"by-tone": "measured"})

    def test_unmeasured_a_decision_model_without_the_check(self):
        """No fallback, but nothing records the model's confidence: an LLM routed the run."""
        issues = self.check()
        self.assertEqual([(i.kind, i.severity) for i in issues], [("unmeasured_route", "warning")])
        self.assertIn("does not name `tone` in its `confidence` list", issues[0].message)
        self.assertEqual(issues[0].location, "body:$.steps[2]")
        self.step("triage")["confidence"] = ["tone"]  # emitted, still not checked
        issues = self.check()
        self.assertEqual(kinds(issues), ["unmeasured_route"])
        self.assertIn("emits `tone_confidence` but the router does not check it", issues[0].message)
        self.assertEqual(classify_sources(self.spec()), {"by-tone": "unmeasured"})

    def test_unmeasured_a_decision_with_fallback(self):
        self.step("triage")["fallback"] = True
        self.step("triage")["confidence"] = ["tone"]
        self.assertEqual(kinds(self.check()), ["unmeasured_route"])
        self.add_check()
        issues = self.check()
        self.assertEqual([(i.kind, i.severity) for i in issues], [("confidence_on_unmeasured_source", "warning")])
        self.assertIn("checks `tone_confidence`, but its branch key `tone` is unmeasured", issues[0].message)
        self.assertIn("`fallback: true`", issues[0].message)
        self.assertEqual(issues[0].location, "body:$.steps[2].confidence")
        self.assertEqual(classify_sources(self.spec()), {"by-tone": "unmeasured"})

    def test_deterministic_a_start_input_or_a_scripts_output(self):
        self.step("start")["inputs"].append({"name": "tone", "type": "string"})   # the client supplies the tone
        self.body["steps"].remove(self.step("triage"))
        self.step("start")["inputs_to"] = "by-tone"
        self.assertEqual(self.check(), [])
        self.assertEqual(classify_sources(self.spec()), {"by-tone": "deterministic"})
        self.body["steps"].insert(2, {"name": "sort", "kind": "execution", "description": "d", "script": "scripts/escalate.py",
                                      "inputs": [{"name": "message", "type": "string"}],
                                      "outputs": [{"name": "tone", "type": "string"}], "inputs_to": "by-tone"})
        self.step("start")["inputs_to"] = "sort"
        self.assertEqual(kinds(self.check()), ["duplicate_producer"])
        self.assertEqual(classify_sources(self.spec()), {"by-tone": "deterministic"})

    def test_unmeasured_a_client_task_the_router_does_not_check(self):
        self.step("reply")["outputs"].append({"name": "tone", "type": "string"})
        self.step("reply")["inputs_to"] = "by-tone"   # reply feeds the router back; the decision is still the first source
        self.step("end")["inputs"].append({"name": "ticket_id", "type": "integer"})
        self.step("triage")["confidence"] = ["tone"]
        self.add_check()
        issues = self.check()
        self.assertEqual(kinds(issues), ["duplicate_producer", "confidence_on_unmeasured_source"])
        self.assertIn("an output of client task `reply`, chosen by the client's own judgment", issues[1].message)
        self.assertEqual(classify_sources(self.spec()), {"by-tone": "unmeasured"}, "the worst producer wins")

    def test_declared_confidence_is_information(self):
        self.step("escalate")["outputs"].extend([{"name": "tone", "type": "string"}, {"name": "sureness", "type": "float"}])
        self.step("escalate")["inputs_to"] = "by-tone"
        self.step("by-tone")["branches"]["angry"] = "end"
        self.step("end")["inputs"] = []
        self.add_check("sureness")
        issues = self.check()
        self.assertEqual([(i.kind, i.severity) for i in issues],
                         [("duplicate_producer", "info"), ("confidence_on_unmeasured_source", "warning"), ("declared_confidence", "info")],
                         "the script's own number measures its route, but the decision's answer has no confidence recorded")
        self.assertEqual(classify_sources(self.spec()), {"by-tone": "unmeasured"}, "the worst producer wins")
        self.step("triage")["confidence"] = ["tone"]
        self.step("by-tone")["confidence"]["key"] = "tone_confidence"
        self.step("escalate")["outputs"][-1]["name"] = "tone_confidence"
        issues = self.check()
        self.assertEqual([(i.kind, i.severity) for i in issues], [("duplicate_producer", "info"), ("duplicate_producer", "info"),
                                                                   ("declared_confidence", "info")])
        self.assertIn("a confidence script `escalate` declares itself; legitimate when the code behind it is calibrated", issues[2].message)
        self.assertEqual(classify_sources(self.spec()), {"by-tone": "measured"})

    def test_declared_confidence_of_a_client_task_is_discouraged(self):
        self.step("reply")["outputs"].extend([{"name": "tone", "type": "string"}, {"name": "tone_confidence", "type": "float"}])
        self.step("reply")["inputs_to"] = "by-tone"
        self.step("end")["inputs"].append({"name": "ticket_id", "type": "integer"})
        self.step("triage")["confidence"] = ["tone"]
        self.add_check()
        issues = self.check()
        self.assertEqual(kinds(issues), ["duplicate_producer", "duplicate_producer", "declared_confidence"])
        self.assertIn("client task `reply` declares itself; discouraged, because an agent cannot calibrate its own confidence", issues[2].message)

    def test_loaded_skill_carries_the_classes(self):
        with tempfile.TemporaryDirectory() as tmp:
            loaded, issues = validate_skill(copy_example(tmp))
            self.assertEqual((issues, loaded.routers), ([], {"by-tone": "measured"}))


class SkillFolder(unittest.TestCase):
    def test_example_is_valid(self):
        loaded, issues = validate_skill(EXAMPLE)
        self.assertEqual([(i.kind, i.severity) for i in issues], [EXAMPLE_WARNING])
        self.assertEqual(loaded.frontmatter["name"], "billing-support")
        self.assertEqual(loaded.routers, {"by-tone": "unmeasured"})

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

    def test_no_earlier_format_is_accepted(self):
        """0.8 is breaking: no earlier format loads unchanged. A skill still carrying the 0.6a1
        block and version is recognised and rejected with `runtime_block_outdated`, which names
        `aip upgrade`; the CLI exits 1."""
        self.assertEqual(ACCEPTED_VERSIONS, ())
        with tempfile.TemporaryDirectory() as tmp:
            skill = copy_example(tmp)
            rewrite(skill, runtime_text().strip(), runtime_text("0.6a1").strip())
            rewrite(skill, f'aip-version: "{FORMAT_VERSION}"', 'aip-version: "0.6a1"')
            loaded, issues = validate_skill(skill)
            self.assertIsNone(loaded)
            self.assertEqual([(i.kind, i.severity) for i in issues], [("runtime_block_outdated", "error")])
            self.assertTrue(issues[0].message.startswith("0.6a1 skill: run `aip upgrade <folder>`"), issues[0].message)
            self.assertIn(f"does not accept 0.6a1 skills", issues[0].message)
            with mock.patch("sys.stdout", new=io.StringIO()), mock.patch("sys.stderr", new=io.StringIO()):
                self.assertEqual(main(["validate", str(skill)]), 1)

    def test_previous_format_is_rejected_as_outdated(self):
        """A skill still carrying the 0.5a1 block and version is recognised and rejected with
        `runtime_block_outdated`, said once; the CLI exits 1."""
        with tempfile.TemporaryDirectory() as tmp:
            skill = copy_example(tmp)
            rewrite(skill, runtime_text().strip(), runtime_text("0.5a1").strip())
            rewrite(skill, f'aip-version: "{FORMAT_VERSION}"', 'aip-version: "0.5a1"')
            loaded, issues = validate_skill(skill)
            self.assertIsNone(loaded)
            self.assertEqual([(i.kind, i.severity) for i in issues], [("runtime_block_outdated", "error")])
            self.assertTrue(issues[0].message.startswith("0.5a1 skill: run `aip upgrade <folder>`"), issues[0].message)
            self.assertIn("then add outputs to each execution and client_task step and a requires block by hand", issues[0].message)
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
            self.assertIn("0.5a1 skill: run `aip upgrade <folder>`", issues[0].message)
            for version in LEGACY_VERSIONS:
                self.assertIn("`aip upgrade <folder>`", UPGRADES[version], version)

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
            self.assertTrue(all(i.location.startswith("body:$.steps[2]") for i in issues), [i.location for i in issues])

    def test_cli_validate_output_contract(self):
        def run(skill) -> tuple[int, str, list[dict]]:
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = validate_command([str(skill)])
            return code, out.getvalue(), [json.loads(line) for line in err.getvalue().splitlines()]

        with tempfile.TemporaryDirectory() as tmp:
            skill = copy_example(tmp)
            code, out, records = run(skill)
            self.assertEqual((code, records), (0, []))
            self.assertTrue(out.startswith("VALID: "))
            self.assertNotIn("see stderr", out)

            rewrite(skill, "        description: The queue the ticket was routed to.\n",
                    "        description: The queue the ticket was routed to.\n      - name: message\n        type: string\n")
            code, out, records = run(skill)   # information never fails validation
            self.assertEqual(code, 0)
            self.assertEqual([(r["kind"], r["severity"]) for r in records], [("duplicate_producer", "info")])
            self.assertTrue(out.startswith("VALID: "), out)
            self.assertIn("(1 info — see stderr)", out)

            rewrite(skill, "angry: escalate", "angry: nowhere")   # escalate stays reachable through the check
            code, out, records = run(skill)
            self.assertEqual(code, 1)
            self.assertEqual({r["kind"] for r in records}, {"unknown_step_reference", "duplicate_producer"})
            self.assertTrue(out.startswith("INVALID: 1 error(s) (1 info — see stderr)"), out)

        code, out, records = run(EXAMPLE)   # the shipped example: valid, with its one warning
        self.assertEqual((code, [(r["kind"], r["severity"]) for r in records]), (0, [EXAMPLE_WARNING]))
        self.assertTrue(out.startswith("VALID: "), out)
        self.assertIn("(1 warning(s) — see stderr)", out)


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
            self.assertEqual([(i.kind, i.severity) for i in validate_skill(copied)[1]], [EXAMPLE_WARNING])
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
        self.assertEqual(frontmatter["name"], "aip-compile")
        self.assertEqual(frontmatter["metadata"]["aip-version"], FORMAT_VERSION)

    def test_install_with_path_writes_the_skill_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, err = self.run_cli("skill", "install", "--path", tmp)
            self.assertEqual((code, err), (0, ""), out)
            self.assert_installed_skill(Path(tmp) / "aip-compile")
            self.assertEqual(self.run_cli("skill", "install", "--path", tmp)[0], 0, "idempotent")
            code, out, _ = self.run_cli("skill", "remove", "--path", tmp)
            self.assertEqual(code, 0)
            self.assertFalse((Path(tmp) / "aip-compile").exists())

    def test_prune_removes_the_retired_name_and_leaves_other_folders(self):
        """Up to 0.6a1 the authoring skill was installed as `aip/`. `skill prune` removes that folder
        when its SKILL.md is that skill (name `aip`, a description naming the protocol), leaves an
        unrelated folder of the name with a warning, and `--dry-run` only reports."""
        ours = "---\nname: aip\ndescription: Create skills as Agent Instruction Protocol (AIP)\n---\nbody\n"
        with tempfile.TemporaryDirectory() as tmp:
            old = Path(tmp) / "aip"
            old.mkdir()
            (old / "SKILL.md").write_text(ours)
            code, out, err = self.run_cli("skill", "prune", "--path", tmp, "--dry-run")
            self.assertEqual((code, err), (0, ""), out)
            self.assertIn(f"would remove {old}", out)
            self.assertTrue(old.is_dir(), "dry run changes nothing")
            code, out, err = self.run_cli("skill", "prune", "--path", tmp)
            self.assertEqual((code, err), (0, ""), out)
            self.assertIn(f"removed {old}", out)
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), [])
            code, out, _ = self.run_cli("skill", "prune", "--path", tmp)
            self.assertEqual(code, 0)
            self.assertIn("nothing to prune", out)
            old.mkdir()
            (old / "SKILL.md").write_text("---\nname: aip\ndescription: my own notes, not that protocol\n---\nbody\n")
            code, out, err = self.run_cli("skill", "prune", "--path", tmp)
            self.assertEqual(code, 0)
            self.assertNotIn("removed", out)
            self.assertIn(f"left {old} alone", err)
            self.assertTrue(old.is_dir())
            self.assertEqual(self.run_cli("skill", "install", "--path", tmp)[0], 0)
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["aip", "aip-compile"], "install never touches it either")

    def test_install_record_removes_only_what_it_installed_before(self):
        """`skill install` records the folders it wrote, per skills directory and tool. The next
        install removes a recorded folder that left the set, and leaves a folder it never wrote."""
        import json

        from aip_spec.agents import read_record, record_path

        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.run_cli("skill", "install", "--path", tmp)[0], 0)
            self.assertEqual(read_record(), {tmp: {"aip-spec": ["aip-compile"]}})
            # Pretend an earlier aip-spec installed the skill under another name, and that the user
            # keeps a folder of their own beside it.
            for name in ("aip-authoring", "mine"):
                (Path(tmp) / name).mkdir()
                (Path(tmp) / name / "SKILL.md").write_text(f"---\nname: {name}\ndescription: x\n---\nbody\n")
            record_path().write_text(json.dumps({"version": 1, "dirs": {tmp: {"aip-spec": ["aip-authoring", "aip-compile"]}}}))
            code, out, err = self.run_cli("skill", "install", "--path", tmp)
            self.assertEqual((code, err), (0, ""), out)
            self.assertIn(f"removed {Path(tmp) / 'aip-authoring'}", out)
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["aip-compile", "mine"])
            self.assertEqual(read_record(), {tmp: {"aip-spec": ["aip-compile"]}})
            # Another tool's entry for the same directory is not this tool's to clean up.
            record_path().write_text(json.dumps({"version": 1, "dirs": {tmp: {"aip-spec": ["aip-compile"], "aip": ["aip-compile", "mine"]}}}))
            self.assertEqual(self.run_cli("skill", "install", "--path", tmp)[0], 0)
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["aip-compile", "mine"])
            self.assertEqual(self.run_cli("skill", "remove", "--path", tmp)[0], 0)
            self.assertEqual(read_record(), {tmp: {"aip": ["mine"]}}, "remove drops the entry")

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
                self.assert_installed_skill(Path(home) / agent / "skills" / "aip-compile")
            code, out, _ = self.run_cli("skill", "list")
            rows = {line.split()[0]: line.split()[1:3] for line in out.splitlines()[1:]}
            self.assertEqual((rows["claude-code"], rows["cursor"], rows["codex"]), (["yes", "aip-compile"], ["yes", "aip-compile"], ["no", "-"]))
            code, out, _ = self.run_cli("skill", "remove", "cursor")
            self.assertEqual(code, 0)
            self.assertFalse((Path(home) / ".cursor" / "skills" / "aip-compile").exists())
            self.assertTrue((Path(home) / ".claude" / "skills" / "aip-compile").exists())
            self.assertEqual(self.run_cli("skill", "remove")[0], 0)
            self.assertFalse((Path(home) / ".claude" / "skills" / "aip-compile").exists())
            self.assertEqual(self.run_cli("skill", "install", "emacs")[0], 1)


if __name__ == "__main__":
    unittest.main()
