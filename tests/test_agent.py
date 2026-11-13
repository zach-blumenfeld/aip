"""`aip agent` (plan aip#29, A3; `docs/agent.md`): a chat model outside the run answers the pauses
of `assist`, one call per pause and no tools; the runtime never calls it.

The model here is a stand-in (`Scripted`): each reply is the next one in its list, or what a
function makes of the messages it was sent. The runs are local (no server), so `assist`'s
scripts find the procedures aip ships and run a folder by its path; `act.py`'s guard is also
tried against the real server in process (`served`)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

import aip
from aip.agent import AGENT, MAX_REFUSALS, AgentError, Sessions, continuation
from aip.chat import Completion
from aip.client.runs import RunFile, local_runs, run_path
from aip.client.server import Server
from aip.compiler import example_dir, relate

from served import Served

pytestmark = pytest.mark.skipif(not relate.available(), reason="relate is not installed")

ACT = example_dir("assist") / "scripts" / "act.py"
GREET = """Procedure greet
  "Greet someone by name."

Start "Who to greet." {
  name: string "Their name."
  Next_Step reply
}

Task_Agent reply "Write a one-line greeting for the name." {
  Read name
  Produce text: string "The greeting."
  Next_Step end
}

End "The greeting." {
  Read text
}
"""


def finish(note: str) -> dict:
    return {"verb": "finish", "args": {}, "note": note, "done": True}


class Scripted:
    """A chat endpoint that answers from a script: a dict is sent as JSON, a string as it is, a
    function is called with the messages. `asked` keeps every request's messages."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.asked: list[list[dict]] = []

    def complete(self, model, messages, tools=None, max_tokens=0):
        self.asked.append([dict(m) for m in messages])
        reply = self.replies.pop(0)
        if callable(reply):
            reply = reply(messages)
        text = reply if isinstance(reply, str) else json.dumps(reply)
        return Completion({"role": "assistant", "content": text}, "stop", 100, 20, {"model": "stand-in-1"})


def client(chat: Scripted) -> aip.Client:
    return aip.Client(agent_chat=chat, agent="tests")


def test_no_model_key_no_agent():
    with pytest.raises(AgentError, match="aip config agent --model-key"):
        aip.Client().ask("count the refunds")


def test_a_sessions_second_call_fills_outcome_from_the_first_runs_note(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    chat = Scripted(finish("Which folder holds the notes?"), finish("monday 2, tuesday 0"))
    c = client(chat)
    first = c.ask("count the lines mentioning refund in each note", shell="sh-1")
    assert (first.status, first.note) == ("done", "Which folder holds the notes?")
    plan = chat.asked[0][1]["content"]
    assert plan.startswith("# Procedure step: plan") and "## Reference: references/aip-skill.md" in plan
    assert '"outcome": ""' in plan and "The verbs assist has" in plan      # the reference's text, not its path alone

    second = c.ask("./notes", shell="sh-1")
    assert second.session == first.session and second.status == "done" and second.note == "monday 2, tuesday 0"
    asked = chat.asked[1][1]["content"]
    assert json.dumps(continuation("Which folder holds the notes?", "./notes"))[1:-1] in asked
    assert "You asked: Which folder holds the notes?. The person answered: ./notes" in asked
    assert '"task": "count the lines mentioning refund in each note"' in asked     # the session's task, not the reply

    saved = Sessions().load(first.session)
    assert saved["runs"] == [first.run_id, second.run_id] and saved["note"] == "monday 2, tuesday 0"
    run = RunFile.load(run_path(second.run_id)).run
    assert run["identity"]["agent"] == AGENT and run["identity"]["session"] == first.session
    plan_entry = next(e for e in run["history"] if e["step"] == "plan")
    assert plan_entry["answered_by"]["agent"] == AGENT and plan_entry["answered_by"]["model"] == "stand-in-1"
    assert plan_entry["work"] == "reported" and plan_entry["tokens"]["total"] == 120

    other = client(Scripted(finish("ok"))).ask("something else", shell="sh-1", new=True)
    assert other.session != first.session
    assert Sessions().current("sh-1") == other.session


def test_a_refused_answer_goes_back_to_the_model_then_the_run_is_left_paused(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    once = Scripted("I would finish here.", finish("done"))
    out = client(once).ask("anything", shell="sh-2")
    assert out.status == "done" and out.calls == 2
    assert once.asked[1][-1]["content"].startswith("That answer was refused: the reply holds no JSON object")

    wrong = {"verb": "dance", "args": {}, "note": "", "done": False}
    chat = Scripted(*[wrong] * (MAX_REFUSALS + 1))
    out = client(chat).ask("anything", shell="sh-3")
    assert out.status == "paused" and out.calls == MAX_REFUSALS + 1 and not chat.replies
    assert f"refused {MAX_REFUSALS + 1} times" in out.reason and "dance" in out.reason
    assert all(asked[-1]["content"].startswith("That answer was refused") for asked in chat.asked[1:])
    run = RunFile.load(run_path(out.run_id))
    assert run.status == "paused" and run.run["pause"]["step"] == "plan" and out.pause["paused"] == "task"


def test_a_child_runs_pause_comes_back_to_plan_and_is_answered_with_resume(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    folder = tmp_path / "greet"
    folder.mkdir()
    (folder / "procedure.aip").write_text(GREET, encoding="utf-8")

    def answer_the_child(messages):
        outcome = json.loads(json.loads(messages[-1]["content"].split("```json\n")[1].split("\n```")[0])["outcome"])
        assert outcome["status"] == "paused", outcome
        assert outcome["step"] == "reply" and outcome["tasks"][0]["state"] == {"name": "Ada"}
        return {"verb": "resume", "args": {"run_id": outcome["run_id"], "answers": {"text": "Hello, Ada!"}}, "note": "", "done": False}

    chat = Scripted({"verb": "run", "args": {"procedure": "greet", "inputs": {"name": "Ada"}}, "note": "", "done": False},
                    answer_the_child, finish("Greeted Ada: Hello, Ada!"))
    out = client(chat).ask("greet Ada", shell="sh-4")
    assert out.status == "done" and out.note == "Greeted Ada: Hello, Ada!" and not chat.replies
    child = next(r for r in local_runs() if r.name == "greet")
    assert child.status == "done" and child.run["result"] == {"text": "Hello, Ada!"}
    assert child.run["identity"]["agent"] == AGENT and child.run["identity"]["session"] == out.session
    reply = next(e for e in child.run["history"] if e["step"] == "reply")
    assert reply["answered_by"]["agent"] == AGENT
    assert '"status": "done"' in chat.asked[2][1]["content"]       # plan saw the child finish


def act(verb: str, args: dict, cwd: Path) -> dict:
    """assist's act.py as the runtime runs it: stdin in, the outcome out."""
    proc = subprocess.run([sys.executable, str(ACT)], input=json.dumps({"state": {"verb": verb, "args": args}}),
                          capture_output=True, text=True, cwd=cwd, check=True)
    return json.loads(json.loads(proc.stdout)["outcome"])


def test_act_has_six_verbs_and_none_that_changes_the_catalog(tmp_path):
    for verb in ("retire", "pin", "overwrite", "unpublish"):
        out = act(verb, {"name": "billing_support"}, tmp_path)
        assert out["status"] == "refused" and "search, runs, run, resume, publish, finish" in out["message"]
    assert act("run", {"procedure": "assist", "inputs": {}}, tmp_path)["status"] == "refused"
    assert act("run", {"procedure": "assist@1", "inputs": {}}, tmp_path)["status"] == "refused"
    assert act("finish", {}, tmp_path) == {"status": "finished"}


def _act_module():
    spec = importlib.util.spec_from_file_location("assist_act", ACT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_act_refuses_to_publish_over_a_taken_name_and_publishes_a_draft(tmp_path, monkeypatch):
    fake = Served(token_names={"secret": "zach"})
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ticket_triage").mkdir()            # a folder named as the procedure is not the catalog (A3's live proof)
    (tmp_path / "ticket_triage" / "procedure.aip").write_text(
        (example_dir("ticket-triage") / "procedure.aip").read_text(encoding="utf-8"), encoding="utf-8")
    try:
        c = aip.Client(Server("http://testserver", token="secret", session=fake), agent="tests")
        c.publish(example_dir("billing-support"))
        module = _act_module()
        taken = module.publish(c, {"path": str(example_dir("billing-support"))})
        assert taken["status"] == "refused" and "already has billing_support" in taken["message"]
        draft = module.publish(c, {"path": str(example_dir("billing-support")), "draft": True})
        assert draft["status"] == "published" and draft["draft"] is True
        fresh = module.publish(c, {"path": str(example_dir("ticket-triage"))})
        assert fresh["status"] == "published" and fresh["revision"] == "1" and fresh["run_it_as"] == fresh["name"]
        assert [e.name for e in c.list()].count("billing_support") == 1
    finally:
        fake.close()


def test_answer_has_the_model_answer_one_pause_of_any_run(tmp_path, monkeypatch, capsys):
    """`aip agent --answer RUN` (plan C6): the console's model steps. The same call as at a pause of
    `assist`, on any run; the answer is recorded as the caller's agent; a run left unanswerable
    comes back paused, with why."""
    from aip.client import cli
    from aip.sdk import Done, Paused, RunError

    monkeypatch.chdir(tmp_path)
    folder = tmp_path / "greet"
    folder.mkdir()
    (folder / "procedure.aip").write_text(GREET, encoding="utf-8")
    chat = Scripted({"text": "Hello, Ada!"})
    c = client(chat)
    paused = c.run(folder, {"name": "Ada"}, agent="studio", session="page-1")
    assert isinstance(paused, Paused) and paused.step == "reply"
    events = []
    done, reason = c.answer(paused.run_id, agent="studio", session="page-1", on_event=events.append)
    assert isinstance(done, Done) and reason is None and done.result == {"text": "Hello, Ada!"}
    assert chat.asked[0][1]["content"].startswith("# Procedure step: reply") and '"name": "Ada"' in chat.asked[0][1]["content"]
    assert [e["event"] for e in events] == ["answer"]
    reply = next(e for e in RunFile.load(run_path(done.run_id)).run["history"] if e["step"] == "reply")
    assert reply["answered_by"]["agent"] == "studio" and reply["answered_by"]["model"] == "stand-in-1"
    with pytest.raises(RunError) as exc:
        c.answer(done.run_id)
    assert exc.value.error["error"] == "not_paused"

    second = c.run(folder, {"name": "Bo"})
    stuck = client(Scripted(*[{"txt": "no"}] * (MAX_REFUSALS + 1)))
    left, reason = stuck.answer(second.run_id)
    assert isinstance(left, Paused) and left.run_id == second.run_id and f"refused {MAX_REFUSALS + 1} times" in reason

    # The command: progress lines, then the paused object with `gave_up`, exit 1.
    monkeypatch.setattr(cli, "_client", lambda: client(Scripted(*[{"txt": "no"}] * (MAX_REFUSALS + 1))))
    assert cli.main(["agent", "--answer", second.run_id, "--progress"]) == 1
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert [line.get("event") for line in lines[:-1]] == ["answer", "refused"] * MAX_REFUSALS + ["answer", "gave_up"]
    assert lines[-1]["paused"] == "task" and lines[-1]["step"] == "reply" and "refused" in lines[-1]["gave_up"]
    monkeypatch.setattr(cli, "_client", lambda: client(Scripted({"text": "Hi, Bo"})))
    assert cli.main(["agent", "--answer", second.run_id, "--progress"]) == 0
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert lines[-1]["done"] is True and lines[-1]["result"] == {"text": "Hi, Bo"}
    assert any(line.get("event") == "step" and line.get("step") == "reply" for line in lines)
