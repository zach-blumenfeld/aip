"""The CLI's JSON contract (`docs/cli-json.md`): every example in the doc is what `aip run` and
`aip resume` print for `billing-support` with a fake decision model, `billing-support-agent`
with none, for the batched pause `ticket-triage`, and for the loop at its cap `fixed-policy`, all run with no
server configured. Before comparing, the run's id becomes the doc's `SAMPLE_ID`, `run_file` is reduced to its
file name and a step's `seconds` to `<seconds>`, so nothing else varies. The stderr line about recording is
checked too, and so are `aip runs`, `aip --help` and `aip server --help`.
Everything here opens a Relate store, so it skips with the install hint where Relate is missing."""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from aip.compiler import LANGUAGE_VERSION, example_dir, relate

from aip.client.cli import main
from aip.client.runs import RunFile, run_path

REPO = Path(__file__).parent.parent
DOC = REPO / "docs" / "cli-json.md"
EXAMPLE = example_dir("billing-support")            # triage is a Decide: needs a model
AGENT = example_dir("billing-support-agent")        # triage is a Task_Agent: runs with none
TRIAGE = example_dir("ticket-triage")
FIXED = example_dir("fixed-policy")
BLOCK = re.compile(r"<!-- cli-json: (?P<name>[a-z-]+) -->\s*```(?:json|jsonl)\n(?P<body>.*?)```", re.DOTALL)

CALM = "I was charged twice for March. Could you check?"
ANGRY = "This is the THIRD time you have double charged me. Fix it today or I cancel."
REPLY = "Thanks for flagging this; duplicate charges are refunded in full within 5 business days."
SAMPLE_ID = "4f1c9a2e7b3d5068"
TICKETS = ["Can I get a copy of my March invoice?", "You charged me twice, fix it NOW", "How do I move to the annual plan?"]
POLICY = "Duplicate charges are refunded in full within 5 business days. Plan changes take effect next cycle."
NOT_RECORDED = ("aip: not recorded: no server is configured; run `aip config server local` to record runs on this machine, "
                "or `aip config server URL` for a server elsewhere\n")
NO_MODEL = ("no decision model is configured, and this procedure asks one at triage: a run that reaches it fails there with "
            "no_decision_model until one is set (run `aip config --decision-model-key KEY`, and `aip config --decision-model URL` "
            "for an endpoint other than TypeSafe's)")
# A script that fails until the "ticket service" is up: a marker file in the run's working directory.
FLAKY = ('import json, os, sys\n'
         'if not os.path.exists(os.path.join(os.environ["AIP_WORKDIR"], "ticket-service-up")):\n'
         '    print("ticket service unreachable", file=sys.stderr)\n    sys.exit(1)\n'
         'json.dump({"ticket_id": 7, "queue": "tier2"}, sys.stdout)\n')


def documented() -> dict:
    """Name -> the JSON object (or, for `jsonl` blocks, the list of lines) the doc shows."""
    out = {}
    for m in BLOCK.finditer(DOC.read_text(encoding="utf-8")):
        body = m.group("body").strip()
        try:
            out[m.group("name")] = json.loads(body)
        except json.JSONDecodeError:
            out[m.group("name")] = [json.loads(line) for line in body.splitlines()]
    return out


def normalise(obj, run_id: str | None = None):
    def value(k, v):
        if k == "run_id" and v:
            return SAMPLE_ID
        if k == "run_file" and v:
            return Path(v).name.replace(run_id, SAMPLE_ID) if run_id else Path(v).name
        if k == "seconds":
            return "<seconds>"
        return normalise(v, run_id)
    if isinstance(obj, dict):
        return {k: value(k, v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [normalise(x, run_id) for x in obj]
    return obj


class FakeTypeSafe:
    """Stands in for `TypeSafeClient()`: billing is clear (noul 0.97); the tone is `calm` with
    probability `CALM_P`, or read off the ticket for `ticket-triage` (`NOW` means angry). Any
    other questions (`fixed-policy`'s four policies) are answered `HOLDS_P` each. The keyword
    arguments it was opened with (the key, the `base_url`) are kept in `OPENED`."""
    CALM_P = 0.9
    HOLDS_P = 0.3
    OPENED: list[dict] = []

    def __init__(self, **kwargs):
        FakeTypeSafe.OPENED.append(kwargs)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def system_one(self, state, questions, **_):
        if "billing" not in questions:
            return {"model": "jev-1", "usage": {"input_tokens": 1, "output_tokens": 1},
                    "answers": {name: {"type": "noul", "noul": self.HOLDS_P} for name in questions}}
        text = json.dumps(state.get("state", {}))
        calm_p = 0.1 if "NOW" in text else self.CALM_P
        angry_p = round(1 - calm_p, 6)
        tone = "calm" if calm_p >= 0.5 else "angry"
        return {"model": "jev-1", "usage": {"input_tokens": 1, "output_tokens": 1},
                "answers": {"billing": {"type": "noul", "noul": 0.97},
                            "tone": {"type": "choice", "choice": tone, "confidence": max(calm_p, angry_p),
                                     "probabilities": {"angry": angry_p, "calm": calm_p}}}}


@unittest.skipUnless(relate.available(), relate.INSTALL_HINT)
class CliJson(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        env = mock.patch.dict(os.environ, {"AIP_CONFIG": str(self.tmp / "none.json"), "AIP_HOME": str(self.tmp / "home")})
        env.start()
        self.addCleanup(env.stop)
        for key in ("AIP_DECISION_MODEL", "AIP_DECISION_MODEL_KEY", "TYPESAFE_API_KEY", "AIP_SERVER", "AIP_AGENT", "AIP_SESSION"):
            os.environ.pop(key, None)
        self.run_id: str | None = None
        self.docs = documented()

    def aip(self, *argv: str) -> tuple[int, list, str]:
        """Exit code, every JSON line or object printed on stdout (the text lines for `config`), and stderr."""
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("sys.stdout", new=out), mock.patch("sys.stderr", new=err):
            code = main(list(argv))
        text = out.getvalue()
        if argv[0] in ("config", "runs") and "--json" not in argv:
            printed = text.splitlines()
        else:
            printed = [json.loads(line) for line in text.splitlines()] if "--progress" in argv else [json.loads(text)]
        return code, printed, err.getvalue()

    @property
    def run_file(self) -> Path:
        return run_path(self.run_id)

    def run_(self, target, inputs: dict, *flags: str):
        code, printed, err = self.aip("run", str(target), "--inputs", json.dumps(inputs), "--workdir", str(self.tmp), *flags)
        self.run_id = printed[-1]["run_id"]
        self.assertTrue(self.run_file.is_file(), "the run file is under AIP_HOME, keyed by the run id")
        return code, printed, err

    def resume(self, answers, *flags: str):
        extra = ("--answers", json.dumps(answers)) if answers is not None else ()
        code, printed, err = self.aip("resume", self.run_id, *extra, *flags)
        self.assertEqual(printed[-1]["run_id"], self.run_id, "a resumed run keeps its id")
        return code, printed, err

    def assert_documented(self, name: str, printed):
        self.assertIn(name, self.docs, f"docs/cli-json.md has no `<!-- cli-json: {name} -->` block")
        self.assertEqual(normalise(printed, self.run_id), normalise(self.docs[name]), f"docs/cli-json.md `{name}` differs from the CLI")

    @contextmanager
    def decision_model(self, calm_p: float = 0.9):
        """A decision model configured by its key in the environment, answered by the fake."""
        with mock.patch.dict(os.environ, {"AIP_DECISION_MODEL_KEY": "stub"}), mock.patch.object(FakeTypeSafe, "CALM_P", calm_p), \
                mock.patch.object(FakeTypeSafe, "OPENED", []), mock.patch("typesafe_sdk.TypeSafeClient", FakeTypeSafe):
            yield

    def variant(self, edit=None, script: str | None = None, example: Path = AGENT) -> Path:
        """An example (the agent one by default) with another escalate script, or its source edited."""
        folder = self.tmp / example.name
        shutil.copytree(example, folder)
        if script is not None:
            (folder / "scripts" / "escalate.py").write_text(script, newline="\n")
        if edit is not None:
            source = folder / "procedure.aip"
            source.write_text(edit(source.read_text(encoding="utf-8")), encoding="utf-8")
        return folder

    # ----------------------------------------------------------------- the doc's examples

    def test_agent_triage_pause_bad_answer_task_pause_done(self):
        code, [pause], err = self.run_(AGENT, {"message": CALM})                 # the agent decides: no model needed
        self.assertEqual((code, err), (0, NOT_RECORDED))
        self.assert_documented("paused-task-labels", pause)

        code, [error], err = self.resume({"billing": True})                     # one of two keys
        self.assertEqual((code, err), (1, ""), "a refused answer changed nothing: no line about recording")
        self.assert_documented("error-invalid-output", error)
        self.assertEqual(RunFile.load(self.run_file).status, "paused", "a bad answer leaves the pause")
        code, [error], err = self.resume({"billing": True, "tone": "calm", "confidence": 0.9})   # a key the pause did not ask for
        self.assertEqual((code, err), (1, ""))
        self.assert_documented("error-extra-key", error)
        code, [error], _ = self.resume([{"billing": True, "tone": "calm"}, {"billing": True, "tone": "angry"}])   # two answers, one task
        self.assertEqual((code, error["error"], error["invalid_tasks"], error["resumable"]), (1, "invalid_output", [1], True))
        held = RunFile.load(self.run_file)
        self.assertEqual((held.status, [e["step"] for e in held.run["history"]]), ("paused", ["start"]), "still paused, nothing applied")

        code, [pause], _ = self.resume({"billing": True, "tone": "calm"})       # the route branches on the agent's answer
        self.assertEqual((code, pause.get("paused"), pause.get("step")), (0, "task", "reply"))
        self.assertEqual(pause["tasks"][0]["state"]["tone"], {"value": "calm"}, "an agent's answer is its value and nothing else")
        code, [done], _ = self.resume({"reply": REPLY})
        self.assertEqual((code, done.get("done")), (0, True))
        history = RunFile.load(self.run_file).run["history"]
        self.assertEqual([e["step"] for e in history], ["start", "triage", "by_tone", "reply", "end"])
        self.assertEqual(history[1]["result"], {"billing": {"value": True}, "tone": {"value": "calm"}})
        self.assertEqual((history[2]["check"], history[2]["value"], history[2]["to"]), (None, "calm", "reply"))
        self.assertEqual((history[2]["input"], history[2]["read"], history[2]["result"]), ({"tone": {"value": "calm"}}, "tone", {}))
        self.assertEqual(history[1]["answered_by"], {"agent": "cli", "session": None}, "who answered the task")
        self.assertIsInstance(history[1]["waited_seconds"], float)
        self.assertTrue(all("bundle_id" not in e and isinstance(e["seconds"], float) for e in history))
        saved = json.loads(self.run_file.read_text(encoding="utf-8"))
        self.assertEqual((len(saved["bundle_id"]), "bundle_id" in saved["run"]), (64, False), "the run file names the bundle once")
        self.assertEqual((saved["run"]["position"], saved["run"]["loops"], bool(saved["run"]["started"]), bool(saved["run"]["finished"])),
                         (None, {}, True, True))

        with self.decision_model(0.9):                                           # a model sure of calm: the check passes
            code, [pause], _ = self.run_(EXAMPLE, {"message": CALM})
            self.assertEqual(FakeTypeSafe.OPENED, [{"api_key": "stub", "model": None, "base_url": "https://api.typesafe.ai"}],
                             "the key from the environment, TypeSafe's endpoint by default")
        self.assertEqual(code, 0)
        self.assert_documented("paused-task", pause)
        code, [done], err = self.resume({"reply": REPLY})
        self.assertEqual((code, err), (0, ""), "the line about recording is `aip run`'s, once; a resume does not repeat it")
        self.assert_documented("done", done)
        history = RunFile.load(self.run_file).run["history"]
        self.assertEqual([e["step"] for e in history], ["start", "triage", "by_tone", "reply", "end"])
        self.assertEqual(history[1]["answered_by"], {"model": "jev-1", "endpoint": "https://api.typesafe.ai"})
        self.assertEqual(history[2]["check"], {"below": 0.9, "confidence": 0.9, "fired": False})
        self.assertEqual((list(history[2]["input"]), history[2]["read"]), (["tone"], "triage_decision.tone"),
                         "one spelling of a read key in input; the dotted path is kept as read")
        self.assertIsInstance(history[1]["model_seconds"], float)

    def test_the_answer_can_be_keyed_by_task_index_or_listed(self):
        self.run_(AGENT, {"message": CALM})
        code, [done], _ = self.resume({"0": {"billing": True, "tone": "angry"}})
        self.assertEqual((code, done.get("done")), (0, True))
        self.run_(AGENT, {"message": CALM})
        code, [done], _ = self.resume([{"billing": True, "tone": "angry"}])
        self.assertEqual((code, done.get("done")), (0, True))

    def test_a_decision_without_a_model_fails_until_a_model_answers(self):
        code, [error], err = self.run_(EXAMPLE, {"message": CALM})
        self.assertEqual((code, err), (1, f"aip: warning: {NO_MODEL}\n" + NOT_RECORDED), "said before the first step, and in the object")
        self.assertEqual(error["warning"], NO_MODEL)
        self.assert_documented("error-no-decision-model", error)
        held = RunFile.load(self.run_file)
        self.assertEqual((held.status, held.run["position"]), ("failed", "step:triage"), "the run waits at the decision")
        code, [again], _ = self.resume({"billing": True, "tone": "calm"})      # a failed run takes no answer
        self.assertEqual((code, again["error"], again["step"], again["resumable"]), (1, "not_paused", "triage", True))
        with self.decision_model(0.9):                                           # a model configured: the retry asks it
            code, [pause], _ = self.resume(None)
        self.assertEqual((code, pause.get("paused"), pause["step"]), (0, "task", "reply"))
        self.assertEqual(RunFile.load(self.run_file).run["history"][1]["answered_by"], {"model": "jev-1", "endpoint": "https://api.typesafe.ai"})

    def test_a_decision_model_that_fails_is_retried_once_the_endpoint_is_fixed(self):
        """Plan R4's proof: an endpoint nothing answers at fails the decision with
        `decision_model_failed`; `aip config` moves the endpoint and `aip resume` asks again. The
        first call is the real SDK against `http://localhost:9/`."""
        code, printed, _ = self.aip("config", "--decision-model", "http://localhost:9/", "--decision-model-key", "k")
        self.assertEqual(code, 0)
        code, [error], _ = self.run_(EXAMPLE, {"message": CALM})
        self.assertEqual((code, error["error"], error["step"], error["resumable"], error["model"], error["endpoint"]),
                         (1, "decision_model_failed", "triage", True, "typesafe", "http://localhost:9"))
        self.assertIn("the decision model typesafe at http://localhost:9 failed on triage: TypeSafeAPIConnectionError", error["message"])
        self.assertTrue(error["cause"].startswith("TypeSafeAPIConnectionError"), error["cause"])
        code, printed, _ = self.aip("config", "--decision-model", "")                 # back to TypeSafe's endpoint; the key stays
        with self.decision_model(0.9):
            code, [pause], _ = self.resume(None)
            self.assertEqual(FakeTypeSafe.OPENED[0]["base_url"], "https://api.typesafe.ai")
        self.assertEqual((code, pause.get("paused"), pause["step"]), (0, "task", "reply"))

    def test_config_prints_the_endpoint_and_whether_a_key_is_set_never_the_key(self):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("sys.stdout", new=out), mock.patch("sys.stderr", new=err):
            self.assertEqual(main(["config"]), 0)
            self.assertEqual(main(["config", "--decision-model-key", "s3cret"]), 0)
            self.assertEqual(main(["config", "--decision-model", "http://model.test/"]), 0)
        text = out.getvalue()
        self.assertIn("decision model: none (a Decide fails the run with no_decision_model; run `aip config --decision-model-key KEY`", text)
        self.assertIn("decision model: https://api.typesafe.ai  (TypeSafe's, the default)  key: set", text)
        self.assertIn("decision model: http://model.test  key: set", text)
        self.assertNotIn("s3cret", text)

    def test_progress_on_the_angry_branch(self):
        with self.decision_model(0.1):                                           # a model sure of angry
            code, printed, _ = self.run_(EXAMPLE, {"message": ANGRY}, "--progress")
        self.assertEqual(code, 0)
        lines, final = printed[:-1], printed[-1]
        self.assertEqual([l["step"] for l in lines], ["start", "triage", "by_tone", "escalate", "end"])
        self.assertEqual({k: v for k, v in lines[0].items() if k != "seconds"},
                         {"event": "step", "step": "start", "kind": "Start", "pass": None, "passes": []})
        self.assertTrue(all(isinstance(line["seconds"], float) for line in lines))
        self.assert_documented("progress", printed)
        self.assertTrue(final["done"])

    def test_failing_script_then_retry(self):
        folder = self.variant(script=FLAKY)
        self.run_(folder, {"message": ANGRY})
        code, [error], err = self.resume({"billing": True, "tone": "angry"})
        self.assertEqual(code, 1)
        self.assertEqual((error["error"], error["exit_code"], error["stderr"]), ("script_failed", 1, "ticket service unreachable"))
        self.assertNotIn("Traceback", err)
        self.assert_documented("error-script-failed", error)
        held = RunFile.load(self.run_file)
        self.assertEqual((held.status, held.run["position"]), ("failed", "step:escalate"))
        self.assertEqual(held.run["state"]["message"], ANGRY)
        code, [again], _ = self.resume(None)                                     # still down: the same error
        self.assertEqual((code, again["error"]), (1, "script_failed"))
        (self.tmp / "ticket-service-up").touch()
        code, [done], _ = self.resume(None)                                      # the retry runs the step again
        self.assertEqual((code, done.get("done")), (0, True))
        self.assertEqual((done["result"]["message"], done["result"]["queue"], set(done["result"])), (ANGRY, "tier2", {"message", "ticket_id", "queue"}),
                         "the result is what the path produced: the ticket, and no reply")
        history = RunFile.load(self.run_file).run["history"]
        self.assertEqual([e["step"] for e in history], ["start", "triage", "by_tone", "escalate", "end"])
        self.assertEqual(history[3]["result"], {"ticket_id": 7, "queue": "tier2"})

    def test_a_batched_pause_carries_one_task_per_pass(self):
        with self.decision_model():
            code, [pause], _ = self.run_(TRIAGE, {"tickets": TICKETS, "policy": POLICY})
        self.assertEqual((code, pause["paused"], pause["step"]), (0, "task", "draft"))
        self.assertEqual([(t["index"], t["pass"]) for t in pause["tasks"]], [(0, 0), (1, 2)], "the angry ticket ran its pass to the end")
        self.assert_documented("paused-tasks", pause)
        replies = {"0": {"reply": f"{POLICY.split('.')[0]}. We will send the invoice copy today."},
                   "1": {"reply": f"{POLICY.split('.')[0]}. The annual plan starts next cycle."}}
        with self.decision_model():
            code, [pause], _ = self.resume(replies)
        self.assertEqual((code, pause["paused"], pause["step"]), (0, "task", "summarize"))
        self.assertEqual(len(pause["tasks"][0]["state"]["replies"]), 3)
        code, [done], _ = self.resume({"summary": "Two replies drafted, one ticket escalated."})
        self.assertEqual((code, done.get("done")), (0, True))
        self.assertEqual(done["result"]["summary"], "Two replies drafted, one ticket escalated.")

    def test_progress_reports_a_batch_as_it_goes(self):
        """Inside a batch the lines appear as the entries are written, before the pause: the
        classifications with their values, the routes, the escalation."""
        with self.decision_model():
            code, printed, _ = self.run_(TRIAGE, {"tickets": TICKETS, "policy": POLICY}, "--progress")
        lines, pause = printed[:-1], printed[-1]
        self.assertEqual((code, pause["paused"], pause["step"]), (0, "task", "draft"))
        self.assertEqual([(l["step"], l["pass"]) for l in lines],
                         [("start", None), ("classify", 0), ("by_tone", 0), ("classify", 1), ("by_tone", 1), ("escalate", 1),
                          ("classify", 2), ("by_tone", 2)], "pass by pass, as they run")
        self.assertEqual(lines[3]["answers"]["tone"], {"value": "angry", "confidence": 0.9})
        self.assertEqual([(l["to"], l["fired"]) for l in lines if l["step"] == "by_tone"],
                         [("draft", False), ("escalate", False), ("draft", False)])

    def test_the_last_pass_is_announced_and_a_loop_at_its_cap_is_not_resumable(self):
        """Plan R5's proof on fixed-policy, with a model that never finds the policies held: the
        third `fix` task says it is the last pass, the cap fails the run for good, and the final
        state holds no loop key."""
        with self.decision_model():
            code, [pause], _ = self.run_(FIXED, {"request": "Write a thank-you note."})
            self.assertEqual((code, pause["step"], "last_pass" in pause["tasks"][0]), (0, "draft", False))
            seen, lines = [], []
            code, [pause], _ = self.resume({"work": "Thank you!"})
            for _ in range(3):
                task = pause["tasks"][0]
                self.assertEqual((code, pause["step"]), (0, "fix"))
                seen.append((task["pass"], task["last_pass"], task["pass_of"]))
                code, printed, _ = self.resume({"work": "Thank you."}, "--progress")
                pause = printed[-1]
                lines += printed[:-1]
        self.assertEqual(seen, [(0, False, 3), (1, False, 3), (2, True, 3)])
        self.assertEqual(code, 1)
        self.assert_documented("error-loop-cap", pause)
        self.assertEqual(printed[-2], {"event": "step", "step": "revise", "kind": "Loop", "pass": None, "passes": [], "exit": "cap",
                                       "where": "head", "iterations": 3}, "the loop's exit entry is written at the cap too")
        aggregate = [l for l in lines if l.get("kind") == "Aggregate"][0]
        self.assertEqual(aggregate["result"], {"all_hold": False}, "a progress line carries the aggregation's result")
        held = RunFile.load(self.run_file)
        self.assertEqual((held.status, held.run["loops"], held.run["frames"]), ("failed", {}, []))
        self.assertFalse({"index", "iterations", "revise"} & set(held.run["state"]), "no loop key in the final state")
        check = [e for e in held.run["history"] if e["step"] == "check"]
        self.assertEqual([e["until"]["holds"] for e in check], [False, False, False], "each pass's first entry carries the head's Until test")
        self.assertEqual((check[0]["until"]["resolution"], check[1]["until"]["resolution"]["value"]), (None, False))
        code, [again], err = self.resume(None)
        self.assertEqual((code, again["error"], again["resumable"], err), (1, "not_paused", False, ""))
        self.assertIn("a retry would only repeat", again["message"])

    def test_runs_lists_this_machines_runs_and_prints_one_as_a_table(self):
        code, printed, _ = self.aip("runs")
        self.assertEqual((code, printed), (0, ["no runs on this machine"]))
        with self.decision_model(0.1):
            self.run_(EXAMPLE, {"message": ANGRY})
        done_id = self.run_id
        self.run_(AGENT, {"message": CALM})
        code, printed, err = self.aip("runs")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(printed[0].split(), ["RUN", "NAME", "STATUS", "AGENT", "STARTED", "UPDATED"])
        self.assertEqual([line.split()[:5] for line in printed[1:]], [[self.run_id, "billing_support_agent", "(draft)", "paused", "cli"],
                                                                       [done_id, "billing_support", "(draft)", "done", "cli"]])
        code, [rows], _ = self.aip("runs", "--json", "--status", "done")
        self.assertEqual([(r["run_id"], r["status"]) for r in rows], [(done_id, "done")])
        code, table, _ = self.aip("runs", done_id)
        self.assertEqual(code, 0)
        self.assertEqual(table[0].split(), ["run", done_id, "billing_support", "draft", "done"])
        header = next(i for i, line in enumerate(table) if line.startswith("STEP"))
        self.assertEqual(table[header].split(), ["STEP", "KIND", "PASS", "WHEN", "+MS", "WHAT"])
        rows = [line.split() for line in table[header + 1:header + 6]]
        self.assertEqual([(r[0], r[1], r[2]) for r in rows], [("start", "Start", "-"), ("triage", "Decide", "-"), ("by_tone", "Route", "-"),
                                                             ("escalate", "Execute", "-"), ("end", "End", "-")])
        self.assertTrue(all(r[4].isdigit() for r in rows), "+ms: the step's own time")
        self.assertIn("billing=true 0.94, tone=angry 0.9  (by jev-1)", table[header + 2])
        self.assertIn("-> escalate  (triage_decision.tone is angry; confidence 0.9 not below 0.9)", table[header + 3])
        self.assertTrue(table[-1].startswith("result: {"))
        code, paused, _ = self.aip("runs", self.run_id)
        self.assertIn(f"paused at triage since ", paused[-1])
        code, [record], _ = self.aip("runs", done_id, "--json")
        self.assertEqual((record["run_id"], record["status"], len(record["history"])), (done_id, "done", 5))
        code, printed, err = self.aip("runs", "zzz")
        self.assertEqual((code, printed, err), (1, [], "aip: no run zzz on this machine\n"))

    def test_help_has_a_line_per_command_and_server_help_prints(self):
        from aip.client.cli import COMMANDS, SUMMARIES

        self.assertEqual(set(SUMMARIES), set(COMMANDS))
        out = io.StringIO()
        with mock.patch("sys.stdout", new=out):
            self.assertEqual(main(["--help"]), 0)
        for command in COMMANDS:
            self.assertRegex(out.getvalue(), rf"(?m)^  {command}\s+\S.+$")
        self.assertNotIn("db", COMMANDS, "the server is the store's only writer: publish, list and get do what `aip db` did")
        for command, marker in (("server", "usage: aip server"), ("server", "one Relate file"), ("runs", "this machine's run files")):
            out = io.StringIO()
            with mock.patch("sys.stdout", new=out), self.assertRaises(SystemExit) as stop:
                main([command, "--help"])
            self.assertEqual(stop.exception.code, 0)
            self.assertIn(marker, " ".join(out.getvalue().split()))

    def test_a_file_that_is_not_a_bundle_says_so_and_nothing_about_the_engine(self):
        garbage = self.tmp / "garbage.rl"
        garbage.write_bytes(b"not a bundle")
        code, [error], _ = self.aip("run", str(garbage), "--inputs", "{}")
        self.assertEqual((code, error["error"], error["kind"]), (1, "invalid_input", "not_a_bundle"))
        self.assertEqual(error["message"], f"{garbage} is not an .rl bundle")

    def test_errors_before_anything_ran_are_not_resumable(self):
        code, [error], err = self.aip("run", str(EXAMPLE), "--inputs", json.dumps({"msg": "wrong key"}))
        self.assertEqual((code, err), (1, ""))
        self.assert_documented("error-invalid-input", error)
        code, [error], _ = self.aip("run", str(self.tmp / "nowhere"), "--inputs", "{}")
        self.assertEqual((code, error["error"], error["kind"], error["resumable"]), (1, "invalid_input", "not_found", False))
        code, [error], _ = self.aip("run", "billing_support", "--inputs", "{}")
        self.assertEqual((error["error"], error["kind"]), ("invalid_input", "no_server"))
        self.assertIn("aip config server local", error["message"])
        code, [error], _ = self.aip("run", str(EXAMPLE), "--inputs", "not json")
        self.assertEqual((code, error["error"]), (1, "invalid_input"))
        self.assertIn("--inputs", error["message"])
        code, [error], _ = self.aip("resume", "0123456789abcdef")
        self.assertEqual((code, error["error"]), (1, "invalid_input"))

    def test_debug_prints_the_traceback_for_a_crash(self):
        with mock.patch("aip.sdk.Client.run", side_effect=RuntimeError("boom")):
            code, [error], err = self.aip("run", str(EXAMPLE), "--inputs", "{}", "--debug")
        self.assertEqual((code, error["error"], error["message"]), (1, "server", "boom"))
        self.assertIn("Traceback", err)

    def test_every_documented_example_is_exercised(self):
        names = {"paused-task-labels", "paused-task", "paused-tasks", "done", "error-invalid-output", "error-extra-key",
                 "error-invalid-input", "error-script-failed", "error-no-decision-model", "error-loop-cap", "progress"}
        self.assertEqual(set(self.docs), names)


VERSION = re.compile(r"^aip (?P<version>\S+) language (?P<language>\S+)$")


class VersionLine(unittest.TestCase):
    """`aip --version` is the documented `aip <version> language <language>` line the console checks."""

    def test_version_line(self):
        from importlib.metadata import version

        text = DOC.read_text(encoding="utf-8")
        self.assertIn("`aip <version> language <language>`", text)
        sample = re.search(r"<!-- cli-version -->\s*```text\n(.*?)\n```", text).group(1)
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            self.assertEqual(main(["--version"]), 0)
        line = out.getvalue()
        self.assertEqual(line.count("\n"), 1)
        got = VERSION.match(line.rstrip("\n"))
        self.assertIsNotNone(got, line)
        self.assertEqual(got.group("version"), version("agent-instruction-protocol"))
        self.assertEqual(got.group("language"), LANGUAGE_VERSION)
        self.assertEqual(sample, line.rstrip("\n"))         # the doc shows this branch's real line


if __name__ == "__main__":
    unittest.main()
