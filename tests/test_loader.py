"""Tests for the loader: the bundled `billing-support` example (from `aip-spec`) becomes an
executable `Procedure` and runs end to end through the server path. The format itself
(models, schema, graph checks, skill-folder validation) is tested in the `aip-spec` repo.

Run with: uv run python -m unittest tests.test_loader
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from aip_spec import example_dir
from typesafe_sdk import SystemOneResponse

from aip.model import OutputValidationError
from aip.spec.loader import load_procedure

EXAMPLE = example_dir("billing-support")


def copy_example(tmp: str) -> Path:
    skill = Path(tmp) / "billing-support"
    shutil.copytree(EXAMPLE, skill)
    return skill


def rewrite(skill: Path, old: str, new: str) -> None:
    md = skill / "SKILL.md"
    text = md.read_text()
    assert old in text, old
    md.write_text(text.replace(old, new))


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
        described = proc.describe()
        self.assertEqual(described["steps"], {
            "start": "start", "triage": "decision", "by-tone": "router", "escalate": "execution", "end": "end",
            "reply": "client_task"})
        self.assertEqual(described["start"], {"step": "start", "kind": "start", "inputs": {"message": "string"}})
        self.assertEqual(described["decisions"]["triage"]["fallback"], True)   # the quickstart answers by hand
        self.assertEqual(proc.meta.name, "billing-support")

        r0 = proc.run(None, {"message": "I was charged twice!"})          # the start step hands the input on
        self.assertEqual((r0.ran, r0.next["step"]), ("start", "triage"))
        r1 = proc.run(r0.ran, r0.suggested, r0.history)
        self.assertEqual(set(jev.questions), {"billing", "tone"})
        self.assertEqual(jev.questions["tone"].criteria["angry"], "Frustrated, demanding, or threatening to leave.")
        self.assertEqual(r1.suggested["tone"], "angry")
        self.assertEqual(r1.next["branch_on"], "tone")

        r2 = proc.run(r1.ran, r1.suggested, r1.history)  # server routes to escalate and runs the real script
        self.assertEqual((r2.ran, r2.result["queue"]), ("escalate", "tier2"))
        self.assertIn("ticket_id", r2.result)

        r3 = proc.run(r1.ran, {**r1.suggested, "tone": "calm"}, r1.history)  # override -> client task
        self.assertEqual(r3.kind, "client_task")
        self.assertIn("Duplicate charges are refunded in full", r3.result["task"])
        self.assertNotIn('pertaining to', r3.result["task"])                # no framing prepended
        self.assertEqual(r3.result["references"][0]["uri"], "billing-support/references/help.md")

        r4 = proc.run(r2.ran, r2.suggested, r2.history)
        self.assertEqual((r4.ran, r4.next), ("end", None))
        self.assertEqual([h["step"] for h in r4.history], ["start", "triage", "by-tone", "escalate", "end"])

    def test_confidence_and_fallback_load_onto_the_runtime_nodes(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = copy_example(tmp)
            rewrite(skill, "    fallback: true\n", "    fallback: false\n    confidence: [tone]\n")
            rewrite(skill, "    branch_on: tone\n",
                    "    branch_on: tone\n    confidence: {key: tone_confidence, below: 0.6, to: reply}\n")
            proc = load_procedure(skill, client=FakeJev())
            triage, router = proc.nodes["triage"], proc.nodes["by-tone"]
            self.assertEqual((triage.confidence, triage.fallback), (["tone"], False))
            self.assertEqual((router.confidence.key, router.confidence.below), ("tone_confidence", 0.6))
            self.assertIs(router.confidence.to, proc.nodes["reply"])
            self.assertEqual(proc.describe()["routers"]["by-tone"]["confidence"]["to"], "reply")

            r0 = proc.run(None, {"message": "I was charged twice!"})
            r1 = proc.run(r0.ran, r0.suggested, r0.history)
            self.assertEqual(r1.suggested["tone_confidence"], 0.9)
            with self.assertRaises(OutputValidationError):               # no fallback: a manual answer is refused
                triage.accept_answers(r0.suggested, r0.history, {"billing": True, "tone": "angry"})

    def test_invalid_skill_raises_with_issues(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = copy_example(tmp)
            rewrite(skill, "angry: escalate", "angry: nowhere")
            with self.assertRaises(ValueError) as ctx:
                load_procedure(skill)
            self.assertIn("unknown_step_reference", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
