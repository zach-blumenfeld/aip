"""The server holds the run (B1): `POST /runs` and `POST /runs/{id}/result`.

Each call loads the run from the backend, steps it, and stores what changed under a version
check, so two app instances over one filesystem root can serve one run alternately, and of
two concurrent posts to one run exactly one wins (the other is a 409). The server's record of
a run (`GET /runs/{id}`) is the same state and history a local run of the same inputs writes
to its run file, and a served run's file is only a handle: no history, no accumulated state.
"""

import io
import json
import os
import shutil
import threading
from pathlib import Path
from unittest import mock

import pytest
from aip_spec import example_dir
from fastapi.testclient import TestClient

from aip.client.backend import HttpBackend, LocalBackend
from aip.client.runner import RunFile, Runner
from aip.client.server import Server
from aip.server.app import create_app, upload_of
from aip.server.backends.filesystem import FilesystemBackend

EXAMPLE = example_dir("billing-support")
ANGRY = "This is the THIRD time you have double charged me. Fix it today or I cancel."
CALM = "I was charged twice for March. Could you check?"
REPLY = "Thanks for flagging this; duplicate charges are refunded in full within 5 business days."


@pytest.fixture(autouse=True)
def no_key(monkeypatch, tmp_path):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setenv("AIP_HOME", str(tmp_path / "home"))


@pytest.fixture
def root(tmp_path):
    return tmp_path / "root"


def app_over(root: Path) -> TestClient:
    """One server process over `root`: its own backend objects, nothing shared with another but the disk."""
    return TestClient(create_app(FilesystemBackend(root)), raise_server_exceptions=False)


@pytest.fixture
def api(root):
    api = app_over(root)
    assert api.post("/catalog", json=upload_of(EXAMPLE)).status_code == 201
    return api


def without_seconds(history: list) -> list:
    return [{k: v for k, v in e.items() if k != "seconds"} for e in history]


# --------------------------------------------------------------------------- the api


def test_open_answer_and_finish(api):
    r = api.post("/runs", json={"name": "billing-support", "input": {"message": CALM}})
    assert r.status_code == 201, r.text
    pause = r.json()
    run_id, version = pause["run_id"], pause["version"]
    assert (pause["paused"], pause["step"], pause["state"]) == ("decision", "triage", {"message": CALM})
    assert pause["thresholds"] == {"billing": 0.15, "tone": 0.6}            # the author's, sent with the questions
    assert pause["steps"] == []

    r = api.post(f"/runs/{run_id}/result", json={"step": "triage", "version": version,
                                                   "answer": {"billing": True, "tone": "calm"}})
    assert r.status_code == 200, r.text
    task = r.json()
    assert (task["paused"], task["step"], task["answer_with"]) == ("client_task", "reply", {"reply": "string"})
    assert task["state"] == {"message": CALM, "tone": "calm"}
    assert [line["step"] for line in task["steps"]] == ["triage", "by-tone"]
    assert task["version"] > version

    r = api.post(f"/runs/{run_id}/result", json={"step": "reply", "version": task["version"],
                                                   "answer": {"reply": REPLY}})
    assert r.status_code == 200, r.text
    done = r.json()
    assert (done["done"], done["state"]) == (True, {"message": CALM})
    run = api.get(f"/runs/{run_id}").json()
    assert (run["status"], run["state"], run["version"]) == ("done", {"message": CALM}, done["version"])
    assert [e["step"] for e in run["history"]] == ["triage", "by-tone", "reply", "end"]

    r = api.post(f"/runs/{run_id}/result", json={"answer": {"reply": "again"}})
    assert r.status_code == 409                                             # nothing left to answer


def test_bad_answers_and_bad_input_change_nothing(api):
    r = api.post("/runs", json={"name": "billing-support", "input": {"msg": "typo"}})
    assert r.status_code == 422 and r.json()["error"]["kind"] == "invalid_input"
    assert r.json()["error"]["missing"] == ["message"]
    assert api.get("/runs").json() == []                                    # nothing opened

    pause = api.post("/runs", json={"name": "billing-support", "input": {"message": CALM}}).json()
    before = api.get(f"/runs/{pause['run_id']}").json()
    r = api.post(f"/runs/{pause['run_id']}/result", json={"answer": {"billing": True}})
    assert r.status_code == 422
    assert (r.json()["error"]["kind"], r.json()["error"]["missing"]) == ("invalid_output", ["tone"])
    assert api.get(f"/runs/{pause['run_id']}").json() == before             # the pause stands
    r = api.post(f"/runs/{pause['run_id']}/result", json={"step": "reply", "answer": {"reply": "x"}})
    assert r.status_code == 409 and r.json()["error"]["kind"] == "stale_run"
    assert api.post("/runs/0123456789abcdef/result", json={}).status_code == 404


def test_a_failed_step_is_recorded_and_an_empty_post_retries_it(root, tmp_path):
    broken = tmp_path / "billing-support"
    shutil.copytree(EXAMPLE, broken)
    (broken / "scripts" / "escalate.py").write_text("import sys\nsys.stderr.write('queue down')\nsys.exit(3)\n")
    api = app_over(root)
    assert api.post("/catalog", json=upload_of(broken)).status_code == 201

    pause = api.post("/runs", json={"name": "billing-support", "input": {"message": ANGRY}}).json()
    r = api.post(f"/runs/{pause['run_id']}/result", json={"answer": {"billing": True, "tone": "angry"}})
    assert r.status_code == 200, r.text
    error = r.json()
    assert (error["error"], error["step"], error["exit_code"], error["stderr"], error["resumable"]) == (
        "script_failed", "escalate", 3, "queue down", True)
    run = api.get(f"/runs/{pause['run_id']}").json()
    assert (run["status"], run["after"], run["pause"]["kind"]) == ("failed", "triage", "error")
    assert run["state"] == {"message": ANGRY, "billing": True, "tone": "angry"}   # the state before the step
    assert run["history"][-1]["kind"] == "error"

    r = api.post(f"/runs/{pause['run_id']}/result")                         # no body: retry
    assert r.status_code == 200 and r.json()["error"] == "script_failed"
    assert api.get("/governance/failing-scripts").json()[0]["failed"] == 2


# ------------------------------------------------------------------ no state in memory


def test_two_servers_over_one_root_serve_one_run_alternately(root, api):
    a, b = api, app_over(root)
    pause = a.post("/runs", json={"name": "billing-support", "input": {"message": CALM}}).json()
    task = b.post(f"/runs/{pause['run_id']}/result",
                  json={"version": pause["version"], "answer": {"billing": True, "tone": "calm"}}).json()
    assert task["paused"] == "client_task", task
    done = a.post(f"/runs/{pause['run_id']}/result", json={"version": task["version"], "answer": {"reply": REPLY}}).json()
    assert done["done"] is True, done
    for server in (a, b):
        run = server.get(f"/runs/{pause['run_id']}").json()
        assert run["status"] == "done"
        assert [e["step"] for e in run["history"]] == ["triage", "by-tone", "reply", "end"]


def test_two_concurrent_results_for_one_run_one_is_a_409(root, api):
    """Both posts load the run at the same version before either writes (a barrier holds them
    there), so both pass their checks; the backend's version check lets exactly one write."""
    from aip.model import engine

    pause = api.post("/runs", json={"name": "billing-support", "input": {"message": CALM}}).json()
    servers = [api, app_over(root)]
    barrier = threading.Barrier(2, timeout=10)
    real = engine.submit

    def held(*args, **kwargs):
        barrier.wait()
        return real(*args, **kwargs)

    statuses = []

    def post(server, tone):
        r = server.post(f"/runs/{pause['run_id']}/result",
                        json={"version": pause["version"], "answer": {"billing": True, "tone": tone}})
        statuses.append((r.status_code, r.json()))

    with mock.patch.object(engine, "submit", held):
        threads = [threading.Thread(target=post, args=(s, t)) for s, t in zip(servers, ("calm", "angry"))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    codes = sorted(code for code, _ in statuses)
    assert codes == [200, 409], statuses
    loser = next(body for code, body in statuses if code == 409)
    assert loser["error"]["kind"] == "stale_run"
    winner = next(body for code, body in statuses if code == 200)
    run = api.get(f"/runs/{pause['run_id']}").json()
    assert run["version"] == winner["version"]
    assert [e["step"] for e in run["history"]][:2] == ["triage", "by-tone"]   # one answer, recorded once


# ---------------------------------------------------------------- the same run, two homes


def drive(backend, start: dict, answers: list, tmp: Path) -> RunFile:
    """Run to the end through the CLI's runner, answering each pause in turn; the final run file."""
    out = io.StringIO()
    outcome = Runner(backend, run_file=tmp / "run.json", out=out).start(start)
    for answer in answers:
        run = RunFile.load(outcome.run_file)
        outcome = Runner(backend, run_file=outcome.run_file, out=out, run_id=run.run_id).resume(run, answer)
    assert outcome.code == 0 and RunFile.load(outcome.run_file).pause["kind"] == "done", out.getvalue()
    return RunFile.load(outcome.run_file)


@pytest.mark.parametrize("start, answers", [
    ({"message": ANGRY}, [{"billing": True, "tone": "angry"}]),
    ({"message": CALM}, [{"billing": True, "tone": "calm"}, {"reply": REPLY}]),
], ids=["angry", "calm"])
def test_the_servers_record_is_what_a_local_run_writes(api, tmp_path, monkeypatch, start, answers):
    monkeypatch.setenv("PYTHONHASHSEED", "0")         # the escalate script's ticket id hashes the message
    (tmp_path / "local").mkdir()
    (tmp_path / "served").mkdir()
    local = drive(LocalBackend(EXAMPLE), start, answers, tmp_path / "local")
    served = drive(HttpBackend(Server("http://testserver", session=api), name="billing-support"),
                   start, answers, tmp_path / "served")
    record = api.get(f"/runs/{served.run_id}").json()
    assert record["state"] == local.state
    assert without_seconds(record["history"]) == without_seconds(local.history)
    assert record["status"] == "done" and local.pause["kind"] == "done"


def test_a_served_run_file_is_a_handle(api, tmp_path):
    out = io.StringIO()
    backend = HttpBackend(Server("http://testserver", session=api), name="billing-support")
    outcome = Runner(backend, run_file=tmp_path / "run.json", out=out).start({"message": CALM})
    run = RunFile.load(outcome.run_file)
    outcome = Runner(backend, run_file=outcome.run_file, out=out, run_id=run.run_id).resume(
        run, {"billing": True, "tone": "calm"})
    assert outcome.payload["paused"] == "client_task"
    data = json.loads(Path(outcome.run_file).read_text())
    assert "history" not in data and "state" not in data and "after" not in data
    assert set(data) == {"pause", "run_id", "server", "name", "revision", "version", "created"}
    assert data["pause"]["kind"] == "client_task" and data["pause"]["state"] == {"message": CALM, "tone": "calm"}
    assert data["version"] == api.get(f"/runs/{data['run_id']}").json()["version"]
