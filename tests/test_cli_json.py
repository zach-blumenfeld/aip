"""The CLI's JSON contract (`docs/cli-json.md`): every example in the doc is what `aip run` /
`aip resume` actually print for `billing-support`, run locally with no decision model (and, for
the review pause, a stub one). Run files go to the default place, `$AIP_HOME/runs/<run-id>.json`,
and `resume` is given the run id. Before comparing, the run's generated id becomes the doc's
`SAMPLE_ID`, `run_file` is reduced to its file name, and an execution step's `seconds` to
`<seconds>`, so nothing else varies.

Also here: a failing escalate script is `script_failed` with its stderr and exit code, and
`aip resume` with no input retries it; `--progress` on the angry branch prints three step lines;
a skill requiring a package the machine lacks stops before any script runs, naming the package;
a step's `command` launches its script.
"""

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

from aip_spec import example_dir

from aip.client.cli import main
from aip.client.runner import RunFile, run_path

REPO = Path(__file__).parent.parent
DOC = REPO / "docs" / "cli-json.md"
EXAMPLE = example_dir("billing-support")
BLOCK = re.compile(r"<!-- cli-json: (?P<name>[a-z-]+) -->\s*```(?:json|jsonl)\n(?P<body>.*?)```", re.DOTALL)

MESSAGE = "I was charged twice for March. Could you check?"
ANGRY = "This is the THIRD time you have double charged me. Fix it today or I cancel."
REPLY = "Thanks for flagging this; duplicate charges are refunded in full within 5 business days."
SAMPLE_ID = "4f1c9a2e7b3d5068"
BROKEN = 'import sys\nprint("ticket service unreachable", file=sys.stderr)\nsys.exit(1)\n'
REQUIRES = 'requires:\n  interpreter:\n    name: python\n    version: "3.10"\n'


def documented() -> dict:
    """Name -> the JSON object (or, for `jsonl` blocks, the list of lines) the doc shows."""
    out = {}
    for m in BLOCK.finditer(DOC.read_text()):
        body = m.group("body").strip()
        lines = body.splitlines()
        try:
            out[m.group("name")] = json.loads(body)
        except json.JSONDecodeError:
            out[m.group("name")] = [json.loads(line) for line in lines]
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
    """Stands in for `TypeSafeClient()`: billing is clear, tone is a coin flip under its 0.6 threshold."""
    TONE = 0.58

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def system_one(self, state, questions, **_):
        from typesafe_sdk import SystemOneResponse
        return SystemOneResponse.model_validate({
            "model": "jev-1", "usage": {"input_tokens": 1, "output_tokens": 1},
            "answers": {"billing": {"type": "noul", "noul": 0.97},
                        "tone": {"type": "choice", "choice": "angry", "confidence": self.TONE,
                                 "probabilities": {"angry": self.TONE, "calm": round(1 - self.TONE, 6)}}}})


class CliJson(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        env = mock.patch.dict(os.environ, {"AIP_CONFIG": str(self.tmp / "none.json"),
                                           "AIP_HOME": str(self.tmp / "home")})
        env.start()
        self.addCleanup(env.stop)
        for key in ("TYPESAFE_API_KEY", "AIP_SERVER"):
            os.environ.pop(key, None)
        self.run_id: str | None = None
        self.docs = documented()

    def write(self, name: str, obj: dict) -> str:
        path = self.tmp / name
        path.write_text(json.dumps(obj))
        return str(path)

    def aip_text(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("sys.stdout", new=out), mock.patch("sys.stderr", new=err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def aip(self, *argv: str) -> tuple[int, list, str]:
        """Exit code, every JSON line or object printed on stdout, and stderr."""
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("sys.stdout", new=out), mock.patch("sys.stderr", new=err):
            code = main(list(argv))
        text = out.getvalue()
        if "--progress" in argv:
            printed = [json.loads(line) for line in text.splitlines()]
        else:
            printed = [json.loads(text)]
        return code, printed, err.getvalue()

    @property
    def run_file(self) -> Path:
        return run_path(self.run_id)

    def run_(self, skill, message: str, *flags: str):
        code, printed, err = self.aip("run", str(skill), "--input", self.write("start.json", {"message": message}),
                                      *flags)
        self.run_id = printed[-1]["run_id"]
        self.assertTrue(self.run_file.is_file(), "the run file is under AIP_HOME, keyed by the run id")
        return code, printed, err

    def resume(self, answer: dict | None, *flags: str):
        extra = ("--input", self.write("answer.json", answer)) if answer is not None else ()
        code, printed, err = self.aip("resume", self.run_id, *extra, *flags)
        self.assertEqual(printed[-1]["run_id"], self.run_id, "a resumed run keeps its id")
        return code, printed, err

    def assert_documented(self, name: str, printed):
        self.assertIn(name, self.docs, f"docs/cli-json.md has no `<!-- cli-json: {name} -->` block")
        self.assertEqual(normalise(printed, self.run_id), normalise(self.docs[name]),
                         f"docs/cli-json.md `{name}` differs from the CLI")

    @contextmanager
    def decision_model(self):
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "stub"}), \
                mock.patch("aip.client.resolver.TypeSafeClient", return_value=FakeTypeSafe()):
            yield

    def broken_example(self) -> Path:
        skill = self.tmp / "billing-support"
        shutil.copytree(EXAMPLE, skill)
        (skill / "scripts" / "escalate.py").write_text(BROKEN)
        return skill

    def variant(self, requires: str, script: str | None = None, name: str = "escalate.py",
                command: list | None = None) -> Path:
        """billing-support with another `requires` block and, optionally, another escalate script."""
        skill = self.tmp / "billing-support"
        shutil.copytree(EXAMPLE, skill)
        md = skill / "SKILL.md"
        text = md.read_text()
        self.assertIn(REQUIRES, text)
        text = text.replace(REQUIRES, requires)
        if script is not None:
            (skill / "scripts" / name).write_text(script)
            launch = f"    command: {json.dumps(command)}\n" if command else ""
            text = text.replace("    script: scripts/escalate.py\n", f"    script: scripts/{name}\n{launch}")
        md.write_text(text)
        return skill

    # ----------------------------------------------------------------- the doc's examples

    def test_calm_branch_decision_client_task_done(self):
        code, [pause], err = self.run_(EXAMPLE, MESSAGE)
        self.assertEqual((code, err), (0, ""))
        self.assert_documented("paused-decision", pause)

        code, [error], _ = self.resume({"billing": True})          # one of two questions
        self.assertEqual(code, 1)
        self.assert_documented("error-invalid-output", error)
        self.assertEqual(RunFile.load(self.run_file).pause["kind"], "decision", "a bad answer leaves the pause")

        code, [pause], _ = self.resume({"billing": True, "tone": "calm"})
        self.assertEqual(code, 0)
        self.assert_documented("paused-client-task", pause)

        code, [done], _ = self.resume({"reply": REPLY})
        self.assertEqual(code, 0)
        self.assert_documented("done", done)
        history = RunFile.load(self.run_file).history
        self.assertEqual([e["step"] for e in history], ["triage", "by-tone", "reply", "end"])
        self.assertEqual(history[0]["attribution"],                     # no key: answered by the agent
                         {"resolver": "manual", "model": None, "confidence": None, "reviewed": False})

    def test_review_pause(self):
        with self.decision_model():
            code, [pause], _ = self.run_(EXAMPLE, MESSAGE)
            self.assertEqual(code, 0)
            self.assert_documented("paused-review", pause)
            self.assertEqual(RunFile.load(self.run_file).history, [], "nothing is recorded until the review is answered")
            code, [pause], _ = self.resume({"tone": "calm"})            # override: the calm branch
            self.assertEqual((code, pause["paused"]), (0, "client_task"))
        triage = RunFile.load(self.run_file).history[0]
        self.assertEqual(triage["result"], {"answers": {"billing": True, "tone": "calm"}})
        self.assertEqual(triage["attribution"], {"resolver": "typesafe", "model": "jev-1",
                                                 "confidence": {"billing": 0.97, "tone": 0.58}, "reviewed": True,
                                                 "proposed": {"billing": True, "tone": "angry"}})

    def test_the_decision_model_key_is_the_clients(self):
        """`aip config --decision-model KEY` is what this client resolves decisions with; an empty
        key forgets it, and every decision pauses again."""
        code, _, _ = self.aip_text("config", "--decision-model", "from-config")
        self.assertEqual(code, 0)
        with mock.patch("aip.client.resolver.TypeSafeClient", return_value=FakeTypeSafe()) as typesafe:
            code, [pause], _ = self.run_(EXAMPLE, MESSAGE)
        self.assertEqual((code, pause["paused"]), (0, "review"))
        typesafe.assert_called_once_with(api_key="from-config")
        _, text, _ = self.aip_text("config")
        self.assertIn("decision model: TypeSafe", text)

        self.aip_text("config", "--decision-model", "")
        code, [pause], _ = self.run_(EXAMPLE, MESSAGE)
        self.assertEqual((code, pause["paused"]), (0, "decision"))
        _, text, _ = self.aip_text("config")
        self.assertIn("decision model: none", text)

    def test_progress_names_the_models_resolver(self):
        with self.decision_model(), mock.patch.object(FakeTypeSafe, "TONE", 0.9):
            code, printed, _ = self.run_(EXAMPLE, ANGRY, "--progress")
        self.assertEqual((code, printed[-1].get("done")), (0, True))
        self.assertEqual(printed[0], {"event": "step", "step": "triage", "kind": "decision", "resolver": "typesafe"})

    def test_progress_on_the_angry_branch(self):
        code, [pause], _ = self.run_(EXAMPLE, ANGRY, "--progress")       # nothing completed yet
        self.assertEqual((code, pause["paused"]), (0, "decision"))
        code, printed, _ = self.resume({"billing": True, "tone": "angry"}, "--progress")
        self.assertEqual(code, 0)
        lines, final = printed[:-1], printed[-1]
        self.assertEqual(len(lines), 3)
        self.assertTrue(all(isinstance(line["seconds"], float) for line in lines if line["kind"] == "execution"))
        self.assert_documented("progress", printed)
        self.assertTrue(final["done"])

    def test_failing_script_then_retry(self):
        skill = self.broken_example()
        self.run_(skill, ANGRY)
        code, [error], err = self.resume({"billing": True, "tone": "angry"})
        self.assertEqual(code, 1)
        self.assertEqual((error["error"], error["exit_code"], error["stderr"]),
                         ("script_failed", 1, "ticket service unreachable"))
        self.assertNotIn("Traceback", err)
        self.assert_documented("error-script-failed", error)
        held = RunFile.load(self.run_file)
        self.assertEqual((held.pause["kind"], held.after), ("error", "triage"))
        self.assertEqual(held.state, {"message": ANGRY, "billing": True, "tone": "angry"})  # the state before it

        code, [again], _ = self.resume(None)                              # still broken: same error
        self.assertEqual((code, again["error"]), (1, "script_failed"))

        shutil.copy(EXAMPLE / "scripts" / "escalate.py", skill / "scripts" / "escalate.py")
        code, [done], _ = self.resume(None)                               # fixed: the retry runs it
        self.assertEqual(code, 0)
        self.assertEqual(done["state"], {"message": ANGRY})
        history = RunFile.load(self.run_file).history
        self.assertEqual([e["step"] for e in history], ["triage", "by-tone", "escalate", "end"])
        self.assertEqual(history[2]["result"]["queue"], "tier2")

    def test_requires_unmet_stops_before_any_script(self):
        ran = self.tmp / "escalate-ran"
        touch = f"import pathlib, sys\npathlib.Path({str(ran)!r}).touch()\nprint('{{\"ticket_id\": 1, \"queue\": \"q\"}}')\n"
        skill = self.variant(REQUIRES + "  packages:\n    - nosuchpkg\n    - jsonschema>=1.0\n"
                             "  tools:\n    - nosuchtool\n", touch)
        self.run_(skill, ANGRY)
        code, [error], err = self.resume({"billing": True, "tone": "angry"})
        self.assertEqual((code, error["error"], error["step"]), (1, "requires_unmet", "escalate"))
        self.assertEqual(error["missing"], ["package nosuchpkg", "tool nosuchtool (not on PATH)"])
        self.assertIn("nosuchpkg", error["message"])
        self.assertNotIn("Traceback", err)
        self.assertFalse(ran.exists(), "no script ran")
        self.assert_documented("error-requires-unmet", error)
        self.assertEqual(RunFile.load(self.run_file).pause["kind"], "error")

        md = skill / "SKILL.md"                                           # the machine "gets" them: retry
        md.write_text(md.read_text().replace("    - nosuchpkg\n", "").replace("  tools:\n    - nosuchtool\n", ""))
        code, [done], _ = self.resume(None)
        self.assertEqual((code, done.get("done")), (0, True))
        self.assertTrue(ran.exists())

    def test_python_below_the_minimum_version_is_unmet(self):
        skill = self.variant(REQUIRES.replace('"3.10"', '"99.0"'))
        self.run_(skill, ANGRY)
        code, [error], _ = self.resume({"billing": True, "tone": "angry"})
        self.assertEqual((code, error["error"]), (1, "requires_unmet"))
        self.assertEqual(len(error["missing"]), 1)
        self.assertTrue(error["missing"][0].startswith("interpreter python>=99.0 (found 3."), error["missing"])

    def test_command_launches_the_script(self):
        script = 'cat > /dev/null\necho \'{"ticket_id": 7, "queue": "from-bash"}\'\n'
        skill = self.variant(REQUIRES + "  tools:\n    - bash\n", script, "x.sh", ["bash", "x.sh"])
        self.run_(skill, ANGRY)
        code, [done], _ = self.resume({"billing": True, "tone": "angry"})
        self.assertEqual((code, done.get("done")), (0, True), done)
        escalate = RunFile.load(self.run_file).history[2]
        self.assertEqual((escalate["step"], escalate["result"]), ("escalate", {"ticket_id": 7, "queue": "from-bash"}))

    def test_debug_prints_the_traceback(self):
        skill = self.broken_example()
        self.run_(skill, ANGRY)
        code, [error], err = self.resume({"billing": True, "tone": "angry"}, "--debug")
        self.assertEqual((code, error["error"]), (1, "script_failed"))
        self.assertIn("Traceback", err)

    def test_every_documented_example_is_exercised(self):
        names = {"paused-decision", "paused-client-task", "paused-review", "done", "error-invalid-output",
                 "error-script-failed", "error-requires-unmet", "progress"}
        self.assertEqual(set(self.docs), names)


class Validation(unittest.TestCase):
    def test_aip_spec_validate_reports_runtime_block_outdated_on_a_0_5a1_skill(self):
        """`aip-spec validate` on billing-support carrying the 0.5a1 block and version string."""
        from aip_spec import runtime_text
        from aip_spec.cli import main as aip_spec

        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp) / "billing-support"
            shutil.copytree(EXAMPLE, skill)
            md = skill / "SKILL.md"
            md.write_text(md.read_text().replace(runtime_text().strip(), runtime_text("0.5a1").strip())
                          .replace('aip-version: "0.6a0"', 'aip-version: "0.5a1"'))
            out, err = io.StringIO(), io.StringIO()
            with mock.patch("sys.stdout", new=out), mock.patch("sys.stderr", new=err):
                code = aip_spec(["validate", str(skill)])
            self.assertEqual(code, 1)
            kinds = [json.loads(line)["kind"] for line in err.getvalue().splitlines() if line.startswith("{")]
            self.assertEqual(kinds, ["runtime_block_outdated"])


if __name__ == "__main__":
    unittest.main()


VERSION = re.compile(r"^aip (?P<version>\S+) format (?P<format>\S+)$")


class VersionLine(unittest.TestCase):
    """`aip --version` is the documented `aip <version> format <format>` line the console checks."""

    def test_version_line(self):
        from importlib.metadata import version

        from aip.spec import FORMAT_VERSION

        text = DOC.read_text()
        self.assertIn("`aip <version> format <format>`", text)
        sample = re.search(r"<!-- cli-version -->\s*```text\n(.*?)\n```", text).group(1)
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            self.assertEqual(main(["--version"]), 0)
        line = out.getvalue()
        self.assertEqual(line.count("\n"), 1)
        got = VERSION.match(line.rstrip("\n"))
        self.assertIsNotNone(got, line)
        self.assertEqual(got.group("version"), version("aip"))
        self.assertEqual(got.group("format"), FORMAT_VERSION)
        self.assertEqual(sample, line.rstrip("\n"))         # the doc shows this branch's real line
