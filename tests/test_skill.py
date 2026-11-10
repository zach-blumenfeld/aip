"""The `aip` skill (`skills/aip/`, plan aip-dev#1, K1): the one page an agent reads to run and
to write procedures, with the language on one page beside it. It is a plain Agent Skill, so its
frontmatter must pass the Agent Skills rules; every `aip <command>` it shows must exist; the
example program on the language page must compile; and `aip skill install` must write it, take
away the two skills of 0.8 it replaced, and leave anyone else's folder alone."""

import io
import json
import re
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest
import yaml

from aip.client.cli import COMMANDS, main
from aip.compiler import LANGUAGE_VERSION, check_source, example_dir, has_errors
from aip.compiler.agents import read_record, record_path
from aip.compiler.keywords import keyword
from aip.compiler.resources import LEGACY_SKILL_NAMES, SKILL_ENTRIES, SKILL_NAME, skill_dir

REPO = Path(__file__).parent.parent
SKILL_DIR = REPO / "skills" / "aip"
SKILL_MD = SKILL_DIR / "SKILL.md"
LANGUAGE_MD = SKILL_DIR / "references" / "language.md"
FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)
FENCE = re.compile(r"^[ \t]*```[a-z]*\n(.*?)^[ \t]*```", re.DOTALL | re.MULTILINE)
SPAN = re.compile(r"`([^`\n]+)`")
COMMAND = re.compile(r"^(?:\$ )?aip ([a-z][a-z_-]*)")
MAX_LINES = 160


def frontmatter_and_body() -> tuple[dict, str]:
    match = FRONTMATTER.match(SKILL_MD.read_text(encoding="utf-8"))
    assert match, "SKILL.md must begin with YAML frontmatter"
    return yaml.safe_load(match.group(1)), match.group(2)


def commands_shown(text: str) -> set[str]:
    """The `aip <command>` of every line of a code block and of every inline code span."""
    code = [line.strip() for block in FENCE.findall(text) for line in block.splitlines()]
    code += [span.strip() for span in SPAN.findall(FENCE.sub("", text))]
    return {m.group(1) for m in map(COMMAND.match, code) if m}


def call(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


def test_the_frontmatter_is_an_agent_skill():
    front, _ = frontmatter_and_body()
    assert front["name"] == SKILL_NAME == SKILL_DIR.name == "aip", "an Agent Skill's name is its folder's"
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", front["name"]) and len(front["name"]) <= 64
    assert 0 < len(front["description"]) <= 1024
    assert front["metadata"]["aip-version"] == LANGUAGE_VERSION, "the skill is versioned with the language"
    assert set(front) <= {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}


def test_the_description_triggers_on_the_words_a_task_uses():
    description = frontmatter_and_body()[0]["description"]
    for word in ("procedure", "runbook", "workflow", "aip", "Agent Instruction Protocol", "make_procedure"):
        assert word in description


def test_every_command_shown_exists():
    for file in (SKILL_MD, LANGUAGE_MD):
        shown = commands_shown(file.read_text(encoding="utf-8"))
        assert shown and shown <= set(COMMANDS), f"{file.name} shows commands `aip` does not have: {sorted(shown - set(COMMANDS))}"
    shown = commands_shown(SKILL_MD.read_text(encoding="utf-8"))
    for needed in ("search", "info", "run", "resume", "runs", "config", "compile", "fmt", "publish"):
        assert needed in shown, f"the skill should show `aip {needed}`"


def test_every_flag_shown_is_one_the_command_takes():
    shown = set(re.findall(r"aip ([a-z]+)[^\n`|]*?(--[a-z-]+)", SKILL_MD.read_text(encoding="utf-8")))
    assert {("run", "--inputs"), ("resume", "--answers"), ("info", "--example-inputs"), ("compile", "--check")} <= shown
    for command, flag in shown:
        helped = io.StringIO()
        with redirect_stdout(helped), pytest.raises(SystemExit):
            main([command, "--help"])
        assert flag in helped.getvalue(), f"`aip {command}` has no {flag}"


def test_it_is_one_page():
    lines = SKILL_MD.read_text(encoding="utf-8").count("\n")
    assert lines < MAX_LINES, f"skills/aip/SKILL.md is {lines} lines; keep it under {MAX_LINES}"
    assert "make_procedure" in SKILL_MD.read_text(encoding="utf-8") and "references/language.md" in SKILL_MD.read_text(encoding="utf-8")


def test_the_language_page_is_the_one_make_procedure_hands_over():
    shipped = example_dir("make_procedure") / "assets" / "language.md"
    assert shipped.read_text(encoding="utf-8") == LANGUAGE_MD.read_text(encoding="utf-8"), \
        "skills/aip/references/language.md and examples/language/make_procedure/assets/language.md have drifted; copy one over " \
        "the other, then compile make_procedure again (src/aip/server/builtins.py says how)"


def test_the_language_page_survives_being_a_prompt():
    """It is interpolated into make_procedure's prompts, where `{key}` of a key those steps read
    would be filled in: it must not name one."""
    text = LANGUAGE_MD.read_text(encoding="utf-8")
    for key in ("name", "description", "materials", "path", "diagnostics"):
        assert "{" + key + "}" not in text


def test_the_language_page_example_compiles_and_its_keywords_are_the_language():
    text = LANGUAGE_MD.read_text(encoding="utf-8")
    [example] = re.findall(r"^```aip\n(.*?)^```", text, re.DOTALL | re.MULTILINE)
    folder = example_dir("ticket-triage")                    # the same program; its two scripts are there
    program, diagnostics = check_source(example, "procedure.aip", folder)
    assert program is not None and not has_errors(diagnostics), [str(d) for d in diagnostics]
    [fragment] = re.findall(r"^```\n(Aggregate .*?)^```", text, re.DOTALL | re.MULTILINE)      # verbatim from dynamic-policy
    whole = [line.strip() for line in (example_dir("dynamic-policy") / "procedure.aip").read_text(encoding="utf-8").splitlines()]
    lines = [line.strip() for line in fragment.splitlines()]
    assert any(whole[i:i + len(lines)] == lines for i in range(len(whole))), "the Aggregate card is not dynamic-policy's any more"
    named = set(re.findall(r"`([A-Z][a-z]+(?:_[A-Z][a-z]+)*)\b", text))
    assert {"Task_Agent", "Confidence_Below", "Collect", "Else_Exit", "Again", "Aggregations"} <= named
    for word in named:
        assert keyword(word) == word, f"the language page names `{word}`, which is not a keyword's canonical spelling"


def test_skill_install_writes_the_skill_and_takes_the_old_two_away(tmp_path):
    skills = tmp_path / "skills"
    for name in LEGACY_SKILL_NAMES:                          # as 0.8's `aip skill install` left them, with its record
        (skills / name).mkdir(parents=True)
        (skills / name / "SKILL.md").write_text(f"---\nname: {name}\ndescription: Run published AIP procedures\n---\nbody\n")
    record_path().parent.mkdir(parents=True, exist_ok=True)
    record_path().write_text(json.dumps({"version": 1, "dirs": {str(skills): {"aip": list(LEGACY_SKILL_NAMES)}}}))
    (skills / "someone-elses").mkdir()

    code, out, err = call("skill", "install", "--path", str(skills))
    assert code == 0, err
    assert f"installed aip -> {skills / 'aip'}" in out
    for name in LEGACY_SKILL_NAMES:
        assert f"removed {skills / name}" in out
    assert sorted(p.name for p in skills.iterdir()) == ["aip", "someone-elses"]
    assert (skills / "aip" / "SKILL.md").read_text() == SKILL_MD.read_text()
    assert (skills / "aip" / "references" / "language.md").read_text() == LANGUAGE_MD.read_text()
    assert sorted(p.name for p in (skills / "aip").iterdir()) == sorted(SKILL_ENTRIES)
    assert read_record() == {str(skills): {"aip": ["aip"]}}

    assert call("skill", "install", "--path", str(skills))[0] == 0, "idempotent"
    code, out, _ = call("skill", "remove", "--path", str(skills))
    assert code == 0 and f"removed {skills / 'aip'}" in out and read_record() == {}
    assert [p.name for p in skills.iterdir()] == ["someone-elses"]
    assert "is not installed" in call("skill", "remove", "--path", str(skills))[1]


def test_skill_prune_removes_only_our_retired_folders(tmp_path):
    ours, theirs = tmp_path / "aip-runtime", tmp_path / "aip-compile"
    ours.mkdir()
    (ours / "SKILL.md").write_text("---\nname: aip-runtime\ndescription: Run published AIP procedures\n---\nbody\n")
    theirs.mkdir()
    (theirs / "SKILL.md").write_text("---\nname: aip-compile\ndescription: Compile something else entirely\n---\nbody\n")
    assert call("skill", "install", "--path", str(tmp_path))[0] == 0

    code, out, err = call("skill", "prune", "--path", str(tmp_path), "--dry-run")
    assert code == 0 and f"would remove {ours}" in out and ours.is_dir()
    code, out, err = call("skill", "prune", "--path", str(tmp_path))
    assert code == 0 and f"removed {ours}" in out and not ours.exists()
    assert f"left {theirs} alone" in err and theirs.is_dir()
    assert (tmp_path / "aip" / "SKILL.md").is_file(), "the skill itself is not a retired name"


def test_skill_list_and_an_unknown_agent(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".claude").mkdir()
    code, out, _ = call("skill", "list")
    assert code == 0 and re.search(r"claude-code\s+yes\s+-", out) and re.search(r"codex\s+no\s+-", out)
    code, out, _ = call("skill", "install")
    assert code == 0 and out == f"installed aip -> {tmp_path / '.claude' / 'skills' / 'aip'}  (Claude Code)\n"
    assert re.search(r"claude-code\s+yes\s+aip", call("skill", "list")[1])
    code, out, _ = call("skill", "install", "codex")
    assert code == 0 and (tmp_path / ".codex" / "skills" / "aip" / "SKILL.md").is_file()
    code, _, err = call("skill", "install", "emacs")
    assert code == 1 and "unknown agent 'emacs'" in err


def test_the_wheel_carries_the_skill_and_the_shipped_bundle():
    """`pyproject.toml` force-includes the skill's entries under `aip/compiler/_skill/`, where
    `skill_dir()` looks first; the bundle is inside `src/aip`, which the wheel takes whole."""
    import tomllib

    build = tomllib.loads((REPO / "pyproject.toml").read_text())["tool"]["hatch"]["build"]["targets"]["wheel"]
    included = build["force-include"]
    for entry in SKILL_ENTRIES:
        assert included[f"skills/aip/{entry}"] == f"aip/compiler/_skill/{entry}" and (SKILL_DIR / entry).exists()
    assert not [source for source in included if source.startswith("skills/") and not (REPO / source).exists()]
    assert skill_dir() == SKILL_DIR, "a checkout reads the repository's copy"
    assert (REPO / "src" / "aip" / "server" / "bundles" / "make_procedure.rl").is_file() and build["packages"] == ["src/aip"]
