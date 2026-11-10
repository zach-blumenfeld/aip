"""`aip mcp`, the SDK as an MCP server (`aip.mcp`, `docs/mcp.md`; plan aip-dev#1, M1).

An MCP client drives the server the way a framework does: in process for most tests (the MCP
SDK connects a client to a server object directly), and once over stdio against the real `aip
mcp` process. The six tools answer with the CLI's objects; a pause, a refused answer and a
target that cannot be run are ordinary results, never MCP errors; the MCP client's name is the
run's `agent`. `dynamic-policy` runs end to end by its published name against the real server
in process with a scripted decision model, answering its pauses with canned text, and the
server lists the run under the client's name: the milestone's proof without a network.
Everything opens a Relate store, so it skips with the install hint where Relate is missing."""

from __future__ import annotations

import io
import os
import shutil
import socket
import subprocess
import sys
import time
from contextlib import redirect_stderr, redirect_stdout

import anyio
import pytest
from mcp import Client as McpClient
from mcp import Implementation, StdioServerParameters

import aip
from aip.client.cli import COMMANDS, main
from aip.client.runs import RunFile, run_path
from aip.client.server import Server
from aip.compiler import example_dir, relate
from aip.mcp import INSTRUCTIONS, TOOLS, build, result_object
from served import Model, Served

pytestmark = pytest.mark.skipif(not relate.available(), reason=relate.INSTALL_HINT)

AGENT = example_dir("billing-support-agent")        # triage is a Task_Agent: runs with no model
POLICY = example_dir("dynamic-policy")
CALM = "I was charged twice for March. Could you check?"
REPLY = "Sorry about that; the duplicate charge is refunded."
TASK = {"task": "Write a one-line welcome note.", "policies": ["The note is in English.", "The note names no price."]}


class TicketModel:
    """Stands in for `TypeSafeClient` on `ticket-triage`: every ticket is a calm billing question."""

    def system_one(self, state, questions, **_):
        return {"model": "jev-1", "usage": {"input_tokens": 1, "output_tokens": 1},
                "answers": {"billing": {"type": "noul", "noul": 0.97},
                            "tone": {"type": "choice", "choice": "calm", "confidence": 0.9, "probabilities": {"angry": 0.1, "calm": 0.9}}}}


def over(server, script, name: str | None = "test-agent"):
    """Run `script(call, client)` as an MCP client connected to `server` (a server object, or
    the parameters of a process to start). `call(tool, **arguments)` is the tool's object."""
    async def session():
        info = Implementation(name=name, version="1.0") if name else None
        async with McpClient(server, client_info=info) as client:
            async def call(tool: str, **arguments):
                result = await client.call_tool(tool, arguments)
                assert not result.is_error, result.content
                return result_object(result)
            return await script(call, client)
    return anyio.run(session)


@pytest.fixture(autouse=True)
def nobody(monkeypatch):
    for name in ("AIP_DECISION_MODEL", "AIP_DECISION_MODEL_KEY", "AIP_AGENT", "AIP_SESSION"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def store():
    server = Served(token_names={"secret": "zach"})
    yield server
    server.close()


# ------------------------------------------------------------------------ the tools


def test_the_server_offers_six_tools_and_says_how_to_use_them():
    async def script(call, client):
        return (await client.list_tools()).tools, client.server_info, client.instructions
    tools, info, instructions = over(build(aip.Client()), script)
    assert [t.name for t in tools] == list(TOOLS) == ["search", "describe", "compile", "run", "resume", "pull"]
    assert all(t.description and len(t.description) > 80 for t in tools), "the description is what the caller's model reads"
    by_name = {t.name: t.input_schema for t in tools}
    assert by_name["run"]["required"] == ["target"] and set(by_name["run"]["properties"]) == {"target", "inputs", "session", "batch", "workdir"}
    assert by_name["resume"]["required"] == ["run_id"] and set(by_name["resume"]["properties"]) == {"run_id", "answers"}
    assert (info.name, info.version) == ("aip", aip.__version__)
    assert instructions == INSTRUCTIONS and "`resume`" in instructions


def test_a_run_pauses_is_answered_and_ends_under_the_clients_name(tmp_path):
    async def script(call, client):
        described = await call("describe", target=str(AGENT))
        assert described["name"] == "billing_support_agent" and described["inputs"] == {"message": "string"}
        assert described["example_inputs"] == {"message": "<string>"}

        paused = await call("run", target=str(AGENT), inputs={"message": CALM}, workdir=str(tmp_path))
        assert (paused["paused"], paused["step"]) == ("task", "triage") and "recorded" not in paused
        [task] = paused["tasks"]
        assert task["answer_with"] == {"billing": "true_or_false", "tone": "choice"} and task["labels"] == {"tone": ["angry", "calm"]}

        # an answer that does not fit is an ordinary result naming what is wrong, and the pause stands
        refused = await call("resume", run_id=paused["run_id"], answers={"billing": True, "tone": "calm", "mood": "fine"})
        assert (refused["error"], refused["invalid"], refused["resumable"]) == ("invalid_output", ["mood"], True)

        reply = await call("resume", run_id=paused["run_id"], answers={"billing": True, "tone": "calm"})
        assert (reply["paused"], reply["step"]) == ("task", "reply")
        done = await call("resume", run_id=paused["run_id"], answers={"reply": REPLY})
        assert done == {"done": True, "result": {"message": CALM, "reply": REPLY}, "run_id": paused["run_id"], "run_file": paused["run_file"]}
        return paused["run_id"]

    client = aip.Client()
    record = client.run_record(over(build(client), script))
    assert [e["step"] for e in record.history] == ["start", "triage", "by_tone", "reply", "end"]
    assert record.identity["agent"] == "test-agent", "the MCP client's name is who ran it"
    assert record.identity["session"].startswith("mcp-"), "with no session given, one per server"
    assert record.history[1]["answered_by"] == {"agent": "test-agent", "session": record.identity["session"]}


def test_who_ran_it_the_flag_the_client_the_environment_then_mcp(tmp_path, monkeypatch):
    def run_as(name, given=None, **options):
        async def script(call, client):
            arguments = {"target": str(AGENT), "inputs": {"message": CALM}, "workdir": str(tmp_path)}
            return (await call("run", **arguments, **({"session": given} if given else {})))["run_id"]
        client = aip.Client()
        return client.run_record(over(build(client, **options), script, name=name)).identity

    # S3: the client's own version rides beside its name as `agent_version`; another name (`--agent`) has no version of ours to give
    assert run_as("langgraph", "s-9", agent="support-bot") == {"agent": "support-bot", "session": "s-9", "user": None}
    assert run_as("langgraph", "s-9", session="s-1")["session"] == "s-9", "the call's session over the server's"
    assert run_as("langgraph", session="s-1") == {"agent": "langgraph", "session": "s-1", "user": None, "agent_version": "1.0"}
    assert run_as(None)["agent"] == "mcp", "a client that does not say who it is"
    monkeypatch.setenv("AIP_AGENT", "from-env")
    monkeypatch.setenv("AIP_SESSION", "env-session")
    assert run_as("langgraph") == {"agent": "langgraph", "session": "env-session", "user": None, "agent_version": "1.0"}, \
        "the client's own name over AIP_AGENT"


def test_what_cannot_be_done_is_an_error_object_not_an_mcp_error(tmp_path):
    broken = shutil.copytree(AGENT, tmp_path / "broken")
    (broken / "procedure.aip").write_text((AGENT / "procedure.aip").read_text(encoding="utf-8").replace("Next_Step by_tone", "Next_Step nowhere"),
                                          encoding="utf-8")

    async def script(call, client):
        missing = await call("run", target=str(tmp_path / "no-such-folder"), inputs={})
        assert (missing["error"], missing["kind"], missing["step"], missing["resumable"], missing["run_id"]) == \
            ("invalid_input", "not_found", None, False, None)
        inputs = await call("run", target=str(AGENT), inputs={"note": "x"})
        assert (inputs["error"], inputs["missing"], inputs["resumable"]) == ("invalid_input", ["message"], False)
        nothing = await call("resume", run_id="0123456789abcdef")
        assert nothing["error"] == "invalid_input" and "no run" in nothing["message"]
        search = await call("search", query="refund")
        assert (search["error"], search["kind"]) == ("invalid_input", "no_server") and "aip config server local" in search["message"]
        assert (await call("pull", ref="billing_support"))["kind"] == "no_server"

        checked = await call("compile", folder=str(broken))
        assert checked["ok"] is False and checked["bundle_id"] is None
        assert [d["code"] for d in checked["diagnostics"] if d["severity"] == "error"] == ["unknown_step"]
        refused = await call("run", target=str(broken), inputs={"message": CALM})
        assert (refused["error"], refused["kind"]) == ("invalid_input", "compile_error")
        assert [d["code"] for d in refused["diagnostics"] if d["severity"] == "error"] == ["unknown_step"]

        written = await call("compile", folder=str(AGENT), output=str(tmp_path / "agent.rl"))
        assert written["ok"] and written["name"] == "billing_support_agent" and written["output"] == str(tmp_path / "agent.rl")
        assert (await call("describe", target=written["output"]))["bundle_id"] == written["bundle_id"]

        # S3: an output that is not an .rl is refused, and a folder that is not there is a plain not_found
        other = await call("compile", folder=str(AGENT), output=str(tmp_path / "agent.bundle"))
        assert other["error"] == "invalid_input" and ".rl" in other["message"] and not (tmp_path / "agent.bundle").exists()
        nowhere = await call("compile", folder=str(tmp_path / "no-such-folder"))
        assert (nowhere["error"], nowhere["kind"]) == ("invalid_input", "not_found") and "Errno" not in nowhere["message"]

        # S3: arguments that do not fit a tool are an ordinary result in plain words, not an MCP error with the validator's text
        no_query = await call("search")
        assert (no_query["error"], no_query["kind"], no_query["resumable"]) == ("invalid_input", "invalid_arguments", False)
        assert no_query["message"] == "search was not called: `query` is missing. Its arguments are `query`, `limit`."
        paused = await call("run", target=str(AGENT), inputs={"message": CALM})
        text = await call("resume", run_id=paused["run_id"], answers="just a string")
        assert text["kind"] == "invalid_arguments" and "pydantic" not in text["message"]
        assert "`answers` is an object or a list, not a string" in text["message"]
        assert (await call("resume", run_id=paused["run_id"], answers={"billing": True, "tone": "calm"}))["step"] == "reply", \
            "the pause stood"

    over(build(aip.Client()), script)


def test_progress_names_the_loop_and_the_pass_and_ends_with_where_the_run_stopped(tmp_path):
    """S3: two tasks at one step are two passes, and the notification says which; the last
    notification of a call says the run paused, finished or failed."""
    from aip.mcp import step_message, stop_message

    assert step_message({"kind": "Start", "step": "start", "pass": None, "passes": []}) == "Start start"
    assert step_message({"kind": "Execute", "step": "check", "pass": 2,
                         "passes": [{"loop": "each_ticket", "pass": 3}, {"loop": "revise", "pass": 2}]}) == \
        "Execute check: revise pass 2 of each_ticket pass 3"
    assert stop_message({"done": True, "result": {}}) == "done"
    assert stop_message({"error": "no_decision_model", "step": "triage"}) == "error no_decision_model at triage"
    lines = []

    async def script(call, mcp):
        async def progress(n, total, message):
            lines.append(message)
        arguments = {"target": str(example_dir("ticket-triage")), "workdir": str(tmp_path),
                     "inputs": {"tickets": ["Where is my invoice?", "How do I change plan?"], "policy": "Refunds take 5 days."}}
        stop = result_object(await mcp.call_tool("run", arguments, progress_callback=progress))
        return stop

    stop = over(build(aip.Client(decision_client=TicketModel())), script)
    assert (stop["paused"], stop["step"], len(stop["tasks"])) == ("task", "draft", 2)
    assert lines == ["Start start", "Decide classify: each_ticket pass 0", "Route by_tone: each_ticket pass 0",
                     "Decide classify: each_ticket pass 1", "Route by_tone: each_ticket pass 1", "paused at draft: 2 task(s) to answer"]
    assert "warning" not in stop


def test_a_decide_ahead_and_no_model_is_a_warning_before_the_run_and_in_describe(tmp_path):
    """S3: `describe` and `run` say up front that the procedure asks a decision model and none
    is configured; it is a warning, since the run may never reach the step."""
    async def script(call, mcp):
        described = await call("describe", target=str(example_dir("billing-support")))
        assert "no decision model is configured, and this procedure asks one at triage" in described["warning"]
        assert described["result_on_some_paths"] == ["ticket_id", "queue", "reply"], "what a result has depends on the route taken"
        assert "warning" not in await call("describe", target=str(AGENT))
        failed = await call("run", target=str(example_dir("billing-support")), inputs={"message": CALM}, workdir=str(tmp_path))
        assert (failed["error"], failed["step"], failed["warning"]) == ("no_decision_model", "triage", described["warning"])

    over(build(aip.Client()), script)


# ------------------------------------------------------------------------ the catalog, and the record


def test_dynamic_policy_by_name_end_to_end_recorded_under_the_client(store, tmp_path):
    """The milestone's proof, in process: find the procedure, pull it, run it, answer its
    pause, and find the run on the server by the MCP client's name."""
    model = Model(0.9)
    client = aip.Client(Server("http://testserver", token="secret", session=store), decision_client=model)
    client.publish(POLICY)
    lines = []

    async def script(call, mcp):
        [hit] = (await call("search", query="policies the requester supplies"))["hits"]
        assert (hit["name"], hit["revision"]) == ("dynamic_policy", "1")
        described = await call("describe", target="dynamic_policy")
        assert described["inputs"] == {"task": "string", "policies": "list"} and described["revision"] == "1"
        [pulled] = (await call("pull", ref="dynamic_policy"))["pulled"]
        assert (pulled["name"], pulled["revision"], pulled["bundle_id"]) == ("dynamic_policy", "1", described["bundle_id"])
        assert [p["name"] for p in (await call("pull"))["pulled"]] == ["dynamic_policy"]

        async def progress(n, total, message):
            lines.append(message)
        result = await mcp.call_tool("run", {"target": "dynamic_policy", "inputs": TASK, "session": "smoke-1", "workdir": str(tmp_path)},
                                     progress_callback=progress)
        paused = result_object(result)
        assert (paused["paused"], paused["step"], paused["recorded"]) == ("task", "draft", True)
        done = await call("resume", run_id=paused["run_id"], answers={"work": "Welcome aboard!"})
        assert done["done"] is True and done["recorded"] is True and done["result"]["work"] == "Welcome aboard!"
        assert [v["follows"]["value"] for v in done["result"]["verdicts"]] == [True, True]
        return done["run_id"]

    run_id = over(build(client), script, name="mcp-smoke")
    assert lines == ["Start start", "paused at draft: 1 task(s) to answer"], \
        "each step run is a progress notification for a client that asks, and the last says where the run stopped (S3)"
    assert len(model.calls) == 1, "the two policies went to the model as one batch"
    [row] = client.runs(agent="mcp-smoke")
    assert (row.run_id, row.name, row.status, row.draft) == (run_id, "dynamic_policy", "done", False)
    assert row.identity == {"agent": "mcp-smoke", "session": "smoke-1", "user": "zach", "agent_version": "1.0"}
    assert client.runs(agent="mcp-smoke@1.0") == [], "the name alone is the filter"
    assert client.runs(agent="someone-else") == []
    record = store.runs[run_id]
    assert [e["step"] for e in record["history"]] == ["start", "draft", "check", "check", "review", "summarize_check", "revise", "end"]


# ------------------------------------------------------------------------ the command


def test_aip_mcp_is_a_command():
    assert "mcp" in COMMANDS
    out = io.StringIO()
    with redirect_stdout(out), redirect_stderr(io.StringIO()), pytest.raises(SystemExit) as stop:
        main(["mcp", "--help"])
    assert stop.value.code == 0 and "usage: aip mcp" in out.getvalue() and "--http PORT" in out.getvalue()


def test_over_stdio_the_real_process_runs_a_procedure(tmp_path):
    """`aip mcp` as an MCP client starts it: a process speaking the protocol on its stdout and
    nothing else, here with no server configured."""
    env = {**os.environ, "AIP_SERVER": "none", "PYTHONUTF8": "1"}
    process = StdioServerParameters(command=sys.executable, args=["-m", "aip.client.cli", "mcp"], env=env, cwd=str(tmp_path))

    async def script(call, client):
        assert [t.name for t in (await client.list_tools()).tools] == list(TOOLS)
        paused = await call("run", target=str(AGENT), inputs={"message": CALM})
        reply = await call("resume", run_id=paused["run_id"], answers={"billing": True, "tone": "calm"})
        assert reply["step"] == "reply"
        return await call("resume", run_id=paused["run_id"], answers={"reply": REPLY})

    done = over(process, script, name="stdio-agent")
    assert done["done"] is True and done["result"]["reply"] == REPLY and "recorded" not in done
    record = aip.Client().run_record(done["run_id"])                      # the process wrote the run file in this test's AIP_HOME
    assert record.status == "done" and record.identity["agent"] == "stdio-agent"
    assert RunFile.load(run_path(done["run_id"])).workdir == str(tmp_path.resolve()), "scripts run where the server was started, unless a call says otherwise"


def test_over_http_the_same_tools_at_a_url(tmp_path):
    """`aip mcp --http PORT` serves streamable HTTP at `/mcp`; `--agent` names who runs."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "AIP_SERVER": "none", "PYTHONUTF8": "1"}
    process = subprocess.Popen([sys.executable, "-m", "aip.client.cli", "mcp", "--http", str(port), "--agent", "hosted", "--session", "h-1"],
                               env=env, cwd=tmp_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                assert process.poll() is None and time.monotonic() < deadline, process.stderr.read().decode()
                time.sleep(0.1)

        async def script(call, client):
            assert [t.name for t in (await client.list_tools()).tools] == list(TOOLS)
            return await call("run", target=str(AGENT), inputs={"message": CALM})

        paused = over(f"http://127.0.0.1:{port}/mcp", script, name="http-agent")
    finally:
        process.terminate()
        process.wait(timeout=10)
    assert (paused["paused"], paused["step"]) == ("task", "triage")
    assert aip.Client().run_record(paused["run_id"]).identity == {"agent": "hosted", "session": "h-1", "user": None}
    assert RunFile.load(run_path(paused["run_id"])).workdir == str(tmp_path.resolve()), "scripts run where the server was started, unless a call says otherwise"
