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
