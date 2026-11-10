"""The answerer (plan aip-dev#1, A1): the agent model answering `Task_Agent` pauses, one tool-using
chat per task, against a stand-in Chat Completions server whose replies are scripted.

The stand-in is a real HTTP server on a loopback port, so the requests go through the one HTTP
client (`aip.model.answerer.ChatClient`) exactly as they would to a provider. When
`AIP_AGENT_MODEL_KEY` is set in the shell that runs pytest, one run goes to the real configured
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

REAL = {k: os.environ.get(k) for k in ("AIP_AGENT_MODEL", "AIP_AGENT_MODEL_KEY", "AIP_AGENT_MODEL_NAME")}

needs_relate = pytest.mark.skipif(not relate.available(), reason=relate.INSTALL_HINT)

ANGRY = "I was charged twice this month and nobody answers. Cancel my account now."
CALM = "Hi, could you explain the second line on my March invoice? Thanks."


# --------------------------------------------------------------------------- the stand-in server


def tool(name: str, call_id: str = "c", **args: Any) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
        {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]},
        "finish_reason": "tool_calls"}], "usage": {"prompt_tokens": 100, "completion_tokens": 10}}


def say(answer: Any) -> dict:
    text = answer if isinstance(answer, str) else json.dumps(answer)
    return {"choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 20}}


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
        monkeypatch.setenv("AIP_AGENT_MODEL", server.url)
        monkeypatch.setenv("AIP_AGENT_MODEL_KEY", "test-key")
        monkeypatch.setenv("AIP_AGENT_MODEL_NAME", "stand-in-1")
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
    (bundle / "references" / "help.md").write_text("call tier 2\n")
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
def test_the_model_answers_every_task_and_the_record_shows_its_work(stand_in, workdir, tmp_path):
    server = stand_in([
        tool("read_file", path="notes.md"), say({"billing": True, "tone": "calm"}),                     # triage
        tool("read_file", path="bundle:assets/policy.md"), say({"reply": "We will look into the March invoice."}),  # reply
    ])
    lines: list[dict] = []
    done = client(tmp_path / "home").run(example_dir("billing-support-agent"), {"message": CALM}, workdir=workdir,
                                         answer_with="model", on_step=lines.append)
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
    tasks = [e for e in record.history if e["kind"] == "Task_Agent"]
    assert [e["step"] for e in tasks] == ["triage", "reply"]
    for entry in tasks:
        assert entry["answered_by"] == {"agent": "model", "model": "stand-in-1"}
        assert entry["tokens"] == {"prompt": 220, "completion": 30, "total": 250} and entry["refusals"] == 0
        assert isinstance(entry["model_seconds"], float)
    assert [(c["name"], c["args"]) for c in tasks[0]["tool_calls"]] == [("read_file", "notes.md")]
    assert [(c["name"], c["args"]) for c in tasks[1]["tool_calls"]] == [("read_file", "bundle:assets/policy.md")]
    assert "answered by model stand-in-1: 1 tool call (read_file 1), 250 tokens -> billing=true, tone=calm" in record.table()
    tools = [l for l in lines if l.get("event") == "tool"]
    assert [(l["step"], l["tool"], l["args"]) for l in tools] == [("triage", "read_file", "notes.md"),
                                                                    ("reply", "read_file", "bundle:assets/policy.md")]
    props = entry_properties(done.run_id, "b", 1, tasks[0])
    assert (props["agent"], props["model"], props["tool_calls"], props["tokens"]) == ("model", "stand-in-1", 1, 250)


@needs_relate
def test_a_refused_answer_goes_back_to_the_model(stand_in, workdir, tmp_path):
    server = stand_in([say({"billing": True, "tone": "furious"}), say("sorry, no idea"), say({"billing": True, "tone": "angry"})])
    done = client(tmp_path / "home").run(example_dir("billing-support-agent"), {"message": ANGRY}, workdir=workdir, answer_with="model")
    assert isinstance(done, aip.Done) and done.result["queue"]
    refusals = [m["content"] for m in server.requests[2]["body"]["messages"] if m["role"] == "user"][1:]
    assert refusals[0].startswith("That answer was refused: tone: ") and "furious" in refusals[0]
    assert refusals[1] == "That answer was refused: the reply holds no JSON object. Reply with the corrected JSON object only."
    [triage] = [e for e in client(tmp_path / "home").run_record(done.run_id).history if e["step"] == "triage"]
    assert triage["refusals"] == 2 and triage["result"]["tone"] == {"value": "angry"}


@needs_relate
def test_after_three_refusals_the_run_waits_for_a_person(stand_in, workdir, tmp_path):
    stand_in([say({"tone": "calm"})] * 4)
    paused = client(tmp_path / "home").run(example_dir("billing-support-agent"), {"message": CALM}, workdir=workdir, answer_with="model")
    assert isinstance(paused, aip.Paused) and paused.step == "triage"
    assert paused.answerer["answered"] is False and paused.answerer["reason"].startswith("the agent model's answer was refused 4 times")
    assert paused.answerer["refusals"] == 3
    done = client(tmp_path / "home").resume(paused, {"billing": True, "tone": "angry"})
    assert isinstance(done, aip.Done), "a person answers as before"


@needs_relate
def test_the_caps_and_a_failing_endpoint_leave_the_pause_standing(stand_in, workdir, tmp_path, monkeypatch):
    stand_in([tool("list_files")] * 3)
    monkeypatch.setenv("AIP_CONFIG", str(tmp_path / "config.json"))
    aip.configure(max_tool_calls=2)
    paused = client(tmp_path / "home").run(example_dir("billing-support-agent"), {"message": CALM}, workdir=workdir, answer_with="model")
    assert paused.answerer["reason"] == "the agent model reached its cap of 2 tool calls without answering"
    assert len(paused.answerer["tool_calls"]) == 2

    stand_in([])                                                  # answers 500 to everything
    monkeypatch.setattr("aip.model.answerer.chat.time.sleep", lambda s: None)
    paused = client(tmp_path / "home").resume(paused, answer_with="model")
    assert paused.step == "triage" and paused.answerer["reason"].startswith("the agent model failed: ")


@needs_relate
def test_human_steps_pause_and_the_model_goes_on_after_them(stand_in, workdir, tmp_path):
    server = stand_in([say({"reply": "Here is what that line is."})])
    home = tmp_path / "home"
    paused = client(home).run(example_dir("billing-support-agent"), {"message": CALM}, workdir=workdir, answer_with="model",
                              human="triage")
    assert paused.step == "triage" and paused.answerer["reason"].startswith("triage is a human step")
    assert server.requests == []
    done = client(home).resume(paused, {"billing": True, "tone": "calm"}, answer_with="model")
    assert isinstance(done, aip.Done) and done.result["reply"] == "Here is what that line is."
    history = client(home).run_record(done.run_id).history
    assert [(e["step"], e["answered_by"]["agent"]) for e in history if e["kind"] == "Task_Agent"] == [("triage", "tests"), ("reply", "model")]
    with pytest.raises(aip.InvalidInput, match="--human names nowhere, which is not a Task_Agent of billing_support_agent"):
        client(home).run(example_dir("billing-support-agent"), {"message": CALM}, workdir=workdir, answer_with="model", human="nowhere")


@needs_relate
def test_no_agent_model_is_refused_before_the_run(workdir, tmp_path):
    with pytest.raises(aip.InvalidInput, match="--answer-with model needs an agent model: `aip config --agent-model-key KEY`"):
        client(tmp_path / "home").run(example_dir("billing-support-agent"), {"message": CALM}, workdir=workdir, answer_with="model")
    with pytest.raises(aip.InvalidInput, match="--answer-with takes `model`"):
        client(tmp_path / "home").run(example_dir("billing-support-agent"), {"message": CALM}, workdir=workdir, answer_with="claude")


@needs_relate
def test_the_command_line(stand_in, workdir, capsys, monkeypatch):
    stand_in([tool("search", pattern="refund"), say({"billing": True, "tone": "calm"}), say({"reply": "ok"})])
    monkeypatch.chdir(workdir)
    code = main(["run", str(example_dir("billing-support-agent")), "-i", json.dumps({"message": CALM}), "--answer-with", "model",
                 "--progress"])
    out = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert code == 0 and out[-1]["done"] is True and out[-1]["result"]["reply"] == "ok"
    assert {"event": "tool", "step": "triage", "task": 0, "tool": "search", "args": "pattern=refund"}.items() <= out[1].items()
    assert [l["step"] for l in out if l.get("event") == "step"] == ["start", "triage", "by_tone", "reply", "end"]

    code = main(["config"])
    assert "agent model: http://127.0.0.1:" in capsys.readouterr().out


ECHO = 'Procedure echo\n  "Hand back a string."\n\nStart "The string." {\n  a: string\n  Next_Step end\n}\n\nEnd "The string." {\n  Read a\n}\n'


@needs_relate
def test_build_procedure_runs_with_a_scripted_model_and_a_person(stand_in, workdir, tmp_path):
    (workdir / "docs").mkdir()
    (workdir / "docs" / "policy.md").write_text("Refunds up to 100 are automatic.\n")
    server = stand_in([
        tool("read_file", path="docs/policy.md"), say({"notes": "policy.md: refunds up to 100 are automatic."}),       # read_documents
        say({"rules": "1. refunds <= 100: a script approves", "questions": ["Who approves above 100?"], "settled": False}),
        say({"rules": "1. refunds <= 100: a script approves. 2. above: a manager", "questions": [], "settled": True}),
        tool("write_file", path="echo/procedure.aip", content=ECHO.replace("Next_Step end", "Next_Step nowhere")),
        say({"path": "echo"}),                                                                                          # draft
        tool("write_file", path="echo/procedure.aip", content=ECHO), say({"path": "echo"}),                             # fix
        say({"review": "It covers nothing of the policy yet."}),                                                        # review
    ])
    home = tmp_path / "home"
    inputs = {"brief": "Handle refund requests.", "documents": "docs", "out": "echo"}
    paused = client(home).run(example_dir("build_procedure"), inputs, workdir=workdir, answer_with="model", human="ask_user")
    assert paused.step == "ask_user" and paused.task.state["questions"] == ["Who approves above 100?"]
    done = client(home).resume(paused, {"answers": "1. a manager"}, answer_with="model")
    assert isinstance(done, aip.Done), getattr(done, "answerer", None)
    assert done.result["path"] == "echo" and done.result["bundle_id"] and done.result["review"].startswith("It covers")
    assert "ran to its end" in done.result["test_report"]
    history = client(home).run_record(done.run_id).history
    steps = [e["step"] for e in history if e["kind"] not in ("Loop", "For")]
    assert steps == ["start", "prepare", "read_documents", "extract_rules", "ask_user", "extract_rules", "draft", "compile", "fix",
                     "compile", "test_run", "review", "end"]
    [prepare] = [e for e in history if e["step"] == "prepare"]
    assert prepare["result"] == {"files": ["docs/policy.md"], "name": "echo", "answers": ""}
    second = [r for r in server.requests if "# Task: extract_rules" in r["body"]["messages"][1]["content"]][1]
    assert "1. a manager" in second["body"]["messages"][1]["content"], "the person's answers reach the next round"


@needs_relate
def test_edit_procedure_shows_the_change_as_a_diff(stand_in, workdir, tmp_path):
    (workdir / "echo").mkdir()
    (workdir / "echo" / "procedure.aip").write_text(ECHO)
    changed = ECHO.replace('  a: string\n', '  a: string\n  b: string "A second string."\n').replace("Read a", "Read a, b")
    stand_in([tool("write_file", path="echo/procedure.aip", content=changed), say({"changes": "added b"})])
    done = client(tmp_path / "home").run(example_dir("edit_procedure"), {"folder": "echo", "instruction": "add b", "documents": ""},
                                         workdir=workdir, answer_with="model")
    assert isinstance(done, aip.Done), getattr(done, "answerer", None)
    assert done.result["changes"] == "added b" and done.result["bundle_id"]
    assert done.result["diff"].startswith("--- a/procedure.aip\n+++ b/procedure.aip\n")
    assert '+  b: string "A second string."\n' in done.result["diff"] and "+  Read a, b\n" in done.result["diff"]


@needs_relate
@pytest.mark.skipif(not REAL["AIP_AGENT_MODEL_KEY"], reason="AIP_AGENT_MODEL_KEY is not set: no real model run")
def test_a_real_model_answers_billing_support_agent(workdir, tmp_path, monkeypatch):
    for name, value in REAL.items():
        if value:
            monkeypatch.setenv(name, value)
    done = client(tmp_path / "home").run(example_dir("billing-support-agent"), {"message": ANGRY}, workdir=workdir, answer_with="model")
    assert isinstance(done, aip.Done), getattr(done, "answerer", None)
    [triage] = [e for e in client(tmp_path / "home").run_record(done.run_id).history if e["step"] == "triage"]
    assert triage["answered_by"]["agent"] == "model" and triage["tokens"]["total"] > 0
    assert triage["result"]["billing"] == {"value": True} and triage["result"]["tone"] == {"value": "angry"}
