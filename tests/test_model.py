"""End-to-end tests for the AIP runtime model.

Builds a six-node graph (start, decision, router with a confidence check, execution, client
task, end) on a temp package directory and drives it through Procedure.run with a stub
TypeSafe client, so no API key or network is needed.
"""

import json
import tempfile
import unittest
from pathlib import Path

from typesafe_sdk import Choice, Noul, SystemOneResponse

from aip.model import (
    Asset, ClientTask, ConfidenceCheck, DataType, Decision, EndStep, Execution, InputValidationError,
    OutputValidationError, Meta, Procedure, Reference, ResourceLoader, Router, Script, Start, confidence,
    to_json_schema,
)


class FakeJev:
    """Stub TypeSafe client returning fixed noul / choice answers."""

    def __init__(self, tone_p: float, billing_p: float):
        self.tone_p, self.billing_p = tone_p, billing_p
        self.seen = None

    def system_one(self, state, questions, **_):
        self.seen = state
        return SystemOneResponse.model_validate_json(json.dumps({
            "model": "jev-1",
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "answers": {
                "billing": {"type": "noul", "noul": self.billing_p},
                "tone": {
                    "type": "choice",
                    "choice": "angry" if self.tone_p >= 0.5 else "calm",
                    "confidence": max(self.tone_p, 1 - self.tone_p),
                    "probabilities": {"angry": self.tone_p, "calm": 1 - self.tone_p},
                },
            },
        }))


def make_package(root: Path) -> None:
    for folder in ("assets", "references", "scripts"):
        (root / "billing" / folder).mkdir(parents=True)
    (root / "billing/assets/config.json").write_text('{"queue": "tier2"}')
    (root / "billing/assets/policy.md").write_text("Refunds within 30 days.")
    (root / "billing/assets/reply.md").write_text(
        "Skill: {meta.name}\nReply to: {message}\nPolicy:\n{assets[policy]}\nKeep {this} literal.")
    (root / "billing/references/help.md").write_text("long doc")
    (root / "billing/scripts/escalate.py").write_text(
        "import json, sys\n"
        "inp = json.load(sys.stdin)\n"
        "cfg = json.loads(inp['assets']['config'])\n"
        "assert inp['expects']['step'] == 'end', inp['expects']\n"
        "open('stdin.json', 'w').write(json.dumps(inp))\n"
        "json.dump({'ticket_id': 42, 'queue': cfg['queue']}, sys.stdout)\n")
    (root / "billing/scripts/boom.py").write_text("import sys; sys.exit('bad config')")
    (root / "billing/scripts/notjson.py").write_text("print('hello')")
    (root / "billing/scripts/extra.py").write_text("import json, sys; json.dump({'ticket_id': 1, 'note': 'x'}, sys.stdout)")
    (root / "billing/scripts/mistyped.py").write_text("import json, sys; json.dump({'ticket_id': 'one'}, sys.stdout)")


def make_procedure(root: Path, jev: FakeJev) -> Procedure:
    end = EndStep(inputs={"message": DataType.STRING})
    escalate = Execution(
        name="escalate",
        inputs={"tone": DataType.STRING, "message": DataType.STRING},
        script=Script("billing", "escalate.py"),
        assets=[Asset("billing", "config.json")],
        outputs={"ticket_id": DataType.INTEGER, "queue": DataType.STRING},
        inputsTo=end,
    )
    reply = ClientTask(
        name="reply",
        inputs={"tone": DataType.STRING, "message": DataType.STRING},
        template=Asset("billing", "reply.md"),
        assets=[Asset("billing", "policy.md")],
        references=[Reference("billing", "help.md", "help doc")],
        outputs={"reply": DataType.STRING},
        inputsTo=end,
    )
    # an uncertain tone is handled by hand: the check fires before the branches are read
    router = Router(name="by_tone", branch_on="tone", branches={"angry": escalate, "calm": reply},
                    confidence=ConfidenceCheck(key="tone_confidence", below=0.6, to=reply))
    triage = Decision(
        name="triage",
        inputs={"message": DataType.STRING},
        client=jev,
        questions={
            "billing": Noul(instructions="Is this about billing?"),
            "tone": Choice(instructions="Tone?", criteria={"angry": None, "calm": None}),
        },
        confidence=["tone"],
        fallback=True,
        inputsTo=router,
    )
    return Procedure(
        meta=Meta(name="billing-support", description="billing triage"),
        start=Start(name="start", inputs={"message": DataType.STRING}, inputsTo=triage),
        loader=ResourceLoader(root),
    )


class ProcedureRunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        make_package(self.root)
        self.jev = FakeJev(tone_p=0.9, billing_p=0.55)
        self.proc = make_procedure(self.root, self.jev)

    def tearDown(self):
        self.tmp.cleanup()

    def begin(self, payload):
        """Run the start step, then the first runnable step on what it handed on."""
        r0 = self.proc.run(None, payload)
        return self.proc.run(r0.ran, r0.suggested, r0.history)

    def test_graph_walk_binds_meta_and_loader(self):
        described = self.proc.describe()
        self.assertEqual(described["steps"], {
            "start": "start", "triage": "decision", "by_tone": "router", "escalate": "execution", "end": "end",
            "reply": "client_task"})
        self.assertEqual(described["start"], {"step": "start", "kind": "start", "inputs": {"message": "string"}})
        self.assertEqual(described["decisions"], {"triage": {"fallback": True, "confidence": ["tone"]}})
        self.assertEqual(described["routers"], {
            "by_tone": {"branch_on": "tone", "confidence": {"key": "tone_confidence", "below": 0.6, "to": "reply"}}})
        self.assertIs(self.proc.nodes["reply"].meta, self.proc.meta)
        self.assertIs(self.proc.nodes["escalate"].loader, self.proc.loader)
        with self.assertRaises(ValueError):                   # the start of a procedure is a Start node
            Procedure(meta=self.proc.meta, start=self.proc.nodes["triage"])
        with self.assertRaises(ValueError):                   # a confidence list names the step's questions
            Decision(name="d", questions={"q": Noul(instructions="?")}, confidence=["mood"])

    def test_start_step_checks_the_input_and_hands_it_on(self):
        r0 = self.proc.run(None, {"message": "I was charged twice", "customer": "acme"})
        self.assertEqual((r0.ran, r0.kind, r0.result), ("start", "start", {}))
        self.assertEqual(r0.suggested, {"message": "I was charged twice", "customer": "acme"})
        self.assertEqual(r0.history, [{"step": "start", "kind": "start", "input": {"message": "I was charged twice"},
                                       "result": {}}])
        self.assertEqual(r0.next["step"], "triage")
        self.assertEqual(r0.next["kind"], "decision")
        for payload in ({}, {"message": 7}):
            with self.subTest(payload), self.assertRaises(InputValidationError):
                self.proc.run(None, payload)

    def test_decision_collapses_and_emits_confidence(self):
        r = self.begin({"message": "I was charged twice"})
        self.assertEqual(r.ran, "triage")
        self.assertEqual(self.jev.seen, {"state": {"message": "I was charged twice"}})
        # one answer per question, and the model's confidence for the question the step names
        self.assertEqual(r.suggested, {"message": "I was charged twice", "billing": True, "tone": "angry",
                                       "tone_confidence": 0.9})
        self.assertEqual(r.next["kind"], "router")
        self.assertEqual(set(r.next["branches"]), {"angry", "calm"})
        self.assertEqual(r.next["confidence"]["key"], "tone_confidence")
        self.assertEqual(r.next["confidence"]["to"]["step"], "reply")
        self.assertEqual(r.history[-1]["step"], "triage")
        self.assertNotIn("assets", r.history[-1]["input"])
        self.assertEqual(self.proc.nodes["triage"].output_types(),
                         {"billing": DataType.BOOLEAN, "tone": DataType.STRING, "tone_confidence": DataType.FLOAT})

    def test_confidence_is_the_probability_of_the_answer_given(self):
        # a noul's is |2p - 1| (https://docs.typesafe.ai/confidence#noul); choice and score carry their own
        self.assertEqual(confidence({"type": "noul", "noul": 0.55}), 0.1)
        self.assertEqual(confidence({"type": "noul", "noul": 0.03}), 0.94)
        self.assertEqual(confidence({"type": "noul", "noul": 0.5}), 0.0)
        self.assertEqual(confidence({"type": "choice", "choice": "a", "confidence": 0.58, "probabilities": {}}), 0.58)
        self.assertEqual(confidence({"type": "score", "confidence": 0.7, "probabilities": {"0": 0.3, "1": 0.7}}), 0.7)
        # the state key and the attribution are one number
        self.proc.nodes["triage"].confidence = ["billing", "tone"]
        r = self.begin({"message": "hi"})
        self.assertEqual((r.suggested["billing_confidence"], r.suggested["tone_confidence"]), (0.1, 0.9))

    def test_router_check_fires_below_the_bound(self):
        self.jev.tone_p = 0.55                                  # angry, but barely
        r1 = self.begin({"message": "I was charged twice"})
        self.assertEqual((r1.suggested["tone"], r1.suggested["tone_confidence"]), ("angry", 0.55))
        r2 = self.proc.run(r1.ran, r1.suggested, r1.history)
        self.assertEqual((r2.ran, r2.kind), ("reply", "client_task"))     # not escalate
        routed = r2.history[-2]
        self.assertEqual(routed["step"], "by_tone")
        self.assertEqual(routed["result"], {"to": "reply", "confidence": {"fired": True, "reason": "low"}})
        self.assertEqual(routed["input"], {"tone_confidence": 0.55})   # the branch key was not read

    def test_router_check_passes_at_the_bound_and_records_it(self):
        r1 = self.begin({"message": "I was charged twice"})
        r2 = self.proc.run(r1.ran, r1.suggested, r1.history)
        self.assertEqual(r2.ran, "escalate")
        self.assertEqual(r2.history[-2]["result"], {"to": "escalate", "confidence": {"fired": False, "reason": None}})
        self.assertEqual(r2.history[-2]["input"], {"tone_confidence": 0.9, "tone": "angry"})
        router = self.proc.nodes["by_tone"]
        self.assertEqual(router.check({"tone_confidence": 0.6}), {"fired": False, "reason": None})
        with self.assertRaises(InputValidationError):
            router.check({"tone_confidence": "high"})

    def test_router_check_fires_on_an_absent_or_null_confidence(self):
        triage, router = self.proc.nodes["triage"], self.proc.nodes["by_tone"]
        r0 = self.proc.run(None, {"message": "x"})
        manual = triage.accept_answers(r0.suggested, r0.history, {"billing": True, "tone": "angry"})
        self.assertNotIn("tone_confidence", manual.suggested)        # nobody invents a number
        r = self.proc.run(manual.ran, manual.suggested, manual.history)
        self.assertEqual(r.ran, "reply")
        self.assertEqual(r.history[-2]["result"]["confidence"], {"fired": True, "reason": "absent"})
        self.assertEqual(r.history[-2]["input"], {"tone_confidence": None})
        self.assertEqual(router.check({"tone_confidence": None}), {"fired": True, "reason": "null"})
        self.assertIs(router.route({"tone": "angry", "tone_confidence": None}), self.proc.nodes["reply"])

    def test_fallback_off_refuses_a_manual_answer(self):
        triage = self.proc.nodes["triage"]
        triage.fallback = False
        answers = {"billing": True, "tone": "calm"}
        for attribution in (None, {"resolver": "manual", "model": None, "confidence": None}):
            with self.subTest(attribution), self.assertRaises(OutputValidationError) as ctx:
                triage.accept_answers({"message": "x"}, [], answers, attribution)
            self.assertIn("fallback_not_allowed", str(ctx.exception))
            self.assertEqual(ctx.exception.invalid, ["attribution"])
        by_model = {"resolver": "typesafe", "model": "jev-1", "confidence": {"billing": 0.9, "tone": 0.7}}
        r = triage.accept_answers({"message": "x"}, [], answers, by_model)    # a model's answer still lands
        self.assertEqual(r.suggested["tone_confidence"], 0.7)

    def test_server_routes_to_execution_then_end(self):
        r1 = self.begin({"message": "I was charged twice"})
        r2 = self.proc.run(r1.ran, r1.suggested, r1.history)
        self.assertEqual((r2.ran, r2.kind), ("escalate", "execution"))
        self.assertEqual(r2.result, {"ticket_id": 42, "queue": "tier2"})
        self.assertEqual([h["step"] for h in r2.history], ["start", "triage", "by_tone", "escalate"])
        self.assertEqual(r2.history[2]["result"]["to"], "escalate")
        self.assertEqual(r2.next, {"step": "end", "kind": "end", "inputs": {"message": "string"}})

        r3 = self.proc.run(r2.ran, r2.suggested, r2.history)
        self.assertEqual((r3.ran, r3.next), ("end", None))
        self.assertEqual(r3.result, {"message": "I was charged twice"})  # the end step's inputs, nothing else
        self.assertEqual([h["step"] for h in r3.history], ["start", "triage", "by_tone", "escalate", "end"])
        json.dumps(r3.to_dict())  # response is JSON serializable

    def test_client_override_routes_to_client_task(self):
        r1 = self.begin({"message": "I was charged twice"})
        r4 = self.proc.run(r1.ran, {**r1.suggested, "tone": "calm"}, r1.history)
        self.assertEqual(r4.kind, "client_task")
        task = r4.result["task"]
        self.assertNotIn("pertaining to", task)  # the template is the whole task: nothing prepended
        self.assertIn("Skill: billing-support", task)
        self.assertIn("Refunds within 30 days.", task)
        self.assertIn("Keep {this} literal.", task)
        self.assertEqual(r4.result["references"], [{"uri": "billing/references/help.md", "description": "help doc"}])
        self.assertEqual(r4.suggested["tone"], "calm")
        self.assertEqual(r4.result["expects"], {"reply": "string"})  # answer with the step's outputs
        self.assertEqual(r4.next["inputs"], {"message": "string"})
        self.assertEqual(r4.history[-1]["input"], {"tone": "calm", "message": "I was charged twice"})

        with self.assertRaises(OutputValidationError) as ctx:  # the answer must hold the declared outputs
            self.proc.run(r4.ran, r4.suggested, r4.history)
        self.assertIn("reply", str(ctx.exception))
        r5 = self.proc.run(r4.ran, {**r4.suggested, "reply": "Refunded."}, r4.history)
        self.assertEqual((r5.ran, r5.result), ("end", {"message": "I was charged twice"}))

    def test_script_stdin_holds_only_declared_inputs(self):
        r1 = self.begin({"message": "I was charged twice", "customer": "acme"})
        r2 = self.proc.run(r1.ran, r1.suggested, r1.history)
        self.assertEqual(r2.ran, "escalate")
        stdin = json.loads((self.root / "billing/scripts/stdin.json").read_text())
        self.assertEqual(stdin["state"], {"tone": "angry", "message": "I was charged twice"})
        self.assertEqual(stdin["currentState"], stdin["state"])  # the old key, kept for one version
        self.assertEqual(r2.history[-1]["input"], stdin["state"])
        # the full state is kept and grows by exactly the declared outputs
        self.assertEqual(r2.suggested, {"message": "I was charged twice", "customer": "acme", "billing": True,
                                        "tone": "angry", "tone_confidence": 0.9, "ticket_id": 42, "queue": "tier2"})

    def test_script_output_is_checked_against_declared_outputs(self):
        cases = {"extra.py": "'note'", "mistyped.py": "ticket_id"}
        for script, named in cases.items():
            step = Execution(name="x", script=Script("billing", script), loader=self.proc.loader,
                             outputs={"ticket_id": DataType.INTEGER})
            with self.subTest(script), self.assertRaises(OutputValidationError) as ctx:
                step.accept({}, [])
            self.assertIn(named, str(ctx.exception))

    def test_decision_sends_history_only_when_declared(self):
        r1 = self.begin({"message": "I was charged twice"})
        triage = self.proc.nodes["triage"]
        triage.accept({"message": "again"}, r1.history)
        self.assertEqual(self.jev.seen, {"state": {"message": "again"}})
        triage.history = True
        triage.accept({"message": "again"}, r1.history)
        self.assertEqual(self.jev.seen, {"state": {"message": "again"}, "history": r1.history})

    def test_manual_answers_are_typed(self):
        triage = self.proc.nodes["triage"]
        for answers in ({"billing": True, "tone": "meh"}, {"billing": "yes", "tone": "calm"},
                        {"billing": True, "tone": "calm", "mood": "x"}):
            with self.subTest(answers), self.assertRaises(OutputValidationError):
                triage.accept_answers({"message": "x"}, [], answers)

    def test_answers_are_recorded_with_their_attribution(self):
        triage = self.proc.nodes["triage"]
        answers = {"billing": True, "tone": "calm"}
        manual = triage.accept_answers({"message": "x"}, [], answers)
        self.assertEqual(manual.history[-1]["attribution"], {"resolver": "manual", "model": None, "confidence": None})
        self.assertEqual(manual.history[-1]["result"], {"answers": answers})
        self.assertEqual(manual.suggested, {"message": "x", **answers})        # no confidence key

        by_model = {"resolver": "typesafe", "model": "jev-1", "confidence": {"billing": 0.97, "tone": 0.58}}
        r = triage.accept_answers({"message": "x"}, [], answers, by_model)
        self.assertEqual(r.history[-1]["attribution"], by_model)
        self.assertEqual(r.suggested, {"message": "x", **answers, "tone_confidence": 0.58})   # the same number

        bad = [{"resolver": "oracle"}, {**by_model, "confidence": {"tone": 1.5}},
               {**by_model, "confidence": {"mood": 0.5}}, {**by_model, "confidence": {"billing": 0.9}},
               {**by_model, "confidence": None}, {**by_model, "model": 7},
               {"resolver": "manual", "model": "jev-1", "confidence": None}]
        for attribution in bad:
            with self.subTest(attribution), self.assertRaises(OutputValidationError) as ctx:
                triage.accept_answers({"message": "x"}, [], answers, attribution)
            self.assertEqual(ctx.exception.invalid, ["attribution"])

    def test_validation_failures(self):
        cases = {
            "missing key": (None, {}),
            "wrong type": (None, {"message": 7}),
            "bad branch": ("triage", {"message": "x", "billing": True, "tone": "meh", "tone_confidence": 0.9}),
        }
        for label, (after, payload) in cases.items():
            with self.subTest(label), self.assertRaises(InputValidationError):
                self.proc.run(after, payload, [])
        with self.assertRaises(OutputValidationError):  # a decision's outputs are its question names
            self.proc.run("triage", {"message": "x", "billing": True}, [])

    def test_execution_failures_surface(self):
        for name in ("boom.py", "notjson.py"):
            step = Execution(name="x", script=Script("billing", name), loader=self.proc.loader)
            with self.subTest(name), self.assertRaises(RuntimeError):
                step.accept({}, [])


class RouterKeyTest(unittest.TestCase):
    """Collapsed answers are typed; branch keys are YAML strings. Routing must bridge them."""

    def make(self, branches):
        end = EndStep(inputs={})
        targets = {k: Execution(name=f"t-{k}", script=Script("x", "s.py"), inputsTo=end) for k in branches}
        return Router(name="r", branch_on="v", branches=targets), targets

    def test_noul_boolean_routes_on_true_false(self):
        router, targets = self.make(["true", "false"])
        self.assertIs(router.route({"v": True}), targets["true"])
        self.assertIs(router.route({"v": False}), targets["false"])

    def test_score_level_routes_on_string_number(self):
        router, targets = self.make(["0", "1", "2"])
        self.assertIs(router.route({"v": 2}), targets["2"])

    def test_choice_label_routes_as_is(self):
        router, targets = self.make(["angry", "calm"])
        self.assertIs(router.route({"v": "calm"}), targets["calm"])

    def test_unknown_value_still_errors(self):
        router, _ = self.make(["0", "1"])
        with self.assertRaises(InputValidationError):
            router.route({"v": 2})


class TypesTest(unittest.TestCase):
    def test_json_schema_compilation(self):
        schema = to_json_schema({"n": DataType.INTEGER, "xs": DataType.LIST, "f": DataType.FLOAT}, strict=True)
        self.assertEqual(schema["properties"], {"n": {"type": "integer"}, "xs": {"type": "array"}, "f": {"type": "number"}})
        self.assertEqual(schema["required"], ["n", "xs", "f"])
        self.assertFalse(schema["additionalProperties"])


class ResourceLoaderTest(unittest.TestCase):
    def test_guards(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a/assets").mkdir(parents=True)
            (root / "a/assets/x.md").write_text("one")
            loader = ResourceLoader(root)
            asset = Asset("a", "x.md")
            self.assertEqual(loader.load(asset), "one")
            (root / "a/assets/x.md").write_text("two")
            self.assertEqual(loader.load(asset), "one")             # cached
            self.assertEqual(loader.load(asset, fresh=True), "two")  # bypass
            with self.assertRaises(FileNotFoundError):
                loader.load(Asset("a", "missing.md"))
            with self.assertRaises(ValueError):
                loader.load_uri("../../etc/passwd")


if __name__ == "__main__":
    unittest.main()
