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

from aip.compiler import FileEntry, compile_folder, compile_source, example_dir, relate

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
    return {"billing": answers.true_or_false(0.97), "tone": answers.choice({"calm": 0.05, "angry": 0.95})}


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
        self.assertEqual(run.result, {"message": self.message, "reply": "Sorry about that. The policy allows a refund within 30 days."},
                         "End names the ticket keys too, but this path produced the reply")
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
        self.assertEqual(escalate["stdin"]["expects"], {"ticket_id": "integer", "queue": "string"}, "the step's own Produce keys")
        self.assertEqual(escalate["result"]["queue"], "tier2")
        self.assertIsInstance(escalate["result"]["ticket_id"], int)
        self.assertIsInstance(escalate["seconds"], float)
        self.assertEqual(run.state["queue"], "tier2")
        self.assertTrue((self.home / "cache" / self.bundle.id / "scripts" / "escalate.py").is_file())
        route = run.history[2]
        self.assertEqual(route["check"], {"below": 0.9, "confidence": 0.95, "fired": False, "reason": None})
        self.assertEqual((route["value"], route["to"]), ("angry", "escalate"))

    def test_the_confidence_arm_escalates_an_unsure_calm(self):
        engine = self.engine(ScriptedResolver({"triage": unsure()}))
        run = engine.start(self.load(self.bundle), {"message": self.message})
        self.assertEqual((run.status, run.error), (DONE, None))
        self.assertEqual(self.steps_of(run), ["start", "triage", "by_tone", "escalate", "end"])
        route = run.history[2]
        self.assertEqual(route["read"], "triage_decision.tone")
        self.assertEqual(route["check"], {"below": 0.9, "confidence": 0.55, "fired": True, "reason": "below"})
        self.assertEqual((route["value"], route["to"], route["result"]), (None, "escalate", {"to": "escalate"}))

    def test_without_a_model_the_decision_fails_the_run_and_a_retry_with_one_goes_on(self):
        """Spec 2.4: a Decide is always a model's; there is no agent fallback (plan L4)."""
        procedure = self.load(self.bundle)
        run = self.engine(None).start(procedure, {"message": self.message})
        self.assertEqual((run.status, run.error["error"], run.error["step"], run.at), (FAILED, "no_decision_model", "triage", "step:triage"))
        self.assertIn("configure one", run.error["message"])
        self.assertEqual(self.steps_of(run), ["start"], "nothing is recorded for the decision")
        with self.assertRaises(NotPaused):
            self.engine(None).resume(run, {"billing": True, "tone": "calm"})
        run = self.engine(ScriptedResolver({"triage": calm()})).retry(run)
        self.assertEqual((run.status, run.pause["kind"], run.pause["step"]), (PAUSED, "task", "reply"))
        self.assertEqual(run.history[1]["answered_by"], {"model": "scripted", "endpoint": None}, "the record names the model and its endpoint")

    def test_a_failing_model_fails_the_step_and_a_retry_asks_again(self):
        engine = self.engine(ScriptedResolver({}))  # no script for triage: KeyError
        run = engine.start(self.load(self.bundle), {"message": self.message})
        self.assertEqual((run.status, run.error["error"], run.error["step"]), (FAILED, "decision_model_failed", "triage"))
        self.assertTrue(run.error["cause"].startswith("KeyError"), run.error["cause"])
        run = engine.retry(run)
        self.assertEqual((run.status, run.error["error"]), (FAILED, "decision_model_failed"))
        run = self.engine(ScriptedResolver({"triage": angry()})).retry(run)
        self.assertEqual((run.status, self.steps_of(run)), (DONE, ["start", "triage", "by_tone", "escalate", "end"]))

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
            self.assertEqual((entry["bundle_id"], entry["at"], entry["pass"], entry["passes"]), (self.bundle.id, CLOCK(), None, []))
            self.assertIn(entry["kind"], ("Start", "Decide", "Route", "Execute", "End"))
        self.assertEqual(run.history[0], {"bundle_id": self.bundle.id, "step": "start", "kind": "Start", "pass": None, "passes": [],
                                          "at": CLOCK(), "input": {"message": self.message}, "result": {}})
        self.assertEqual(run.identity, {"agent": None, "session": None, "user": None})

    def test_the_identity_is_the_run_s(self):
        engine = self.engine(ScriptedResolver({"triage": angry()}))
        run = engine.start(self.load(self.bundle), {"message": self.message}, identity={"agent": "claude-code 2.1", "session": "s-1"})
        self.assertEqual(run.identity, {"agent": "claude-code 2.1", "session": "s-1", "user": None})
        self.assertEqual(run.to_dict()["identity"], run.identity)
        self.assertEqual(run.to_dict()["batch"], 10)

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


@needs_relate
class BillingSupportAgent(EngineCase):
    """`billing-support-agent`: the same procedure with the agent deciding in a `Task_Agent`
    under declared labels (spec 2.4), so it runs with no model at all and the route branches on
    the agent's answer with no confidence check."""

    def setUp(self):
        super().setUp()
        self.bundle = compiled("billing-support-agent")
        self.message = "Why was I charged twice this month?"

    def test_the_agent_classifies_and_the_route_branches_on_its_answer(self):
        engine = self.engine(None)
        procedure = self.load(self.bundle)
        run = engine.start(procedure, {"message": self.message})
        self.assertEqual((run.status, run.pause["kind"], run.pause["step"]), (PAUSED, "task", "triage"))
        [task] = run.pause["tasks"]
        self.assertIn("Customer message:\n" + self.message, task["prompt"])
        self.assertEqual(task["answer_with"], {"billing": "true_or_false", "tone": "choice"})
        self.assertEqual(task["labels"], {"tone": ["angry", "calm"]}, "the pause names the values the agent may answer with")
        self.assertEqual(task["state"], {"message": self.message})
        self.assertEqual(procedure.labels_of(["tone"]), ["angry", "calm"], "the labels live on the key")

        run = engine.resume(run, {"billing": True, "tone": "calm"})
        self.assertEqual((run.status, run.pause["kind"], run.pause["step"]), (PAUSED, "task", "reply"))
        self.assertEqual((run.state["billing"], run.state["tone"]), ({"value": True}, {"value": "calm"}),
                         "an agent's answer is its value and nothing else")
        route = run.history[2]
        self.assertEqual((route["read"], route["check"], route["value"], route["to"]), ("tone", None, "calm", "reply"))
        self.assertEqual(run.pause["tasks"][0]["state"]["tone"], {"value": "calm"})
        run = engine.resume(run, {"reply": "Sorry about that. The policy allows a refund within 30 days."})
        self.assertEqual((run.status, self.steps_of(run)), (DONE, ["start", "triage", "by_tone", "reply", "end"]))

    def test_an_angry_answer_runs_the_script(self):
        engine = self.engine(None)
        run = engine.start(self.load(self.bundle), {"message": self.message})
        run = engine.resume(run, {"billing": True, "tone": {"value": "angry"}})
        self.assertEqual((run.status, self.steps_of(run)), (DONE, ["start", "triage", "by_tone", "escalate", "end"]))
        self.assertEqual(run.history[3]["stdin"]["state"], {"message": self.message, "tone": {"value": "angry"}})
        self.assertEqual(run.state["queue"], "tier2")

    def test_the_answer_is_checked_against_the_produce_keys(self):
        engine = self.engine(None)
        run = engine.start(self.load(self.bundle), {"message": self.message})
        with self.assertRaises(InvalidOutput) as caught:
            engine.resume(run, {"billing": "yes"})
        self.assertEqual((caught.exception.missing, caught.exception.invalid), (["tone"], ["billing"]))
        self.assertEqual(run.status, PAUSED, "the pause stands")

    def test_the_answer_is_checked_against_the_labels_and_carries_nothing_but_its_value(self):
        """Plan R4: an agent's answer is a bare value or `{"value": ...}` among the key's labels;
        anything else on it is `invalid_output` (spec 2.4)."""
        engine = self.engine(None)
        run = engine.start(self.load(self.bundle), {"message": self.message})
        with self.assertRaises(InvalidOutput) as caught:
            engine.resume(run, {"billing": True, "tone": "furious"})
        self.assertEqual(caught.exception.invalid, ["tone"])
        self.assertIn("'furious' is not one of the labels ['angry', 'calm']", caught.exception.message)
        with self.assertRaises(InvalidOutput) as caught:
            engine.resume(run, {"billing": True, "tone": {"value": "calm", "confidence": 0.9}})
        self.assertEqual(caught.exception.invalid, ["tone"])
        self.assertIn("an agent's answer is its value and nothing else, not confidence", caught.exception.message)
        self.assertEqual(run.status, PAUSED, "the pause stands")
        run = engine.resume(run, {"billing": True, "tone": {"value": "calm"}})
        self.assertEqual((run.status, run.pause["step"], run.state["tone"]), (PAUSED, "reply", {"value": "calm"}))


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
            {"tone": answers.choice({"calm": 0.75, "angry": 0.25}), "risk": answers.score({"low": 0.5, "medium": 0.3, "high": 0.2})})
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
        # != high on a score, whose value is its level's label; the probability is 1 - p(high) = 0.8, above the bar
        self.assertEqual(r["not_high"], [{"source": "judgement.risk", "value": "low", "holds": True, "probability": 0.8, "barred": False}])
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
            {"tone": answers.choice({"calm": 0.9, "angry": 0.1}), "risk": answers.score({"low": 0.9, "medium": 0.05, "high": 0.05})})
        self.assertEqual((run.status, run.state["summary"]["both"]), (DONE, {"value": True}))
        self.assertEqual(self.steps_of(run), ["start", "check", "judge", "summarize", "by_all", "end"])
        self.assertEqual(set(run.result), {"work", "summary"})

    def test_answers_without_probabilities_fail_every_bar(self):
        """A model that returns bare values (no probabilities) is unknown under a bar, so every bar fails closed."""
        _, _, run = self.run_with({"pii": {"value": True}, "claims": {"value": True}}, {"tone": {"value": "calm"}, "risk": {"value": "low"}})
        summary = run.state["summary"]
        self.assertEqual(summary["all_hold"], {"value": True}, "no bar: the condition counts as it is")
        self.assertEqual(summary["both"], {"value": False})
        self.assertEqual(summary["none_angry"], {"value": False})
        self.assertEqual(summary["not_high"], {"value": False})
        self.assertTrue(all(x["probability"] is None and x["barred"] for x in run.history[3]["resolutions"]["both"]))

    def test_a_model_answer_is_checked_against_the_questions(self):
        _, _, run = self.run_with({"pii": answers.true_or_false(0.95), "claims": answers.true_or_false(0.6)},
                                  {"tone": answers.choice({"calm": 0.75, "angry": 0.25}), "risk": {"value": "extreme"}})
        self.assertEqual((run.status, run.error["error"], run.error["step"], run.error["invalid"]), (FAILED, "invalid_output", "judge", ["risk"]))
        self.assertIn("'extreme' is not one of the levels ['low', 'medium', 'high']", run.error["message"])

    def test_a_score_from_the_model_as_a_number_is_refused(self):
        """Spec 2.4: a score's value is its level's label; the resolver maps the model's number on receipt."""
        _, _, run = self.run_with({"pii": answers.true_or_false(0.95), "claims": answers.true_or_false(0.6)},
                                  {"tone": answers.choice({"calm": 0.75, "angry": 0.25}), "risk": {"value": 2}})
        self.assertEqual((run.status, run.error["error"], run.error["invalid"]), (FAILED, "invalid_output", ["risk"]))

    def test_a_bar_holds_only_strictly_above_it(self):
        """Spec 2.5: `With Confidence_Above 0.7` is above 0.7; an answer at the bar is barred."""
        _, _, run = self.run_with({"pii": answers.true_or_false(0.95), "claims": answers.true_or_false(0.7)},
                                  {"tone": answers.choice({"calm": 0.9, "angry": 0.1}), "risk": answers.score({"low": 0.9, "medium": 0.05, "high": 0.05})})
        self.assertEqual(run.history[3]["resolutions"]["both"][1],
                         {"source": "policy_check.claims", "value": True, "holds": False, "probability": 0.7, "barred": True})
        self.assertEqual(run.state["summary"]["both"], {"value": False})
        from aip.model import steps
        just_above = steps.resolve_condition(answers.true_or_false(0.71), "true_or_false", None, None, 0.7, fails_as=False)
        self.assertEqual((just_above["holds"], just_above["barred"]), (True, False))


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
  Produce even: true_or_false, size: choice [small, large]
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
assert p["expects"] == {"even": "true_or_false", "size": "choice"}, p["expects"]   # the step's own Produce keys
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

    def test_a_label_the_key_does_not_declare_is_refused_at_the_script(self):
        """Plan R4: a script's answer is checked against the key's labels where it is produced,
        so a stray label never reaches the route (which would have failed with `no_branch`)."""
        engine = self.engine()
        run = engine.start(self.load(self.bundle(CHECK_PY.replace('"small" if n < limits["big"] else "large"', '"huge"'))), {"n": 4})
        self.assertEqual((run.status, run.error["error"], run.error["step"], run.error["invalid"]), (FAILED, "invalid_output", "check", ["size"]))
        self.assertIn("'huge' is not one of the labels ['small', 'large']", run.error["message"])

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
        engine = self.engine(ScriptedResolver({"rate": {"urgency": answers.score({"low": 0.1, "medium": 0.2, "high": 0.7})}}))
        run = engine.start(self.load(program(SCORED)), {"text": "server down"})
        self.assertEqual((run.status, run.pause["step"]), (PAUSED, "escalate"))
        self.assertEqual(run.state["rating"]["urgency"], {"value": "high", "confidence": 0.7, "score": 1.6, "probabilities": {"low": 0.1, "medium": 0.2, "high": 0.7}},
                         "the value is the level's label, the expected level stays beside it as score")
        self.assertEqual((run.history[2]["value"], run.history[2]["to"]), ("high", "escalate"))
        self.assertEqual(run.pause["tasks"][0]["prompt"], "Escalate: urgency high.")
        run = engine.resume(run, [{"note": "paged"}])
        self.assertEqual(run.status, DONE)

    def test_an_unsure_score_takes_the_check(self):
        engine = self.engine(ScriptedResolver({"rate": {"urgency": answers.score({"low": 0.3, "medium": 0.3, "high": 0.4})}}))
        run = engine.start(self.load(program(SCORED)), {"text": "x"})
        self.assertEqual((run.status, self.steps_of(run)), (DONE, ["start", "rate", "by_urgency", "end"]))
        self.assertEqual(run.history[2]["check"]["reason"], "below")


def without_timestamps(history):
    """The record less what the clock wrote: `at`, and a script's `seconds`."""
    return [{k: v for k, v in e.items() if k not in ("at", "seconds")} for e in history]


def policy_verdicts(request):
    """dynamic-policy's `check`: the question carries the policy; a policy mentioning "short"
    fails until the work says it was fixed. Deterministic per pass, whatever the batch."""
    out = {}
    for q in request.questions:
        fails = "short" in q.instruction and "fixed" not in request.state["work"]
        out[q.name] = answers.true_or_false(0.2 if fails else 0.95)
    return out


@needs_relate
class DynamicPolicy(EngineCase):
    """The proof: `dynamic-policy` with the scripted resolver gives byte-identical records at
    `--batch 1` and `--batch 10` apart from timestamps; a batch of the single-`Decide` body is
    one model call."""

    POLICIES = ["be polite", "be short", "use no names"]

    def setUp(self):
        super().setUp()
        self.bundle = compiled("dynamic-policy")

    def drive(self, batch, resolver=None, clock=None):
        resolver = resolver or ScriptedResolver({"check": policy_verdicts})
        engine = Engine(resolver, home=self.home, workdir=self.tmp, batch=batch, **({"clock": clock} if clock else {}))
        run = engine.start(self.load(self.bundle), {"task": "write a note", "policies": self.POLICIES})
        self.assertEqual((run.status, run.pause["step"]), (PAUSED, "draft"))
        run = engine.resume(run, {"work": "a draft"})
        self.assertEqual((run.status, run.pause["step"]), (PAUSED, "fix"), run.error)
        run = engine.resume(run, {"work": "a fixed draft"})
        self.assertEqual((run.status, run.error), (DONE, None))
        return engine, resolver, run

    def test_the_record_is_the_same_at_every_batch_size_and_a_batch_is_one_call(self):
        _, one, run_1 = self.drive(1)
        _, ten, run_10 = self.drive(10)
        self.assertEqual(without_timestamps(run_1.history), without_timestamps(run_10.history))
        self.assertEqual(run_1.result, run_10.result)
        self.assertEqual([len(r.questions) for r in one.requests], [1, 1, 1, 1, 1, 1], "batch 1: one call per policy per revise pass")
        self.assertEqual([len(r.questions) for r in ten.requests], [3, 3], "batch 10: one call per revise pass")
        self.assertEqual([q.name for q in ten.requests[0].questions], ["follows__0", "follows__1", "follows__2"])
        self.assertIn("be short", ten.requests[0].questions[1].instruction, "each copy of the question is rendered with its pass's item")
        self.assertEqual(ten.requests[0].state, {"work": "a draft"}, "the Read keys once")
        _, two, run_2 = self.drive(2)
        self.assertEqual(without_timestamps(run_2.history), without_timestamps(run_10.history))
        self.assertEqual([len(r.questions) for r in two.requests], [2, 1, 2, 1])

    def test_what_the_record_and_the_state_say(self):
        _, _, run = self.drive(10, clock=CLOCK)
        self.assertEqual([(e["step"], e["pass"]) for e in run.history],
                         [("start", None), ("draft", None), ("check", 0), ("check", 1), ("check", 2), ("review", 0),
                          ("summarize_check", 0), ("fix", 0), ("check", 0), ("check", 1), ("check", 2), ("review", 1),
                          ("summarize_check", 1), ("revise", None), ("end", None)])
        check = run.history[3]
        self.assertEqual(check["passes"], [{"loop": "revise", "pass": 0}, {"loop": "review", "pass": 1}])
        self.assertEqual(check["answered_by"], {"model": "scripted", "endpoint": None})
        self.assertEqual(check["result"], {"follows": answers.true_or_false(0.2)}, "recorded as if the pass had called alone")
        self.assertEqual(check["input"], {"work": "a draft"})
        review = run.history[5]
        self.assertEqual((review["kind"], review["pass"], review["passes"]), ("For", 0, [{"loop": "revise", "pass": 0}]))
        self.assertEqual(review["input"], {"policies": self.POLICIES})
        self.assertEqual(review["exit"], {"reason": "items"})
        self.assertEqual(review["result"]["iterations"], 3)
        self.assertEqual([v["follows"]["value"] for v in review["result"]["verdicts"]], [True, False, True], "collected in input order")
        summary = run.history[6]
        self.assertEqual(summary["result"], {"all_hold": {"value": False}})
        self.assertEqual([r["source"] for r in summary["resolutions"]["all_hold"]], ["verdicts[0].follows", "verdicts[1].follows", "verdicts[2].follows"])
        fix = run.history[7]
        self.assertEqual(fix["kind"], "Task_Agent")
        self.assertEqual(set(fix["input"]), {"task", "work", "policies", "verdicts", "check_summary"})
        revise = run.history[13]
        self.assertEqual((revise["kind"], revise["pass"], revise["passes"]), ("Loop", None, []))
        self.assertEqual(revise["exit"], {"reason": "until", "where": "summarize_check", "resolution": {
            "answer": "check_summary.all_hold", "value": True, "holds": True, "probability": None, "barred": False}},
            "the loop ends the moment the aggregate is produced and holds; fix does not run again")
        self.assertEqual(revise["result"], {"iterations": 2})
        self.assertEqual(run.state["iterations"], 2)
        self.assertNotIn("index", run.state, "the pass index is gone after the loop")
        self.assertEqual(set(run.result), {"work", "verdicts"})
        self.assertEqual(run.result["work"], "a fixed draft")

    def test_the_cap_fails_the_run_with_else_fail_and_a_retry_hits_it_again(self):
        resolver = ScriptedResolver({"check": {"follows": answers.true_or_false(0.2)}})  # never passes
        engine = self.engine(resolver)
        run = engine.start(self.load(self.bundle), {"task": "t", "policies": ["p"]})
        run = engine.resume(run, {"work": "w"})
        for _ in range(3):
            self.assertEqual((run.status, run.pause["step"]), (PAUSED, "fix"))
            run = engine.resume(run, {"work": "w2"})
        self.assertEqual(run.status, FAILED)
        self.assertEqual({k: run.error[k] for k in ("error", "step", "loop", "cap", "count", "pass")},
                         {"error": "loop_cap", "step": "revise", "loop": "revise", "cap": 3, "count": 3, "pass": 3})
        self.assertEqual([e["step"] for e in run.history].count("fix"), 3)
        self.assertEqual(run.at, "loop:revise")
        run = engine.retry(run)
        self.assertEqual((run.status, run.error["error"], run.error["count"]), (FAILED, "loop_cap", 3), "the count does not move on a retry")

    def test_a_list_longer_than_the_cap_fails_before_the_first_pass(self):
        engine = self.engine(ScriptedResolver({"check": policy_verdicts}))
        run = engine.start(self.load(self.bundle), {"task": "t", "policies": [f"p{i}" for i in range(21)]})
        run = engine.resume(run, {"work": "w"})
        self.assertEqual((run.status, run.error["error"], run.error["step"], run.error["count"], run.error["cap"]),
                         (FAILED, "loop_cap", "review", 21, 20))
        self.assertEqual([e["step"] for e in run.history], ["start", "draft"])

    def test_without_a_model_the_batch_fails_at_its_first_pass_and_a_retry_with_one_goes_on(self):
        procedure = self.load(self.bundle)
        run = self.engine(None).start(procedure, {"task": "t", "policies": self.POLICIES})
        run = self.engine(None).resume(run, {"work": "w"})
        self.assertEqual((run.status, run.error["error"], run.error["step"], run.error["pass"]), (FAILED, "no_decision_model", "check", 0))
        self.assertEqual(run.error["passes"], [{"loop": "revise", "pass": 0}, {"loop": "review", "pass": 0}])
        self.assertEqual([(e["step"], e["pass"]) for e in run.history], [("start", None), ("draft", None)])
        holds = ScriptedResolver({"check": {"follows": answers.true_or_false(0.9)}})
        run = self.engine(holds).retry(run)
        self.assertEqual((run.status, run.error), (DONE, None), "with a model the batch runs, every policy holds, the loop exits")
        self.assertEqual(len(holds.requests), 1, "one call for the batch")
        self.assertEqual([(e["step"], e["pass"]) for e in run.history][2:5], [("check", 0), ("check", 1), ("check", 2)])

    def test_a_failing_model_fails_the_batch_and_a_retry_makes_one_call_again(self):
        resolver = ScriptedResolver({})
        engine = self.engine(resolver)
        run = engine.start(self.load(self.bundle), {"task": "t", "policies": self.POLICIES})
        run = engine.resume(run, {"work": "w"})
        self.assertEqual((run.status, run.error["error"], run.error["pass"]), (FAILED, "decision_model_failed", 0))
        self.assertEqual(len(resolver.requests), 1, "one call for the batch")
        run = engine.retry(run)
        self.assertEqual((run.status, len(resolver.requests)), (FAILED, 2), "a retry makes one call for the batch again")

    def test_a_stray_or_missing_key_in_the_batched_reply_is_invalid_output(self):
        resolver = ScriptedResolver({"check": lambda r: {q.name: answers.true_or_false(0.9) for q in r.questions} | {"other__0": answers.true_or_false(0.9)}})
        engine = self.engine(resolver)
        run = engine.resume(engine.start(self.load(self.bundle), {"task": "t", "policies": self.POLICIES}), {"work": "w"})
        self.assertEqual((run.status, run.error["error"], run.error["pass"], run.error["invalid"]), (FAILED, "invalid_output", 0, ["other"]))
        resolver = ScriptedResolver({"check": lambda r: {q.name: answers.true_or_false(0.9) for q in r.questions[1:]}})
        engine = self.engine(resolver)
        run = engine.resume(engine.start(self.load(self.bundle), {"task": "t", "policies": self.POLICIES}), {"work": "w"})
        self.assertEqual((run.status, run.error["error"], run.error["pass"], run.error["missing"]), (FAILED, "invalid_output", 0, ["follows"]))

    def test_a_paused_run_inside_a_loop_survives_a_round_trip_through_json(self):
        from aip.model import Run

        engine = self.engine(ScriptedResolver({"check": policy_verdicts}))
        procedure = self.load(self.bundle)
        run = engine.resume(engine.start(procedure, {"task": "t", "policies": self.POLICIES}), {"work": "a draft"})
        self.assertEqual((run.status, run.at), (PAUSED, "step:fix"))
        restored = Run.from_dict(procedure, json.loads(json.dumps(run.to_dict())))
        self.assertEqual(restored.frames[0]["count"], 0)
        restored = engine.resume(restored, {"work": "a fixed draft"})
        self.assertEqual((restored.status, restored.state["iterations"]), (DONE, 2))


@needs_relate
class FixedPolicy(EngineCase):
    """The proof: `fixed-policy` exits the revise loop where `check_summary.all_hold` is produced."""

    def setUp(self):
        super().setUp()
        self.bundle = compiled("fixed-policy")

    def test_the_loop_exits_where_the_aggregate_is_produced(self):
        calls = []

        def check(request):
            calls.append(request.state["work"])
            sure = request.state["work"].endswith("!")
            return {q.name: answers.true_or_false(0.9 if sure else 0.6) for q in request.questions}

        engine = self.engine(ScriptedResolver({"check": check}))
        run = engine.start(self.load(self.bundle), {"request": "a welcome note"})
        run = engine.resume(run, {"work": "Welcome"})
        self.assertEqual((run.status, run.pause["step"]), (PAUSED, "fix"), "every answer true but under the 0.7 bar: all_hold is false")
        self.assertEqual(run.pause["tasks"][0]["passes"], [{"loop": "revise", "pass": 0}])
        self.assertEqual(run.pause["tasks"][0]["state"]["policy_check"]["pii"]["noul"], 0.6)
        run = engine.resume(run, {"work": "Welcome!"})
        self.assertEqual((run.status, run.error), (DONE, None))
        self.assertEqual([(e["step"], e["pass"]) for e in run.history],
                         [("start", None), ("draft", None), ("check", 0), ("summarize_check", 0), ("fix", 0), ("check", 1),
                          ("summarize_check", 1), ("revise", None), ("end", None)])
        revise = run.history[7]
        self.assertEqual((revise["exit"]["reason"], revise["exit"]["where"], revise["result"]), ("until", "summarize_check", {"iterations": 2}))
        self.assertEqual(calls, ["Welcome", "Welcome!"])
        self.assertEqual(run.result["work"], "Welcome!")
        self.assertEqual(run.result["policy_check"]["tone"]["noul"], 0.9, "End returns the last pass's decision")

    def test_else_exit_leaves_the_loop_at_the_cap(self):
        source = self.bundle.source.replace("Else_Fail", "Else_Exit")
        bundle = program(source, {f.path: f.data.decode() for f in self.bundle.files})
        engine = self.engine(ScriptedResolver({"check": lambda r: {q.name: answers.true_or_false(0.3) for q in r.questions}}))
        run = engine.start(self.load(bundle), {"request": "r"})
        run = engine.resume(run, {"work": "w"})
        for _ in range(3):
            run = engine.resume(run, {"work": "w"})
        self.assertEqual((run.status, run.error), (DONE, None))
        self.assertEqual(run.history[-2]["exit"], {"reason": "cap", "where": "head"})
        self.assertEqual(run.state["iterations"], 3)


def triage_answers(request):
    """ticket-triage's `classify`, from the ticket's text."""
    ticket = request.state["ticket"]
    tone = {"calm": 0.9, "angry": 0.1} if "please" in ticket.lower() else {"calm": 0.1, "angry": 0.9}
    return {"billing": answers.true_or_false(0.8), "tone": answers.choice(tone)}


@needs_relate
class TicketTriage(EngineCase):
    """A `For` whose body is a route, a task, a script and a review loop with `Again`: passes
    drive on until each pauses, one pause carries the passes waiting at the same step, and the
    record is the same at every batch size."""

    TICKETS = ["Please refund me", "Charged twice, fix it now", "Could you please check my plan"]
    POLICY = "We refund within 30 days. Be kind."

    def setUp(self):
        super().setUp()
        self.bundle = compiled("ticket-triage")

    def drive(self, batch):
        engine = Engine(ScriptedResolver({"classify": triage_answers}), home=self.home, workdir=self.tmp, batch=batch, clock=CLOCK)
        run = engine.start(self.load(self.bundle), {"tickets": self.TICKETS, "policy": self.POLICY})
        # the calm tickets wait at draft, the angry one ran the script to the end of its pass
        self.assertEqual((run.status, run.pause["kind"], run.pause["step"]), (PAUSED, "task", "draft"))
        self.assertEqual([(t["index"], t["pass"], t["state"]["ticket"]) for t in run.pause["tasks"]],
                         [(0, 0, self.TICKETS[0]), (1, 2, self.TICKETS[2])][:1 if batch == 1 else 2])
        if batch == 1:
            run = engine.resume(run, {"reply": "We refund within 30 days, of course."})
            self.assertEqual([(t["index"], t["pass"]) for t in run.pause["tasks"]], [(0, 2)])
            run = engine.resume(run, {"reply": "Sure, I will check."})
        else:
            run = engine.resume(run, {"0": {"reply": "We refund within 30 days, of course."}, "1": {"reply": "Sure, I will check."}})
        # the second reply fails the policy check, so its pass is in the revise loop
        self.assertEqual((run.status, run.pause["step"]), (PAUSED, "fix"))
        [task] = run.pause["tasks"]
        self.assertEqual((task["index"], task["pass"], task["passes"]), (0, 0, [{"loop": "each_ticket", "pass": 2}, {"loop": "revise", "pass": 0}]))
        self.assertEqual(task["state"]["reply"], "Sure, I will check.")
        run = engine.resume(run, {"reply": "We refund within 30 days. I checked your plan."})
        self.assertEqual((run.status, run.pause["step"]), (PAUSED, "summarize"))
        [task] = run.pause["tasks"]
        self.assertEqual(task["passes"], [])
        self.assertEqual(task["state"]["replies"][1], "Your request has been escalated to our tier-2 team: " + self.TICKETS[1])
        run = engine.resume(run, {"summary": "two replies, one escalation"})
        self.assertEqual((run.status, run.error), (DONE, None))
        return run

    def test_passes_pause_together_and_the_record_is_in_input_order(self):
        run = self.drive(10)
        self.assertEqual([(e["step"], e["pass"]) for e in run.history], [
            ("start", None),
            ("classify", 0), ("by_tone", 0), ("draft", 0), ("check", 0), ("revise", 0),
            ("classify", 1), ("by_tone", 1), ("escalate", 1),
            ("classify", 2), ("by_tone", 2), ("draft", 2), ("check", 2), ("fix", 0), ("check", 0), ("revise", 2),
            ("each_ticket", None), ("summarize", None), ("end", None)])
        self.assertEqual(run.history[5]["exit"], {"reason": "until", "where": "head", "resolution": {
            "answer": "passed", "value": True, "holds": True, "probability": None, "barred": False}})
        self.assertEqual(run.history[5]["result"], {"iterations": 0}, "the check passed before the first pass")
        fix, check_again, revise = run.history[13], run.history[14], run.history[15]
        self.assertEqual(fix["passes"], [{"loop": "each_ticket", "pass": 2}, {"loop": "revise", "pass": 0}])
        self.assertEqual(check_again["passes"], fix["passes"], "Again check re-runs check at the loop's level, during the pass")
        self.assertEqual(check_again["result"], {"passed": {"value": True}})
        self.assertEqual((revise["exit"]["reason"], revise["exit"]["where"], revise["result"]), ("until", "head", {"iterations": 1}))
        self.assertEqual(run.history[8]["result"]["queue"], "tier-2")
        each = run.history[16]
        self.assertEqual((each["kind"], each["exit"], each["result"]["iterations"]), ("For", {"reason": "items"}, 3))
        self.assertEqual(each["result"]["replies"][0], "We refund within 30 days, of course.")
        self.assertEqual(sorted(run.result), ["replies", "summary"])
        self.assertNotIn("queue", run.state, "a For pass's keys are gone unless collected")

    def test_the_record_matches_at_batch_one(self):
        self.assertEqual(without_timestamps(self.drive(1).history), without_timestamps(self.drive(10).history))

    def test_a_bad_answer_is_refused_a_missing_one_fails_its_pass_and_a_retry_asks_for_it_alone(self):
        engine = Engine(ScriptedResolver({"classify": triage_answers}), home=self.home, workdir=self.tmp, batch=10, clock=CLOCK)
        run = engine.start(self.load(self.bundle), {"tickets": self.TICKETS, "policy": self.POLICY})
        self.assertEqual([(t["index"], t["pass"]) for t in run.pause["tasks"]], [(0, 0), (1, 2)])
        with self.assertRaises(InvalidOutput):
            engine.resume(run, {"0": {"reply": "ok"}, "1": {"reply": 7}})
        self.assertEqual(run.status, PAUSED, "a bad answer is refused and the pause stands")
        run = engine.resume(run, {"0": {"reply": "We refund within 30 days, of course."}})
        self.assertEqual((run.status, run.error["error"], run.error["pass"], run.error["missing"]), (FAILED, "invalid_output", 2, ["1"]))
        recorded = [(e["step"], e["pass"]) for e in run.history]
        self.assertIn(("draft", 0), recorded, "the answered pass is recorded")
        self.assertIn(("escalate", 1), recorded, "the pass that finished is recorded")
        self.assertNotIn(("draft", 2), recorded, "the unanswered pass is not")
        run = engine.retry(run)
        self.assertEqual((run.status, run.pause["step"], [(t["index"], t["pass"]) for t in run.pause["tasks"]]), (PAUSED, "draft", [(0, 2)]))
        run = engine.resume(run, {"reply": "We refund within 30 days. I checked your plan."})
        self.assertEqual((run.status, run.pause["step"]), (PAUSED, "summarize"))


LOOPS = '''
Procedure loops "Counted and fold loops, the runtime's keys, a branch to Continue."
  Requires python 3.10

Start "In." {
  n: integer
  items: list
  Next_Step rounds
}

Loop rounds 3 Times {
  Execute bump "n + index + 1." {
    Read n, index
    Run_Script scripts/bump.py
    Produce n: integer
    Continue
  }
  Next_Step total
}

Loop total Over items As item, At_Most 5 {
  Execute add "n + item." {
    Read n, item
    Run_Script scripts/add.py
    Produce n: integer
    Next_Step gate
  }
  Route gate "Stop early on a big n." {
    Read big
    true -> Continue
    false -> Continue
  }
  Next_Step poll
}

Loop poll Until ready With Confidence_Above 0.5, At_Most 2, Else_Exit {
  Execute probe "Never sure." {
    Read n
    Run_Script scripts/probe.py
    Produce ready: true_or_false, big: true_or_false
    Continue
  }
  Next_Step end
}

End "Out." {
  Read n, iterations, ready
}
'''

NESTED = '''
Procedure nested "A loop in the body exits having produced the watched answer."
  Requires python 3.10

Start "In." {
  n: integer
  Next_Step outer
}

Loop outer Until done, At_Most 3 {
  Loop inner 2 Times {
    Execute mark "done when n reaches 3." {
      Read n
      Run_Script scripts/mark.py
      Produce n: integer, done: true_or_false
      Continue
    }
    Next_Step tail
  }
  Execute tail "Never runs once done." {
    Read n
    Run_Script scripts/tail.py
    Produce tail: string
    Continue
  }
  Next_Step end
}

End "Out." {
  Read n, done, iterations
}
'''

STDIN = "import json, sys\np = json.load(sys.stdin)\ns = p['state']\n"


@needs_relate
class LoopForms(EngineCase):
    def test_times_fold_the_runtime_keys_and_a_branch_to_continue(self):
        # `add` reads item; `gate` reads `big`, which `probe` produces later: a fold's gate needs it before the loop, so give it at Start
        source = LOOPS.replace("  items: list\n", "  items: list\n  big: true_or_false\n")
        bundle = program(source, {
            "scripts/bump.py": STDIN + "print(json.dumps({'n': s['n'] + s['index'] + 1}))",
            "scripts/add.py": STDIN + "print(json.dumps({'n': s['n'] + s['item']}))",
            "scripts/probe.py": STDIN + "print(json.dumps({'ready': True, 'big': s['n'] > 100}))",
        })
        run = self.engine().start(self.load(bundle), {"n": 0, "items": [10, 20], "big": False})
        self.assertEqual((run.status, run.error), (DONE, None))
        # rounds: 0 -> 1 -> 3 -> 6 (n + index + 1, three times); total: 6 + 10 + 20 = 36
        self.assertEqual([(e["step"], e["pass"], e["result"].get("n")) for e in run.history if e["step"] in ("bump", "add")],
                         [("bump", 0, 1), ("bump", 1, 3), ("bump", 2, 6), ("add", 0, 16), ("add", 1, 36)])
        exits = {e["step"]: (e["exit"], e["result"]["iterations"]) for e in run.history if e["kind"] == "Loop"}
        self.assertEqual(exits["rounds"], ({"reason": "times", "where": "head"}, 3))
        self.assertEqual(exits["total"], ({"reason": "items", "where": "head"}, 2))
        # `ready` is a script's answer with no probability, so the bar never lets it hold; Else_Exit leaves at the cap
        self.assertEqual(exits["poll"], ({"reason": "cap", "where": "head"}, 2))
        self.assertEqual([e["pass"] for e in run.history if e["step"] == "probe"], [0, 1])
        self.assertEqual(run.result, {"n": 36, "iterations": 2, "ready": {"value": True}})
        self.assertEqual([e["to"] for e in run.history if e["step"] == "gate"], ["Continue", "Continue"])

    def test_a_fold_longer_than_its_cap_fails_before_the_first_pass(self):
        source = LOOPS.replace("  items: list\n", "  items: list\n  big: true_or_false\n")
        bundle = program(source, {"scripts/bump.py": STDIN + "print(json.dumps({'n': 1}))", "scripts/add.py": "", "scripts/probe.py": ""})
        run = self.engine().start(self.load(bundle), {"n": 0, "items": [1, 2, 3, 4, 5, 6], "big": False})
        self.assertEqual((run.status, run.error["error"], run.error["step"], run.error["count"]), (FAILED, "loop_cap", "total", 6))
        self.assertEqual([e["step"] for e in run.history][-2:], ["bump", "rounds"])

    def test_an_inner_loop_exiting_with_the_watched_answer_ends_the_outer_one(self):
        bundle = program(NESTED, {
            "scripts/mark.py": STDIN + "n = s['n'] + 1\nprint(json.dumps({'n': n, 'done': n >= 3}))",
            "scripts/tail.py": STDIN + "print(json.dumps({'tail': 'ran'}))",
        })
        run = self.engine().start(self.load(bundle), {"n": 0})
        self.assertEqual((run.status, run.error), (DONE, None))
        self.assertEqual([(e["step"], e["pass"]) for e in run.history],
                         [("start", None), ("mark", 0), ("mark", 1), ("inner", 0), ("tail", 0), ("mark", 0), ("mark", 1), ("inner", 1),
                          ("outer", None), ("end", None)], "mark produces done inside the inner loop, which the outer sees when inner exits")
        outer = run.history[8]
        self.assertEqual((outer["exit"]["reason"], outer["exit"]["where"], outer["result"]), ("until", "inner", {"iterations": 2}))
        self.assertEqual(run.history[6]["passes"], [{"loop": "outer", "pass": 1}, {"loop": "inner", "pass": 1}])
        self.assertEqual(run.result, {"n": 4, "done": {"value": True}, "iterations": 2})
        self.assertEqual([e["step"] for e in run.history].count("tail"), 1, "the rest of the pass does not run")


HISTORY = '''
Procedure hist "A pass sees the record from before the loop and its own."

Start "In." {
  items: list
  Next_Step each
}

For each Over items As item, At_Most 5, Collect judgement Into judgements {
  Decide judge "Judge it." {
    Read item
    Answer_Questions {
      ok: true_or_false "Is it ok?"
    }
    History true
    Produce judgement
    Continue
  }
  Next_Step end
}

End "Out." {
  Read judgements
}
'''


LOOP_KEYS = """
Procedure loop_keys "Each loop has its own index and iterations."

Start "A list." {
  items: list
  Next_Step outer
}

Loop outer 2 Times {
  For inner Over items As item, At_Most 5 {
    Task_Agent each "Item {item}, pass {inner.index} of the inner loop, pass {outer.index} of the outer." {
      Read item, inner.index
      Produce o: string
      Continue
    }

    Next_Step after
  }

  Task_Agent after "The inner loop ran {inner.iterations} passes in pass {outer.index}." {
    Read inner, outer, iterations, index
    Produce note: string
    Continue
  }

  Next_Step last
}

Task_Agent last "Inner {inner.iterations}, outer {outer.iterations}." {
  Read inner, outer, iterations
  Produce z: string
  Next_Step end
}

End "Done." {
  Read z
}
"""


@needs_relate
class LoopKeys(EngineCase):
    """Spec 2.6: each loop's name is the runtime's key for it, `<loop>.index` while it runs and
    `<loop>.iterations` once it has exited, so the inner loop's count outlives the outer loop's."""

    def test_each_loop_writes_its_index_and_its_iterations_under_its_name(self):
        engine = self.engine()
        run = engine.start(self.load(program(LOOP_KEYS)), {"items": ["a", "b", "c"]})
        for outer in (0, 1):
            self.assertEqual((run.status, run.pause["step"]), (PAUSED, "each"))
            self.assertEqual([t["state"] for t in run.pause["tasks"]], [{"item": x, "index": i} for i, x in enumerate("abc")],
                             "Read inner.index: the step sees it under the last word of the path")
            self.assertEqual(run.pause["tasks"][1]["prompt"], f"Item b, pass 1 of the inner loop, pass {outer} of the outer.")
            run = engine.resume(run, [{"o": "x"}] * 3)
            self.assertEqual((run.status, run.pause["step"]), (PAUSED, "after"))
            [task] = run.pause["tasks"]
            self.assertEqual(task["state"], {"inner": {"iterations": 3}, "outer": {"index": outer}, "iterations": 3, "index": outer},
                             "the bare words are the last loop that exited and the innermost loop running")
            self.assertEqual(task["prompt"], f"The inner loop ran 3 passes in pass {outer}.")
            run = engine.resume(run, {"note": "n"})
        self.assertEqual((run.status, run.pause["step"]), (PAUSED, "last"))
        [task] = run.pause["tasks"]
        self.assertEqual(task["state"], {"inner": {"iterations": 3}, "outer": {"iterations": 2}, "iterations": 2},
                         "the outer loop's exit moved the bare iterations and left the inner loop's own")
        self.assertEqual(task["prompt"], "Inner 3, outer 2.")
        run = engine.resume(run, {"z": "done"})
        self.assertEqual((run.status, run.result), (DONE, {"z": "done"}))


@needs_relate
class Independence(EngineCase):
    def test_a_pass_reading_the_item_calls_alone_and_sees_only_the_record_before_the_loop(self):
        seen = {}
        for batch in (1, 10):
            resolver = ScriptedResolver(lambda r: {"ok": answers.true_or_false(0.9 if r.state["item"] else 0.1)})
            engine = Engine(resolver, home=self.home, clock=CLOCK, batch=batch)
            run = engine.start(self.load(program(HISTORY)), {"items": [True, False, True]})
            self.assertEqual((run.status, run.error), (DONE, None))
            self.assertEqual([len(r.questions) for r in resolver.requests], [1, 1, 1], "the Decide reads the item: one call per pass")
            self.assertEqual([[e["step"] for e in r.history] for r in resolver.requests], [["start"]] * 3)
            seen[batch] = run.history
        self.assertEqual(seen[1], seen[10])
        self.assertEqual([j["ok"]["value"] for j in run.state["judgements"]], [True, False, True])


class Batching(unittest.TestCase):
    """The suffix scheme needs no store."""

    def test_split_answers(self):
        from aip.model.procedure import Step
        from aip.model.steps import split_answers

        step = Step("step:check", "check", "Decide", "", {})
        self.assertEqual(split_answers(step, {"follows__0": 1, "follows__2": 2, "other__2": 3}, [0, 2]),
                         {0: {"follows": 1}, 2: {"follows": 2, "other": 3}})
        with self.assertRaises(InvalidOutput) as caught:
            split_answers(step, {"follows": 1}, [0])
        self.assertEqual(caught.exception.invalid, ["follows"])
        with self.assertRaises(InvalidOutput):
            split_answers(step, {"follows__7": 1}, [0])

    def test_the_scripted_resolver_answers_suffixed_questions_from_the_plain_name(self):
        from aip.model.procedure import Question
        from aip.model.resolver import DecisionRequest, question_base

        request = DecisionRequest("check", [Question("follows__0", "true_or_false", None, "", [], 0),
                                            Question("follows__1", "true_or_false", None, "", [], 0)], {})
        decision = ScriptedResolver({"check": {"follows": answers.true_or_false(0.9)}}).decide(request)
        self.assertEqual(set(decision.answers), {"follows__0", "follows__1"})
        self.assertEqual((question_base("follows__12"), question_base("follows"), question_base("a__b")), ("follows", "follows", "a__b"))


SCRIPT_ANSWERS = '''
Procedure script_answers "A script's answer, with or without a confidence, under a route's check."
  Requires python 3.10

Start "Input." {
  answer: object "What the script writes as tone."
  Next_Step classify
}

Execute classify "Write the given answer as tone." {
  Read answer
  Run_Script scripts/classify.py
  Produce tone: choice [angry, calm]
  Next_Step by_tone
}

Route by_tone "Branch on the script's answer, checking its confidence." {
  Read tone
  Confidence_Below 0.6 -> unsure
  angry -> end
  calm -> end
}

Task_Agent unsure "The script was not sure: look at it." {
  Read tone
  Produce verdict: string
  Next_Step end
}

End "Done." {
  Read tone
}
'''

CLASSIFY_PY = ('import json, sys\na = json.load(sys.stdin)["state"]["answer"]\n'
               'print(json.dumps({"tone": a["bare"] if "bare" in a else a}))\n')  # {"bare": "calm"} writes the bare value

LABELLED_INPUT = '''
Procedure labelled_input "An input under labels."

Start "Input." {
  tone: choice [angry, calm]
  Next_Step by_tone
}

Route by_tone "Branch on the input." {
  Read tone
  angry -> end
  calm -> end
}

End "Done." {
  Read tone
}
'''


@needs_relate
class ScriptAnswers(EngineCase):
    """Plan R4, spec 2.4: a script's answer may carry `confidence` and `probabilities` as a
    model's would, and a route's check reads them; written without a confidence the check fires
    (`absent`); a stray field or a label the key does not declare is `invalid_output`. An input
    under labels is checked the same way at `Start`."""

    def run_with(self, answer):
        bundle = program(SCRIPT_ANSWERS, {"scripts/classify.py": CLASSIFY_PY})
        return self.engine().start(self.load(bundle), {"answer": answer})

    def test_a_confident_answer_passes_the_check_on_its_value(self):
        run = self.run_with({"value": "calm", "confidence": 0.9, "probabilities": {"angry": 0.1, "calm": 0.9}})
        self.assertEqual((run.status, self.steps_of(run)), (DONE, ["start", "classify", "by_tone", "end"]))
        self.assertEqual(run.state["tone"], {"value": "calm", "confidence": 0.9, "probabilities": {"angry": 0.1, "calm": 0.9}},
                         "the script's confidence and probabilities are kept")
        self.assertEqual(run.history[2]["check"], {"below": 0.6, "confidence": 0.9, "fired": False, "reason": None})

    def test_a_low_or_absent_confidence_fires_the_check(self):
        run = self.run_with({"value": "calm", "confidence": 0.3})
        self.assertEqual((run.status, run.pause["step"]), (PAUSED, "unsure"))
        self.assertEqual(run.history[2]["check"], {"below": 0.6, "confidence": 0.3, "fired": True, "reason": "below"})
        run = self.run_with({"bare": "calm"})
        self.assertEqual((run.status, run.pause["step"]), (PAUSED, "unsure"))
        self.assertEqual(run.state["tone"], {"value": "calm"}, "a bare value is stored as an answer with no confidence")
        self.assertEqual(run.history[2]["check"], {"below": 0.6, "confidence": None, "fired": True, "reason": "absent"})

    def test_anything_but_the_model_fields_or_a_stray_label_is_invalid_output(self):
        run = self.run_with({"value": "calm", "legend": {"calm": "Calm."}})
        self.assertEqual((run.status, run.error["error"], run.error["step"], run.error["invalid"]), (FAILED, "invalid_output", "classify", ["tone"]))
        self.assertIn("a choice answer carries value, confidence, probabilities and nothing else, not legend", run.error["message"])
        run = self.run_with({"value": "furious", "confidence": 0.9})
        self.assertEqual((run.status, run.error["error"], run.error["invalid"]), (FAILED, "invalid_output", ["tone"]))
        self.assertIn("'furious' is not one of the labels", run.error["message"])
        run = self.run_with({"value": "calm", "probabilities": {"calm": 2}})
        self.assertEqual((run.status, run.error["error"]), (FAILED, "invalid_output"))

    def test_an_input_under_labels_is_checked_at_start(self):
        procedure = self.load(program(LABELLED_INPUT))
        with self.assertRaises(InvalidInput) as caught:
            self.engine().start(procedure, {"tone": "furious"})
        self.assertEqual(caught.exception.invalid, ["tone"])
        with self.assertRaises(InvalidInput) as caught:
            self.engine().start(procedure, {"tone": {"value": "calm", "confidence": 1}})
        self.assertIn("nothing else, not confidence", caught.exception.message)
        run = self.engine().start(procedure, {"tone": "calm"})
        self.assertEqual((run.status, run.result), (DONE, {"tone": {"value": "calm"}}))


class Answers(unittest.TestCase):
    """The answer objects and the type checks need no store."""

    def test_answer_objects(self):
        self.assertEqual(answers.true_or_false(0.98), {"value": True, "confidence": 0.96, "noul": 0.98})
        self.assertEqual(answers.true_or_false(0.3)["value"], False)
        self.assertEqual(answers.choice({"angry": 0.9, "calm": 0.1}), {"value": "angry", "confidence": 0.9, "probabilities": {"angry": 0.9, "calm": 0.1}})
        self.assertEqual(answers.score({"low": 0.1, "medium": 0.1, "high": 0.8}),
                         {"value": "high", "confidence": 0.8, "score": 1.7, "probabilities": {"low": 0.1, "medium": 0.1, "high": 0.8}})
        self.assertEqual(answers.probability_of(answers.true_or_false(0.98), "true_or_false", False), 1 - 0.98)
        self.assertEqual(answers.probability_of(answers.choice({"a": 0.6, "b": 0.4}), "choice", "b"), 0.4)
        self.assertEqual(answers.probability_of(answers.score({"low": 0.6, "high": 0.4}), "score", "high"), 0.4)
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
        self.assertIsNotNone(conforms("choice", {"value": "a", "probabilities": {"a": 2}}), "probabilities are numbers in 0..1")
        self.assertIsNone(conforms("choice", {"value": "a", "probabilities": {"a": 0.7, "b": 0.3}}))
        self.assertIsNotNone(conforms("true_or_false", True), "a bare value is normalised before it is checked")
        self.assertIsNone(conforms("score", {"value": "high"}, ["low", "high"]))
        self.assertIsNotNone(conforms("score", {"value": 1}, ["low", "high"]), "a score's value is its level's label, not its number")
        self.assertEqual(normalise("score", "high"), {"value": "high"})
        self.assertEqual((branch_key(True), branch_key(False), branch_key("calm"), branch_key("high")), ("true", "false", "calm", "high"))


if __name__ == "__main__":
    unittest.main()
