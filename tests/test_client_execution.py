"""The client executes scripts (B3).

A served run stops at each execution step and the server replies with the step to perform; the
client fetches the revision's `scripts/` and `assets/` into `~/.aip/cache/<name>@<revision>/`
(verified against the manifest, never `SKILL.md`), runs the script from the cached folder with
the run's working directory as `AIP_WORKDIR`, and posts the result, which the server checks and
records. Server and client here have separate temp roots, as on two machines: the escalate
script's file lands on the client, and the server never runs a script at all.
"""

import io
import json
import shutil
import socket
from pathlib import Path
from unittest import mock

import pytest
from aip_spec import example_dir
from fastapi.testclient import TestClient

from aip.client.backend import HttpBackend, LocalBackend
from aip.client.executor import cache_dir
from aip.client.runner import RunFile, Runner, backend_for
from aip.client.server import Server
from aip.model import Execution
from aip.server.app import create_app, upload_of
from aip.server.backends.filesystem import FilesystemBackend

EXAMPLE = example_dir("billing-support")
ANGRY = "This is the THIRD time you have double charged me. Fix it today or I cancel."

# The example's escalate script, plus a file written to the run's working directory saying
# where the script ran from.
WRITES_A_FILE = '''import json, os, sys
from pathlib import Path

payload = json.load(sys.stdin)
config = json.loads(payload["assets"]["config"])
ticket_id = abs(hash(payload["state"]["message"])) % 100_000
Path(os.environ["AIP_WORKDIR"], "ticket.txt").write_text(json.dumps({"ticket_id": ticket_id, "cwd": os.getcwd()}))
json.dump({"ticket_id": ticket_id, "queue": config["queue"]}, sys.stdout)
'''


@pytest.fixture(autouse=True)
def client_home(tmp_path, monkeypatch):
    """The client machine: its own home (run files, cache) and working directory."""
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    home = tmp_path / "client" / "home"
    monkeypatch.setenv("AIP_HOME", str(home))
    (tmp_path / "client" / "work").mkdir(parents=True)
    return home


@pytest.fixture
def workdir(tmp_path) -> Path:
    return tmp_path / "client" / "work"


@pytest.fixture
def server_root(tmp_path) -> Path:
    return tmp_path / "server"


def variant(tmp_path: Path, script: str, name: str = "billing-support", requires: str | None = None) -> Path:
    """A copy of the example with its escalate script replaced (and its `requires` block, if given)."""
    folder = tmp_path / "skills" / name
    shutil.copytree(EXAMPLE, folder)
    md = folder / "SKILL.md"
    text = md.read_text().replace("name: billing-support", f"name: {name}")
    if requires is not None:
        start = text.index("requires:")
        end = text.index("\n\n", start)
        text = text[:start] + requires + text[end:]
    md.write_text(text)
    (folder / "scripts" / "escalate.py").write_text(script)
    return folder


def serve(root: Path, *folders: Path) -> TestClient:
    api = TestClient(create_app(FilesystemBackend(root)), raise_server_exceptions=False)
    for folder in folders:
        r = api.post("/catalog", json=upload_of(folder))
        assert r.status_code == 201, r.text
    return api


def angry_run(api: TestClient, workdir: Path, name: str = "billing-support"):
    """Open the angry branch and answer its triage; the outcome after the answer, and the output."""
    out = io.StringIO()
    backend = HttpBackend(Server("http://testserver", session=api), name=name, workdir=workdir)
    first = Runner(backend, out=out, progress=True).start({"message": ANGRY})
    assert first.payload["paused"] == "decision", out.getvalue()
    run = RunFile.load(first.run_file)
    outcome = Runner(backend, run_file=first.run_file, out=out, progress=True, run_id=run.run_id).resume(
        run, {"billing": True, "tone": "angry"})
    return outcome, out.getvalue()


def never_on_the_server(*_args, **_kwargs):
    raise AssertionError("the server ran a script")


def test_a_served_script_runs_on_the_client(tmp_path, server_root, workdir, client_home):
    api = serve(server_root, variant(tmp_path, WRITES_A_FILE))
    revision = api.get("/catalog/billing-support").json()["revision"]

    with mock.patch.object(Execution, "_invoke", never_on_the_server):
        outcome, out = angry_run(api, workdir)
    assert outcome.code == 0 and outcome.payload == {"message": ANGRY}, out

    # the file is on the client, written from the cached script folder
    ticket = json.loads((workdir / "ticket.txt").read_text())
    cached = cache_dir("billing-support", revision)
    assert cached.parent == client_home / "cache"
    assert Path(ticket["cwd"]).resolve() == (cached / "scripts").resolve()
    assert not list(server_root.rglob("ticket.txt"))

    # the cache holds scripts and assets only
    files = sorted(p.relative_to(cached).as_posix() for p in cached.rglob("*")
                   if p.is_file() and "__pycache__" not in p.parts)
    assert files == ["assets/config.json", "assets/policy.md", "assets/reply.md", "scripts/escalate.py"]

    # the server's record holds the result
    lines = [json.loads(line) for line in out.splitlines()]
    run_id = lines[-1]["run_id"]
    record = api.get(f"/runs/{run_id}").json()
    assert record["status"] == "done"
    escalate = next(e for e in record["history"] if e["step"] == "escalate")
    assert escalate["result"] == {"ticket_id": ticket["ticket_id"], "queue": "tier2"}
    assert escalate["input"] == {"message": ANGRY, "tone": "angry"} and isinstance(escalate["seconds"], float)
    assert escalate["host"] == socket.gethostname()                       # which machine ran it
    assert [line["step"] for line in lines if line.get("event") == "step"] == ["triage", "by-tone", "escalate"]
    assert RunFile.load(outcome.run_file).workdir == str(workdir.resolve())


def test_a_failing_script_is_reported_and_retried(tmp_path, server_root, workdir):
    broken = "import sys\nsys.stderr.write('queue down')\nsys.exit(2)\n"
    api = serve(server_root, variant(tmp_path, broken))

    with mock.patch.object(Execution, "_invoke", never_on_the_server):
        outcome, _ = angry_run(api, workdir)
    error = outcome.payload
    assert (error["error"], error["step"], error["exit_code"], error["stderr"], error["resumable"]) == (
        "script_failed", "escalate", 2, "queue down", True)

    rows = api.get("/governance/failing-scripts").json()
    assert [(r["name"], r["step"], r["script"], r["failed"]) for r in rows] == [
        ("billing-support", "escalate", "scripts/escalate.py", 1)]
    assert "queue down" in rows[0]["last_error"]
    assert (rows[0]["exit_code"], rows[0]["stderr"]) == (2, "queue down")    # as the client reported it

    # fix the cached script (as a user would fix their machine): resume retries on the client
    run = RunFile.load(outcome.run_file)
    record = api.get(f"/runs/{run.run_id}").json()
    assert record["status"] == "failed" and record["history"][-1]["result"]["stderr"] == "queue down"
    assert record["history"][-1]["result"]["host"] == socket.gethostname()
    out = io.StringIO()
    backend = backend_for(run, session=api)
    assert isinstance(backend, HttpBackend) and backend.workdir == workdir.resolve()
    again = Runner(backend, run_file=outcome.run_file, out=out, run_id=run.run_id).resume(run, None)
    assert again.payload["error"] == "script_failed"
    assert api.get("/governance/failing-scripts").json()[0]["failed"] == 2


def test_requires_is_checked_on_the_client_before_any_script(tmp_path, server_root, workdir):
    requires = "requires:\n  interpreter: {name: python}\n  packages: [nosuchpkg]"
    api = serve(server_root, variant(tmp_path, WRITES_A_FILE, requires=requires))
    outcome, _ = angry_run(api, workdir)
    error = outcome.payload
    assert error["error"] == "requires_unmet" and error["step"] == "escalate" and error["resumable"] is True
    assert error["missing"] == ["package nosuchpkg"] and "nosuchpkg" in error["message"]
    assert not (workdir / "ticket.txt").exists()
    record = api.get(f"/runs/{error['run_id']}").json()
    assert record["status"] == "failed" and record["history"][-1]["result"]["missing"] == ["package nosuchpkg"]


def test_the_cache_is_verified_and_refetched(tmp_path, server_root, workdir):
    api = serve(server_root, variant(tmp_path, WRITES_A_FILE))
    revision = api.get("/catalog/billing-support").json()["revision"]
    outcome, _ = angry_run(api, workdir)
    assert outcome.code == 0
    script = cache_dir("billing-support", revision) / "scripts" / "escalate.py"
    script.write_text("import sys\nsys.exit(9)\n")                          # tampered on disk
    (workdir / "ticket.txt").unlink()
    outcome, _ = angry_run(api, workdir)
    assert outcome.code == 0 and (workdir / "ticket.txt").is_file()
    assert script.read_text() == WRITES_A_FILE


def test_a_local_run_writes_to_its_recorded_workdir(tmp_path, workdir, monkeypatch):
    skill = variant(tmp_path, WRITES_A_FILE)
    monkeypatch.chdir(tmp_path)
    out = io.StringIO()
    first = Runner(LocalBackend(skill, workdir=workdir), out=out).start({"message": ANGRY})
    run = RunFile.load(first.run_file)
    assert run.workdir == str(workdir.resolve())

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)                                             # resume from anywhere
    done = Runner(backend_for(run), run_file=first.run_file, out=out, run_id=run.run_id).resume(
        run, {"billing": True, "tone": "angry"})
    assert done.code == 0, out.getvalue()
    ticket = json.loads((workdir / "ticket.txt").read_text())
    assert Path(ticket["cwd"]).resolve() == (skill / "scripts").resolve()
    assert not (elsewhere / "ticket.txt").exists()


def test_a_tampered_download_stops_the_run_at_the_step(tmp_path, server_root, workdir):
    api = serve(server_root, variant(tmp_path, WRITES_A_FILE))
    with mock.patch.object(Server, "file", return_value=b"import sys\nsys.exit(9)\n"):
        outcome, _ = angry_run(api, workdir)
    error = outcome.payload
    assert error["error"] == "server" and "hash_mismatch" in error["message"] and error["resumable"] is True
    assert not (workdir / "ticket.txt").exists()

    run = RunFile.load(outcome.run_file)                                     # the run waits at the step
    assert (run.pause["kind"], run.pause["step"]) == ("execute", "escalate")
    done = Runner(backend_for(run, session=api), run_file=outcome.run_file, out=io.StringIO(),
                  run_id=run.run_id).resume(run, None)
    assert done.code == 0 and (workdir / "ticket.txt").is_file()
