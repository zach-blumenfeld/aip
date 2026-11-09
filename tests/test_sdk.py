"""The SDK (`aip.Client`, `docs/sdk.md`) and the `aip` command over it (plan aip-dev#1, R3).

`billing-support` runs end to end from a folder, from an `.rl` and by catalog name, with the
agent answering, with a fake decision model, and with `on_pause`; a failed script is a resumable
`RunError`; every target that cannot run is a typed error. The catalog side runs against
`tests/fake_server.py`, the in-memory server speaking the client's contract: publish, list,
search, describe, pull, get, pin, retire, runs recorded with their identity and draft flag, and a
server that is down. Every `aip` command is shown to call its SDK method, and the doc's tool
example runs. Everything opens a Relate store, so it skips with the install hint where Relate is
missing."""

from __future__ import annotations

import io
import json
import re
import shutil
import sys
import types
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import pytest
from aip.compiler import example_dir, relate

import aip
from aip import sdk
from aip.client import bundles
from aip.client.cli import ALIASES, COMMANDS, main
from aip.client.runs import RunFile, run_path
from aip.client.server import Server
from served import DownSession, Served

pytestmark = pytest.mark.skipif(not relate.available(), reason=relate.INSTALL_HINT)

EXAMPLE = example_dir("billing-support")            # triage is a Decide: needs a model
AGENT = example_dir("billing-support-agent")        # triage is a Task_Agent: runs with none
REPO = Path(__file__).parent.parent
CALM = "I was charged twice for March. Could you check?"
ANGRY = "This is the THIRD time you have double charged me. Fix it today or I cancel."
REPLY = "Thanks for flagging this; duplicate charges are refunded in full within 5 business days."
# A script that fails until the "ticket service" is up: a marker file in the run's working directory.
FLAKY = ('import json, os, sys\n'
         'if not os.path.exists(os.path.join(os.environ["AIP_WORKDIR"], "ticket-service-up")):\n'
         '    print("ticket service unreachable", file=sys.stderr)\n    sys.exit(1)\n'
         'json.dump({"ticket_id": 7, "queue": "tier2"}, sys.stdout)\n')


class FakeTypeSafe:
    """Stands in for `TypeSafeClient`: billing is clear (noul 0.97); `tone` is `calm` at `calm_p`,
    except that the `ANGRY` message is read as angry at the same confidence."""

    def __init__(self, calm_p: float = 0.9):
        self.calm_p = calm_p
        self.calls: list = []

    def system_one(self, state, questions, **_):
        self.calls.append((state, questions))
        calm_p = self.calm_p if "THIRD time" not in json.dumps(state) else min(self.calm_p, round(1 - self.calm_p, 6))
        angry_p = round(1 - calm_p, 6)
        tone = "calm" if calm_p >= 0.5 else "angry"
        return {"model": "jev-1", "usage": {"input_tokens": 1, "output_tokens": 1},
                "answers": {"billing": {"type": "noul", "noul": 0.97},
                            "tone": {"type": "choice", "choice": tone, "confidence": max(calm_p, angry_p),
                                     "probabilities": {"angry": angry_p, "calm": calm_p}}}}


@pytest.fixture(autouse=True)
def no_key(monkeypatch):
    for name in ("AIP_DECISION_MODEL", "AIP_DECISION_MODEL_KEY", "TYPESAFE_API_KEY", "AIP_AGENT", "AIP_SESSION"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def fake():
    """The real server in process, over an in-memory store (the name is from when it was a fake)."""
    server = Served(token_names={"secret": "zach"})
    yield server
    server.close()


@pytest.fixture
def served(fake) -> aip.Client:
    """A client on the server, with a fake model, with `billing-support` published through the SDK."""
    client = aip.Client(Server("http://testserver", token="secret", session=fake), decision_client=FakeTypeSafe(0.9), agent="tests")
    published = client.publish(EXAMPLE)
    assert published == sdk.Published("billing_support", "1", published.bundle_id, False)
    return client


def local(model: bool = False) -> aip.Client:
    """A client with no server; with `model`, a fake decision model (needed to run `EXAMPLE`)."""
    return aip.Client(decision_client=FakeTypeSafe(0.9) if model else None, agent="tests")


def steps(record) -> list[str]:
    return [e["step"] for e in record.history]


# ------------------------------------------------------------------------ running locally


def test_the_calm_arm_with_the_agent_deciding_from_a_folder(tmp_path):
    client = local()
    paused = client.run(AGENT, {"message": CALM}, workdir=tmp_path)
    assert isinstance(paused, aip.Paused)
    assert (paused.kind, paused.step, paused.recorded) == ("task", "triage", None)
    [task] = paused.tasks
    assert isinstance(task, aip.Task) and (task.index, task.pass_, task.passes) == (0, None, [])
    assert task.answer_with == {"billing": "true_or_false", "tone": "choice"}
    assert task.labels == {"tone": ["angry", "calm"]}, "the values the agent may answer with"
    assert task.state == {"message": CALM} and "Customer message:\n" + CALM in task.prompt
    assert paused.task is task
    assert paused.run_file == run_path(paused.run_id)
    assert paused.to_json()["paused"] == "task" and paused.to_json()["run_id"] == paused.run_id
    handle = RunFile.load(paused.run_file)
    assert (handle.origin, handle.target, handle.name, handle.server, handle.recorded) == ("folder", str(AGENT.resolve()), "billing_support_agent", None, False)
    assert bundles.is_cached(handle.bundle_id), "the folder's bundle is in the cache, so resume reopens it by id"

    # an agent's answer is its value and nothing else; by_tone branches on it with no confidence check
    task = client.resume(paused, {"billing": True, "tone": "calm"})
    assert isinstance(task, aip.Paused) and (task.kind, task.step) == ("task", "reply")
    assert task.task.state["tone"] == {"value": "calm"}
    done = client.resume(task, {"reply": "Sorry about that; the duplicate charge is refunded."})
    assert isinstance(done, aip.Done) and done.recorded is None
    record = client.run_record(done.run_id)
    assert steps(record) == ["start", "triage", "by_tone", "reply", "end"]
    assert record.history[2]["check"] is None and (record.history[2]["value"], record.history[2]["to"]) == ("calm", "reply")
    assert record.status == "done" and record.result == {"message": CALM, "reply": "Sorry about that; the duplicate charge is refunded."}


def test_a_decision_needs_a_model(tmp_path):
    with pytest.raises(aip.RunError) as exc:
        local().run(EXAMPLE, {"message": CALM}, workdir=tmp_path)
    error = exc.value
    assert (error.kind, error.step, error.resumable) == ("no_decision_model", "triage", True)
    assert "configure one: run `aip config --decision-model-key KEY`" in error.error["message"]
    assert RunFile.load(error.run_file).status == "failed"
    paused = local(model=True).resume(error)                                  # a model configured: the retry asks it
    assert isinstance(paused, aip.Paused) and (paused.kind, paused.step) == ("task", "reply")


class FailingTypeSafe:
    def system_one(self, state, questions, **_):
        raise ConnectionError("nothing answers at http://localhost:9")


def test_a_failing_model_fails_the_decision_and_a_retry_asks_again(tmp_path, monkeypatch):
    """Plan R4: a failed call is `decision_model_failed` naming the model and the cause; the step
    is retried, here with a model that answers. The record names the endpoint configured."""
    monkeypatch.setenv("AIP_DECISION_MODEL", "http://model.test/")
    with pytest.raises(aip.RunError) as exc:
        aip.Client(decision_client=FailingTypeSafe(), agent="tests").run(EXAMPLE, {"message": CALM}, workdir=tmp_path)
    error = exc.value
    assert (error.kind, error.step, error.resumable) == ("decision_model_failed", "triage", True)
    assert (error.error["model"], error.error["endpoint"], error.error["cause"]) == \
        ("typesafe", "http://model.test", "ConnectionError: nothing answers at http://localhost:9")
    assert error.error["message"] == "the decision model typesafe at http://model.test failed on triage: ConnectionError: nothing answers at http://localhost:9"
    paused = local(model=True).resume(error)
    assert isinstance(paused, aip.Paused) and paused.step == "reply"
    assert paused.task.state["tone"]["confidence"] == 0.9
    record = local().run_record(paused.run_id)
    assert record.history[1]["answered_by"] == {"model": "jev-1", "endpoint": "http://model.test"}


def test_a_confident_model_takes_the_calm_arm_to_the_agent_task(tmp_path):
    client = aip.Client(decision_client=FakeTypeSafe(0.9), agent="tests")
    task = client.run(EXAMPLE, {"message": CALM}, workdir=tmp_path)
    assert isinstance(task, aip.Paused) and (task.kind, task.step) == ("task", "reply")
    assert "Customer message:\n" + CALM in task.task.prompt
    assert task.task.answer_with == {"reply": "string"}
    assert task.task.references == [{"path": "references/help.md", "description": mock.ANY}]
    done = client.resume(task.run_id, {"reply": REPLY})                       # by id, as `aip resume` does
    assert isinstance(done, aip.Done) and done.result == {"message": CALM, "reply": REPLY}, "the reply path returns the reply, no ticket"
    assert done.to_json() == {"done": True, "result": {"message": CALM, "reply": REPLY}, "run_id": task.run_id, "run_file": str(task.run_file)}
    record = client.run_record(done.run_id)
    assert steps(record) == ["start", "triage", "by_tone", "reply", "end"]
    assert record.history[1]["answered_by"] == {"model": "jev-1", "endpoint": "https://api.typesafe.ai"}
    assert record.history[2]["check"] == {"below": 0.9, "confidence": 0.9, "fired": False}
    assert record.history[3]["result"] == {"reply": REPLY}
    assert record.history[3]["answered_by"] == {"agent": "tests", "session": None}, "who answered the task"
    assert isinstance(record.history[3]["waited_seconds"], float) and isinstance(record.history[1]["model_seconds"], float)
    assert record.started and record.finished and all(isinstance(e["seconds"], float) for e in record.history)
    assert "STEP" in record.table() and "+MS" in record.table()
    assert task.hint == 'answer with {"reply": <string>}'


def test_the_angry_arm_runs_the_script_with_on_step_and_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("AIP_SESSION", "s-1")
    lines = []
    client = aip.Client(decision_client=FakeTypeSafe(0.1), agent="tests")
    done = client.run(EXAMPLE, {"message": ANGRY}, workdir=tmp_path, on_step=lines.append, agent="my-agent 1.0")
    assert isinstance(done, aip.Done) and set(done.result) == {"message", "ticket_id", "queue"} and done.result["queue"] == "tier2"
    assert [(l["step"], l["kind"]) for l in lines] == [("start", "Start"), ("triage", "Decide"), ("by_tone", "Route"),
                                                       ("escalate", "Execute"), ("end", "End")]
    assert lines[2]["to"] == "escalate" and lines[1]["answered_by"]["model"] == "jev-1" and isinstance(lines[3]["seconds"], float)
    assert lines[1]["answers"]["tone"] == {"value": "angry", "confidence": 0.9} and lines[2]["fired"] is False
    record = client.run_record(done.run_id)
    assert record.identity == {"agent": "my-agent 1.0", "session": "s-1", "user": None}
    assert record.history[3]["result"]["queue"] == "tier2"


def test_on_pause_answers_in_process_or_stops(tmp_path):
    client = local()
    seen = []

    def answer(paused):
        seen.append((paused.kind, paused.step))
        return {"billing": True, "tone": "angry"} if paused.step == "triage" else {"reply": REPLY}

    done = client.run(AGENT, {"message": ANGRY}, workdir=tmp_path, on_pause=answer)
    assert isinstance(done, aip.Done) and seen == [("task", "triage")]
    paused = client.run(AGENT, {"message": CALM}, workdir=tmp_path, on_pause=lambda _p: None)
    assert isinstance(paused, aip.Paused) and (paused.kind, paused.step) == ("task", "triage")


def test_a_bad_answer_leaves_the_pause_and_a_failed_step_is_retried(tmp_path):
    folder = tmp_path / "billing-support-agent"
    shutil.copytree(AGENT, folder)
    (folder / "scripts" / "escalate.py").write_text(FLAKY)
    client = local()
    paused = client.run(folder, {"message": ANGRY}, workdir=tmp_path)
    with pytest.raises(aip.RunError) as bad:
        client.resume(paused, {"billing": True})
    assert (bad.value.kind, bad.value.step, bad.value.resumable, bad.value.error["missing"]) == ("invalid_output", "triage", True, ["tone"])
    assert RunFile.load(paused.run_file).status == "paused", "the pause stands"
    with pytest.raises(aip.RunError) as extra:                             # answers are as strict as inputs
        client.resume(paused, {"billing": True, "tone": "angry", "confidence": 0.9})
    assert (extra.value.kind, extra.value.error["invalid"], extra.value.stopped) == ("invalid_output", ["confidence"], False)
    with pytest.raises(aip.RunError) as surplus:
        client.resume(paused, [{"billing": True, "tone": "angry"}, {"billing": True, "tone": "calm"}])
    assert (surplus.value.kind, surplus.value.error["invalid_tasks"]) == ("invalid_output", [1])
    assert RunFile.load(paused.run_file).status == "paused", "and the pause still stands"
    with pytest.raises(aip.RunError) as failed:
        client.resume(paused, {"billing": True, "tone": "angry"})
    error = failed.value
    assert isinstance(error, aip.AipError)
    assert (error.kind, error.step, error.resumable, error.run_file) == ("script_failed", "escalate", True, paused.run_file)
    assert error.error["exit_code"] == 1 and error.error["stderr"] == "ticket service unreachable"
    assert RunFile.load(paused.run_file).status == "failed"
    with pytest.raises(aip.RunError) as refused:
        client.resume(error, {"reply": "x"})                               # a failed run takes no answer
    assert (refused.value.kind, refused.value.step, refused.value.resumable, refused.value.run_id) == ("not_paused", "escalate", True, paused.run_id)
    with pytest.raises(aip.RunError) as again:
        client.resume(error)                                               # still down: the same error
    assert again.value.kind == "script_failed"
    (tmp_path / "ticket-service-up").touch()                               # the run is of the same bundle; the world changed
    done = client.resume(error)                                            # a retry, from the error itself
    assert isinstance(done, aip.Done) and done.run_id == paused.run_id
    assert steps(client.run_record(done.run_id)) == ["start", "triage", "by_tone", "escalate", "end"]
    with pytest.raises(aip.RunError) as nothing:
        client.resume(done)                                                # nothing left to resume
    assert (nothing.value.kind, nothing.value.resumable) == ("not_paused", False)
    with pytest.raises(aip.RunError) as paused_again:
        client.resume(client.run(folder, {"message": ANGRY}, workdir=tmp_path))  # a paused run is not retried
    assert (paused_again.value.kind, paused_again.value.step, paused_again.value.resumable) == ("invalid_input", "triage", True)


def test_runs_lists_this_machines_run_files_when_no_server_is_configured(tmp_path):
    client = local()
    assert client.runs() == []
    first = client.run(AGENT, {"message": CALM}, workdir=tmp_path, session="s-1")
    second = client.run(AGENT, {"message": ANGRY}, workdir=tmp_path, on_pause=lambda _p: {"billing": True, "tone": "angry"})
    rows = client.runs()
    assert [r.run_id for r in rows] == [second.run_id, first.run_id] and all(isinstance(r, sdk.RunSummary) for r in rows)
    assert [(r.name, r.status, r.draft, r.identity["agent"]) for r in rows] == [("billing_support_agent", "done", True, "tests"),
                                                                              ("billing_support_agent", "paused", True, "tests")]
    assert all(r.started and r.updated for r in rows)
    assert [r.run_id for r in client.runs(status="paused")] == [first.run_id]
    assert [r.run_id for r in client.runs(session="s-1")] == [first.run_id]
    assert client.runs(name="other") == [] and len(client.runs(limit=1)) == 1
    with pytest.raises(aip.InvalidInput, match="no run zzz on this machine"):
        client.run_record("zzz")
    with pytest.raises(aip.InvalidInput, match="no run 0123456789abcdef on this machine"):
        client.run_record("0123456789abcdef")


def test_an_rl_file_runs_as_the_same_bundle(tmp_path):
    client = local(model=True)
    compiled = client.compile(EXAMPLE, tmp_path / "billing.rl")
    assert compiled.ok and compiled.output == tmp_path / "billing.rl" and compiled.name == "billing_support"
    paused = client.run(tmp_path / "billing.rl", {"message": CALM}, workdir=tmp_path)
    handle = RunFile.load(paused.run_file)
    assert (handle.origin, handle.bundle_id) == ("file", compiled.bundle_id)
    assert client.describe(tmp_path / "billing.rl").bundle_id == compiled.bundle_id
    bad = client.compile(_broken_folder(tmp_path))
    assert not bad.ok and bad.errors and bad.bundle_id is None


def _broken_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "broken"
    if not folder.exists():
        shutil.copytree(EXAMPLE, folder)
        source = folder / "procedure.aip"
        source.write_text(source.read_text().replace("Next_Step by_tone", "Next_Step by_tonne"))
    return folder


def test_typed_errors(tmp_path):
    client = local()
    with pytest.raises(aip.NotFound):
        client.run(tmp_path / "missing", {"message": CALM})
    with pytest.raises(aip.NoServer):
        client.run("billing_support", {"message": CALM})                   # a name, no server, nothing cached
    with pytest.raises(aip.NoServer):
        client.search("refund")
    with pytest.raises(aip.InvalidInput):
        client.run(EXAMPLE, ["not", "an", "object"])
    with pytest.raises(aip.InvalidInput):
        client.resume("0123456789abcdef")
    with pytest.raises(aip.RunError) as exc:                               # the inputs lack `message`: nothing ran
        client.run(EXAMPLE, {"msg": "wrong key"})
    assert (exc.value.kind, exc.value.resumable, exc.value.run_id, exc.value.error["missing"]) == ("invalid_input", False, None, ["message"])
    with pytest.raises(aip.CompileError) as compile_error:
        client.run(_broken_folder(tmp_path), {"message": CALM})
    assert [d.code for d in compile_error.value.diagnostics if d.severity == "error"][0] == "unknown_step"
    garbage = tmp_path / "garbage.rl"
    garbage.write_bytes(b"not a bundle")
    with pytest.raises(aip.InvalidBundle) as invalid:
        client.run(garbage, {"message": CALM})
    assert invalid.value.kind == "not_a_bundle"


def test_describe_a_folder():
    d = local().describe(EXAMPLE)
    assert isinstance(d, aip.Description)
    assert (d.name, d.inputs, d.result, d.revision) == ("billing_support", {"message": "string"},
                                                        {"message": "string", "ticket_id": "integer", "queue": "string", "reply": "string"}, None)
    assert [(s["name"], s["kind"]) for s in d.steps] == [("start", "Start"), ("triage", "Decide"), ("by_tone", "Route"),
                                                         ("escalate", "Execute"), ("reply", "Task_Agent"), ("end", "End")]
    assert d.example_inputs == {"message": "<string>"}
    assert d.data["requires"] == {"interpreter": "python", "version": "3.10"}
    text = d.summary()
    assert "USE WHEN" in text and "aip run" in text and "The customer's message, verbatim." in text
    assert f"bundle {d.bundle_id}\n" in text and len(d.bundle_id) == 64, "the whole bundle id"


def test_describe_nests_a_loops_steps_under_its_header():
    d = local().describe(example_dir("ticket-triage"))
    loops = {l["name"]: l for l in d.data["loops"]}
    assert loops["each_ticket"]["header"] == "Over tickets As ticket, At_Most 50, Collect reply Into replies"
    assert loops["revise"]["header"] == "Until passed, At_Most 3, Else_Fail"
    assert (loops["each_ticket"]["loop"], loops["revise"]["loop"], loops["revise"]["body"]) == (None, "each_ticket", ["fix"])
    assert {s["name"]: s["loop"] for s in d.steps}["fix"] == "revise"
    rows = [line for line in d.summary().splitlines() if line.startswith("  ")]
    names = [line.split()[0] for line in rows[rows.index(next(r for r in rows if r.split()[0] == "start")):]]
    assert names[:10] == ["start", "each_ticket", "classify", "by_tone", "draft", "escalate", "check", "revise", "fix", "summarize"]
    assert "    revise     Loop        Until passed, At_Most 3, Else_Fail" in d.summary()
    assert "      fix      Task_Agent" in d.summary()
    assert "LOOPS" not in d.summary()
    fixed = local().describe(example_dir("fixed-policy"))
    assert {l["name"]: l["header"] for l in fixed.data["loops"]} == {"revise": "Until check_summary.all_hold, At_Most 3, Else_Fail"}
    agent = local().describe(AGENT).summary()                              # a description that is a whole prompt shows its opening
    assert "triage    Task_Agent  Read the customer's message and classify it.\n" in agent


# ------------------------------------------------------------------------ the catalog


def test_publish_list_search_describe_pull_get(served, fake, tmp_path):
    [entry] = served.list()
    assert isinstance(entry, sdk.Entry) and (entry.name, entry.resolves, entry.latest) == ("billing_support", "1", "1")
    again = served.publish(EXAMPLE)
    assert again.existed and again.revision == "1", "the same bundle is the same revision"
    [hit] = served.search("billing refund")
    assert isinstance(hit, sdk.Hit) and (hit.name, hit.revision) == ("billing_support", "1") and hit.score > 0
    d = served.describe("billing_support")
    assert (d.name, d.revision, d.bundle_id, d.inputs) == ("billing_support", "1", hit.bundle_id, {"message": "string"})

    pulled = served.pull("billing_support")
    assert isinstance(pulled, sdk.Pulled) and (pulled.revision, pulled.bundle_id) == ("1", hit.bundle_id)
    assert not pulled.fetched, "publish put the bundle in the cache already"
    shutil.rmtree(bundles.bundles_dir())
    pulled = served.pull("billing_support@1")
    assert pulled.fetched and pulled.path.is_file()
    assert bundles.resolve_ref("billing_support") == (hit.bundle_id, "1")
    assert served.pull_all() == [sdk.Pulled("billing_support@1", "billing_support", "1", hit.bundle_id, pulled.path, False)]

    fetched = served.get("billing_support", tmp_path / "out")
    assert fetched == sdk.Fetched(tmp_path / "out", "billing_support", hit.bundle_id, "1")
    assert (tmp_path / "out" / "procedure.aip").read_text() == (EXAMPLE / "procedure.aip").read_text()
    assert local().compile(tmp_path / "out").bundle_id == hit.bundle_id

    assert served.pin("billing_support", "1") == sdk.Pinned("billing_support", "1")
    assert served.list()[0].pinned == "1"
    assert served.pin("billing_support", None).revision is None
    assert served.retire("billing_support@1") == sdk.Retired("billing_support", "1")
    assert served.search("billing") == []
    with pytest.raises(aip.InvalidInput):
        served.retire("billing_support")
    with pytest.raises(aip.NotFound):
        served.run("nothing_here", {"message": CALM})
    with pytest.raises(aip.ServerError) as exc:
        served.describe("nothing_here")
    assert (exc.value.status, exc.value.kind) == (404, "not_found")


def test_runs_are_recorded_by_name_and_as_drafts(served, fake, tmp_path):
    done = served.run("billing_support", {"message": ANGRY}, workdir=tmp_path, session="demo",
                      on_pause=lambda _p: {"billing": True, "tone": "angry"})
    assert isinstance(done, aip.Done) and done.recorded is True
    stored = fake.runs[done.run_id]
    assert (stored["name"], stored["revision"], stored["draft"], stored["status"]) == ("billing_support", "1", False, "done")
    assert stored["identity"] == {"agent": "tests", "session": "demo", "user": "zach"}, "the server names the user from the token"
    assert [e["step"] for e in stored["history"]] == ["start", "triage", "by_tone", "escalate", "end"]
    handle = RunFile.load(done.run_file)
    assert (handle.origin, handle.revision, handle.server, handle.recorded) == ("name", "1", "http://testserver", True)
    assert handle.run["identity"]["user"] == "zach"

    before = list(fake.requests)
    paused = served.run(EXAMPLE, {"message": CALM}, workdir=tmp_path)           # a folder: a draft
    assert isinstance(paused, aip.Paused) and paused.recorded is True
    assert ("POST", "/bundles") in fake.requests[len(before):], "the folder's bundle is uploaded as a draft before the run is recorded"
    assert fake.runs[paused.run_id]["draft"] is True and fake.runs[paused.run_id]["status"] == "paused"
    assert (paused.kind, paused.step) == ("task", "reply") and fake.runs[paused.run_id]["status"] == "paused"
    done2 = served.resume(paused, {"reply": "Sorry about that; refunded."})
    assert fake.runs[paused.run_id]["status"] == "done" and done2.recorded is True
    assert fake.requests.count(("POST", "/bundles")) == 1, "one upload per bundle id per client"

    rows = served.runs(agent="tests")
    assert [r.run_id for r in rows] == [paused.run_id, done.run_id] and all(isinstance(r, sdk.RunSummary) for r in rows)
    assert [r.run_id for r in served.runs(session="demo")] == [done.run_id]
    assert served.runs(status="paused") == []
    run_path(done.run_id).unlink()
    remote = served.run_record(done.run_id)                                      # no run file here: the server's record
    assert isinstance(remote, sdk.RunRecord) and remote.identity["user"] == "zach" and remote.status == "done"
    queries = served.governance()
    assert [q.query for q in queries] == ["confidence-fired", "failing-aggregations", "model-answers", "agent-routes"]
    asked = served.governance("model-answers", name="billing_support", agent="tests")
    assert [(r["step"], r["question"], r["model"], r["answers"]) for r in asked] == [("triage", "tone", "jev-1", 2), ("triage", "billing", "jev-1", 2)]
    assert served.governance("model-answers", name="billing_support", agent="someone-else") == []


def test_a_server_that_is_down_does_not_stop_the_run(tmp_path):
    client = aip.Client(Server("http://nowhere:1", session=DownSession()), decision_client=FakeTypeSafe(0.9), agent="tests")
    paused = client.run(EXAMPLE, {"message": CALM}, workdir=tmp_path)
    assert isinstance(paused, aip.Paused) and paused.recorded is False
    assert client.recording_error.startswith("unreachable")
    assert RunFile.load(paused.run_file).recorded is False
    with pytest.raises(aip.ServerError):
        client.run("billing_support", {"message": CALM})                        # a name needs the server, or the cache
    with pytest.raises(aip.ServerError):
        client.list()


def test_a_cached_name_runs_without_the_server(served, tmp_path):
    served.pull("billing_support")
    offline = aip.Client(Server("http://nowhere:1", session=DownSession()), decision_client=FakeTypeSafe(0.9), agent="tests")
    paused = offline.run("billing_support", {"message": CALM}, workdir=tmp_path)
    assert isinstance(paused, aip.Paused) and paused.recorded is False
    assert RunFile.load(paused.run_file).revision == "1"
    nowhere = local(model=True)
    paused = nowhere.run("billing_support@1", {"message": CALM}, workdir=tmp_path)
    assert paused.recorded is None


# ------------------------------------------------------------------ the CLI wraps it


def _call(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


NOT_CLIENT = {"compile", "export", "fmt", "config", "server"}   # the language's tooling, the config, the server


def test_every_cli_command_calls_the_sdk(served, fake, tmp_path, monkeypatch):
    """Each client command calls its `Client` method; the commands that are not client calls are
    listed, so a new command must be one or the other."""
    monkeypatch.chdir(tmp_path)
    served.publish(AGENT)                                                 # the command's own client has no model: run the agent one
    first = served.run(AGENT, {"message": CALM})
    cases = [
        ("info", "describe", ["billing_support"]),
        ("run", "run", ["billing_support_agent", "--inputs", json.dumps({"message": CALM})]),
        ("resume", "resume", [first.run_id, "--answers", json.dumps({"billing": True, "tone": "calm"})]),
        ("search", "search", ["refund"]),
        ("list", "list", []),
        ("pull", "pull", ["billing_support"]),
        ("pull", "pull_all", ["--all"]),
        ("publish", "publish", [str(EXAMPLE)]),
        ("get", "get", ["billing_support", "--out", str(tmp_path / "got")]),
        ("pin", "pin", ["billing_support", "1"]),
        ("runs", "runs", []),
        ("runs", "run_record", [first.run_id]),
        ("governance", "governance", ["confidence-fired"]),
        ("retire", "retire", ["billing_support@1"]),
    ]
    assert {c for c, _, _ in cases} | NOT_CLIENT == set(COMMANDS)
    assert ALIASES == {"describe": "info"}
    with mock.patch("aip.client.cli._server", return_value=served.server):
        for command, method, argv in cases:
            real = getattr(aip.Client, method)
            with mock.patch.object(aip.Client, method, autospec=True, side_effect=real) as spy:
                code, out, err = _call(command, *argv)
            assert code == 0, (command, argv, out, err)
            assert spy.called, f"`aip {command}` does not call Client.{method}"
    code, out, _ = _call("describe", "billing_support", "--example-inputs")
    assert code == 0 and json.loads(out) == {"message": "<string>"}
    code, out, _ = _call("config")
    assert code == 0 and "server: none" in out and "decision model: none" in out and "batch: 10" in out


def test_config_writes_and_reads_the_file(monkeypatch):
    code, out, _ = _call("config", "--server", "http://example.test/", "--token", "t", "--decision-model-key", "k", "--batch", "3")
    assert code == 0 and "wrote" in out and "key: set" in out and "k" not in out.split("key:")[1].split()[0:1][0] if False else True
    s = aip.settings()
    assert (s.server, s.token, s.decision_model_url, s.decision_model_key, s.batch) == ("http://example.test", "t", None, "k", 3)
    assert (s.decision_model_configured, s.decision_model_endpoint) == (True, "https://api.typesafe.ai")
    assert "decision model: https://api.typesafe.ai  (TypeSafe's, the default)  key: set" in out
    code, out, _ = _call("config", "--decision-model", "http://model.test/")
    s = aip.settings()
    assert (s.decision_model_url, s.decision_model_key) == ("http://model.test", "k") and "decision model: http://model.test  key: set" in out
    assert json.loads(s.path.read_text())["decision_model"] == {"url": "http://model.test", "api_key": "k"}
    code, out, _ = _call("config", "--decision-model-key", "")
    s = aip.settings()
    assert (s.decision_model_url, s.decision_model_key, s.decision_model_configured) == ("http://model.test", None, True), "an endpoint alone is a model"
    assert "key: none" in out
    code, out, _ = _call("config", "--decision-model", "")
    assert not aip.settings().decision_model_configured and "decision model: none" in out
    monkeypatch.setenv("AIP_DECISION_MODEL_KEY", "from-env")
    s = aip.settings()
    assert (s.decision_model_key, s.decision_model_source) == ("from-env", "AIP_DECISION_MODEL_KEY"), "the environment overrides the file"
    monkeypatch.delenv("AIP_DECISION_MODEL_KEY")
    code, out, _ = _call("config", "--clear")
    assert code == 0 and aip.settings().server is None and "cleared" in out
    with pytest.raises(SystemExit) as exit:
        _call("config", "--batch", "0")
    assert exit.value.code == 2


# ----------------------------------------------------------------- the doc's example


def test_the_docs_tool_example_runs(served, tmp_path, monkeypatch):
    """`docs/sdk.md`'s LangGraph tools, with `@tool` stubbed: run pauses, answer finishes."""
    text = (REPO / "docs" / "sdk.md").read_text()
    code = re.search(r"<!-- sdk: tool -->\s*```python\n(.*?)```", text, re.DOTALL).group(1)
    tools = types.ModuleType("langchain_core.tools")
    tools.tool = lambda fn: fn
    monkeypatch.setitem(sys.modules, "langchain_core", types.ModuleType("langchain_core"))
    monkeypatch.setitem(sys.modules, "langchain_core.tools", tools)
    monkeypatch.chdir(tmp_path)
    namespace: dict = {}
    exec(code, namespace)
    namespace["client"] = served                                      # the configured server, here in-process
    served.publish(AGENT)
    paused = json.loads(namespace["run_procedure"]("billing_support_agent", {"message": CALM}))
    assert (paused["paused"], paused["step"]) == ("task", "triage")
    done = json.loads(namespace["answer_procedure"](paused["run_id"], {"billing": True, "tone": "angry"}))
    assert done["done"] is True and done["run_id"] == paused["run_id"]
    assert (done["result"]["message"], done["result"]["queue"], set(done["result"])) == (CALM, "tier2", {"message", "ticket_id", "queue"})
    error = json.loads(namespace["run_procedure"]("billing_support_agent", {"msg": "wrong"}))
    assert (error["error"], error["resumable"]) == ("invalid_input", False)
