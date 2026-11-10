"""What bounds a script (plan aip-dev#1, A2): a trial runs none (`Client.run(..., scripts=False)`),
and one script may run `aip config --script-timeout` seconds (`AIP_SCRIPT_TIMEOUT`, 300 by default)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import aip
from aip.compiler import relate

needs_relate = pytest.mark.skipif(not relate.available(), reason=relate.INSTALL_HINT)

TOUCH = '''Procedure touch
  "Leave a mark in the working directory."
  Requires python 3.10

Start "Nothing to give." {
  Next_Step mark
}

Execute mark "Write the file MARK in the working directory." {
  Run_Script scripts/mark.py
  Produce marked: boolean
  Next_Step end
}

End "Whether it marked." {
  Read marked
}
'''
MARK = ('import json, os, sys, time\ntime.sleep(float(os.environ.get("MARK_SLEEP") or 0))\n'
        'open(os.path.join(os.environ["AIP_WORKDIR"], "MARK"), "w").write("x")\njson.dump({"marked": True}, sys.stdout)\n')


@pytest.fixture
def touch(tmp_path) -> Path:
    folder = tmp_path / "touch"
    (folder / "scripts").mkdir(parents=True)
    (folder / "procedure.aip").write_text(TOUCH)
    (folder / "scripts" / "mark.py").write_text(MARK)
    return folder


@needs_relate
def test_a_run_that_executes_no_script_stops_before_the_first(touch, tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    client = aip.Client(agent="tests")
    with pytest.raises(aip.RunError) as stopped:
        client.run(touch, {}, workdir=work, scripts=False)
    error = stopped.value.error
    assert (error["error"], error["step"], error["script"]) == ("script_not_run", "mark", "scripts/mark.py")
    assert error["message"] == "mark would run scripts/mark.py; this run executes no script"
    assert error["resumable"] is False and "run_file" not in error, "a trial is over where it stopped"
    assert not (work / "MARK").exists(), "the script did not run"
    with pytest.raises(aip.RunError) as again:
        client.resume(stopped.value.run_id)
    assert again.value.error["error"] == "not_paused" and not (work / "MARK").exists()

    done = client.run(touch, {}, workdir=work)
    assert isinstance(done, aip.Done) and (work / "MARK").exists(), "a run executes its scripts as before"


@needs_relate
def test_a_trial_is_not_recorded(touch, tmp_path):
    from served import Served
    from aip.client.server import Server

    served = Served()
    client = aip.Client(Server("http://testserver", session=served), agent="tests")
    with pytest.raises(aip.RunError) as stopped:
        client.run(touch, {}, workdir=tmp_path, scripts=False)
    assert stopped.value.error.get("recorded") is None
    assert [p for m, p in served.requests if m == "POST"] == [], "nothing was sent"


@needs_relate
def test_the_script_cap_is_named_and_the_step_can_be_tried_again(touch, tmp_path, monkeypatch):
    assert aip.settings().script_timeout == 300
    monkeypatch.setenv("MARK_SLEEP", "3")
    aip.configure(script_timeout=1)
    assert aip.settings().script_timeout == 1
    with pytest.raises(aip.RunError) as slow:
        aip.Client(agent="tests").run(touch, {}, workdir=tmp_path)
    error = slow.value.error
    assert (error["error"], error["step"], error["seconds"]) == ("timeout", "mark", 1)
    assert "the cap on one script (`aip config --script-timeout N` or AIP_SCRIPT_TIMEOUT raises it)" in error["message"]
    assert error["resumable"] is True
    monkeypatch.setenv("AIP_SCRIPT_TIMEOUT", "10")                     # the environment wins over the file
    done = aip.Client(agent="tests").resume(slow.value.run_id)
    assert isinstance(done, aip.Done) and done.result == {"marked": True}
    assert json.loads(Path(aip.settings().path).read_text())["script_timeout"] == 1
