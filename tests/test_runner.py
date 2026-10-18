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

from aip_spec import example_dir
from fastapi.testclient import TestClient
from typesafe_sdk import SystemOneResponse

from aip.client.backend import HttpBackend, LocalBackend
from aip.client.runner import EXIT_DONE, EXIT_ERROR, EXIT_PAUSED, RunFile, Runner, backend_for
from aip.client.server import Server
from aip.server.app import create_app, upload_of
from aip.server.backends.filesystem import FilesystemBackend

EXAMPLE = example_dir("billing-support")


def result_of(history: list, step: str) -> dict:
    """What a step produced, from the run history: the final state holds only the end step's inputs."""
    return next(e["result"] for e in history if e["step"] == step)


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
                        prompter=lambda _prompt: next(feed), out=out, run_id=run.run_id if run else None)
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
            self.assertRegex(run.run_id, r"^[0-9a-f]{16}$")             # a local run's generated id


class NonInteractive(Both):
    def test_confident_angry_runs_straight_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = self.harness(tmp, FakeJev(0.95, 0.97))
            runner, out = h.runner(tmp)
            outcome = runner.start({"message": "I was charged twice!"})
            self.assertEqual(outcome.code, EXIT_DONE)
            self.assertEqual(outcome.payload, {"message": "I was charged twice!"})  # the end step's inputs
            printed = json.loads(out.getvalue())
            self.assertEqual(set(printed), {"done", "run_id", "state", "run_file"})
            history = RunFile.load(outcome.run_file).history            # the ledger is in the run file
            self.assertEqual(result_of(history, "escalate")["queue"], "tier2")
            self.assertEqual(history[2]["input"], {"message": "I was charged twice!", "tone": "angry"})
            self.assertEqual([x["step"] for x in history], ["triage", "by-tone", "escalate", "end"])
            if self.BACKEND == "http":                                 # the server recorded the whole run
                run = h.server_run(runner.backend.run_id)
                self.assertEqual(run["status"], "done")
                self.assertEqual(run["history"], history)
                self.assertEqual(printed["run_id"], runner.backend.run_id)

    def test_low_confidence_pauses_for_review_then_resumes(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = self.harness(tmp, FakeJev(0.55, 0.97))              # tone confidence 0.55 < 0.6
            runner, out = h.runner(tmp)
            outcome = runner.start({"message": "hmm"})
            self.assertEqual(outcome.code, EXIT_PAUSED)
            block = json.loads(out.getvalue())
            self.assertEqual((block["paused"], block["step"]), ("review", "triage"))
            self.assertEqual(block["review"][0]["question"], "tone")
            self.assertEqual(block["proposed_answers"], {"billing": True, "tone": "angry"})
            self.assertEqual(block["state"], {"message": "hmm"})              # the decision's inputs only
            self.assertNotIn("suggested", block)
            self.assertNotIn("expects", block)

            run = RunFile.load(outcome.run_file)
            self.assertEqual(run.after, "triage")
            self.assert_run_file_points_at_the_server(run)
            runner2, out2 = h.runner(tmp, run=run)
            outcome2 = runner2.resume(run, {"tone": "calm"})          # client overrides -> client task
            self.assertEqual(outcome2.code, EXIT_PAUSED)
            block2 = json.loads(out2.getvalue())
            self.assertEqual((block2["paused"], block2["step"]), ("client_task", "reply"))
            self.assertIn("Duplicate charges are refunded", block2["task"])
            self.assertEqual(block2["answer_with"], {"reply": "string"})    # the step's declared outputs
            self.assertEqual(block2["state"], {"message": "hmm", "tone": "calm"})
            self.assertNotIn("resume", block2)

            run2 = RunFile.load(outcome2.run_file)
            self.assertEqual(run2.run_id, run.run_id)                 # one run across the resumes
            runner3, out3 = h.runner(tmp, run=run2)
            outcome3 = runner3.resume(run2, {"reply": "Sorry about that, refund issued."})
            self.assertEqual(outcome3.code, EXIT_DONE)
            self.assertEqual(outcome3.payload, {"message": "hmm"})
            history = RunFile.load(outcome3.run_file).history
            self.assertEqual(result_of(history, "end"), {"message": "hmm"})
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
            history = RunFile.load(outcome2.run_file).history
            self.assertEqual([x["step"] for x in history], ["triage", "by-tone", "escalate", "end"])
            self.assertTrue(history[0]["manual"])
            self.assertEqual(history[0]["result"]["answers"]["tone"]["manual"], "angry")


class Interactive(Both):
    def test_prompts_for_start_review_and_client_task(self):
        # start: message; review: override angry -> calm; client task: one prompt per
        # declared output, so just `reply`
        with tempfile.TemporaryDirectory() as tmp:
            runner, out = self.harness(tmp, FakeJev(0.55, 0.97)).runner(
                tmp, interactive=True, answers=["I was charged twice", "calm", "Refund issued."])
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
            self.assertEqual(outcome.payload, {"message": "charged twice"})
            self.assertEqual(result_of(RunFile.load(outcome.run_file).history, "escalate")["queue"], "tier2")


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
            self.assertEqual(done["state"], {"message": "charged twice"})
            self.assertIn("ticket_id", result_of(RunFile.load(run_file).history, "escalate"))
            if self.BACKEND == "http":
                runs = h.api.get("/runs").json()
                self.assertEqual(len(runs), 1)
                self.assertEqual((runs[0]["status"], runs[0]["steps"]), ("done", 4))

    def test_run_files_live_under_aip_home_keyed_by_run_id(self):
        """No `--run-file`: the run file is `$AIP_HOME/runs/<run-id>.json`, and `aip resume <run-id>`
        finds it from another directory. Served, the run is paused before the server has a run, so
        the file is keyed by the local id until the answer is posted, then by the server's."""
        from aip.client.cli import main
        from aip.client.runner import run_path

        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as elsewhere, \
                mock.patch.dict(os.environ, {"AIP_CONFIG": tmp + "/none.json", "AIP_HOME": tmp + "/home"}):
            os.environ.pop("TYPESAFE_API_KEY", None)
            os.environ.pop("AIP_SERVER", None)
            h = self.harness(tmp, None)
            start = Path(tmp) / "start.json"
            start.write_text(json.dumps({"message": "charged twice"}))
            answers = Path(tmp) / "answers.json"
            answers.write_text(json.dumps({"billing": True, "tone": "angry"}))
            cwd = os.getcwd()
            self.addCleanup(os.chdir, cwd)

            target = self.target(h)
            if self.BACKEND == "local":                # started from a relative path, as `aip run ./skill` is
                os.chdir(EXAMPLE.parent)
                target = EXAMPLE.name
            out = io.StringIO()
            with self.patched(h), mock.patch("sys.stdout", new=out):
                self.assertEqual(main(["run", target, "--input", str(start)]), EXIT_PAUSED)
            pause = json.loads(out.getvalue())
            run_id = pause["run_id"]
            self.assertRegex(run_id, r"^[0-9a-f]{16}$")
            self.assertEqual(Path(pause["run_file"]), run_path(run_id))
            self.assertEqual(run_path(run_id).parent, Path(tmp) / "home" / "runs")
            self.assertTrue(run_path(run_id).is_file())

            os.chdir(elsewhere)
            out = io.StringIO()
            with self.patched(h), mock.patch("sys.stdout", new=out):
                self.assertEqual(main(["resume", run_id, "--input", str(answers)]), EXIT_DONE)
            done = json.loads(out.getvalue())
            self.assertEqual(done["state"], {"message": "charged twice"})
            self.assertEqual(Path(done["run_file"]), run_path(done["run_id"]))
            self.assertEqual([p.name for p in run_path(done["run_id"]).parent.iterdir()], [f"{done['run_id']}.json"])
            self.assertFalse((Path(elsewhere) / ".aip").exists())
            if self.BACKEND == "http":
                self.assertEqual(done["run_id"], h.api.get("/runs").json()[0]["run_id"])   # the server's id
            else:
                self.assertEqual(done["run_id"], run_id)

            out = io.StringIO()
            with self.patched(h), mock.patch("sys.stdout", new=out):
                self.assertEqual(main(["resume", "0123456789abcdef"]), EXIT_ERROR)
            self.assertIn("no run '0123456789abcdef'", json.loads(out.getvalue())["message"])

    def test_errors_are_one_json_object(self):
        """A bad start input and an unknown skill: one error object on stdout, exit 1, nothing on
        stderr, and no run file (nothing ran, so there is nothing to resume)."""
        from aip.client.cli import main

        with tempfile.TemporaryDirectory() as tmp, self.patched(h := self.harness(tmp, FakeJev(0.9, 0.9))):
            start = Path(tmp) / "start.json"
            start.write_text(json.dumps({"msg": "wrong key"}))
            run_file = str(Path(tmp) / "run.json")
            nope = "nope" if self.BACKEND == "http" else str(Path(tmp) / "nope")
            for target, kind, needle in ((self.target(h), "invalid_input", "message"), (nope, None, "nope")):
                out, err = io.StringIO(), io.StringIO()
                with mock.patch("sys.stderr", new=err), mock.patch("sys.stdout", new=out):
                    self.assertEqual(main(["run", target, "--input", str(start), "--run-file", run_file]), EXIT_ERROR)
                error = json.loads(out.getvalue())
                self.assertEqual(err.getvalue(), "")
                self.assertFalse(error["resumable"])
                self.assertIn(needle, json.dumps(error))
                if kind:
                    self.assertEqual((error["error"], error["step"], error["missing"]), (kind, "triage", ["message"]))
            self.assertFalse(Path(run_file).exists())


class Failures(Both):
    """A script that fails: the error object carries its exit code and stderr, the run file holds the
    state before it, and `resume` with no input retries it; served, the server records the failure."""

    def test_script_failure_is_resumable(self):
        import shutil

        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp) / "billing-support"
            shutil.copytree(EXAMPLE, skill)
            script = skill / "scripts" / "escalate.py"
            script.write_text('import sys\nprint("queue down", file=sys.stderr)\nsys.exit(3)\n')
            with mock.patch(f"{__name__}.EXAMPLE", skill):
                h = self.harness(tmp, FakeJev(0.95, 0.97))
                runner, out = h.runner(tmp)
                outcome = runner.start({"message": "I was charged twice!"})
            self.assertEqual(outcome.code, EXIT_ERROR)
            error = json.loads(out.getvalue())
            self.assertEqual((error["error"], error["step"], error["exit_code"], error["stderr"], error["resumable"]),
                             ("script_failed", "escalate", 3, "queue down", True))
            run = RunFile.load(outcome.run_file)
            self.assertEqual((run.pause["kind"], run.after), ("error", "triage"))
            if self.BACKEND == "http":
                self.assertEqual(error["run_id"], run.run_id)
                self.assertEqual(h.server_run(run.run_id)["status"], "error")
                self.assertEqual(h.api.get("/governance/failing-scripts").json()[0]["failed"], 1)
                runner2, out2 = h.runner(tmp, run=run)  # the retry reaches the server: same revision, same failure
                self.assertEqual(runner2.resume(run, None).code, EXIT_ERROR)
                self.assertEqual(json.loads(out2.getvalue())["run_id"], run.run_id)
                self.assertEqual(h.api.get("/governance/failing-scripts").json()[0]["failed"], 2)
                return                                  # the published revision cannot be fixed in place
            shutil.copy(EXAMPLE / "scripts" / "escalate.py", script)
            runner2, _ = Harness("local", tmp, FakeJev(0.95, 0.97)).runner(tmp, run=run)
            runner2.backend = LocalBackend(skill, client=FakeJev(0.95, 0.97))
            self.assertEqual(runner2.resume(run, None).code, EXIT_DONE)


class HttpFailures(Failures):
    BACKEND = "http"


class HttpNonInteractive(NonInteractive):
    BACKEND = "http"


class HttpInteractive(Interactive):
    BACKEND = "http"


class HttpCli(Cli):
    BACKEND = "http"


if __name__ == "__main__":
    unittest.main()
