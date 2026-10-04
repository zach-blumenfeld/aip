"""Tests for `aip run` / `aip resume`: the runner loop over both backends.

Drives the bundled example skill with a stub decision model, and without one to
exercise the manual-answer fallback. Scripts run for real. Every test runs twice: once
over `LocalBackend`, once over `HttpBackend` against an in-process server (FastAPI's
test client) with the example published, where the run file carries the server and
`run_id` and `resume` rebuilds the backend from it.
"""

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient
from typesafe_sdk import SystemOneResponse

from aip.client.backend import HttpBackend, LocalBackend
from aip.client.runner import EXIT_DONE, EXIT_ERROR, EXIT_PAUSED, RunFile, Runner, backend_for
from aip.client.server import Server
from aip.server.app import create_app, upload_of
from aip.server.backends.filesystem import FilesystemBackend

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


class Harness:
    """One backend per test: the example folder in-process, or an in-process server with it published."""

    def __init__(self, kind: str, tmp: str, client):
        self.kind, self.client = kind, client
        self.api = self.server = None
        if kind == "http":
            app = create_app(FilesystemBackend(Path(tmp) / "root"), client=client)
            self.api = TestClient(app, raise_server_exceptions=False)
            assert self.api.post("/catalog", json=upload_of(EXAMPLE)).status_code == 201
            self.server = Server("http://testserver", session=self.api)

    def backend(self, run: RunFile | None = None):
        if self.kind == "local":
            return LocalBackend(EXAMPLE, client=self.client)
        if run is None:
            return HttpBackend(self.server, name="billing-support")
        return backend_for(run, session=self.api)                     # what `aip resume` does

    def runner(self, tmp, interactive=False, answers=None, run=None):
        out = io.StringIO()
        feed = iter(answers or [])
        runner = Runner(self.backend(run), EXAMPLE, run_file=Path(tmp) / "run.json", interactive=interactive,
                        prompter=lambda _prompt: next(feed), out=out)
        return runner, out

    def server_run(self, run_id: str) -> dict:
        return self.api.get(f"/runs/{run_id}").json()


class Both(unittest.TestCase):
    """Subclasses set BACKEND; the Http* classes below re-run every test over the server."""
    BACKEND = "local"

    def harness(self, tmp, client):
        return Harness(self.BACKEND, tmp, client)

    def assert_run_file_points_at_the_server(self, run: RunFile, started: bool = True):
        """`started` is False for a pause before the first step ran: the server has no run yet."""
        if self.BACKEND == "http":
            self.assertEqual(run.server, "http://testserver")
            self.assertEqual(run.name, "billing-support")
            self.assertEqual(len(run.revision), 16)
            self.assertEqual(bool(run.run_id), started)
        else:
            self.assertIsNone(run.server)
            self.assertIsNone(run.run_id)


class NonInteractive(Both):
    def test_confident_angry_runs_straight_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = self.harness(tmp, FakeJev(0.95, 0.97))
            runner, out = h.runner(tmp)
            outcome = runner.start({"message": "I was charged twice!"})
            self.assertEqual(outcome.code, EXIT_DONE)
            self.assertEqual(outcome.payload["queue"], "tier2")
            self.assertIn("ticket_id", outcome.payload)
            printed = json.loads(out.getvalue())
            self.assertEqual([x["step"] for x in printed["history"]], ["triage", "by-tone", "escalate", "end"])
            if self.BACKEND == "http":                                 # the server recorded the whole run
                run = h.server_run(runner.backend.run_id)
                self.assertEqual(run["status"], "done")
                self.assertEqual(run["history"], printed["history"])

    def test_low_confidence_pauses_for_review_then_resumes(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = self.harness(tmp, FakeJev(0.55, 0.97))              # tone confidence 0.55 < 0.6
            runner, out = h.runner(tmp)
            outcome = runner.start({"message": "hmm"})
            self.assertEqual(outcome.code, EXIT_PAUSED)
            block = json.loads(out.getvalue())
            self.assertEqual((block["paused"], block["step"]), ("review", "triage"))
            self.assertEqual(block["review"][0]["question"], "tone")
            self.assertEqual(block["suggested"]["tone"], "angry")
            self.assertEqual(set(block["expects"]), {"message", "tone"})

            run = RunFile.load(outcome.run_file)
            self.assertEqual(run.after, "triage")
            self.assert_run_file_points_at_the_server(run)
            runner2, out2 = h.runner(tmp, run=run)
            outcome2 = runner2.resume(run, {"tone": "calm"})          # client overrides -> client task
            self.assertEqual(outcome2.code, EXIT_PAUSED)
            block2 = json.loads(out2.getvalue())
            self.assertEqual((block2["paused"], block2["step"]), ("client_task", "reply"))
            self.assertIn("Duplicate charges are refunded", block2["task"])
            self.assertEqual(block2["expects"], {"message": "string"})

            run2 = RunFile.load(outcome2.run_file)
            self.assertEqual(run2.run_id, run.run_id)                 # one run across the resumes
            runner3, out3 = h.runner(tmp, run=run2)
            outcome3 = runner3.resume(run2, {"reply": "Sorry about that, refund issued."})
            self.assertEqual(outcome3.code, EXIT_DONE)
            self.assertEqual(outcome3.payload["reply"], "Sorry about that, refund issued.")
            history = json.loads(out3.getvalue())["history"]
            self.assertEqual([x["step"] for x in history], ["triage", "by-tone", "reply", "end"])
            if self.BACKEND == "http":
                recorded = h.server_run(run.run_id)
                self.assertEqual(recorded["status"], "done")
                self.assertEqual([x["step"] for x in recorded["history"]], ["triage", "by-tone", "reply", "end"])
                self.assertEqual(len(h.api.get("/runs").json()), 1)

    def test_threshold_override_skips_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner, _ = self.harness(tmp, FakeJev(0.55, 0.97)).runner(tmp)
            outcome = runner.start({"message": "hmm"}, thresholds={"tone": 0.5})
            self.assertEqual(outcome.code, EXIT_DONE)

    def test_missing_input_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner, _ = self.harness(tmp, FakeJev(0.9, 0.9)).runner(tmp)
            with mock.patch("sys.stderr", new=io.StringIO()):
                self.assertEqual(runner.start(None).code, EXIT_ERROR)

    def test_no_decision_model_pauses_for_manual_answers(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TYPESAFE_API_KEY", None)
            h = self.harness(tmp, None)
            runner, out = h.runner(tmp)
            outcome = runner.start({"message": "charged twice"})
            self.assertEqual(outcome.code, EXIT_PAUSED)
            block = json.loads(out.getvalue())
            self.assertEqual((block["paused"], block["step"]), ("decision", "triage"))
            self.assertEqual(set(block["questions"]), {"billing", "tone"})
            self.assertEqual(block["questions"]["tone"]["criteria"]["angry"], "Frustrated, demanding, or threatening to leave.")

            run = RunFile.load(outcome.run_file)
            self.assertIsNone(run.after)
            self.assert_run_file_points_at_the_server(run, started=False)   # nothing ran yet: no run exists
            runner2, out2 = h.runner(tmp, run=run)
            outcome2 = runner2.resume(run, {"billing": True, "tone": "angry"})
            self.assertEqual(outcome2.code, EXIT_DONE)
            history = json.loads(out2.getvalue())["history"]
            self.assertEqual([x["step"] for x in history], ["triage", "by-tone", "escalate", "end"])
            self.assertTrue(history[0]["manual"])
            self.assertEqual(history[0]["result"]["answers"]["tone"]["manual"], "angry")


class Interactive(Both):
    def test_prompts_for_start_review_and_client_task(self):
        # start: message; review: override angry -> calm; client task: end declares only
        # `message`, so one prompt, and enter keeps the suggested value
        with tempfile.TemporaryDirectory() as tmp:
            runner, out = self.harness(tmp, FakeJev(0.55, 0.97)).runner(
                tmp, interactive=True, answers=["I was charged twice", "calm", ""])
            outcome = runner.start(None)
            self.assertEqual(outcome.code, EXIT_DONE)
            self.assertEqual(outcome.payload["message"], "I was charged twice")
            self.assertIn("model says \"angry\"", out.getvalue())
            self.assertIn("Duplicate charges are refunded", out.getvalue())  # the task was shown

    def test_manual_decision_prompts(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TYPESAFE_API_KEY", None)
            # billing: yes; tone: first an invalid label, then angry
            runner, out = self.harness(tmp, None).runner(tmp, interactive=True, answers=["y", "furious", "angry"])
            outcome = runner.start({"message": "charged twice"})
            self.assertEqual(outcome.code, EXIT_DONE)
            self.assertIn("pick one of ['angry', 'calm']", out.getvalue())
            self.assertEqual(outcome.payload["queue"], "tier2")


class Cli(Both):
    """The commands, by folder or (over HTTP) by name; `_server` is patched to the in-process server."""

    def target(self, h: Harness) -> str:
        return "billing-support" if self.BACKEND == "http" else str(EXAMPLE)

    def patched(self, h: Harness):
        return mock.patch("aip.client.cli._server", return_value=h.server)

    def test_info_is_readable_and_example_input_is_runnable(self):
        from aip.client.cli import main

        with tempfile.TemporaryDirectory() as tmp, self.patched(h := self.harness(tmp, FakeJev(0.9, 0.9))):
            out = io.StringIO()
            with mock.patch("sys.stdout", new=out):
                self.assertEqual(main(["info", self.target(h)]), EXIT_DONE)
            text = out.getvalue()
            for needle in ("START INPUT", "message  string", '{"message": "<string>"}', "by-tone  [router on `tone`]",
                           "? tone [choice]  (threshold 0.6)", "script: scripts/escalate.py", "RESULT",
                           f"run:  aip run {self.target(h)} --input start.json"):
                self.assertIn(needle, text, needle)

            out = io.StringIO()
            with mock.patch("sys.stdout", new=out):
                self.assertEqual(main(["info", self.target(h), "--example-input"]), EXIT_DONE)
            example = json.loads(out.getvalue())
            self.assertEqual(example, {"message": "<string>"})
            # the example input is accepted by the start step as-is
            runner, _ = h.runner(tmp)
            self.assertEqual(runner.start(example).code, EXIT_DONE)

            out = io.StringIO()
            with mock.patch("sys.stdout", new=out):
                self.assertEqual(main(["info", self.target(h), "--json"]), EXIT_DONE)
            self.assertEqual(json.loads(out.getvalue())["start"]["step"], "triage")

    def test_run_and_resume_via_cli(self):
        from aip.client.cli import main

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"AIP_CONFIG": tmp + "/none.json"}):
            os.environ.pop("TYPESAFE_API_KEY", None)
            os.environ.pop("AIP_SERVER", None)
            h = self.harness(tmp, None)
            start = Path(tmp) / "start.json"
            start.write_text(json.dumps({"message": "charged twice"}))
            run_file = Path(tmp) / "run.json"
            out = io.StringIO()
            with self.patched(h), mock.patch("sys.stdout", new=out):
                code = main(["run", self.target(h), "--input", str(start), "--run-file", str(run_file)])
            self.assertEqual(code, EXIT_PAUSED)
            self.assertEqual(json.loads(out.getvalue())["paused"], "decision")
            self.assert_run_file_points_at_the_server(RunFile.load(run_file), started=False)

            answers = Path(tmp) / "answers.json"
            answers.write_text(json.dumps({"billing": True, "tone": "angry"}))
            out = io.StringIO()
            with self.patched(h), mock.patch("sys.stdout", new=out):
                code = main(["resume", str(run_file), "--input", str(answers)])
            self.assertEqual(code, EXIT_DONE)
            done = json.loads(out.getvalue())
            self.assertTrue(done["done"])
            self.assertIn("ticket_id", done["state"])
            if self.BACKEND == "http":
                runs = h.api.get("/runs").json()
                self.assertEqual(len(runs), 1)
                self.assertEqual((runs[0]["status"], runs[0]["steps"]), ("done", 4))

    def test_server_errors_are_one_line(self):
        if self.BACKEND != "http":
            self.skipTest("server only")
        from aip.client.cli import main

        with tempfile.TemporaryDirectory() as tmp, self.patched(h := self.harness(tmp, FakeJev(0.9, 0.9))):
            start = Path(tmp) / "start.json"
            start.write_text(json.dumps({"msg": "wrong key"}))
            run_file = str(Path(tmp) / "run.json")
            err = io.StringIO()
            with mock.patch("sys.stderr", new=err), mock.patch("sys.stdout", new=io.StringIO()):
                self.assertEqual(main(["run", "billing-support", "--input", str(start), "--run-file", run_file]), EXIT_ERROR)
            self.assertIn("invalid_input at triage", err.getvalue())
            err = io.StringIO()
            with mock.patch("sys.stderr", new=err), mock.patch("sys.stdout", new=io.StringIO()):
                self.assertEqual(main(["run", "nope", "--input", str(start), "--run-file", run_file]), EXIT_ERROR)
            self.assertIn("not_found", err.getvalue())
            self.assertFalse(Path(run_file).exists())


class HttpNonInteractive(NonInteractive):
    BACKEND = "http"


class HttpInteractive(Interactive):
    BACKEND = "http"


class HttpCli(Cli):
    BACKEND = "http"


if __name__ == "__main__":
    unittest.main()
