"""Tests for `aip run` / `aip resume`: the local backend and the runner loop.

Drives the bundled example skill with a stub decision model, and without one to
exercise the manual-answer fallback. Scripts run for real.
"""

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from typesafe_sdk import SystemOneResponse

from aip.client.backend import LocalBackend
from aip.client.runner import EXIT_DONE, EXIT_ERROR, EXIT_PAUSED, RunFile, Runner

EXAMPLE = Path(__file__).parent.parent / "examples" / "billing-support"


class FakeJev:
    def __init__(self, tone_p: float, billing_p: float):
        self.tone_p, self.billing_p = tone_p, billing_p

    def system_one(self, state, questions, **_):
        return SystemOneResponse.model_validate_json(json.dumps({
            "model": "jev-1", "usage": {"input_tokens": 1, "output_tokens": 1},
            "answers": {
                "billing": {"type": "noul", "noul": self.billing_p},
                "tone": {"type": "choice", "choice": "angry" if self.tone_p >= 0.5 else "calm",
                         "confidence": max(self.tone_p, 1 - self.tone_p),
                         "probabilities": {"angry": self.tone_p, "calm": 1 - self.tone_p}},
            }}))


def make_runner(client, tmp, interactive=False, answers=None):
    out = io.StringIO()
    feed = iter(answers or [])
    backend = LocalBackend(EXAMPLE, client=client)
    runner = Runner(backend, EXAMPLE, run_file=Path(tmp) / "run.json", interactive=interactive,
                    prompter=lambda _prompt: next(feed), out=out)
    return runner, out


class NonInteractive(unittest.TestCase):
    def test_confident_angry_runs_straight_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner, out = make_runner(FakeJev(0.95, 0.97), tmp)
            outcome = runner.start({"message": "I was charged twice!"})
        self.assertEqual(outcome.code, EXIT_DONE)
        self.assertEqual(outcome.payload["queue"], "tier2")
        self.assertIn("ticket_id", outcome.payload)
        printed = json.loads(out.getvalue())
        self.assertEqual([h["step"] for h in printed["history"]], ["triage", "by-tone", "escalate", "end"])

    def test_low_confidence_pauses_for_review_then_resumes(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner, out = make_runner(FakeJev(0.55, 0.97), tmp)  # tone confidence 0.55 < 0.6
            outcome = runner.start({"message": "hmm"})
            self.assertEqual(outcome.code, EXIT_PAUSED)
            block = json.loads(out.getvalue())
            self.assertEqual((block["paused"], block["step"]), ("review", "triage"))
            self.assertEqual(block["review"][0]["question"], "tone")
            self.assertEqual(block["suggested"]["tone"], "angry")
            self.assertEqual(set(block["expects"]), {"message", "tone"})

            run = RunFile.load(outcome.run_file)
            self.assertEqual(run.after, "triage")
            runner2, out2 = make_runner(FakeJev(0.55, 0.97), tmp)
            outcome2 = runner2.resume(run, {"tone": "calm"})  # client overrides -> client task
            self.assertEqual(outcome2.code, EXIT_PAUSED)
            block2 = json.loads(out2.getvalue())
            self.assertEqual((block2["paused"], block2["step"]), ("client_task", "reply"))
            self.assertIn("Duplicate charges are refunded", block2["task"])
            self.assertEqual(block2["expects"], {"message": "string"})

            run2 = RunFile.load(outcome2.run_file)
            runner3, out3 = make_runner(FakeJev(0.55, 0.97), tmp)
            outcome3 = runner3.resume(run2, {"reply": "Sorry about that, refund issued."})
            self.assertEqual(outcome3.code, EXIT_DONE)
            self.assertEqual(outcome3.payload["reply"], "Sorry about that, refund issued.")
            self.assertEqual([h["step"] for h in json.loads(out3.getvalue())["history"]],
                             ["triage", "by-tone", "reply", "end"])

    def test_threshold_override_skips_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner, _ = make_runner(FakeJev(0.55, 0.97), tmp)
            outcome = runner.start({"message": "hmm"}, thresholds={"tone": 0.5})
        self.assertEqual(outcome.code, EXIT_DONE)

    def test_missing_input_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner, _ = make_runner(FakeJev(0.9, 0.9), tmp)
            with mock.patch("sys.stderr", new=io.StringIO()):
                self.assertEqual(runner.start(None).code, EXIT_ERROR)

    def test_no_decision_model_pauses_for_manual_answers(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TYPESAFE_API_KEY", None)
            runner, out = make_runner(None, tmp)
            outcome = runner.start({"message": "charged twice"})
            self.assertEqual(outcome.code, EXIT_PAUSED)
            block = json.loads(out.getvalue())
            self.assertEqual((block["paused"], block["step"]), ("decision", "triage"))
            self.assertEqual(set(block["questions"]), {"billing", "tone"})
            self.assertEqual(block["questions"]["tone"]["criteria"]["angry"], "Frustrated, demanding, or threatening to leave.")

            run = RunFile.load(outcome.run_file)
            self.assertIsNone(run.after)
            runner2, out2 = make_runner(None, tmp)
            outcome2 = runner2.resume(run, {"billing": True, "tone": "angry"})
            self.assertEqual(outcome2.code, EXIT_DONE)
            history = json.loads(out2.getvalue())["history"]
            self.assertEqual([h["step"] for h in history], ["triage", "by-tone", "escalate", "end"])
            self.assertTrue(history[0]["manual"])
            self.assertEqual(history[0]["result"]["answers"]["tone"]["manual"], "angry")


class Interactive(unittest.TestCase):
    def test_prompts_for_start_review_and_client_task(self):
        # start: message; review: override angry -> calm; client task: end declares only
        # `message`, so one prompt, and enter keeps the suggested value
        with tempfile.TemporaryDirectory() as tmp:
            runner, out = make_runner(FakeJev(0.55, 0.97), tmp, interactive=True,
                                      answers=["I was charged twice", "calm", ""])
            outcome = runner.start(None)
        self.assertEqual(outcome.code, EXIT_DONE)
        self.assertEqual(outcome.payload["message"], "I was charged twice")
        self.assertIn("model says \"angry\"", out.getvalue())
        self.assertIn("Duplicate charges are refunded", out.getvalue())  # the task was shown

    def test_manual_decision_prompts(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TYPESAFE_API_KEY", None)
            # billing: yes; tone: first an invalid label, then angry
            runner, out = make_runner(None, tmp, interactive=True, answers=["y", "furious", "angry"])
            outcome = runner.start({"message": "charged twice"})
        self.assertEqual(outcome.code, EXIT_DONE)
        self.assertIn("pick one of ['angry', 'calm']", out.getvalue())
        self.assertEqual(outcome.payload["queue"], "tier2")


class Cli(unittest.TestCase):
    def test_info_is_readable_and_example_input_is_runnable(self):
        from aip.client.cli import main

        out = io.StringIO()
        with mock.patch("sys.stdout", new=out):
            self.assertEqual(main(["info", str(EXAMPLE)]), EXIT_DONE)
        text = out.getvalue()
        for needle in ("START INPUT", "message  string", '{"message": "<string>"}', "by-tone  [router on `tone`]",
                       "? tone [choice]  (threshold 0.6)", "script: scripts/escalate.py", "RESULT"):
            self.assertIn(needle, text, needle)

        out = io.StringIO()
        with mock.patch("sys.stdout", new=out):
            self.assertEqual(main(["info", str(EXAMPLE), "--example-input"]), EXIT_DONE)
        example = json.loads(out.getvalue())
        self.assertEqual(example, {"message": "<string>"})
        # the example input is accepted by the start step as-is
        with tempfile.TemporaryDirectory() as tmp:
            runner, _ = make_runner(FakeJev(0.9, 0.9), tmp)
            self.assertEqual(runner.start(example).code, EXIT_DONE)

        out = io.StringIO()
        with mock.patch("sys.stdout", new=out):
            self.assertEqual(main(["info", str(EXAMPLE), "--json"]), EXIT_DONE)
        self.assertEqual(json.loads(out.getvalue())["start"]["step"], "triage")

    def test_run_and_resume_via_cli(self):
        from aip.client.cli import main

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TYPESAFE_API_KEY", None)
            start = Path(tmp) / "start.json"
            start.write_text(json.dumps({"message": "charged twice"}))
            run_file = Path(tmp) / "run.json"
            out = io.StringIO()
            with mock.patch("sys.stdout", new=out):
                code = main(["run", str(EXAMPLE), "--input", str(start), "--run-file", str(run_file)])
            self.assertEqual(code, EXIT_PAUSED)
            self.assertEqual(json.loads(out.getvalue())["paused"], "decision")

            answers = Path(tmp) / "answers.json"
            answers.write_text(json.dumps({"billing": True, "tone": "angry"}))
            out = io.StringIO()
            with mock.patch("sys.stdout", new=out):
                code = main(["resume", str(run_file), "--input", str(answers)])
            self.assertEqual(code, EXIT_DONE)
            self.assertTrue(json.loads(out.getvalue())["done"])


if __name__ == "__main__":
    unittest.main()
