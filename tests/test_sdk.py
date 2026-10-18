"""The SDK (`aip.Client`, `docs/sdk.md`): `billing-support` end to end against a folder and a
served catalog, both branches, with typed results and typed errors; and every `aip` command is
a wrapper over it (each client command calls its SDK method; the rest are named as not client
calls). The doc's LangGraph-style tools run against the same skill."""

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
from aip_spec import example_dir
from fastapi.testclient import TestClient

import aip
from aip import sdk
from aip.client.cli import COMMANDS, main
from aip.server.app import create_app
from aip.server.backends.filesystem import FilesystemBackend

EXAMPLE = example_dir("billing-support")
REPO = Path(__file__).parent.parent
CALM = "I was charged twice for March. Could you check?"
ANGRY = "This is the THIRD time you have double charged me. Fix it today or I cancel."
REPLY = "Thanks for flagging this; duplicate charges are refunded in full within 5 business days."
BROKEN = 'import sys\nprint("ticket service unreachable", file=sys.stderr)\nsys.exit(1)\n'


@pytest.fixture(autouse=True)
def no_key(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)


@pytest.fixture
def api(tmp_path) -> TestClient:
    return TestClient(create_app(FilesystemBackend(tmp_path / "server")), raise_server_exceptions=False)


@pytest.fixture
def served(api) -> aip.Client:
    """A client on an in-process server with `billing-support` published through the SDK."""
    client = aip.Client("http://testserver", session=api)
    published = client.publish(EXAMPLE)
    assert isinstance(published, sdk.Published) and published.name == "billing-support"
    return client


@pytest.fixture(params=["folder", "served"])
def home(request, tmp_path, api):
    """`(client, skill)`: a folder client running the skill by name, or a served one."""
    if request.param == "folder":
        shutil.copytree(EXAMPLE, tmp_path / "skills" / "billing-support")
        return aip.Client(tmp_path / "skills"), "billing-support"
    return request.getfixturevalue("served"), "billing-support"


def history(client: aip.Client, run_id: str) -> list:
    return client.run_record(run_id).history


# ------------------------------------------------------------------------ end to end


def test_calm_branch_end_to_end(home, tmp_path):
    client, skill = home
    paused = client.run(skill, {"message": CALM}, workdir=tmp_path)
    assert isinstance(paused, aip.Paused)
    assert (paused.kind, paused.step, paused.state) == ("decision", "triage", {"message": CALM})
    assert set(paused.questions) == {"billing", "tone"}
    assert paused.run_file == aip.Client.run_file(paused.run_id)          # under AIP_HOME, by id

    task = client.resume(paused, {"billing": True, "tone": "calm"})
    assert (task.kind, task.step, task.answer_with) == ("client_task", "reply", {"reply": "string"})
    assert task.run_id == paused.run_id and CALM in task.task

    done = client.resume(task.run_id, {"reply": REPLY})                   # by id, as `aip resume` does
    assert isinstance(done, aip.Done)
    assert done.state == {"message": CALM}
    assert done.to_json() == {"done": True, "run_id": paused.run_id, "state": {"message": CALM},
                              "run_file": str(paused.run_file)}
    record = client.run_record(done.run_id)
    assert record.status == "done"
    assert [e["step"] for e in record.history] == ["triage", "by-tone", "reply", "end"]
    assert record.history[0]["attribution"]["resolver"] == "manual"
    assert record.history[2]["kind"] == "client_task"


def test_angry_branch_end_to_end_with_on_pause_and_progress(home, tmp_path):
    client, skill = home
    lines, seen = [], []

    def answer(paused):
        seen.append(paused.kind)
        return {"billing": True, "tone": "angry"}

    done = client.run(skill, {"message": ANGRY}, workdir=tmp_path, on_step=lines.append, on_pause=answer)
    assert isinstance(done, aip.Done) and done.state == {"message": ANGRY}
    assert seen == ["decision"]
    assert [(line["step"], line["kind"]) for line in lines] == [("triage", "decision"), ("by-tone", "router"),
                                                                ("escalate", "execution")]
    escalate = next(e for e in history(client, done.run_id) if e["step"] == "escalate")
    assert set(escalate["result"]) == {"ticket_id", "queue"}


def test_on_pause_returning_none_stops_at_the_pause(home, tmp_path):
    client, skill = home
    paused = client.run(skill, {"message": CALM}, workdir=tmp_path, on_pause=lambda _p: None)
    assert isinstance(paused, aip.Paused) and paused.kind == "decision"


def test_a_failed_step_raises_and_resume_retries_it(tmp_path):
    skill = tmp_path / "billing-support"
    shutil.copytree(EXAMPLE, skill)
    script = skill / "scripts" / "escalate.py"
    good = script.read_text()
    script.write_text(BROKEN)
    client = aip.Client.over(None)
    paused = client.run(skill, {"message": ANGRY}, workdir=tmp_path)
    with pytest.raises(aip.RunError) as exc:
        client.resume(paused, {"billing": True, "tone": "angry"})
    error = exc.value
    assert isinstance(error, aip.AipError)
    assert (error.kind, error.step, error.resumable) == ("script_failed", "escalate", True)
    assert error.error["exit_code"] == 1 and error.error["stderr"] == "ticket service unreachable"
    assert error.run_file == paused.run_file
    script.write_text(good)
    done = client.resume(error)                                       # retry, from the error itself
    assert isinstance(done, aip.Done) and done.run_id == paused.run_id


def test_typed_errors(tmp_path, api):
    nowhere = aip.Client.over(None)
    with pytest.raises(aip.NoServer):
        nowhere.search("refund")
    with pytest.raises(aip.NoServer):
        nowhere.run("billing-support", {"message": CALM})
    with pytest.raises(aip.NotFound):
        aip.Client(tmp_path / "missing")
    with pytest.raises(aip.InvalidInput):
        nowhere.resume("0123456789abcdef")
    with pytest.raises(aip.RunError) as exc:                              # the start input lacks `message`
        nowhere.run(EXAMPLE, {"msg": "wrong key"})
    assert (exc.value.kind, exc.value.resumable, exc.value.error["missing"]) == ("invalid_input", False, ["message"])
    with pytest.raises(aip.InvalidInput):
        nowhere.run(EXAMPLE, ["not", "an", "object"])

    client = aip.Client("http://testserver", session=api)
    with pytest.raises(aip.ServerError) as exc:
        client.info("nope")
    assert (exc.value.status, exc.value.kind) == (404, "not_found")
    broken = tmp_path / "broken"
    shutil.copytree(EXAMPLE, broken)
    (broken / "SKILL.md").write_text((broken / "SKILL.md").read_text().replace("outputs:", "outputz:", 1))
    with pytest.raises(aip.InvalidSkill) as exc:
        client.publish(broken)
    assert exc.value.validation.errors
    assert client.list() == []                                            # nothing was uploaded


def test_catalog_runs_and_governance_are_typed(served, tmp_path):
    [hit] = served.search("refund")
    assert isinstance(hit, sdk.Hit) and hit.name == "billing-support" and hit.score > 0
    [entry] = served.list()
    assert entry.resolves == hit.revision
    info = served.info("billing-support")
    assert (info.name, info.revision, info.start_step, info.inputs) == ("billing-support", hit.revision, "triage",
                                                                       {"message": "string"})
    assert info.example_input == {"message": "<string>"} and "START INPUT" in info.summary()
    local = aip.Client.over(None).info(EXAMPLE)
    assert (local.revision, local.inputs, local.result) == (None, info.inputs, info.result)

    fetched = served.get("billing-support", tmp_path / "out")
    assert fetched.path == tmp_path / "out" / "billing-support" and fetched.validation.valid
    assert served.pin("billing-support", hit.revision) == sdk.Pinned("billing-support", hit.revision)
    assert served.list()[0].pinned == hit.revision
    assert served.pin("billing-support", None).revision is None

    done = served.run("billing-support", {"message": ANGRY}, workdir=tmp_path,
                      on_pause=lambda _p: {"billing": True, "tone": "angry"})
    [summary] = served.runs()
    assert isinstance(summary, sdk.RunSummary) and (summary.run_id, summary.status) == (done.run_id, "done")
    queries = served.governance()
    assert "manual-decisions" in {q.query for q in queries}
    rows = served.governance("manual-decisions")
    assert rows and rows[0]["name"] == "billing-support"

    assert served.retire(f"billing-support@{hit.revision}") == sdk.Retired("billing-support", hit.revision)
    assert served.search("refund") == []


# ------------------------------------------------------------------ the CLI wraps it


def _call(*argv: str) -> int:
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        return main(list(argv))


NOT_CLIENT = {"schema", "runtime", "skill", "db", "server"}       # format tooling, Neo4j loader, the server


def test_every_cli_command_calls_the_sdk(served, api, tmp_path, monkeypatch):
    """Each client command calls its `Client` method (or `aip.configure`); the commands that are
    not client calls are listed, so a new command must be one or the other."""
    monkeypatch.chdir(tmp_path)
    revision = served.list()[0].resolves
    start = tmp_path / "start.json"
    start.write_text(json.dumps({"message": CALM}))
    answer = tmp_path / "answer.json"
    answer.write_text(json.dumps({"billing": True, "tone": "calm"}))
    first = served.run(EXAMPLE, {"message": CALM})

    cases = [
        ("validate", "validate", [str(EXAMPLE)]),
        ("info", "info", ["billing-support"]),
        ("run", "run", ["billing-support", "--input", str(start)]),
        ("resume", "resume", [first.run_id, "--input", str(answer)]),
        ("search", "search", ["refund"]),
        ("list", "list", []),
        ("publish", "publish", [str(EXAMPLE)]),
        ("get", "get", ["billing-support", "--out", str(tmp_path / "got")]),
        ("pin", "pin", ["billing-support", revision]),
        ("runs", "runs", []),
        ("runs", "run_record", [first.run_id]),
        ("governance", "governance", ["manual-decisions"]),
        ("retire", "retire", [f"billing-support@{revision}"]),
    ]
    assert {c for c, _, _ in cases} | {"config"} | NOT_CLIENT == set(COMMANDS)
    with mock.patch("aip.client.cli._server", return_value=served.server):
        for command, method, argv in cases:
            real = getattr(aip.Client, method)
            with mock.patch.object(aip.Client, method, autospec=True, side_effect=real) as spy:
                assert _call(command, *argv) == 0, (command, argv)
            assert spy.called, f"`aip {command}` does not call Client.{method}"
    with mock.patch("aip.sdk.configure", wraps=sdk.configure) as spy:
        assert _call("config") == 0
    spy.assert_called_once()


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
    namespace["client"] = aip.Client.over(served.server)        # the configured server, here in-process
    paused = json.loads(namespace["run_procedure"]("billing-support", {"message": CALM}))
    assert (paused["paused"], paused["step"]) == ("decision", "triage")
    task = json.loads(namespace["answer_procedure"](paused["run_id"], {"billing": True, "tone": "calm"}))
    assert task["paused"] == "client_task"
    done = json.loads(namespace["answer_procedure"](paused["run_id"], {"reply": REPLY}))
    assert done == {"done": True, "run_id": paused["run_id"], "state": {"message": CALM}, "run_file": paused["run_file"]}
    error = json.loads(namespace["run_procedure"]("billing-support", {"msg": "wrong"}))
    assert (error["error"], error["resumable"]) == ("invalid_input", False)
