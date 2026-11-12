"""runah (plan aip#29, A1 and A2): a chat model answering `Task_Agent` pauses, one tool-using
chat per task, against a stand-in Chat Completions server whose replies are scripted; and what
goes with it: `run` calls no model, a trial runs no script, an outside agent reports its work.

The stand-in is a real HTTP server on a loopback port, so the requests go through the one HTTP
client (`aip.model.answerer.ChatClient`) exactly as they would to a provider. When
`AIP_RUNAH_MODEL_KEY` is set in the shell that runs pytest, one run goes to the real configured
model too (the variable is read when this module is imported, before the per-test isolation
clears it)."""

from __future__ import annotations

import json
import os
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

import aip
from aip.client.cli import main
from aip.compiler import example_dir, relate
from aip.model.answerer import ChatClient, Tools, parse_answer, task_message
from aip.server.store import entry_properties

REAL = {k: os.environ.get(k) for k in ("AIP_RUNAH_MODEL_URI", "AIP_RUNAH_MODEL_KEY", "AIP_RUNAH_MODEL_NAME")}
REPORTED = "stand-in-1-20261101"       # the id the stand-in says answered, a snapshot of the `stand-in-1` asked for

needs_relate = pytest.mark.skipif(not relate.available(), reason=relate.INSTALL_HINT)

ANGRY = "I was charged twice this month and nobody answers. Cancel my account now."
CALM = "Hi, could you explain the second line on my March invoice? Thanks."


# --------------------------------------------------------------------------- the stand-in server


def tool(name: str, call_id: str = "c", **args: Any) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
        {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]},
        "finish_reason": "tool_calls"}], "usage": {"prompt_tokens": 100, "completion_tokens": 10}, "model": REPORTED}


def say(answer: Any) -> dict:
    text = answer if isinstance(answer, str) else json.dumps(answer)
    return {"choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 20}, "model": REPORTED}


class StandIn:
    """A Chat Completions endpoint that answers each request with the next scripted reply and
    keeps every request it was sent."""

    def __init__(self, replies: list[dict]):
        self.replies = list(replies)
        self.requests: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers["content-length"])))
                outer.requests.append({"path": self.path, "auth": self.headers.get("authorization"), "body": body})
                if not outer.replies:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(b'{"error": "the script ran out"}')
                    return
                data = json.dumps(outer.replies.pop(0)).encode()
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

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def stand_in(monkeypatch):
    servers = []

    def make(replies: list[dict]) -> StandIn:
        server = StandIn(replies)
        servers.append(server)
        monkeypatch.setenv("AIP_RUNAH_MODEL_URI", server.url)
        monkeypatch.setenv("AIP_RUNAH_MODEL_KEY", "test-key")
        monkeypatch.setenv("AIP_RUNAH_MODEL_NAME", "stand-in-1")
        return server
    yield make
    for server in servers:
        server.close()


@pytest.fixture
def workdir(tmp_path) -> Path:
    folder = tmp_path / "work"
    folder.mkdir()
    (folder / "notes.md").write_text("Refunds over 100 need a manager.\n")
    return folder


# --------------------------------------------------------------------------- the tools


def test_the_tools_stay_inside_the_working_directory(tmp_path, workdir):
    bundle = tmp_path / "bundle"
    (bundle / "references").mkdir(parents=True)
    (bundle / "references" / "help.md").write_text("call tier 2\n", newline="\n")  # 12 bytes on Windows too
    (tmp_path / "secret.txt").write_text("no")
    tools = Tools(workdir, bundle)
    assert tools.call("read_file", {"path": "notes.md"}) == "Refunds over 100 need a manager.\n"
    assert tools.call("read_file", {"path": "../secret.txt"}).startswith("error: ../secret.txt is outside the working directory")
    assert tools.call("read_file", {"path": str(tmp_path / "secret.txt")}).startswith("error:"), "an absolute path outside too"
    (workdir / "link").symlink_to(tmp_path / "secret.txt")
    assert tools.call("read_file", {"path": "link"}).startswith("error:"), "a link that leads out"
    assert tools.call("read_file", {"path": "bundle:references/help.md"}) == "call tier 2\n"
    assert tools.call("write_file", {"path": "bundle:references/help.md", "content": "x"}).startswith("error: the procedure's own files are read-only")
    assert tools.call("write_file", {"path": "out/a/procedure.txt", "content": "hello"}) == "wrote out/a/procedure.txt (5 bytes)"
    assert "out/a/procedure.txt  5" in tools.call("list_files", {})
    assert tools.call("list_files", {"path": "bundle:"}) == "bundle:references/help.md  12"
    assert tools.call("search", {"pattern": "MANAGER"}) == "notes.md:1: Refunds over 100 need a manager."
    assert tools.call("nope", {}).startswith("error: there is no tool 'nope'")
    assert tools.call("read_file", "{not json").startswith("error: the arguments are not JSON")
    assert tools.call("read_file", {"file": "x"}).startswith("error:"), "a wrong argument is a result, not a crash"


@needs_relate
def test_compile_answers_the_diagnostics(workdir):
    shutil.copytree(example_dir("billing-support-agent"), workdir / "bs")
    tools = Tools(workdir)
    done = json.loads(tools.call("compile", {"path": "bs"}))
    assert done["compiled"] is True and done["bundle_id"] and done["folder"] == "bs"
    source = workdir / "bs" / "procedure.aip"
    source.write_text(source.read_text().replace("Next_Step by_tone", "Next_Step nowhere"))
    broken = json.loads(tools.call("compile", {"path": "bs/procedure.aip"}))
    assert broken["compiled"] is False and any("unknown_step" in d for d in broken["diagnostics"])
    assert tools.call("compile", {"path": "."}).startswith("error: . holds no procedure.aip")


def test_an_answer_is_the_json_object_in_the_reply():
    assert parse_answer('{"tone": "calm"}') == {"tone": "calm"}
    assert parse_answer('Here it is:\n```json\n{"tone": "calm"}\n```') == {"tone": "calm"}
    assert parse_answer('Done. {"path": "/x"} as asked') == {"path": "/x"}
    with pytest.raises(ValueError):
        parse_answer("I could not do it.")


def test_the_task_message_carries_the_prompt_the_state_and_the_shape():
    task = {"index": 1, "pass": 0, "passes": [{"loop": "each", "pass": 0}], "prompt": "Classify it.", "state": {"message": "hi"},
            "references": [{"path": "references/help.md", "description": "contacts"}], "answer_with": {"tone": "choice"},
            "labels": {"tone": ["angry", "calm"]}}
    text = task_message("triage", task, 2, 'answer with {"tone": "angry" | "calm"}')
    for part in ("# Task: triage (task 2 of 2)", "Loop: each pass 0", "Classify it.", '"message": "hi"',
                 "- bundle:references/help.md: contacts", '{"tone": "choice"}', 'Labels: {"tone": ["angry", "calm"]}',
                 'Answer with {"tone": "angry" | "calm"}.'):
        assert part in text



# --------------------------------------------------------------------------- runs


def client(home: Path) -> aip.Client:
    return aip.Client(home=home, agent="tests")


@needs_relate
def test_runah_answers_every_task_and_the_record_shows_its_work(stand_in, workdir, tmp_path):
    server = stand_in([
        tool("read_file", path="notes.md"), say({"billing": True, "tone": "calm"}),                     # triage
        tool("read_file", path="bundle:assets/policy.md"), say({"reply": "We will look into the March invoice."}),  # reply
    ])
    lines: list[dict] = []
    done = client(tmp_path / "home").runah(example_dir("billing-support-agent"), {"message": CALM}, workdir=workdir,
                                           on_step=lines.append)
    assert isinstance(done, aip.Done) and done.result["reply"] == "We will look into the March invoice."
    assert [r["path"] for r in server.requests] == ["/v1/chat/completions"] * 4
    assert server.requests[0]["auth"] == "Bearer test-key" and server.requests[0]["body"]["model"] == "stand-in-1"
    first = server.requests[0]["body"]
    assert first["messages"][0]["role"] == "system" and "The AIP procedure language on one page" in first["messages"][0]["content"]
    assert "# Task: triage" in first["messages"][1]["content"] and CALM in first["messages"][1]["content"]
    assert [t["function"]["name"] for t in first["tools"]] == ["read_file", "list_files", "search", "write_file", "compile"]
    second = server.requests[1]["body"]["messages"]
    assert second[-1] == {"role": "tool", "tool_call_id": "c", "content": "Refunds over 100 need a manager.\n"}, "the tool's result went back"

    record = client(tmp_path / "home").run_record(done.run_id)
    assert record.identity["agent"] == "tests", "the run is whoever launched it"
    assert record.data["workdir"] == str(workdir.resolve())
    tasks = [e for e in record.history if e["kind"] == "Task_Agent"]
    assert [e["step"] for e in tasks] == ["triage", "reply"]
    for entry in tasks:
        assert entry["answered_by"] == {"agent": "runah", "model": REPORTED}, "the id the endpoint reported, not the name asked for"
        assert entry["work"] == "observed"
        assert entry["tokens"] == {"prompt": 220, "completion": 30, "total": 250} and entry["refusals"] == 0
        assert isinstance(entry["model_seconds"], float)
    assert [(c["name"], c["args"]) for c in tasks[0]["tool_calls"]] == [("read_file", "notes.md")]
    assert [(c["name"], c["args"]) for c in tasks[1]["tool_calls"]] == [("read_file", "bundle:assets/policy.md")]
    assert (f"answered by runah ({REPORTED}), observed: 1 tool call (read_file 1), 250 tokens -> billing=true, tone=calm"
            in record.table())
    tools = [l for l in lines if l.get("event") == "tool"]
    assert [(l["step"], l["tool"], l["args"]) for l in tools] == [("triage", "read_file", "notes.md"),
                                                                    ("reply", "read_file", "bundle:assets/policy.md")]
    props = entry_properties(done.run_id, "b", 1, tasks[0])
    assert (props["agent"], props["model"], props["work"], props["tool_calls"], props["tokens"]) == ("runah", REPORTED, "observed", 1, 250)


@needs_relate
def test_run_pauses_at_every_task_whatever_is_configured(stand_in, workdir, tmp_path):
    server = stand_in([say({"billing": True, "tone": "calm"})])
    paused = client(tmp_path / "home").run(example_dir("billing-support-agent"), {"message": CALM}, workdir=workdir)
    assert isinstance(paused, aip.Paused) and paused.step == "triage" and paused.answerer is None
    assert server.requests == [], "run calls no chat model"
    with pytest.raises(TypeError):
        client(tmp_path / "home").run(example_dir("billing-support-agent"), {"message": CALM}, answer_with="model")


@needs_relate
def test_a_refused_answer_goes_back_to_the_model(stand_in, workdir, tmp_path):
    server = stand_in([say({"billing": True, "tone": "furious"}), say("sorry, no idea"), say({"billing": True, "tone": "angry"})])
    done = client(tmp_path / "home").runah(example_dir("billing-support-agent"), {"message": ANGRY}, workdir=workdir)
    assert isinstance(done, aip.Done) and done.result["queue"]
    refusals = [m["content"] for m in server.requests[2]["body"]["messages"] if m["role"] == "user"][1:]
    assert refusals[0].startswith("That answer was refused: tone: ") and "furious" in refusals[0]
    assert refusals[1] == "That answer was refused: the reply holds no JSON object. Reply with the corrected JSON object only."
    [triage] = [e for e in client(tmp_path / "home").run_record(done.run_id).history if e["step"] == "triage"]
    assert triage["refusals"] == 2 and triage["result"]["tone"] == {"value": "angry"}


@needs_relate
def test_after_three_refusals_the_run_waits_and_run_resume_and_runah_mix(stand_in, workdir, tmp_path):
    stand_in([say({"tone": "calm"})] * 4)
    paused = client(tmp_path / "home").runah(example_dir("billing-support-agent"), {"message": CALM}, workdir=workdir)
    assert isinstance(paused, aip.Paused) and paused.step == "triage"
    assert paused.answerer["answered"] is False and paused.answerer["reason"].startswith("runah's model's answer was refused 4 times")
    assert paused.answerer["refusals"] == 3
    paused = client(tmp_path / "home").resume(paused, {"billing": True, "tone": "calm"})
    assert paused.step == "reply", "resume answers as before and stops at the next task: it calls no model"
    stand_in([say({"reply": "Here it is."})])
    done = client(tmp_path / "home").runah(paused.run_id)
    assert isinstance(done, aip.Done) and done.result["reply"] == "Here it is.", "runah carries the run on from its pause"


@needs_relate
def test_the_caps_and_a_failing_endpoint_leave_the_pause_standing(stand_in, workdir, tmp_path, monkeypatch):
    stand_in([tool("list_files")] * 3)
    aip.configure_runah(max_tool_calls_per_task=2)
    paused = client(tmp_path / "home").runah(example_dir("billing-support-agent"), {"message": CALM}, workdir=workdir)
    assert paused.answerer["reason"] == ("runah's model reached its cap of 2 tool calls on one task without answering "
                                         "(`aip config runah --max-tool-calls-per-task N`)")
    assert len(paused.answerer["tool_calls"]) == 2

    stand_in([])                                                  # answers 500 to everything
    monkeypatch.setattr("aip.model.answerer.chat.time.sleep", lambda s: None)
    paused = client(tmp_path / "home").runah(paused.run_id)
    assert paused.step == "triage" and paused.answerer["reason"].startswith("runah's model failed: ")


@needs_relate
def test_human_steps_pause_and_runah_goes_on_after_them(stand_in, workdir, tmp_path):
    server = stand_in([say({"reply": "Here is what that line is."})])
    home = tmp_path / "home"
    paused = client(home).runah(example_dir("billing-support-agent"), {"message": CALM}, workdir=workdir, human="triage")
    assert paused.step == "triage" and paused.answerer["human"] == "listed" and paused.answerer["reason"] == (
        f"triage is a human step (listed in --human): answer it with `aip runah {paused.run_id} --answers JSON`")
    assert server.requests == []
    done = client(home).runah(paused.run_id, answers={"billing": True, "tone": "calm"})
    assert isinstance(done, aip.Done) and done.result["reply"] == "Here is what that line is."
    history = client(home).run_record(done.run_id).history
    assert [(e["step"], e["answered_by"]["agent"]) for e in history if e["kind"] == "Task_Agent"] == [("triage", "tests"), ("reply", "runah")]
    with pytest.raises(aip.InvalidInput, match="--human names nowhere, which is not a Task_Agent of billing_support_agent"):
        client(home).runah(example_dir("billing-support-agent"), {"message": CALM}, workdir=workdir, human="nowhere")
    with pytest.raises(aip.InvalidInput, match="a run that is already going takes answers, not inputs"):
        client(home).runah(done.run_id, {"message": CALM})
    with pytest.raises(aip.InvalidInput, match="answers go to a run that is paused"):
        client(home).runah(example_dir("billing-support-agent"), {"message": CALM}, {"billing": True})


@needs_relate
def test_runah_with_no_model_key_is_refused_before_the_run(workdir, tmp_path):
    with pytest.raises(aip.InvalidInput, match=r"aip runah needs a chat model to answer the tasks: `aip config runah --model-key KEY`"):
        client(tmp_path / "home").runah(example_dir("billing-support-agent"), {"message": CALM}, workdir=workdir)
    assert not list((tmp_path / "home").glob("runs/*.json")), "nothing ran"


@needs_relate
def test_the_command_line(stand_in, workdir, capsys, monkeypatch):
    stand_in([tool("search", pattern="refund"), say({"billing": True, "tone": "calm"}), say({"reply": "ok"})])
    monkeypatch.chdir(workdir)
    code = main(["runah", str(example_dir("billing-support-agent")), "-i", json.dumps({"message": CALM}), "--progress"])
    out = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert code == 0 and out[-1]["done"] is True and out[-1]["result"]["reply"] == "ok"
    assert {"event": "tool", "step": "triage", "task": 0, "tool": "search", "args": "pattern=refund"}.items() <= out[1].items()
    assert [l["step"] for l in out if l.get("event") == "step"] == ["start", "triage", "by_tone", "reply", "end"]

    code = main(["run", str(example_dir("billing-support-agent")), "-i", json.dumps({"message": CALM})])
    paused = json.loads(capsys.readouterr().out)
    assert code == 0 and paused["paused"] == "task" and paused["step"] == "triage", "aip run pauses at the first task"
    with pytest.raises(SystemExit):
        main(["run", str(example_dir("billing-support-agent")), "--answer-with", "model"])
    capsys.readouterr()

    stand_in([say({"reply": "fine"})])
    code = main(["runah", paused["run_id"], "--answers", json.dumps({"billing": True, "tone": "calm"})])
    assert code == 0 and json.loads(capsys.readouterr().out)["result"]["reply"] == "fine"


def test_config_shows_the_runah_block_and_the_script_timeout(capsys, monkeypatch, tmp_path):
    assert main(["config"]) == 0
    out = capsys.readouterr().out
    assert "script timeout: 300 seconds per script" in out
    assert "runah:\n  model uri:   https://api.anthropic.com/v1\n  model name:  claude-opus-5-5\n  model key:   none" in out

    assert main(["config", "runah", "--model-key", "sk-secret", "--model-name", "gpt-x", "--max-tool-calls-per-task", "12"]) == 0
    out = capsys.readouterr().out
    assert "sk-secret" not in out and "model key:   set" in out and "model name:  gpt-x" in out and "at most 12 tool calls" in out
    saved = json.loads(Path(os.environ["AIP_CONFIG"]).read_text())
    assert saved["runah"] == {"model_key": "sk-secret", "model_name": "gpt-x", "max_tool_calls_per_task": 12}
    monkeypatch.setenv("AIP_RUNAH_MODEL_NAME", "from-env")
    assert aip.settings().runah_model == "from-env", "the environment wins over the file"
    assert main(["config", "runah", "--model-key", ""]) == 0 and "model key:   none" in capsys.readouterr().out

    assert main(["config", "--script-timeout", "45"]) == 0 and "script timeout: 45 seconds per script" in capsys.readouterr().out
    monkeypatch.setenv("AIP_SCRIPT_TIMEOUT", "none")
    assert aip.settings().script_timeout is None
    monkeypatch.delenv("AIP_SCRIPT_TIMEOUT")
    assert main(["config", "--script-timeout", ""]) == 0 and aip.settings().script_timeout == 300


def test_a_config_from_before_runah_is_read_and_moved(monkeypatch):
    path = Path(os.environ["AIP_CONFIG"])
    path.write_text(json.dumps({"agent_model": {"api_key": "old-key", "name": "old-model"}}))
    s = aip.settings()
    assert (s.runah_model_key, s.runah_model) == ("old-key", "old-model")
    aip.configure_runah(max_tokens_per_task=1000)
    assert json.loads(path.read_text()) == {"runah": {"model_key": "old-key", "model_name": "old-model", "max_tokens_per_task": 1000}}


@needs_relate
def test_an_outside_agent_reports_its_work(workdir, tmp_path, capsys):
    home = None                     # AIP_HOME, which the command line below uses too
    paused = client(home).run(example_dir("billing-support-agent"), {"message": CALM}, workdir=workdir)
    with pytest.raises(aip.RunError) as refused:
        client(home).resume(paused, {"billing": True, "tone": "calm"}, work={"model": "claude-x", "cost": 3})
    assert refused.value.error["error"] == "invalid_input" and "cost is not reported" in refused.value.error["message"]
    assert refused.value.resumable, "the pause stands"
    paused = client(home).resume(paused, {"billing": True, "tone": "calm"},
                                 work={"model": "claude-x", "tool_calls": 3, "tokens": 1200, "seconds": 4.5})
    assert paused.step == "reply"
    [triage] = [e for e in client(home).run_record(paused.run_id).history if e["step"] == "triage"]
    assert triage["work"] == "reported" and triage["answered_by"]["model"] == "claude-x" and triage["answered_by"]["agent"] == "tests"
    assert (triage["tool_calls"], triage["tokens"], triage["work_seconds"]) == (3, {"total": 1200}, 4.5)
    assert "answered by tests (claude-x), reported: 3 tool calls, 1200 tokens, 4.5s -> billing=true, tone=calm" in \
        client(home).run_record(paused.run_id).table()
    props = entry_properties(paused.run_id, "b", 1, triage)
    assert (props["work"], props["model"], props["tool_calls"], props["tokens"]) == ("reported", "claude-x", 3, 1200)

    code = main(["resume", str(paused.run_file), "--answers", json.dumps({"reply": "ok"}), "--work",
                 json.dumps({"tokens": {"prompt": 10, "completion": 5}})])
    assert code == 0 and json.loads(capsys.readouterr().out)["done"] is True
    [reply] = [e for e in client(home).run_record(paused.run_id).history if e["step"] == "reply"]
    assert reply["work"] == "reported" and reply["tokens"] == {"prompt": 10, "completion": 5, "total": 15}


@needs_relate
def test_the_audit_says_whose_account_the_work_is(stand_in, workdir, tmp_path):
    from served import Served
    from aip.client.server import Server
    from aip.server import audit

    served = Served()
    stand_in([say({"billing": True, "tone": "calm"}), say({"reply": "ok"})])
    c = aip.Client(Server("http://testserver", session=served), home=tmp_path / "home", agent="tests")
    c.runah(example_dir("billing-support-agent"), {"message": CALM}, workdir=workdir)
    paused = c.run(example_dir("billing-support-agent"), {"message": CALM}, workdir=workdir)
    c.resume(paused, {"billing": True, "tone": "calm"}, work={"model": "claude-x", "tokens": 900, "tool_calls": 2})
    rows = audit.run(served.store, "agent-work")
    assert [(r["step"], r["agent"], r["model"], r["work"], r["tasks"], r["tool_calls"], r["tokens"]) for r in rows] == [
        ("triage", "tests", "claude-x", "reported", 1, 2, 900), ("reply", "runah", REPORTED, "observed", 1, 0, 140),
        ("triage", "runah", REPORTED, "observed", 1, 0, 140)]


ECHO = 'Procedure echo\n  "Hand back a string."\n\nStart "The string." {\n  a: string\n  Next_Step end\n}\n\nEnd "The string." {\n  Read a\n}\n'

FETCH = '''Procedure fetch_feed
  "Collect a feed and hand it back."
  Requires python 3.10

Start "Whose feed." {
  user: string
  Next_Step fetch
}

Execute fetch "Fetch the user's feed." {
  Read user
  Run_Script scripts/fetch.py
  Produce feed: string
  Next_Step end
}

End "The feed." {
  Read feed
}
'''
FETCH_SCRIPT = '"""Fetch the user\'s notifications from GitHub with their own token (GITHUB_TOKEN)."""\nimport os, json, sys\nopen(os.path.join(os.environ["AIP_WORKDIR"], "RAN"), "w").write("x")\njson.dump({"feed": "x"}, sys.stdout)\n'


@needs_relate
def test_build_procedure_runs_ahead_to_a_person_and_on(stand_in, workdir, tmp_path):
    (workdir / "docs").mkdir()
    (workdir / "docs" / "policy.md").write_text("Refunds up to 100 are automatic.\n")
    server = stand_in([
        tool("read_file", path="docs/policy.md"), say({"notes": "policy.md: refunds up to 100 are automatic."}),       # read_documents
        say({"rules": "1. refunds <= 100: a script approves", "questions": ["Who approves above 100?"], "settled": False}),
        say({"rules": "1. refunds <= 100: a script approves. 2. above: a manager", "questions": [], "settled": True}),
        tool("write_file", path="out/procedure.aip", content=ECHO.replace("Next_Step end", "Next_Step nowhere")),
        say({"path": "out", "procedure": "echo"}),                                                                      # draft
        tool("write_file", path="out/procedure.aip", content=ECHO), say({"path": "out"}),                               # fix
        say({"review": "It covers nothing of the policy yet.\nScripts:\n(none)"}),                                      # review
    ])
    home = tmp_path / "home"
    inputs = {"brief": "Handle refund requests.", "documents": "docs", "out": "out", "title": ""}
    paused = client(home).runah(example_dir("build_procedure"), inputs, workdir=workdir, human="ask_user")
    assert paused.step == "ask_user" and paused.task.state["questions"] == ["Who approves above 100?"]
    done = client(home).runah(paused.run_id, answers={"answers": "1. a manager"})
    assert isinstance(done, aip.Done), getattr(done, "answerer", None)
    assert done.result["path"] == "out" and done.result["procedure"] == "echo" and done.result["bundle_id"]
    assert done.result["review"].startswith("It covers")
    assert "ran to its end" in done.result["test_report"] and "The draft carries no script." in done.result["test_report"]
    history = client(home).run_record(done.run_id).history
    steps = [e["step"] for e in history if e["kind"] not in ("Loop", "For")]
    assert steps == ["start", "prepare", "read_documents", "extract_rules", "ask_user", "extract_rules", "draft", "compile", "fix",
                     "compile", "test_run", "review", "end"]
    [prepare] = [e for e in history if e["step"] == "prepare"]
    assert prepare["result"] == {"files": ["docs/policy.md"], "name": "", "answers": ""}
    draft = [r for r in server.requests if "# Task: draft" in r["body"]["messages"][1]["content"]][0]
    assert "name it from the brief's" in draft["body"]["messages"][1]["content"]
    second = [r for r in server.requests if "# Task: extract_rules" in r["body"]["messages"][1]["content"]][1]
    assert "1. a manager" in second["body"]["messages"][1]["content"], "the person's answers reach the next round"


@needs_relate
def test_the_trial_runs_none_of_the_scripts_the_model_wrote(stand_in, workdir, tmp_path):
    stand_in([
        say({"notes": "none"}), say({"rules": "fetch the feed", "questions": [], "settled": True}),
        tool("write_file", path="feed/procedure.aip", content=FETCH), tool("write_file", path="feed/scripts/fetch.py", content=FETCH_SCRIPT),
        say({"path": "feed", "procedure": "fetch_feed"}),
        say({"review": "Scripts:\nscripts/fetch.py: calls GitHub with GITHUB_TOKEN"}),
    ])
    inputs = {"brief": "My GitHub feed.", "documents": "", "out": "feed", "title": "My Feed"}
    done = client(tmp_path / "home").runah(example_dir("build_procedure"), inputs, workdir=workdir)
    assert isinstance(done, aip.Done), getattr(done, "answerer", None)
    report = done.result["test_report"]
    assert "stopped before fetch, which would run scripts/fetch.py: the trial runs no script." in report
    assert "- scripts/fetch.py: Fetch the user's notifications from GitHub with their own token (GITHUB_TOKEN)." in report
    assert not (workdir / "RAN").exists() and not list(workdir.rglob("RAN")), "the model's script did not run"
    [prepare] = [e for e in client(tmp_path / "home").run_record(done.run_id).history if e["step"] == "prepare"]
    assert prepare["result"]["name"] == "my_feed", "the name the requester gave, tidied"


@needs_relate
def test_edit_procedure_shows_the_change_as_a_diff(stand_in, workdir, tmp_path):
    (workdir / "echo").mkdir()
    (workdir / "echo" / "procedure.aip").write_text(ECHO)
    changed = ECHO.replace('  a: string\n', '  a: string\n  b: string "A second string."\n').replace("Read a", "Read a, b")
    stand_in([tool("write_file", path="echo/procedure.aip", content=changed), say({"changes": "added b"})])
    done = client(tmp_path / "home").runah(example_dir("edit_procedure"), {"folder": "echo", "instruction": "add b", "documents": ""},
                                           workdir=workdir)
    assert isinstance(done, aip.Done), getattr(done, "answerer", None)
    assert done.result["changes"] == "added b" and done.result["bundle_id"]
    assert done.result["diff"].startswith("--- a/procedure.aip\n+++ b/procedure.aip\n")
    assert '+  b: string "A second string."\n' in done.result["diff"] and "+  Read a, b\n" in done.result["diff"]


@needs_relate
@pytest.mark.skipif(not REAL["AIP_RUNAH_MODEL_KEY"], reason="AIP_RUNAH_MODEL_KEY is not set: no real model run")
def test_a_real_model_answers_billing_support_agent(workdir, tmp_path, monkeypatch):
    for name, value in REAL.items():
        if value:
            monkeypatch.setenv(name, value)
    done = client(tmp_path / "home").runah(example_dir("billing-support-agent"), {"message": ANGRY}, workdir=workdir)
    assert isinstance(done, aip.Done), getattr(done, "answerer", None)
    [triage] = [e for e in client(tmp_path / "home").run_record(done.run_id).history if e["step"] == "triage"]
    assert triage["answered_by"]["agent"] == "runah" and triage["answered_by"]["model"] and triage["tokens"]["total"] > 0
    assert triage["result"]["billing"] == {"value": True} and triage["result"]["tone"] == {"value": "angry"}
