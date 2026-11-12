"""The orchestrator (plan aip#29, R7): runs started from runs. A run a script starts is the
script's run's child (`parent`, `depth`, the parent's children index), runah refuses one deeper
than `--max-depth`, a token budget counts the children's tokens, and the shipped `assist`
procedure waits on a child longer than its script cap allows, refuses to run itself and has no
verb that changes the catalog.

The chat model is a stand-in Chat Completions server on a loopback port, as in
`test_answerer.py`, since the children run in processes of their own and reach it over HTTP."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

import pytest

import aip
from aip.client.runs import run_path, run_table
from aip.compiler import example_dir, relate

needs_relate = pytest.mark.skipif(not relate.available(), reason=relate.INSTALL_HINT)

ASSIST = example_dir("assist")


def say(answer: Any) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": json.dumps(answer)}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 20}, "model": "stand-in-1"}        # 140 tokens a task


class StandIn:
    """A Chat Completions endpoint whose reply to each request is `reply(request body)`."""

    def __init__(self, reply: Callable[[dict], dict]):
        self.requests: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers["content-length"])))
                outer.requests.append(body)
                data = json.dumps(reply(body)).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


@pytest.fixture
def stand_in(monkeypatch):
    servers = []

    def make(reply: Callable[[dict], dict]) -> StandIn:
        server = StandIn(reply)
        servers.append(server)
        monkeypatch.setenv("AIP_RUNAH_MODEL_URI", server.url)
        monkeypatch.setenv("AIP_RUNAH_MODEL_KEY", "test-key")
        monkeypatch.setenv("AIP_RUNAH_MODEL_NAME", "stand-in-1")
        return server
    yield make
    for server in servers:
        server.server.shutdown()
        server.server.server_close()


def write(folder: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return folder


def two_tasks(folder: Path) -> Path:
    """A child: two tasks for the model, one after the other."""
    return write(folder, {"procedure.aip": '''Procedure two_tasks
  "Two tasks for the model."

Start "Nothing." {
  Next_Step one
}

Task_Agent one "Say a." {
  Produce a: string "a"
  Next_Step two
}

Task_Agent two "Say b." {
  Read a
  Produce b: string "b"
  Next_Step end
}

End "Both." {
  Read a, b
}
'''})


SPAWN = '''import json, os, sys
import aip
json.load(sys.stdin)
key = "status" if os.environ["AIP_STEP"] == "first" else "again"   # the engine says which step runs the script
try:
    aip.Client().runah(os.environ["CHILD_FOLDER"], {})
    print(json.dumps({key: "done"}))
except aip.RunError as err:
    print(json.dumps({key: err.error["error"]}))
'''


def spawner(folder: Path) -> Path:
    """A parent: two steps that each start the child with runah in their script, then one more step."""
    return write(folder, {"procedure.aip": '''Procedure spawner
  "Start the child twice, then tidy up."
  Requires python 3.10

Start "Nothing." {
  Next_Step first
}

Execute first "Start the child." {
  Run_Script scripts/spawn.py
  Produce status: string "How the child ended."
  Next_Step second
}

Execute second "Start it again." {
  Run_Script scripts/spawn.py
  Produce again: string "How the child ended."
  Next_Step tidy
}

Execute tidy "Nothing to tidy." {
  Run_Script scripts/tidy.py
  Next_Step end
}

End "How the children ended." {
  Read status, again
}
''', "scripts/spawn.py": SPAWN,
         "scripts/tidy.py": "import json, sys\njson.load(sys.stdin)\nprint('{}')\n"})


# --------------------------------------------------------------------------- depth


@needs_relate
def test_runah_refuses_a_run_deeper_than_the_max_depth(stand_in, tmp_path, monkeypatch):
    stand_in(lambda body: say({"a": "x"}) if "Task: one" in json.dumps(body) else say({"b": "y"}))
    child = two_tasks(tmp_path / "child")
    monkeypatch.setenv("AIP_RUN_ID", "parent0001")
    monkeypatch.setenv("AIP_STEP", "spawn")
    monkeypatch.setenv("AIP_RUNAH_DEPTH", "3")
    with pytest.raises(aip.DepthExceeded) as refused:
        aip.Client().runah(child, {}, workdir=tmp_path)
    assert refused.value.kind == "depth_exceeded" and "--max-depth" in str(refused.value) and "3 deep" in str(refused.value)
    assert not list((Path(os.environ["AIP_HOME"]) / "runs").glob("*.json")), "nothing ran"
    assert isinstance(aip.Client().run(child, {}, workdir=tmp_path), aip.Paused), "`run` is not bounded by it: it calls no model"
    aip.configure_runah(max_depth=3)
    done = aip.Client().runah(child, {}, workdir=tmp_path)
    assert isinstance(done, aip.Done)
    record = aip.Client().run_record(done.run_id).data
    assert record["parent"] == {"run_id": "parent0001", "step": "spawn", "pass": None} and record["depth"] == 3


# --------------------------------------------------------------------------- children and the budget


@needs_relate
def test_a_child_is_recorded_under_its_parent_and_the_budget_counts_its_tokens(stand_in, tmp_path, monkeypatch):
    stand_in(lambda body: say({"a": "x"}) if "Task: one" in json.dumps(body) else say({"b": "y"}))
    child = two_tasks(tmp_path / "child")
    parent = spawner(tmp_path / "parent")
    monkeypatch.setenv("CHILD_FOLDER", str(child))
    client = aip.Client(agent="tests")

    # 400 tokens: the first child spends 280 (two tasks); the second is given the 120 left, spends
    # 140 on its first task and fails before its second; the parent, at 420, fails before tidy.
    with pytest.raises(aip.RunError) as failed:
        client.runah(parent, {}, workdir=tmp_path, budget_tokens=400, session="s-r7")
    error = failed.value.error
    assert (error["error"], error["step"], error["budget"], error["spent"], error["resumable"]) == ("budget_exhausted", "tidy", 400, 420, True)

    record = client.run_record(failed.value.run_id).data
    assert record["tokens"] == {"own": 0, "children": 420, "total": 420} and record["budget_tokens"] == 400
    kids = record["children"]
    assert [(k["step"], k["status"], k["tokens"]) for k in kids] == [("first", "done", 280), ("second", "failed", 140)]
    first, second = (client.run_record(k["run_id"]).data for k in kids)
    assert first["parent"] == {"run_id": record["run_id"], "step": "first", "pass": None} and first["depth"] == 1
    assert first["identity"]["agent"] == "tests" and first["identity"]["session"] == "s-r7", "a child is run by whoever ran its parent"
    assert second["budget_tokens"] == 120 and second["error"]["error"] == "budget_exhausted" and second["error"]["step"] == "two"
    assert [e["result"] for e in record["history"] if e["kind"] == "Execute"] == [{"status": "done"}, {"again": "budget_exhausted"}]

    table = run_table(record)
    assert "tokens    420 (own 0, children 420)   budget 400" in table
    lines = table.splitlines()
    first_row = next(i for i, line in enumerate(lines) if line.startswith("first "))
    assert lines[first_row + 1].startswith(f"  -> run {kids[0]['run_id']}  two_tasks") and "done, 280 tokens" in lines[first_row + 1]
    assert f"parent    run {record['run_id']} at first   depth 1" in run_table(first)

    done = client.runah(failed.value.run_id, budget_tokens=10_000)        # a larger budget carries it on
    assert isinstance(done, aip.Done) and done.result == {"status": "done", "again": "budget_exhausted"}


# --------------------------------------------------------------------------- assist


def slow(folder: Path) -> Path:
    """A child that takes longer than the parent's script may wait: three steps of 1.2 s each."""
    return write(folder, {"procedure.aip": '''Procedure slow
  "Three slow steps."
  Requires python 3.10

Start "Nothing." {
  Next_Step one
}

Execute one "Sleep." {
  Run_Script scripts/nap.py
  Next_Step two
}

Execute two "Sleep." {
  Run_Script scripts/nap.py
  Next_Step three
}

Execute three "Sleep, and say so." {
  Run_Script scripts/nap.py
  Produce slept: string "That it slept."
  Next_Step end
}

End "It slept." {
  Read slept
}
''', "scripts/nap.py": "import json, os, sys, time\njson.load(sys.stdin)\ntime.sleep(1.2)\n"
                                    "print(json.dumps({'slept': 'yes'} if os.environ['AIP_STEP'] == 'three' else {}))\n"})


def last_outcome(body: dict) -> str:
    text = body["messages"][-1]["content"]
    return text.split("## The outcome of the last run", 1)[1].split("## The catalog", 1)[0]


@needs_relate
def test_assist_waits_on_a_child_past_its_script_cap(stand_in, tmp_path, monkeypatch):
    child = slow(tmp_path / "slow")

    def plan(body: dict) -> dict:
        outcome = last_outcome(body)
        status = re.search(r'"status": "(\w+)"', outcome)
        run_id = re.search(r'"run_id": "(\w+)"', outcome)
        if status is None:
            return say({"run": str(child), "inputs": "{}", "note": "", "done": False})
        if status.group(1) == "running":
            return say({"run": run_id.group(1), "inputs": "{}", "note": "", "done": False})
        return say({"run": "", "inputs": "{}", "note": f"{status.group(1)} by {run_id.group(1)}", "done": True})

    server = stand_in(plan)
    monkeypatch.setenv("AIP_SCRIPT_TIMEOUT", "3")                  # act waits a second at most; the child takes four
    work = tmp_path / "work"
    work.mkdir()
    done = aip.Client(agent="tests").runah(ASSIST, {"task": "sleep three times", "outcome": ""}, workdir=work)
    assert isinstance(done, aip.Done)

    record = aip.Client().run_record(done.run_id).data
    outcomes = [json.loads(e["result"]["outcome"]) for e in record["history"] if e["step"] == "act"]
    assert len(outcomes) >= 2 and outcomes[0]["status"] == "running" and outcomes[-1]["status"] == "done"
    child_id = outcomes[0]["run_id"]
    assert {o["run_id"] for o in outcomes} == {child_id}, "every pass after the first waited on the same child"
    assert outcomes[-1]["result"] == {"slept": "yes"} and done.result == {"note": f"done by {child_id}"}
    assert [k["run_id"] for k in record["children"]] == [child_id]
    kid = aip.Client().run_record(child_id).data
    assert kid["parent"] == {"run_id": done.run_id, "step": "act", "pass": 0} and kid["depth"] == 1 and kid["status"] == "done"
    assert "build_procedure" in record["history"][1]["result"]["catalog"], "search lists the shipped procedures with no server"
    assert len(server.requests) == len(outcomes) + 1, "one model call a pass, no more"


def act(state: dict, env: dict | None = None) -> dict:
    script = ASSIST / "scripts" / "runah.py"
    out = subprocess.run([sys.executable, str(script)], input=json.dumps({"state": state}), capture_output=True, text=True,
                         env={**os.environ, **(env or {})}, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(json.loads(out.stdout)["outcome"])


def test_assist_does_not_run_itself_and_has_no_verb_that_changes_the_catalog(tmp_path):
    for run in ("assist", "assist@3", str(ASSIST), "bundles/assist.rl"):
        outcome = act({"run": run, "inputs": "{}"}, {"AIP_WORKDIR": str(tmp_path)})
        assert outcome["status"] == "refused" and "does not run itself" in outcome["message"]
    assert act({"run": "", "inputs": "{}"})["status"] == "refused"
    assert act({"run": "x", "inputs": "[1]"})["message"] == "inputs is one JSON object"
    for script in (ASSIST / "scripts").glob("*.py"):
        source = script.read_text(encoding="utf-8")
        assert not re.search(r"\.(retire|pin|save_audit|delete_audit)\(", source), f"{script.name} calls a verb that changes the catalog"
        assert ".publish(" not in source or script.name == "runah.py"
    source = (ASSIST / "scripts" / "runah.py").read_text(encoding="utf-8")
    assert "if name in taken:" in source and "client.publish(folder, draft=True)" in source, "a taken name is never published over"
