"""`make_procedure` (plan aip-dev#1, K1): the procedure that writes procedures, an example
under `examples/language/make_procedure/` and the one bundle that ships inside the package.

The shipped `.rl` is the folder's bundle; a server's fresh store has it as `make_procedure@1`
and `aip upgrade` offers it to a server that does not; and a run of it hands the agent the
language, compiles what the agent wrote with a real script, and loops on the compiler's
diagnostics until the folder compiles. Everything opens a Relate store, so it skips with the
install hint where Relate is missing."""

from __future__ import annotations

from pathlib import Path

import pytest

import aip
from aip.client.server import Server
from aip.compiler import compile_folder, example_dir, read_bundle, relate
from aip.server.builtins import builtin_files
from served import Served

pytestmark = pytest.mark.skipif(not relate.available(), reason=relate.INSTALL_HINT)

FOLDER = example_dir("make_procedure")
INPUTS = {"name": "echo", "description": "Hand back the one string it is given.", "materials": ""}
BROKEN = 'procedure echo "Hand back a string."\nstart "The string." {\n  a: string\n  next nowhere\n}\nend "The string." {\n  read a\n}\n'
WORKING = BROKEN.replace("nowhere", "end")
CANONICAL = 'Procedure echo\n  "Hand back a string."\n\nStart "The string." {\n  a: string\n  Next_Step end\n}\n\nEnd "The string." {\n  Read a\n}\n'
REBUILD = "uv run aip compile examples/language/make_procedure -o src/aip/server/bundles/make_procedure.rl"


def write(folder: Path, source: str) -> Path:
    folder.mkdir(exist_ok=True)
    (folder / "procedure.aip").write_text(source, encoding="utf-8")
    return folder


def steps(client: aip.Client, run_id: str) -> list[str]:
    return [entry["step"] for entry in client.run_record(run_id).history]


def test_the_shipped_bundle_is_the_example_folder():
    [shipped] = builtin_files()
    assert shipped.name == "make_procedure.rl"
    folder, diagnostics = compile_folder(FOLDER)
    assert folder is not None and [str(d) for d in diagnostics] == [], "the example compiles with nothing to say"
    bundle = read_bundle(shipped)                             # verified as it is read: the graph is the one the source compiles to
    assert (bundle.name, bundle.id) == ("make_procedure", folder.id), \
        f"src/aip/server/bundles/make_procedure.rl is not what examples/language/make_procedure compiles to; run: {REBUILD}"


def test_a_fresh_store_has_it_and_upgrade_offers_it_to_one_that_does_not():
    fresh = Served(builtins=True)
    client = aip.Client(Server("http://testserver", session=fresh), agent="tests")
    [entry] = client.list()
    assert (entry.name, entry.resolves, entry.description.startswith("Build an AIP procedure from a description")) == ("make_procedure", "1", True)
    [again] = client.upgrade()
    assert (again.name, again.revision, again.existed) == ("make_procedure", "1", True), "the server had it: nothing changes"
    assert client.search("write a new procedure from a description")[0].name == "make_procedure"
    fresh.close()

    older = Served()                                          # a server whose package ships nothing
    client = aip.Client(Server("http://testserver", session=older), agent="tests")
    assert client.list() == []
    [published] = client.upgrade()
    assert (published.name, published.revision, published.existed) == ("make_procedure", "1", False)
    assert [(e.name, e.resolves) for e in client.list()] == [("make_procedure", "1")]
    older.close()
    with pytest.raises(aip.NoServer):
        aip.Client(agent="tests").upgrade()


def test_it_describes_itself_and_needs_no_decision_model():
    described = aip.Client(agent="tests").describe(FOLDER)
    assert described.example_inputs == {"name": "<string>", "description": "<string>", "materials": "<string>"}
    kinds = {step["kind"] for step in described.data["steps"]}
    assert "Decide" not in kinds and {"Task_Agent", "Execute"} <= kinds


def test_a_folder_that_does_not_compile_is_fixed_until_it_does(tmp_path):
    client = aip.Client(agent="tests")
    paused = client.run(FOLDER, INPUTS, workdir=tmp_path)
    assert isinstance(paused, aip.Paused) and paused.step == "write" and paused.task.answer_with == {"path": "string"}
    prompt = paused.task.prompt
    assert "a procedure called `echo`" in prompt and "Hand back the one string it is given." in prompt
    assert "# The AIP procedure language on one page" in prompt and "Loop revise Until passed, At_Most 4, Else_Fail" in prompt
    for unrendered in ("{name}", "{description}", "{materials}", "{assets[language]}"):
        assert unrendered not in prompt
    assert "`{assets[policy]}`" in prompt, "the page's own braces are left as written"

    write(tmp_path / "echo", BROKEN)
    paused = client.resume(paused, {"path": "echo"})          # relative: taken from the run's working directory
    assert isinstance(paused, aip.Paused) and paused.step == "fix"
    task = paused.task
    assert (task.pass_, task.pass_of, task.last_pass) == (0, 6, False)
    assert task.state == {"path": "echo", "diagnostics": [
        "procedure.aip:4:3: error unknown_step: Next_Step nowhere: no step or loop is called nowhere (step start)"]}
    assert "unknown_step" in task.prompt and "# The AIP procedure language on one page" in task.prompt

    paused = client.resume(paused, {"path": "echo"})          # answered without fixing anything: the same errors come back
    assert isinstance(paused, aip.Paused) and paused.step == "fix" and paused.task.pass_ == 1

    folder = write(tmp_path / "echo", WORKING)
    done = client.resume(paused, {"path": str(folder)})
    assert isinstance(done, aip.Done)
    compiled, _ = compile_folder(folder)
    assert done.result == {"path": str(folder), "bundle_id": compiled.id, "diagnostics": []}
    assert (folder / "procedure.aip").read_text() == WORKING, "S3: the compile step checks and reports; the author's file is left as written"
    assert CANONICAL != WORKING and compile_folder(write(tmp_path / "canonical", CANONICAL))[0].id != compiled.id
    assert steps(client, done.run_id) == ["start", "write", "compile", "fix", "compile", "fix", "compile", "revise", "end"]


def test_a_folder_that_compiles_first_time_is_never_sent_to_fix(tmp_path):
    client = aip.Client(agent="tests")
    paused = client.run(FOLDER, INPUTS, workdir=tmp_path)
    folder = write(tmp_path / "echo", CANONICAL)
    done = client.resume(paused, {"path": str(folder)})
    assert isinstance(done, aip.Done) and done.result["diagnostics"] == []
    assert steps(client, done.run_id) == ["start", "write", "compile", "revise", "end"]
    assert (folder / "procedure.aip").read_text() == CANONICAL


def test_a_path_with_no_procedure_is_a_diagnostic_and_a_sixth_failed_pass_ends_the_run(tmp_path):
    # L7: compile is inside the loop, a fix is checked by the pass after it, and At_Most 6 is five checked fixes
    client = aip.Client(agent="tests")
    paused = client.run(FOLDER, INPUTS, workdir=tmp_path)
    paused = client.resume(paused, {"path": str(tmp_path / "nothing-here")})
    assert paused.step == "fix" and len(paused.task.state["diagnostics"]) == 1
    assert "error missing_file: no procedure.aip here" in paused.task.state["diagnostics"][0]
    for attempt in range(5):
        assert (paused.task.pass_, paused.task.last_pass) == (attempt, False)
        paused = client.resume(paused, {"path": str(tmp_path / "nothing-here")})
    assert (paused.task.pass_, paused.task.last_pass) == (5, True), "the sixth pass's compile failed too: no check follows this fix"
    with pytest.raises(aip.RunError) as failed:
        client.resume(paused, {"path": str(tmp_path / "nothing-here")})
    assert (failed.value.kind, failed.value.error["loop"], failed.value.error["count"], failed.value.resumable) == ("loop_cap", "revise", 6, False)


def test_it_runs_by_name_from_a_server_that_just_started(tmp_path):
    server = Served(builtins=True)
    client = aip.Client(Server("http://testserver", session=server), agent="tests")
    paused = client.run("make_procedure", INPUTS, workdir=tmp_path)
    assert isinstance(paused, aip.Paused) and (paused.step, paused.recorded) == ("write", True)
    done = client.resume(paused, {"path": str(write(tmp_path / "echo", WORKING))})
    assert isinstance(done, aip.Done) and done.recorded is True
    [row] = client.runs(name="make_procedure")
    assert (row.status, row.revision, row.draft) == ("done", "1", False)
    server.close()
