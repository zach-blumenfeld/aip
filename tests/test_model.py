"""End-to-end tests for the AIP runtime model.

Builds a four-node graph on a temp package directory and drives it through
Procedure.run with a stub TypeSafe client, so no API key or network is needed.
"""

import json
import tempfile
import unittest
from pathlib import Path

from typesafe_sdk import Choice, Noul, SystemOneResponse

from aip.model import (
    Asset, ClientTask, DataType, Decision, EndStep, Execution, InputValidationError,
    Meta, Procedure, Reference, ResourceLoader, Router, Script, to_json_schema,
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
        "json.dump({'ticket_id': 42, 'queue': cfg['queue']}, sys.stdout)\n")
    (root / "billing/scripts/boom.py").write_text("import sys; sys.exit('bad config')")
    (root / "billing/scripts/notjson.py").write_text("print('hello')")


def make_procedure(root: Path, jev: FakeJev) -> Procedure:
    end = EndStep(inputs={"message": DataType.STRING})
    escalate = Execution(
        name="escalate",
        inputs={"tone": DataType.STRING, "message": DataType.STRING},
        script=Script("billing", "escalate.py"),
        assets=[Asset("billing", "config.json")],
        inputsTo=end,
    )
    reply = ClientTask(
        name="reply",
        inputs={"tone": DataType.STRING, "message": DataType.STRING},
        template=Asset("billing", "reply.md"),
        assets=[Asset("billing", "policy.md")],
        references=[Reference("billing", "help.md", "help doc")],
        inputsTo=end,
    )
    router = Router(name="by_tone", branch_on="tone", branches={"angry": escalate, "calm": reply})
    triage = Decision(
        name="triage",
        inputs={"message": DataType.STRING},
        client=jev,
        questions={
            "billing": Noul(instructions="Is this about billing?"),
            "tone": Choice(instructions="Tone?", criteria={"angry": None, "calm": None}),
        },
        inputsTo=router,
    )
    return Procedure(
        meta=Meta(name="billing-support", description="billing triage"),
        start=triage,
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

    def test_graph_walk_binds_meta_and_loader(self):
        self.assertEqual(
            self.proc.describe()["steps"],
            {"triage": "decision", "by_tone": "router", "escalate": "execution", "end": "end", "reply": "client_task"},
        )
        self.assertIs(self.proc.nodes["reply"].meta, self.proc.meta)
        self.assertIs(self.proc.nodes["escalate"].loader, self.proc.loader)

    def test_decision_collapses_and_reviews(self):
        r = self.proc.run(None, {"message": "I was charged twice"})
        self.assertEqual(r.ran, "triage")
        self.assertEqual(self.jev.seen, {"currentState": {"message": "I was charged twice"}})
        self.assertEqual(r.suggested, {"message": "I was charged twice", "billing": True, "tone": "angry"})
        self.assertEqual([x["question"] for x in r.review], ["billing"])  # 0.55 is within 0.15 of 0.5
        self.assertEqual(r.next["kind"], "router")
        self.assertEqual(set(r.next["branches"]), {"angry", "calm"})
        self.assertEqual(r.history[-1]["step"], "triage")
        self.assertNotIn("assets", r.history[-1]["input"])

    def test_threshold_override_silences_review(self):
        r = self.proc.run(None, {"message": "hi"}, thresholds={"billing": 0.01})
        self.assertEqual(r.review, [])

    def test_server_routes_to_execution_then_end(self):
        r1 = self.proc.run(None, {"message": "I was charged twice"})
        r2 = self.proc.run(r1.ran, r1.suggested, r1.history)
        self.assertEqual((r2.ran, r2.kind), ("escalate", "execution"))
        self.assertEqual(r2.result, {"ticket_id": 42, "queue": "tier2"})
        self.assertEqual([h["step"] for h in r2.history], ["triage", "by_tone", "escalate"])
        self.assertEqual(r2.history[1]["result"], {"to": "escalate"})
        self.assertEqual(r2.next, {"step": "end", "kind": "end", "inputs": {"message": "string"}})

        r3 = self.proc.run(r2.ran, r2.suggested, r2.history)
        self.assertEqual((r3.ran, r3.next), ("end", None))
        self.assertEqual([h["step"] for h in r3.history], ["triage", "by_tone", "escalate", "end"])
        json.dumps(r3.to_dict())  # response is JSON serializable

    def test_client_override_routes_to_client_task(self):
        r1 = self.proc.run(None, {"message": "I was charged twice"})
        r4 = self.proc.run(r1.ran, {**r1.suggested, "tone": "calm"}, r1.history)
        self.assertEqual(r4.kind, "client_task")
        task = r4.result["task"]
        self.assertIn('pertaining to "billing triage"', task)  # framing prepended
        self.assertIn("Skill: billing-support", task)
        self.assertIn("Refunds within 30 days.", task)
        self.assertIn("Keep {this} literal.", task)
        self.assertEqual(r4.result["references"], [{"uri": "billing/references/help.md", "description": "help doc"}])
        self.assertEqual(r4.suggested["tone"], "calm")
        self.assertEqual(r4.next["inputs"], {"message": "string"})

    def test_validation_failures(self):
        cases = {
            "missing key": (None, {}),
            "wrong type": (None, {"message": 7}),
            "bad branch": ("triage", {"message": "x", "tone": "meh"}),
            "missing router key": ("triage", {"message": "x"}),
        }
        for label, (after, payload) in cases.items():
            with self.subTest(label), self.assertRaises(InputValidationError):
                self.proc.run(after, payload, [])

    def test_execution_failures_surface(self):
        for name in ("boom.py", "notjson.py"):
            step = Execution(name="x", script=Script("billing", name), loader=self.proc.loader)
            with self.subTest(name), self.assertRaises(RuntimeError):
                step.accept({}, [])


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
