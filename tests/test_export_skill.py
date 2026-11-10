"""`aip export <target> --skill DIR` (plan aip-dev#1, K2): a procedure as a plain Agent Skill.

The page is rendered from the graph alone, so every example is rendered and held to the Agent
Skills format (frontmatter `name` and `description` within their limits) and to the walk: every
step and loop once, numbered in control-flow order, a loop's body right after it, `End` last.
The export runs from a folder with no Relate, and from an `.rl` and a published name with it."""

from __future__ import annotations

import io
import re
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest
import yaml
from aip.compiler import example_dir, relate
from aip.compiler.bundle import compile_folder, write_bundle
from aip.compiler.skill import DESCRIPTION_LIMIT, NAME_LIMIT, render_skill, skill_name

import aip
from aip.client.cli import main
from aip.client.server import Server
from served import Served

EXAMPLES = ["billing-support", "billing-support-agent", "dynamic-policy", "fixed-policy", "make_procedure", "ticket-triage"]
HEADING = re.compile(r"^#{3,6} (\d+)\. (?:Start|End|The loop `(\w+)`|`(\w+)` \()", re.M)
needs_relate = pytest.mark.skipif(not relate.available(), reason=relate.INSTALL_HINT)


def _render(name: str) -> tuple[str, object]:
    bundle, diagnostics = compile_folder(example_dir(name))
    assert bundle is not None, diagnostics
    return render_skill(bundle.graph, bundle_id=bundle.id), bundle


def _frontmatter(text: str) -> dict:
    assert text.startswith("---\n")
    head, _, _ = text[4:].partition("\n---\n")
    return yaml.safe_load(head)


def _walk(text: str) -> list[str]:
    """The headings' step names in page order: `start`, `end`, a loop's or a step's name."""
    out = []
    for m in HEADING.finditer(text):
        whole = m.group(0)
        out.append(m.group(2) or m.group(3) or ("start" if "Start" in whole else "end"))
        assert int(m.group(1)) == len(out), whole
    return out


@pytest.mark.parametrize("name", EXAMPLES)
def test_every_example_is_an_agent_skill_naming_every_step_once(name):
    text, bundle = _render(name)
    meta = _frontmatter(text)
    assert meta["name"] == skill_name(bundle.name)
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", meta["name"]) and len(meta["name"]) <= NAME_LIMIT
    assert 0 < len(meta["description"]) <= DESCRIPTION_LIMIT and "<" not in meta["description"]
    assert meta["metadata"]["aip-bundle"] == bundle.id
    walked = _walk(text)
    names = {n.properties["name"] for n in bundle.graph.with_label("Step") + bundle.graph.with_label("Loop")}
    assert sorted(walked) == sorted(names)
    assert walked[0] == "start" and walked[-1] == "end"
    assert "no decision\nmodel is asked" in text


def test_billing_support_in_control_flow_order():
    text, _ = _render("billing-support")
    assert _walk(text) == ["start", "triage", "by_tone", "escalate", "reply", "end"]
    assert "  - First: if you are less than 0.9 sure of that value, go to step 4, `escalate`." in text
    assert "  - `calm`: go to step 5, `reply`." in text
    assert "Answer these questions yourself" in text
    assert "- Run `scripts/escalate.py` with python" in text
    assert "  - `references/help.md`: Escalation contacts and plan matrix." in text


def test_a_loop_body_follows_its_loop_and_says_where_a_pass_ends():
    text, _ = _render("ticket-triage")
    assert _walk(text) == ["start", "each_ticket", "classify", "by_tone", "escalate", "draft", "revise", "check", "fix",
                           "summarize", "end"]
    assert "do one pass of steps 3 to 9, from step 3, `classify`" in text
    assert "as the list `replies`" in text
    assert "- Then this pass of `each_ticket` is over: go back to step 2." in text
    assert "Repeat steps 8 and 9, from step 8, `check`, until `passed` is true, at most 4 passes." in text
    assert "- Now test the loop `revise`: if `passed` is true, leave the loop: this pass of `each_ticket` is over" in text
    text, _ = _render("dynamic-policy")
    assert "- Now test the loop `revise`: if `check_summary.all_hold` is true, leave the loop: go to step 8, End." in text
    assert "true when every answer in `verdicts.follows` holds, where an answer holds when it is true, and you are more than 0.7 sure" in text


def _call(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


def test_export_a_folder_writes_the_page_and_the_files(tmp_path):
    folder = example_dir("billing-support")
    code, out, err = _call("export", str(folder), "--skill", str(tmp_path / "billing-support"))
    assert code == 0, err
    assert out.startswith("wrote the skill billing-support from billing_support") and "note:" not in out
    skill = tmp_path / "billing-support"
    assert (skill / "SKILL.md").read_text(encoding="utf-8") == _render("billing-support")[0]
    for f in ("assets/config.json", "assets/policy.md", "assets/reply.md", "references/help.md", "scripts/escalate.py"):
        assert (skill / f).read_bytes() == (folder / f).read_bytes()
    assert not (skill / "procedure.aip").exists()
    code, _, err = _call("export", str(folder), "--skill", str(skill))
    assert code == 1 and "not empty" in err
    code, out, _ = _call("export", str(folder), "--skill", str(tmp_path / "bs"))
    assert code == 0 and "note: an agent expects the folder to be named after the skill, billing-support" in out


@needs_relate
def test_export_a_bundle_and_a_published_name(tmp_path):
    bundle, _ = compile_folder(example_dir("billing-support"))
    write_bundle(bundle, tmp_path / "bs.rl")
    code, _, err = _call("export", str(tmp_path / "bs.rl"), "--skill", str(tmp_path / "from-file"))
    assert code == 0, err
    assert (tmp_path / "from-file" / "SKILL.md").read_text(encoding="utf-8") == _render("billing-support")[0]
    served = Served(token_names={"secret": "zach"})
    try:
        client = aip.Client(Server("http://testserver", token="secret", session=served), agent="tests")
        client.publish(example_dir("billing-support"))
        e = client.export_skill("billing_support@1", tmp_path / "billing-support")
    finally:
        served.close()
    assert (e.name, e.skill, e.revision, e.bundle_id) == ("billing_support", "billing-support", "1", bundle.id)
    text = e.skill_file.read_text(encoding="utf-8")
    assert "`aip run billing_support@1 --inputs '{...}'`" in text
    assert _walk(text) == ["start", "triage", "by_tone", "escalate", "reply", "end"]
