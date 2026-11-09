"""The engine (plan milestone R1): a compiled procedure behind an in-memory Relate store, the
state, every step kind of a straight procedure, answers, routes with their confidence check,
aggregations, the file cache and the record. `billing-support` runs end to end through both
route arms and the confidence arm with the scripted resolver; small programs compiled in memory
cover what the example does not say. Everything here opens a Relate store, so it skips with the
install hint when Relate is missing."""

import json
import os
import tempfile
import textwrap
import unittest
from pathlib import Path

from aip_spec import FileEntry, compile_folder, compile_source, example_dir, relate

from aip.model import (
    DONE, FAILED, PAUSED, Engine, InvalidInput, InvalidOutput, NotPaused, Procedure, ScriptedResolver, answers,
)

needs_relate = unittest.skipUnless(relate.available(), relate.INSTALL_HINT)

CLOCK = lambda: "2026-11-09T12:00:00.000+00:00"  # noqa: E731


def compiled(name: str):
    bundle, diagnostics = compile_folder(example_dir(name))
    assert bundle is not None, [str(d) for d in diagnostics]
    return bundle


def program(source: str, files: dict[str, str] | None = None):
    entries = [FileEntry(path, text.encode("utf-8"), 0o755 if path.startswith("scripts/") else 0o644)
               for path, text in sorted((files or {}).items())]
    bundle, diagnostics = compile_source(textwrap.dedent(source).lstrip(), entries, "test.aip", "test")
    assert bundle is not None, [str(d) for d in diagnostics]
    return bundle


def calm():
    return {"billing": answers.true_or_false(0.97), "tone": answers.choice({"calm": 0.9, "angry": 0.1})}


def angry():
    return {"billing": answers.true_or_false(0.97), "tone": answers.choice({"calm": 0.2, "angry": 0.8})}


def unsure():
    return {"billing": answers.true_or_false(0.6), "tone": answers.choice({"calm": 0.55, "angry": 0.45})}


class EngineCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="aip-engine-"))
        self.home = self.tmp / "home"
        self.procedures = []

    def tearDown(self):
        for p in self.procedures:
            p.close()

    def load(self, bundle) -> Procedure:
        procedure = Procedure.load(bundle)
        self.procedures.append(procedure)
        return procedure

    def engine(self, resolver=None, **kwargs) -> Engine:
        return Engine(resolver, home=self.home, clock=CLOCK, workdir=self.tmp, **kwargs)

    def steps_of(self, run):
        return [e["step"] for e in run.history]


@needs_relate
class BillingSupport(EngineCase):
    """The proof: both route arms and the confidence arm, with the scripted resolver and the
    example's own stub `scripts/escalate.py`."""

    def setUp(self):
        super().setUp()
        self.bundle = compiled("billing-support")
        self.message = "Why was I charged twice this month?"

    def test_the_calm_arm_pauses_for_the_agent_and_ends_with_the_message(self):
        resolver = ScriptedResolver({"triage": calm()})
        engine = self.engine(resolver)
        run = engine.start(self.load(self.bundle), {"message": self.message})
        self.assertEqual((run.status, self.steps_of(run)), (PAUSED, ["start", "triage", "by_tone"]))
        self.assertEqual(run.pause["kind"], "task")
        self.assertEqual(run.pause["step"], "reply")
        [task] = run.pause["tasks"]
        self.assertEqual(task["index"], 0)
        self.assertIn("Customer message:\n" + self.message, task["prompt"], "{message} is rendered from the state")
        self.assertIn("# Refund policy", task["prompt"], "{assets[policy]} is rendered from the Use file")
        self.assertEqual(task["state"], {"message": self.message, "tone": run.state["triage_decision"]["tone"]})
        self.assertEqual(task["references"], [{"path": "references/help.md", "description":
                                              "Escalation contacts and plan matrix. Only for plan changes, currency issues, "
                                              "or charges older than 30 days."}])
        self.assertEqual(task["answer_with"], {"reply": "string"})
        # the resolver saw the Read keys as the thing to judge, and the questions rendered
        [request] = resolver.requests
        self.assertEqual(request.state, {"message": self.message})
        self.assertEqual([q.name for q in request.questions], ["billing", "tone"])
        self.assertEqual(request.questions[1].labels, ["angry", "calm"])
        self.assertEqual(request.questions[1].criteria[0], ("angry", "Frustrated, demanding, or threatening to leave."))
        self.assertIsNone(request.history, "History is off")

        run = engine.resume(run, {"reply": "Sorry about that. The policy allows a refund within 30 days."})
        self.assertEqual((run.status, run.error), (DONE, None))
        self.assertEqual(run.result, {"message": self.message}, "End reads message only")
        self.assertEqual(self.steps_of(run), ["start", "triage", "by_tone", "reply", "end"])
        reply = run.history[3]
        self.assertEqual(reply["result"], {"reply": "Sorry about that. The policy allows a refund within 30 days."})
        self.assertEqual(reply["prompt"], task["prompt"])
        self.assertEqual(run.state["reply"], "Sorry about that. The policy allows a refund within 30 days.")

    def test_the_angry_arm_runs_the_script_from_the_cache(self):
        engine = self.engine(ScriptedResolver({"triage": angry()}))
        run = engine.start(self.load(self.bundle), {"message": self.message})
        self.assertEqual((run.status, run.error), (DONE, None))
        self.assertEqual(self.steps_of(run), ["start", "triage", "by_tone", "escalate", "end"])
        escalate = run.history[3]
        self.assertEqual(escalate["kind"], "Execute")
        self.assertEqual(escalate["script"], "scripts/escalate.py")
        self.assertEqual(escalate["stdin"]["state"], {"message": self.message, "tone": run.state["triage_decision"]["tone"]},
                         "Read triage_decision.tone gives the script the one answer as tone")
        self.assertEqual(json.loads(escalate["stdin"]["assets"]["config"]), {"queue": "tier2", "sla_hours": 4})
        self.assertEqual(escalate["stdin"]["expects"], {"message": "string"}, "the next step's Read keys")
        self.assertEqual(escalate["result"]["queue"], "tier2")
        self.assertIsInstance(escalate["result"]["ticket_id"], int)
        self.assertIsInstance(escalate["seconds"], float)
        self.assertEqual(run.state["queue"], "tier2")
        self.assertTrue((self.home / "cache" / self.bundle.id / "scripts" / "escalate.py").is_file())
        route = run.history[2]
        self.assertEqual(route["check"], {"below": 0.6, "confidence": 0.8, "fired": False, "reason": None})
        self.assertEqual((route["value"], route["to"]), ("angry", "escalate"))

    def test_the_confidence_arm_escalates_an_unsure_calm(self):
        engine = self.engine(ScriptedResolver({"triage": unsure()}))
        run = engine.start(self.load(self.bundle), {"message": self.message})
        self.assertEqual((run.status, run.error), (DONE, None))
        self.assertEqual(self.steps_of(run), ["start", "triage", "by_tone", "escalate", "end"])
        route = run.history[2]
        self.assertEqual(route["read"], "triage_decision.tone")
        self.assertEqual(route["check"], {"below": 0.6, "confidence": 0.55, "fired": True, "reason": "below"})
        self.assertEqual((route["value"], route["to"], route["result"]), (None, "escalate", {"to": "escalate"}))

    def test_without_a_model_the_agent_answers_and_the_check_fires_on_the_absent_confidence(self):
        engine = self.engine(None)
        run = engine.start(self.load(self.bundle), {"message": self.message})
        self.assertEqual((run.status, run.pause["kind"], run.pause["step"], run.pause["reason"]),
                         (PAUSED, "decision", "triage", "no_decision_model"))
        [task] = run.pause["tasks"]
        self.assertEqual([q["name"] for q in task["questions"]], ["billing", "tone"])
        self.assertEqual(task["questions"][1]["labels"], ["angry", "calm"])
        self.assertEqual(task["questions"][1]["criteria"][1], {"label": "calm", "text": "Neutral or polite, asking a question."})
        self.assertEqual(task["answer_with"], {"billing": "true_or_false", "tone": "choice"})
        self.assertEqual(task["state"], {"message": self.message})

        run = engine.resume(run, {"billing": True, "tone": {"value": "calm", "confidence": 0.99}})
        self.assertEqual(run.status, DONE)
        self.assertEqual(run.state["triage_decision"], {"billing": {"value": True}, "tone": {"value": "calm"}},
                         "a hand answer is its value and nothing else")
        triage = run.history[1]
        self.assertEqual((triage["answered_by"], triage["result"]), ("agent", run.state["triage_decision"]))
        self.assertEqual(run.history[2]["check"], {"below": 0.6, "confidence": None, "fired": True, "reason": "absent"})
        self.assertEqual(self.steps_of(run), ["start", "triage", "by_tone", "escalate", "end"])

    def test_a_hand_answer_is_checked_against_the_questions(self):
        engine = self.engine(None)
        run = engine.start(self.load(self.bundle), {"message": self.message})
        with self.assertRaises(InvalidOutput) as caught:
            engine.resume(run, {"billing": True, "tone": "furious"})
        self.assertEqual(caught.exception.invalid, ["tone"])
        self.assertIn("not one of the labels", caught.exception.message)
        with self.assertRaises(InvalidOutput) as caught:
            engine.resume(run, {"billing": "yes"})
        self.assertEqual((caught.exception.missing, caught.exception.invalid), (["tone"], ["billing"]))
        self.assertEqual(run.status, PAUSED, "the pause stands")

    def test_a_failing_model_hands_the_decision_to_the_agent_when_the_step_allows_it(self):
        engine = self.engine(ScriptedResolver({}))  # no script for triage: KeyError
        run = engine.start(self.load(self.bundle), {"message": self.message})
        self.assertEqual((run.status, run.pause["kind"]), (PAUSED, "decision"))
        self.assertTrue(run.pause["reason"].startswith("decision_model_failed: KeyError"), run.pause["reason"])

    def test_the_inputs_are_checked_before_anything_runs(self):
        engine = self.engine(ScriptedResolver({"triage": calm()}))
        procedure = self.load(self.bundle)
        with self.assertRaises(InvalidInput) as caught:
            engine.start(procedure, {})
        self.assertEqual(caught.exception.missing, ["message"])
        with self.assertRaises(InvalidInput) as caught:
            engine.start(procedure, {"message": 12})
        self.assertEqual(caught.exception.invalid, ["message"])
        with self.assertRaises(InvalidInput) as caught:
            engine.start(procedure, {"message": "x", "mesage": "y"})
        self.assertEqual(caught.exception.invalid, ["mesage"])
        with self.assertRaises(InvalidInput):
            engine.start(procedure, ["message"])

    def test_every_entry_carries_the_bundle_id_and_the_clock(self):
        engine = self.engine(ScriptedResolver({"triage": angry()}))
        run = engine.start(self.load(self.bundle), {"message": self.message})
        for entry in run.history:
            self.assertEqual((entry["bundle_id"], entry["at"], entry["pass"]), (self.bundle.id, CLOCK(), None))
            self.assertIn(entry["kind"], ("Start", "Decide", "Route", "Execute", "End"))
        self.assertEqual(run.history[0], {"bundle_id": self.bundle.id, "step": "start", "kind": "Start", "pass": None,
                                          "at": CLOCK(), "input": {"message": self.message}, "result": {}})

    def test_a_run_survives_a_round_trip_through_json(self):
        engine = self.engine(ScriptedResolver({"triage": calm()}))
        procedure = self.load(self.bundle)
        run = engine.start(procedure, {"message": self.message})
        data = json.loads(json.dumps(run.to_dict()))
        self.assertEqual(data["status"], PAUSED)
        from aip.model import Run

        restored = Run.from_dict(procedure, data)
        restored = engine.resume(restored, {"0": {"reply": "ok"}})
        self.assertEqual((restored.status, restored.state["reply"]), (DONE, "ok"))
        with self.assertRaises(ValueError):
            Run.from_dict(procedure, {**data, "bundle_id": "other"})

    def test_resume_is_refused_when_nothing_is_paused(self):
        engine = self.engine(ScriptedResolver({"triage": angry()}))
        run = engine.start(self.load(self.bundle), {"message": self.message})
        self.assertEqual(run.status, DONE)
        with self.assertRaises(NotPaused):
            engine.resume(run, {"reply": "x"})
        with self.assertRaises(NotPaused):
            engine.retry(run)

    def test_the_files_are_unpacked_once_per_bundle_id(self):
        engine = self.engine(ScriptedResolver({"triage": angry()}))
        engine.start(self.load(self.bundle), {"message": self.message})
        marker = self.home / "cache" / self.bundle.id / "marker"
        marker.write_text("kept")
        other = self.engine(ScriptedResolver({"triage": angry()}))
        run = other.start(self.load(self.bundle), {"message": self.message})
        self.assertEqual(run.status, DONE)
        self.assertEqual(marker.read_text(), "kept")
        self.assertEqual(sorted(p.name for p in (self.home / "cache").iterdir()), [self.bundle.id], "no temporary directory is left")
        if os.name == "posix":
            script = self.home / "cache" / self.bundle.id / "scripts" / "escalate.py"
            self.assertEqual(script.stat().st_mode & 0o777, self.bundle.file("scripts/escalate.py").mode)


AGGREGATE = '''
Procedure agg "Aggregations over a decision."

Start "The work." {
  work: string
  policy: string "Written into the question."
  Next_Step check
}

Decide check "Does the work follow each policy?" {
  Read work
  Answer_Questions {
    pii:    true_or_false "No personal data. Policy: {policy}"
    claims: true_or_false "Only approved claims."
  }
  History true
  Produce policy_check
  Next_Step judge
}

Decide judge "How does it read?" {
  Read work
  Answer_Questions {
    tone:   choice [calm, angry] "How does it sound?"
    risk:   score [low, medium, high] "How risky is it?"
  }
  Produce judgement
  Next_Step summarize
}

Aggregate summarize "Combine." {
  Read policy_check, judgement
  Aggregations {
    all_hold:   All policy_check.pii
    both:       All policy_check With Confidence_Above 0.7
    any_fails:  Any policy_check.claims == false
    none_angry: None judgement.tone == angry With Confidence_Above 0.8
    not_high:   All judgement.risk != high With Confidence_Above 0.5
  }
  Produce summary
  Next_Step by_all
}

Route by_all "Branch on the aggregation." {
  Read summary.both
  true -> end
  false -> fix
}

Task_Agent fix "Fix {work}: tone was {judgement.tone.value}." {
  Read work
  Produce fixed: string
  Next_Step end
}

End "The work." {
  Read work, summary
}
'''


@needs_relate
class Aggregations(EngineCase):
    def run_with(self, check: dict, judge: dict, policy: str = "no names"):
        resolver = ScriptedResolver({"check": check, "judge": judge})
        engine = self.engine(resolver)
        run = engine.start(self.load(program(AGGREGATE)), {"work": "Dear customer", "policy": policy})
        return engine, resolver, run

    def test_all_any_none_with_bars_and_not_equal(self):
        engine, resolver, run = self.run_with(
            {"pii": answers.true_or_false(0.95), "claims": answers.true_or_false(0.6)},
            {"tone": answers.choice({"calm": 0.75, "angry": 0.25}), "risk": answers.score({0: 0.5, 1: 0.3, 2: 0.2})})
        summary = run.state["summary"]
        self.assertEqual(summary, {"all_hold": {"value": True}, "both": {"value": False}, "any_fails": {"value": False},
                                   "none_angry": {"value": False}, "not_high": {"value": True}},
                         "an aggregation's answers carry a value and nothing else")
        agg = run.history[3]
        self.assertEqual(agg["kind"], "Aggregate")
        self.assertEqual(set(agg["input"]), {"policy_check", "judgement"})
        r = agg["resolutions"]
        self.assertEqual(r["all_hold"], [{"source": "policy_check.pii", "value": True, "holds": True, "probability": 0.95, "barred": False}])
        # `All policy_check` tests every answer of the decision, a bare true_or_false as == true; claims at 0.6 is under the 0.7 bar
        self.assertEqual(r["both"], [{"source": "policy_check.pii", "value": True, "holds": True, "probability": 0.95, "barred": False},
                                     {"source": "policy_check.claims", "value": True, "holds": False, "probability": 0.6, "barred": True}])
        # == false on a true_or_false: the probability is 1 - noul
        self.assertEqual(r["any_fails"], [{"source": "policy_check.claims", "value": True, "holds": False, "probability": 0.4, "barred": False}])
        # None: `== angry` at 0.25 is under the 0.8 bar, so it counts as holding, which is what fails a None
        self.assertEqual(r["none_angry"], [{"source": "judgement.tone", "value": "calm", "holds": True, "probability": 0.25, "barred": True}])
        # != high on a score: the level by its label; the probability is 1 - p(high) = 0.8, above the bar
        self.assertEqual(r["not_high"], [{"source": "judgement.risk", "value": 0, "holds": True, "probability": 0.8, "barred": False}])
        # the route read summary.both (false) with no check and went to fix; the prompt names the fields
        self.assertEqual(run.status, PAUSED)
        self.assertEqual(run.history[4]["check"], None)
        self.assertEqual((run.history[4]["value"], run.history[4]["to"]), ("false", "fix"))
        self.assertEqual(run.pause["tasks"][0]["prompt"], "Fix Dear customer: tone was calm.")
        # the question interpolated {policy}, and the history went with the request of the step that says History true
        check, judge = resolver.requests
        self.assertEqual(check.questions[0].instruction, "No personal data. Policy: no names")
        self.assertEqual([e["step"] for e in check.history], ["start"])
        self.assertIsNone(judge.history)
        self.assertEqual((run.history[1]["history_sent"], run.history[2]["history_sent"]), (True, False))
        run = engine.resume(run, {"fixed": "Dear customer, fixed"})
        self.assertEqual((run.status, run.state["fixed"], set(run.result)), (DONE, "Dear customer, fixed", {"work", "summary"}))

    def test_an_aggregation_that_holds_routes_to_the_end(self):
        engine, _, run = self.run_with(
            {"pii": answers.true_or_false(0.95), "claims": answers.true_or_false(0.9)},
            {"tone": answers.choice({"calm": 0.9, "angry": 0.1}), "risk": answers.score({0: 0.9, 1: 0.05, 2: 0.05})})
        self.assertEqual((run.status, run.state["summary"]["both"]), (DONE, {"value": True}))
        self.assertEqual(self.steps_of(run), ["start", "check", "judge", "summarize", "by_all", "end"])
        self.assertEqual(set(run.result), {"work", "summary"})

    def test_hand_answers_have_no_probability_and_fail_every_bar(self):
        engine = self.engine(None)
        source = AGGREGATE.replace("History true", "History true\n  Agent_Fallback true").replace("Produce judgement", "Agent_Fallback true\n  Produce judgement")
        run = engine.start(self.load(program(source)), {"work": "w", "policy": "p"})
        run = engine.resume(run, {"pii": True, "claims": True})
        run = engine.resume(run, {"tone": "calm", "risk": 0})
        summary = run.state["summary"]
        self.assertEqual(summary["all_hold"], {"value": True}, "no bar: the condition counts as it is")
        self.assertEqual(summary["both"], {"value": False})
        self.assertEqual(summary["none_angry"], {"value": False})
        self.assertEqual(summary["not_high"], {"value": False})
        self.assertTrue(all(x["probability"] is None and x["barred"] for x in run.history[3]["resolutions"]["both"]))

    def test_a_model_answer_is_checked_against_the_questions(self):
        _, _, run = self.run_with({"pii": answers.true_or_false(0.95), "claims": answers.true_or_false(0.6)},
                                  {"tone": answers.choice({"calm": 0.75, "angry": 0.25}), "risk": {"value": 7}})
        self.assertEqual((run.status, run.error["error"], run.error["step"], run.error["invalid"]), (FAILED, "invalid_output", "judge", ["risk"]))
        self.assertIn("level 7 is outside 0..2", run.error["message"])


SCRIPTS = '''
Procedure scripted "A script drives a route."
  Requires python 3.10

Start "Input." {
  n: integer
  Next_Step check
}

Execute check "Is n even?" {
  Read n
  Run_Script scripts/check.py
  Use assets/limits.json
  Produce even: true_or_false, size: choice
  Next_Step by_even
}

Route by_even "Branch on the script's answer." {
  Read even
  true -> by_size
  false -> end
}

Route by_size "Branch on a label." {
  Read size
  small -> end
  large -> end
}

End "Done." {
  Read n, even, size
}
'''

CHECK_PY = '''
import json, sys
p = json.load(sys.stdin)
n = p["state"]["n"]
limits = json.loads(p["assets"]["limits"])
assert p["expects"] == {"even": "true_or_false"}, p["expects"]
assert "AIP_WORKDIR" in __import__("os").environ
print(json.dumps({"even": n % 2 == 0, "size": {"value": "small" if n < limits["big"] else "large"}}))
'''


@needs_relate
class Scripts(EngineCase):
    def bundle(self, script: str = CHECK_PY, source: str = SCRIPTS):
        return program(source, {"scripts/check.py": script, "assets/limits.json": '{"big": 100}'})

    def test_a_bare_answer_from_a_script_is_stored_as_an_answer_and_routed_on(self):
        engine = self.engine()
        run = engine.start(self.load(self.bundle()), {"n": 4})
        self.assertEqual((run.status, run.error), (DONE, None))
        self.assertEqual(run.state["even"], {"value": True}, "true is stored as {value: true}")
        self.assertEqual(run.state["size"], {"value": "small"})
        self.assertEqual(self.steps_of(run), ["start", "check", "by_even", "by_size", "end"])
        self.assertEqual(run.history[2]["check"], None)
        self.assertEqual(run.history[2]["input"], {"even": {"value": True}})
        self.assertEqual((run.history[2]["value"], run.history[3]["value"]), ("true", "small"))
        self.assertEqual(run.result, {"n": 4, "even": {"value": True}, "size": {"value": "small"}})
        run = engine.start(self.load(self.bundle()), {"n": 3})
        self.assertEqual(self.steps_of(run), ["start", "check", "by_even", "end"])

    def test_a_script_that_fails_fails_the_step_and_a_retry_runs_it_again(self):
        engine = self.engine()
        run = engine.start(self.load(self.bundle('import sys; sys.stderr.write("boom"); sys.exit(3)')), {"n": 4})
        self.assertEqual(run.status, FAILED)
        self.assertEqual({k: run.error[k] for k in ("error", "step", "script", "exit_code", "stderr")},
                         {"error": "script_failed", "step": "check", "script": "scripts/check.py", "exit_code": 3, "stderr": "boom"})
        self.assertEqual(self.steps_of(run), ["start"], "the record keeps everything up to the failure")
        self.assertEqual(run.at, "step:check")
        run = engine.retry(run)
        self.assertEqual((run.status, run.error["error"]), (FAILED, "script_failed"))

    def test_a_script_output_is_checked_against_produce(self):
        engine = self.engine()
        run = engine.start(self.load(self.bundle('print(\'{"even": true, "extra": 1}\')')), {"n": 4})
        self.assertEqual((run.status, run.error["error"], run.error["script"]), (FAILED, "invalid_output", "scripts/check.py"))
        self.assertEqual((run.error["missing"], run.error["invalid"]), (["size"], ["extra"]))
        run = engine.start(self.load(self.bundle('print(\'{"even": "yes", "size": "small"}\')')), {"n": 4})
        self.assertEqual((run.status, run.error["invalid"]), (FAILED, ["even"]))
        run = engine.start(self.load(self.bundle("print('not json')")), {"n": 4})
        self.assertEqual((run.status, run.error["error"]), (FAILED, "script_failed"))

    def test_a_value_with_no_branch_fails_the_route(self):
        engine = self.engine()
        run = engine.start(self.load(self.bundle(CHECK_PY.replace('"small" if n < limits["big"] else "large"', '"huge"'))), {"n": 4})
        self.assertEqual((run.status, run.error["error"], run.error["step"]), (FAILED, "no_branch", "by_size"))
        self.assertEqual((run.error["value"], run.error["branches"]), ("huge", ["large", "small"]))

    def test_a_timeout_and_an_unmet_requires(self):
        engine = self.engine(timeout=0.5)
        run = engine.start(self.load(self.bundle("import time; time.sleep(5)")), {"n": 4})
        self.assertEqual((run.status, run.error["error"], run.error["seconds"]), (FAILED, "timeout", 0.5))
        run = self.engine().start(self.load(self.bundle(source=SCRIPTS.replace("python 3.10", "python 99.0"))), {"n": 4})
        self.assertEqual((run.status, run.error["error"]), (FAILED, "requires_unmet"))
        self.assertTrue(run.error["missing"][0].startswith("interpreter python>=99.0 (found 3."), run.error["missing"])

    def test_a_command_line_replaces_the_launcher(self):
        source = SCRIPTS.replace("Run_Script scripts/check.py", 'Run_Script scripts/check.py\n  Command "python scripts/check.py --flag"')
        script = CHECK_PY.replace("n = p", 'assert sys.argv[1:] == ["--flag"], sys.argv\nn = p')
        run = self.engine().start(self.load(self.bundle(script, source)), {"n": 4})
        self.assertEqual((run.status, run.error), (DONE, None))


SCORED = '''
Procedure scored "A route on a score by its label."

Start "Input." {
  text: string
  Next_Step rate
}

Decide rate "Rate it." {
  Read text
  Answer_Questions {
    urgency: score [low, medium, high] "How urgent?"
  }
  Produce rating
  Next_Step by_urgency
}

Route by_urgency "Branch on the level." {
  Read rating.urgency
  Confidence_Below 0.5 -> end
  low -> end
  medium -> end
  high -> escalate
}

Task_Agent escalate "Escalate: urgency {rating.urgency.value}." {
  Read text
  Produce note: string
  Next_Step end
}

End "Done." {
  Read text
}
'''


@needs_relate
class Scores(EngineCase):
    def test_a_score_branches_by_the_label_of_its_level(self):
        engine = self.engine(ScriptedResolver({"rate": {"urgency": answers.score({"0": 0.1, "1": 0.2, "2": 0.7})}}))
        run = engine.start(self.load(program(SCORED)), {"text": "server down"})
        self.assertEqual((run.status, run.pause["step"]), (PAUSED, "escalate"))
        self.assertEqual(run.state["rating"]["urgency"], {"value": 2, "confidence": 0.7, "score": 1.6, "probabilities": {"0": 0.1, "1": 0.2, "2": 0.7}})
        self.assertEqual((run.history[2]["value"], run.history[2]["to"]), ("high", "escalate"))
        self.assertEqual(run.pause["tasks"][0]["prompt"], "Escalate: urgency 2.")
        run = engine.resume(run, [{"note": "paged"}])
        self.assertEqual(run.status, DONE)

    def test_an_unsure_score_takes_the_check(self):
        engine = self.engine(ScriptedResolver({"rate": {"urgency": answers.score({"0": 0.3, "1": 0.3, "2": 0.4})}}))
        run = engine.start(self.load(program(SCORED)), {"text": "x"})
        self.assertEqual((run.status, self.steps_of(run)), (DONE, ["start", "rate", "by_urgency", "end"]))
        self.assertEqual(run.history[2]["check"]["reason"], "below")


@needs_relate
class Loops(EngineCase):
    def test_a_flow_into_a_loop_fails_until_the_next_milestone(self):
        engine = self.engine()
        run = engine.start(self.load(compiled("dynamic-policy")), {"task": "write", "policies": ["short"]})
        self.assertEqual((run.status, run.pause["step"]), (PAUSED, "draft"))
        run = engine.resume(run, {"work": "a draft"})
        self.assertEqual((run.status, run.error["step"]), (FAILED, "revise"))
        self.assertIn("R2", run.error["message"])


class Answers(unittest.TestCase):
    """The answer objects and the type checks need no store."""

    def test_answer_objects(self):
        self.assertEqual(answers.true_or_false(0.98), {"value": True, "confidence": 0.96, "noul": 0.98})
        self.assertEqual(answers.true_or_false(0.3)["value"], False)
        self.assertEqual(answers.choice({"angry": 0.9, "calm": 0.1}), {"value": "angry", "confidence": 0.9, "probabilities": {"angry": 0.9, "calm": 0.1}})
        self.assertEqual(answers.score({0: 0.1, 1: 0.1, 2: 0.8}), {"value": 2, "confidence": 0.8, "score": 1.7, "probabilities": {"0": 0.1, "1": 0.1, "2": 0.8}})
        self.assertEqual(answers.by_hand("calm"), {"value": "calm"})
        self.assertEqual(answers.probability_of(answers.true_or_false(0.98), "true_or_false", False), 1 - 0.98)
        self.assertEqual(answers.probability_of(answers.choice({"a": 0.6, "b": 0.4}), "choice", "b"), 0.4)
        self.assertEqual(answers.probability_of(answers.score({0: 0.6, 1: 0.4}), "score", 1), 0.4)
        self.assertIsNone(answers.probability_of({"value": True}, "true_or_false", True))

    def test_conforms_and_normalise(self):
        from aip.model import branch_key, conforms, normalise

        self.assertIsNone(conforms("string", "x"))
        self.assertIsNotNone(conforms("integer", True), "a boolean is not an integer")
        self.assertIsNone(conforms("float", 1))
        self.assertIsNone(conforms(None, object()))
        self.assertEqual(normalise("true_or_false", True), {"value": True})
        self.assertEqual(normalise("choice", "a"), {"value": "a"})
        self.assertEqual(normalise("string", "a"), "a")
        self.assertIsNotNone(conforms("choice", {"value": "c"}, ["a", "b"]))
        self.assertIsNotNone(conforms("true_or_false", {"value": True, "confidence": 2}))
        self.assertIsNotNone(conforms("true_or_false", True), "a bare value is normalised before it is checked")
        self.assertEqual((branch_key(True), branch_key("calm"), branch_key(2, ["low", "medium", "high"]), branch_key(5)),
                         ("true", "calm", "high", "5"))


if __name__ == "__main__":
    unittest.main()
