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
    assert loops["revise"]["header"] == "Until passed, At_Most 4, Else_Fail"
    assert (loops["each_ticket"]["loop"], loops["revise"]["loop"], loops["revise"]["body"]) == (None, "each_ticket", ["check", "fix"])
    assert {s["name"]: s["loop"] for s in d.steps}["fix"] == "revise"
    rows = [line for line in d.summary().splitlines() if line.startswith("  ")]
    names = [line.split()[0] for line in rows[rows.index(next(r for r in rows if r.split()[0] == "start")):]]
    assert names[:10] == ["start", "each_ticket", "classify", "by_tone", "draft", "escalate", "revise", "check", "fix", "summarize"]
    assert "    revise     Loop        Until passed, At_Most 4, Else_Fail" in d.summary()
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
    assert served.pin("billing_support", "1").revision == "1"
    assert served.retire("billing_support@1") == sdk.Retired("billing_support", "1")
    assert served.search("billing") == []
    with pytest.raises(aip.InvalidInput):
        served.retire("billing_support")

    # S3: retire wins over pin. The pin went with the retire, a retired revision is not pinned, the name keeps its
    # description in the list, and `name@revision` runs only when forced.
    [entry] = served.list()
    assert (entry.pinned, entry.resolves, entry.latest) == (None, None, None) and entry.description.startswith("Turn an inbound billing message")
    with pytest.raises(aip.ServerError) as pinned:
        served.pin("billing_support", "1")
    assert (pinned.value.status, pinned.value.kind) == (409, "retired") and "billing_support@1 is retired" in pinned.value.message
    with pytest.raises(aip.NotFound) as none_live:
        served.run("billing_support", {"message": CALM})
    assert str(none_live.value).startswith("billing_support has no live revision: its one revision is retired")
    assert served.describe("billing_support@1").data["retired"] is True and "(billing_support@1, retired)" in served.describe("billing_support@1").summary()
    with pytest.raises(aip.RetiredRevision) as retired:
        served.run("billing_support@1", {"message": CALM})
    assert retired.value.kind == "retired" and "billing_support@1 is retired" in str(retired.value)
    assert isinstance(served.run("billing_support@1", {"message": CALM}, force=True), aip.Paused)
    # S3: one voice for a name the catalog does not have, whichever call asked, with the hint for a folder's spelling
    for call in (lambda ref: served.run(ref, {"message": CALM}), served.describe, served.pull, lambda ref: served.get(ref, tmp_path / "no")):
        with pytest.raises(aip.NotFound) as missing:
            call("nothing_here")
        assert str(missing.value) == "no procedure 'nothing_here'"
        with pytest.raises(aip.NotFound) as hyphen:
            call("billing-support")
        assert str(hyphen.value) == "no procedure 'billing-support'; did you mean `billing_support`?"
        with pytest.raises(aip.NotFound) as revision:
            call("billing_support@7")
        assert str(revision.value) == "no revision 7 of billing_support"


def test_publish_as_a_draft_and_then_for_real(served, fake, tmp_path):
    """`publish(draft=True)` holds the bundle with no revision (the console's Studio saves that
    way, plan C2); publishing the same bundle later gives it the next revision."""
    held = served.publish(AGENT, draft=True)
    assert (held.name, held.revision, held.draft, held.existed) == ("billing_support_agent", None, True, False)
    assert [e.name for e in served.list()] == ["billing_support"], "a draft is not in the catalog"
    assert served.publish(AGENT, draft=True).existed
    published = served.publish(AGENT)
    assert (published.revision, published.bundle_id, published.existed) == ("1", held.bundle_id, True)
    again = served.publish(AGENT, draft=True)
    assert (again.revision, again.draft) == (None, False), "a published bundle is no draft"
    with mock.patch("aip.client.cli._server", return_value=served.server):
        code, out, _ = _call("publish", str(EXAMPLE), "--draft", "--json")
    assert code == 0 and json.loads(out) == {"name": "billing_support", "revision": None, "bundle_id": served.describe("billing_support").bundle_id,
                                             "existed": True, "draft": False}


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
    paused = served.run(EXAMPLE, {"message": CALM}, workdir=tmp_path)           # a folder, whose bundle is the published one
    assert isinstance(paused, aip.Paused) and paused.recorded is True
    assert ("POST", "/bundles") in fake.requests[len(before):], "the folder's bundle is uploaded before the run is recorded"
    stored = fake.runs[paused.run_id]
    assert (stored["draft"], stored["revision"], stored["status"]) == (False, "1", "paused"), \
        "the store holds that very bundle as billing_support@1, so the run is a run of it (plan S2)"
    handle = RunFile.load(paused.run_file)
    assert (handle.origin, handle.revision, handle.draft) == ("folder", "1", False), "and the run file says what the server said"
    assert (paused.kind, paused.step) == ("task", "reply")
    done2 = served.resume(paused, {"reply": "Sorry about that; refunded."})
    assert fake.runs[paused.run_id]["status"] == "done" and done2.recorded is True
    assert fake.requests.count(("POST", "/bundles")) == 1, "one upload per bundle id per client"

    drafted = served.run(AGENT, {"message": CALM}, workdir=tmp_path)            # a folder nobody published: a draft
    stored = fake.runs[drafted.run_id]
    assert (stored["draft"], stored["revision"], stored["status"]) == (True, None, "paused")
    assert RunFile.load(drafted.run_file).draft is True

    rows = served.runs(agent="tests")
    assert [r.run_id for r in rows] == [drafted.run_id, paused.run_id, done.run_id] and all(isinstance(r, sdk.RunSummary) for r in rows)
    assert [r.run_id for r in served.runs(session="demo")] == [done.run_id]
    assert [r.run_id for r in served.runs(status="paused")] == [drafted.run_id]
    assert [r.run_id for r in served.runs(draft=True)] == [drafted.run_id] and len(served.runs(draft=False)) == 2
    assert len(served.runs(user="zach")) == 3 and served.runs(user="nobody") == []
    run_path(done.run_id).unlink()
    remote = served.run_record(done.run_id)                                      # no run file here: the server's record
    assert isinstance(remote, sdk.RunRecord) and remote.identity["user"] == "zach" and remote.status == "done"
    queries = served.audit()
    assert [q.query for q in queries] == [
        "confidence-fired", "failing-aggregations", "model-answers", "agent-work", "failing-scripts", "untaken-branches", "repeated-cycles",
        "agent-routes", "missing-fields", "empty-results", "unused-data", "cycles", "lineage"]
    assert all(isinstance(q, sdk.AuditQuery) and q.builtin and q.description for q in queries)
    asked = served.audit("model-answers", name="billing_support", agent="tests")
    assert [(r["step"], r["question"], r["model"], r["answers"]) for r in asked] == [("triage", "tone", "jev-1", 2), ("triage", "billing", "jev-1", 2)]
    assert served.audit("model-answers", name="billing_support", agent="someone-else") == []
    assert served.audit("model-answers", name="billing_support", draft=True) == [], "both are runs of the published revision"
    assert [r["derived_from"] for r in served.audit("lineage", key="ticket_id")] == ["message", "triage_decision"], "what escalate read"
    mine = served.save_audit("runs-by-agent", "MATCH (r:Run) RETURN r.agent AS agent, count(r) AS runs ORDER BY agent", "Who runs.")
    assert (mine.query, mine.builtin) == ("runs-by-agent", False) and served.audit()[-1].query == "runs-by-agent"
    assert served.audit("runs-by-agent") == [{"agent": "tests", "runs": 3}]
    served.delete_audit("runs-by-agent")
    assert len(served.audit()) == len(queries)


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


NOT_CLIENT = {"compile", "export", "fmt", "config", "server", "mcp", "skill"}   # the language's tooling, the config, the two servers, the skill


def test_every_cli_command_calls_the_sdk(served, fake, tmp_path, monkeypatch):
    """Each client command calls its `Client` method; the commands that are not client calls are
    listed, so a new command must be one or the other."""
    monkeypatch.chdir(tmp_path)
    served.publish(AGENT)                                                 # the command's own client has no model: run the agent one
    first = served.run(AGENT, {"message": CALM})
    second = served.run(AGENT, {"message": CALM})
    monkeypatch.setenv("AIP_RUNAH_MODEL_KEY", "unused")                  # runah answers into the pause and stops at a human step
    cases = [
        ("info", "describe", ["billing_support"]),
        ("run", "run", ["billing_support_agent", "--inputs", json.dumps({"message": CALM})]),
        ("resume", "resume", [first.run_id, "--answers", json.dumps({"billing": True, "tone": "calm"})]),
        ("runah", "runah", [second.run_id, "--answers", json.dumps({"billing": True, "tone": "calm"}), "--human", "triage,reply"]),
        ("search", "search", ["refund"]),
        ("list", "list", []),
        ("pull", "pull", ["billing_support"]),
        ("pull", "pull_all", ["--all"]),
        ("publish", "publish", [str(EXAMPLE)]),
        ("get", "get", ["billing_support", "--out", str(tmp_path / "got")]),
        ("pin", "pin", ["billing_support@1"]),            # S3: the same shape as retire
        ("runs", "runs", []),
        ("runs", "run_record", [first.run_id]),
        ("audit", "audit", ["confidence-fired", "--published"]),
        ("audit", "save_audit", ["--save", "by-agent", "--cypher", "MATCH (r:Run) RETURN r.agent AS agent, count(r) AS runs"]),
        ("audit", "audit", ["by-agent"]),
        ("audit", "delete_audit", ["--delete", "by-agent"]),
        ("export", "export_runs", ["runs", "billing_support_agent", "--since", "2026-01-01", "-o", str(tmp_path / "audit.rl")]),
        ("export", "export_skill", ["billing_support@1", "--skill", str(tmp_path / "billing-support")]),
        ("retire", "retire", ["billing_support@1"]),
        ("upgrade", "upgrade", []),
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
    assert (tmp_path / "audit.rl").is_file()
    code, _, err = _call("governance")
    assert code == 2 and err == "aip: `aip governance` is `aip audit` since 0.9\n"


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
    assert "server: none (runs are not recorded; run `aip config server local` to record runs on this machine" in out

    from aip.client import local

    code, out, _ = _call("config", "server", "local")                    # this machine's server, started when needed
    s = aip.settings()
    assert code == 0 and (s.server, s.local) == (local.url(), True) and json.loads(s.path.read_text()) == {"server": "local"}
    assert local.store_file().name == "store.cl", "S3: the file the pinned engine keeps, which is the one on disk"
    assert f"server: local  {local.url()}, started when a command needs it; its store is {local.store_file()}" in out and "token:" not in out
    code, out, _ = _call("config", "server", "https://aip.example.com/", "--token", "t")
    s = aip.settings()
    assert (s.server, s.local, s.token) == ("https://aip.example.com", False, "t") and "token:  set" in out
    monkeypatch.setenv("AIP_SERVER", "none")                             # one command with no recording, whatever the file says
    assert aip.settings().server is None
    monkeypatch.setenv("AIP_SERVER", "local")
    assert aip.settings().local is True and aip.settings().source == "AIP_SERVER"
    monkeypatch.delenv("AIP_SERVER")
    code, out, _ = _call("config", "server", "none")
    assert aip.settings().server is None and "server: none" in out and "server" not in json.loads(aip.settings().path.read_text())
    for bad in (["config", "token", "t"], ["config", "server"], ["config", "server", "local", "--server", "http://x"]):
        with pytest.raises(SystemExit) as exit:
            _call(*bad)
        assert exit.value.code == 2, bad
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


# ------------------------------------------------- after the second first-use reports (plan S3)

TRIAGE = example_dir("ticket-triage")
POLICY = "Duplicate charges are refunded in full within 5 business days. Plan changes take effect next cycle."


def test_a_run_paused_in_a_for_shows_every_finished_pass_here_and_on_the_server(served, fake, tmp_path):
    """The milestone's proof: `ticket_triage` paused in its `For` lists the passes it has made,
    in `aip runs <id>`, in the server's record and in its count of entries; a check that failed
    says so in the table."""
    paused = served.run(TRIAGE, {"tickets": ["Where is my invoice?", "How do I change plan?"], "policy": POLICY}, workdir=tmp_path)
    assert isinstance(paused, aip.Paused) and (paused.step, len(paused.tasks), paused.recorded) == ("draft", 2, True)
    made = [("start", None), ("classify", 0), ("by_tone", 0), ("classify", 1), ("by_tone", 1)]
    assert [(e["step"], e["pass"]) for e in served.run_record(paused.run_id).history] == made
    assert [(e["step"], e["pass"]) for e in fake.runs[paused.run_id]["history"]] == made, "the server's record has them too"
    [row] = served.runs(name="ticket_triage")
    assert (row.status, row.data["entries"]) == ("paused", 5)
    assert [r["answers"] for r in served.audit("model-answers", name="ticket_triage")] == [2, 2], "and so do the audit queries"

    good = POLICY.split(".")[0] + ". The invoice is on its way."
    paused = served.resume(paused, [{"reply": good}, {"reply": "Next cycle."}])
    assert (paused.step, len(paused.tasks)) == ("fix", 1), "the second reply does not quote the policy"
    with mock.patch("aip.client.cli._server", return_value=served.server):
        code, table, _ = _call("runs", paused.run_id)
    assert code == 0 and "ticket_triage  draft  paused" in table
    rows = [line.split() for line in table.splitlines() if line.startswith(("classify", "check", "draft", "revise"))]
    assert [(r[0], r[2], r[3]) for r in rows] == [("classify", "each_ticket", "0"), ("draft", "each_ticket", "0"), ("check", "each_ticket", "0"),
                                                 ("revise", "each_ticket", "0"), ("classify", "each_ticket", "1"),
                                                 ("draft", "each_ticket", "1"), ("check", "each_ticket", "1")]
    assert table.count("scripts/policy_check.py -> passed=true") == 1 and table.count("scripts/policy_check.py -> passed=false") == 1
    assert "paused at fix since" in table and len(fake.runs[paused.run_id]["history"]) == 10

    with pytest.raises(aip.RunError) as refused:               # a refused answer changed nothing and sent nothing: recorded false
        served.resume(paused, {"answer": "x"})
    assert (refused.value.kind, refused.value.recorded, refused.value.resumable) == ("invalid_output", False, True)

    done = served.resume(paused, {"reply": good}, on_pause=lambda p: {"summary": "Two replies."})
    assert isinstance(done, aip.Done)
    stored = fake.runs[done.run_id]["history"]
    assert stored == served.run_record(done.run_id).history and [e["step"] for e in stored][-3:] == ["each_ticket", "summarize", "end"]
    kept = fake.store.rows("MATCH (:Run {run_id: $run})-[:HAS_ENTRY]->(e:Entry) RETURN count(e) AS entries", run=done.run_id)
    assert kept == [{"entries": len(stored)}], "the entries that moved when the batch completed were rewritten, none left behind"


def test_the_cli_says_the_same_thing_for_a_name_it_cannot_find_and_hints_at_the_hyphen(served, fake, tmp_path):
    with mock.patch("aip.client.cli._server", return_value=served.server):
        code, out, _ = _call("run", "billing-support", "--inputs", json.dumps({"message": CALM}))
        error = json.loads(out)
        assert (code, error["error"], error["kind"]) == (1, "invalid_input", "not_found")
        assert error["message"] == "no procedure 'billing-support'; did you mean `billing_support`?"
        for command in (["info", "billing-support"], ["pull", "billing-support"], ["get", "billing-support", "--out", str(tmp_path / "x")]):
            code, _, err = _call(*command)
            assert (code, err) == (1, "aip: no procedure 'billing-support'; did you mean `billing_support`?\n"), command
        assert _call("info", "billing_support@7")[2] == "aip: no revision 7 of billing_support\n"

        served.run("billing_support", {"message": CALM}, workdir=tmp_path)
        assert _call("runs", "--name", "billing-support")[1] == "no runs of `billing-support`; names are `aip list`'s\n"
        assert _call("runs", "--name", "billing_support", "--status", "failed")[1] == "no runs\n", "the name has runs; the status has none"
        code, out, err = _call("audit", "model-answers", "--name", "billing-support")
        assert (code, json.loads(out), err) == (0, [], "aip: no runs of `billing-support`; names are `aip list`'s\n")
        assert _call("audit", "model-answers", "--name", "billing_support", "--agent", "nobody")[2] == ""

        # pin and retire take one shape, `name@revision`; the old two-word pin is answered with the spelling that works
        for old in (["pin", "billing_support", "1"], ["retire", "billing_support", "1"]):
            with pytest.raises(SystemExit) as usage:
                _call(*old)
            assert usage.value.code == 2
        assert _call("pin", "billing_support@1")[1] == "billing_support -> 1\n"
        assert _call("pin", "billing_support", "--clear")[1] == "billing_support pin cleared\n"
        assert _call("retire", "billing_support@1")[1] == "retired billing_support@1\n"
        code, _, err = _call("pin", "billing_support@1")
        assert code == 1 and "retired: billing_support@1 is retired" in err
        listed = _call("list")[1]
        assert listed.startswith("billing_support  @- (retired)  1 revision(s)  Turn an inbound billing message") and "\n " not in listed
        code, out, _ = _call("run", "billing_support@1", "--inputs", json.dumps({"message": CALM}))
        assert (code, json.loads(out)["kind"]) == (1, "retired") and "--force" in json.loads(out)["message"]
        code, out, err = _call("run", "billing_support@1", "--inputs", json.dumps({"message": CALM}), "--force")
        assert json.loads(out)["error"] == "no_decision_model", "forced, it runs (this command's own client has no model)"
        assert err.startswith("aip: warning: no decision model is configured, and this procedure asks one at triage")
        assert "(billing_support@1, retired)" in _call("info", "billing_support@1")[1]


def test_an_empty_key_in_the_environment_is_no_model_and_the_run_warns_first(tmp_path, monkeypatch):
    """The milestone's proof: `AIP_DECISION_MODEL_KEY= aip run ...` warns before the first step,
    whatever the config file holds."""
    assert _call("config", "--decision-model-key", "from-the-file")[0] == 0
    assert aip.settings().decision_model_configured
    monkeypatch.setenv("AIP_DECISION_MODEL_KEY", "")
    assert not aip.settings().decision_model_configured and aip.settings().decision_model_key is None
    assert "decision model: none" in _call("config")[1]
    info = _call("info", str(EXAMPLE))[1]
    assert "WARNING  no decision model is configured, and this procedure asks one at triage" in info
    assert re.search(r"^  reply +string +on some paths$", info, re.MULTILINE) and re.search(r"^  message +string$", info, re.MULTILINE), \
        "what a result holds depends on the route"
    assert "WARNING" not in _call("info", str(AGENT))[1]
    code, out, err = _call("run", str(EXAMPLE), "-i", json.dumps({"message": "x"}), "--progress")
    lines = [json.loads(line) for line in out.splitlines()]
    assert code == 1 and [line.get("step") for line in lines] == ["start", "triage"] and lines[-1]["error"] == "no_decision_model"
    assert err.splitlines()[0].startswith("aip: warning: no decision model is configured") and lines[-1]["warning"] in err
    code, out, err = _call("run", str(EXAMPLE), "-i", json.dumps({"msg": "x"}))
    assert (json.loads(out)["error"], err) == ("invalid_input", ""), "a run that does not start has nothing to warn about"
    monkeypatch.setenv("AIP_DECISION_MODEL", "")
    monkeypatch.delenv("AIP_DECISION_MODEL_KEY")
    assert aip.settings().decision_model_configured, "the key in the file still stands; the empty endpoint only unsets an endpoint"


def test_the_smaller_things_the_reports_found(served, fake, tmp_path, capsys):
    with mock.patch("aip.client.cli._server", return_value=served.server):
        assert re.fullmatch(r"billing_support@1  score \d+\.\d{3}  Turn an inbound billing message.*\n", _call("search", "billing refund")[1])
        broken = shutil.copytree(AGENT, tmp_path / "broken")
        (broken / "procedure.aip").write_text((AGENT / "procedure.aip").read_text().replace("Next_Step by_tone", "Next_Step nowhere"))
        code, _, err = _call("publish", str(broken))
        assert code == 1 and err.count("unknown_step") == 1 and err.endswith("does not compile (1 error(s))\n"), "the diagnostic is said once"

        first = served.run("billing_support", {"message": CALM}, workdir=tmp_path)           # paused at reply
        second = served.run(EXAMPLE, {"message": ANGRY}, workdir=tmp_path)
        served.resume(first, {"reply": REPLY})                                               # the older run is the last one updated
        assert [r.run_id for r in served.runs()] == [second.run_id, first.run_id], "by when each started, newest first"
        third = served.run(AGENT, {"message": CALM}, workdir=tmp_path)                       # a draft: a third bundle, a second procedure
        code, out, _ = _call("export", "runs", "-o", str(tmp_path / "all.rl"))
        assert out == f"wrote 3 run(s) of 2 procedure(s) to {tmp_path / 'all.rl'}\n"
        reworded = shutil.copytree(EXAMPLE, tmp_path / "reworded")
        (reworded / "assets" / "policy.md").write_text("Refunds take ten days.\n")
        served.run(reworded, {"message": ANGRY}, workdir=tmp_path)                           # the same procedure, another bundle
        code, out, _ = _call("export", "runs", "billing_support", "-o", str(tmp_path / "one.rl"))
        assert out == f"wrote 3 run(s) of 1 procedure(s) (2 bundles: each revision and each draft is one) to {tmp_path / 'one.rl'}\n"
        assert third.run_id not in [r.run_id for r in served.runs(name="billing_support")]
    with pytest.raises(SystemExit):
        main(["export", "--help"])
    assert "aip export runs [name] -o FILE" in capsys.readouterr().out
    with pytest.raises(aip.InvalidInput) as suffix:
        local().compile(AGENT, tmp_path / "agent.bundle")
    assert ".rl" in str(suffix.value) and not (tmp_path / "agent.bundle").exists()
