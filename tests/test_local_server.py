"""The local server, started on demand (plan aip#29, S2, open item 3).

With `aip config server local` nothing is started by hand: the first command that needs the
server starts `aip server --local` as a process of its own, later commands reuse it, it stops
when idle, and the next command starts it again over the same store. These tests run the real
process on a port of their own with its store in a temp directory, through the real `aip`
command: a folder's run is recorded as a draft and `aip runs --agent cli` lists it, which is the
milestone's proof, and `aip export runs` writes a file the engine opens. They need Relate and
the server extra."""

from __future__ import annotations

import http.server
import io
import json
import socket
import threading
import time
from contextlib import redirect_stderr, redirect_stdout

import pytest

import aip
from aip.client import local
from aip.client.cli import main
from aip.client.server import ServerError
from aip.compiler import example_dir, relate

pytest.importorskip("uvicorn")
pytestmark = pytest.mark.skipif(not relate.available(), reason=relate.INSTALL_HINT)

AGENT = example_dir("billing-support-agent")
CALM = "I was charged twice for March. Could you check?"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def call(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


@pytest.fixture
def machine(tmp_path, monkeypatch):
    """A machine of its own: a free port and an empty data directory for the local server,
    which is stopped afterwards if a test left it running."""
    monkeypatch.setenv("AIP_LOCAL_PORT", str(free_port()))
    monkeypatch.setenv("AIP_LOCAL_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("AIP_LOCAL_IDLE", "600")
    monkeypatch.chdir(tmp_path)
    yield tmp_path
    try:
        local.stop()
    except ServerError:
        pass


def test_a_run_starts_the_local_server_and_is_recorded_as_a_draft(machine):
    assert call("config", "server", "local")[0] == 0
    assert local.health() is None, "nothing is running, and nothing was started to configure it"

    code, out, err = call("run", str(AGENT), "--inputs", json.dumps({"message": CALM}))
    paused = json.loads(out)
    assert (code, err) == (0, ""), err
    assert (paused["paused"], paused["step"], paused["recorded"]) == ("task", "triage", True)
    about = local.health()
    assert about is not None and (about["local"], about["backend"]) == (True, "relate") and isinstance(about["pid"], int)
    assert (machine / "data" / "store.rl").is_file(), "the store is under the data directory"

    code, out, _ = call("runs", "--agent", "cli")
    assert code == 0 and paused["run_id"] in out and "billing_support_agent (draft)" in out
    assert call("runs", "--agent", "someone-else")[1] == "no runs\n"
    assert paused["run_id"] in call("runs", "--draft")[1] and call("runs", "--published")[1] == "no runs\n"

    code, out, err = call("resume", paused["run_id"], "--answers", json.dumps({"billing": True, "tone": "angry"}))
    done = json.loads(out)
    assert (code, err, done["done"], done["recorded"]) == (0, "", True, True)
    assert local.health()["pid"] == about["pid"], "the same server answered: it is reused, not started again"
    record = json.loads(call("runs", paused["run_id"], "--json")[1])
    assert (record["status"], record["draft"], record["server"], record["recorded"]) == ("done", True, local.url(), True)

    def routes(out: str) -> list:                    # the shipped assist has an agent's route too (its next_move, plan R8)
        return [r for r in json.loads(out) if r["name"] != "assist"]

    code, out, _ = call("audit", "agent-routes")
    assert code == 0 and routes(out) == [], "a draft is not a published revision; nothing is published"
    code, out, _ = call("publish", str(AGENT))
    assert code == 0 and out.startswith("billing_support_agent@1")
    [route] = routes(call("audit", "agent-routes")[1])
    assert (route["route"], route["reads"], route["runs"]) == ("by_tone", "tone", 1)

    code, out, err = call("export", "runs", "billing_support_agent", "--since", "2026-01-01", "-o", "audit.rl")
    assert (code, out) == (0, "wrote 1 run(s) of 1 procedure(s) to audit.rl\n"), err
    with relate.open(machine / "audit.rl") as conn:
        assert [dict(r) for r in conn.execute("MATCH (r:Run) RETURN count(r) AS runs")] == [{"runs": 1}]
        assert [dict(r) for r in conn.execute("MATCH (:Run)-[:OF]->(:Bundle)-[:HOLDS]->(p:Procedure) RETURN p.name AS name")] == [
            {"name": "billing_support_agent"}]

    code, out, _ = call("server", "--local", "--stop")
    assert code == 0 and out.startswith(f"stopped the local server (pid {about['pid']})") and local.health() is None
    assert call("server", "--local", "--stop")[1].startswith("no local server is running")
    code, out, _ = call("runs", "--agent", "cli")                            # the next command starts it again, over the same store
    assert code == 0 and paused["run_id"] in out and local.health()["pid"] != about["pid"]


def test_the_local_server_stops_when_idle_and_the_next_call_starts_it_again(machine, monkeypatch):
    monkeypatch.setenv("AIP_LOCAL_IDLE", "1")
    client = aip.Client("local", agent="tests")
    shipped = [(e.name, e.resolves) for e in client.list()]
    assert shipped == [("assist", "1"), ("build_procedure", "1"), ("edit_procedure", "1"), ("make_procedure", "1")] and client.server.url == local.url(), "a fresh store holds what the package ships"
    first = local.health()["pid"]
    deadline = time.monotonic() + 15
    while local.health() is not None and time.monotonic() < deadline:
        time.sleep(1.5)                                                      # asking is a request too: ask less often than it waits
    assert local.health() is None, "no request for a second, and it stopped by itself"
    assert "no request for 1s; stopping" in local.log_path().read_text()
    assert [(e.name, e.resolves) for e in client.list()] == shipped and local.health()["pid"] != first, "offered once: still @1"


def test_a_port_something_else_holds_does_not_stop_the_run(machine):
    class NotAip(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(404)
            self.end_headers()

        def log_message(self, *args):
            pass

    other = http.server.HTTPServer(("127.0.0.1", local.port()), NotAip)
    threading.Thread(target=other.serve_forever, daemon=True).start()
    try:
        with pytest.raises(ServerError) as taken:
            local.ensure()
        assert "not an aip 0.9 server" in str(taken.value) and "AIP_LOCAL_PORT" in str(taken.value)
        assert call("config", "server", "local")[0] == 0
        code, out, err = call("run", str(AGENT), "--inputs", json.dumps({"message": CALM}))
        paused = json.loads(out)
        assert (code, paused["paused"], paused["recorded"]) == (0, "task", False), "the run works; it is not recorded, and says why"
        assert err.startswith("aip: not recorded: ") and "the next stop will try again" in err
    finally:
        other.shutdown()
        other.server_close()
