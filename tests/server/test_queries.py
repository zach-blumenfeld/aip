"""What the store keeps of a run, and every query the docs print over it, on each backend.

`docs/language/queries.md` is run whole: each `cypher` block must execute against a store
holding the examples and a run of each kind (`scenes.record`), and the blocks of its second
half, the server's store, must answer what their headings say. The named governance queries
(`aip.server.governance`) are checked the same way, so the document, the server and the two
databases cannot drift apart unnoticed."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from aip.server import governance
from scenes import POLICIES, record

DOC = Path(__file__).parent.parent.parent / "docs" / "language" / "queries.md"


def blocks() -> dict[str, list[str]]:
    """The document's Cypher, by the heading each block stands under."""
    out: dict[str, list[str]] = {}
    heading = ""
    for part in re.split(r"(?m)^(#{2,3} .+)$", DOC.read_text()):
        if part.startswith("#"):
            heading = part.lstrip("# ").strip()
        else:
            found = re.findall(r"```cypher\n(.*?)```", part, re.DOTALL)
            if found:
                out[heading] = found
    return out


@pytest.fixture
def scene(served, tmp_path):
    ids = record(served, tmp_path)
    return served.store, ids


def test_every_query_in_the_document_runs(scene):
    store, ids = scene
    doc = blocks()
    assert len(doc) == 18 and sum(len(q) for q in doc.values()) == 21, sorted(doc)
    for heading, queries in doc.items():
        for cypher in queries:
            store.rows(cypher, run_id=ids["policy"], key="check_summary")     # raises if the database refuses it


def test_the_bundle_queries_see_every_bundle_in_the_store(scene):
    store, _ = scene
    doc = blocks()
    routes = store.rows(doc["Routes, and what steers them"][0])
    assert {(r["procedure"], r["route"], r["reads"], r["source"]) for r in routes} == {
        ("billing_support", "by_tone", "triage_decision.tone", "measured"), ("billing_support_agent", "by_tone", "tone", "agent")}
    questions = store.rows(doc["Decisions and their questions"][0])
    assert [q["question"] for q in questions if q["procedure"] == "fixed_policy"] == ["pii", "claims", "tone", "length"]


def test_revisions_and_drafts(scene):
    store, _ = scene
    doc = blocks()
    revisions = store.rows(doc["Revisions"][0])
    assert [(r["name"], r["revision"], r["retired"], r["pinned"]) for r in revisions] == [
        ("billing_support", "1", False, None), ("billing_support_agent", "1", False, None), ("dynamic_policy", "1", False, None)]
    store.pin("billing_support", "1")
    assert store.rows(doc["Revisions"][0])[0]["pinned"] == "1"
    [draft] = store.rows(doc["Drafts"][0])
    assert (draft["name"], draft["runs"]) == ("fixed_policy", 2)


def test_a_runs_path_and_its_time(scene):
    store, ids = scene
    doc = blocks()
    path = store.rows(doc["A run's path"][0], run_id=ids["policy"])
    assert [(r["seq"], r["step"], r["kind"]) for r in path] == [
        (0, "start", "Start"), (1, "draft", "Task_Agent"), (2, "check", "Decide"), (3, "summarize_check", "Aggregate"),
        (4, "fix", "Task_Agent"), (5, "check", "Decide"), (6, "summarize_check", "Aggregate"), (7, "revise", "Loop"), (8, "end", "End")]
    assert [r["passes"] for r in path][2:7] == [["revise 0"]] * 3 + [["revise 1"]] * 2 and path[0]["passes"] is None
    assert all(isinstance(r["seconds"], float) for r in path if r["kind"] != "Loop") and path[7]["seconds"] is None
    fired = store.rows(doc["A run's path"][0], run_id=ids["fired"])
    assert [(r["step"], r["went_to"]) for r in fired] == [("start", None), ("triage", None), ("by_tone", "escalate"), ("escalate", None), ("end", None)]
    drawn = store.rows(doc["A run's path"][1], run_id=ids["policy"])
    assert len(drawn) == 9 and sum(1 for r in drawn if r["next"] is None) == 1, "one chain, start to end"

    time = {r["step"]: r for r in store.rows(doc["Where a run's time went"][0], run_id=ids["policy"])}
    assert (time["check"]["ran"], time["fix"]["ran"], time["draft"]["kind"]) == (2, 1, "Task_Agent")
    assert time["check"]["model_seconds"] is not None and time["check"]["model_seconds"] <= time["check"]["seconds"] + 1e-6
    assert time["draft"]["waited_seconds"] is not None and time["fix"]["waited_seconds"] is not None, "the wait for the agent is kept apart"
    assert not time["check"]["waited_seconds"]


def test_checks_answers_and_aggregations(scene):
    store, ids = scene
    doc = blocks()
    [fired] = store.rows(doc["Routes whose check fired, and why"][0])
    assert fired == {"procedure": "billing_support", "route": "by_tone", "reason": "below", "answer": "triage_decision.tone",
                     "confidence": 0.6, "bound": 0.9, "went_to": "escalate", "run": ids["fired"]}

    answers = store.rows(doc["What the model answered, and how sure it was"][0])
    assert len(answers) == 2 * 2 + 2 * 4 + 3 * 4 + 2 * 3, "two billing runs, the policy run's two checks, the capped run's three, the batch's two"
    assert answers[0]["confidence"] <= answers[-1]["confidence"]
    tone = next(a for a in answers if a["run"] == ids["fired"] and a["question"] == "tone")
    assert (tone["value"], tone["confidence"], tone["type"], tone["model"], tone["passes_in_call"]) == ("calm", 0.6, "choice", "jev-1", 1)
    batched = [a for a in answers if a["run"] == ids["batched"]]
    assert {a["passes_in_call"] for a in batched} == {len(POLICIES)} and {a["question"] for a in batched} == {"follows"}
    assert sorted(a["value"] for a in batched) == [False] + [True] * 5

    failing = store.rows(doc["Aggregations that fail most often"][0])
    assert [(r["procedure"], r["step"], r["aggregation"], r["mode"], r["computed"], r["failed"]) for r in failing] == [
        ("fixed_policy", "summarize_check", "all_hold", "All", 5, 4), ("dynamic_policy", "summarize_check", "all_hold", "All", 2, 1)]
    assert failing[0]["barred"] == 4 + 3 * 4, "0.6 and 0.3 are answers the 0.7 bar turned; 0.9 is not"


def test_lineage_tasks_and_loops(scene):
    store, ids = scene
    doc = blocks()
    lineage = store.rows(doc["The lineage of a key"][0], run_id=ids["policy"], key="check_summary")
    assert lineage, "a path from the steps upstream to the key"
    produced = store.rows(doc["The lineage of a key"][1], run_id=ids["policy"], key="check_summary")
    assert [(r["seq"], r["produced_by"], r["passes"], r["read"]) for r in produced] == [
        (3, "summarize_check", ["revise 0"], ["policy_check"]), (6, "summarize_check", ["revise 1"], ["policy_check"])]
    work = store.rows(doc["The lineage of a key"][1], run_id=ids["policy"], key="work")
    assert [(r["seq"], r["produced_by"]) for r in work] == [(1, "draft"), (4, "fix")]

    tasks = store.rows(doc["Who answered the tasks"][0])
    who = {(r["procedure"], r["task"], r["agent"], r["session"]): r["answered"] for r in tasks}
    assert who[("billing_support", "reply", "claude", "s1")] == 1 and who[("billing_support_agent", "triage", "codex", "s2")] == 1
    assert who[("fixed_policy", "fix", "codex", "s2")] == 1 and who[("fixed_policy", "fix", "codex", None)] == 3
    assert all(r["mean_wait_seconds"] is not None for r in tasks)

    loops = {(r["procedure"], r["loop"], r["reason"]): r for r in store.rows(doc["Why loops ended"][0])}
    assert loops[("fixed_policy", "revise", "until")]["exit_at"] == "summarize_check" and loops[("fixed_policy", "revise", "until")]["mean_passes"] == 2
    assert (loops[("fixed_policy", "revise", "cap")]["exit_at"], loops[("fixed_policy", "revise", "cap")]["mean_passes"]) == ("head", 3)
    assert (loops[("dynamic_policy", "review", "items")]["times"], loops[("dynamic_policy", "review", "items")]["mean_passes"]) == (2, 3)

    until = store.rows(doc["Passes that ran because `Until` did not hold yet"][0], run_id=ids["capped"])
    assert [(r["first_step"], r["passes"], r["tested_at"]) for r in until] == [("check", [f"revise {n}"], "head") for n in range(3)]


def test_what_the_store_keeps_of_a_run(scene):
    """The fields R5 added to the record are on the nodes (plan S1), so a query can ask where
    time goes and who answered."""
    store, ids = scene
    [run] = store.rows("MATCH (r:Run {run_id: $id})-[:OF]->(b:Bundle) RETURN properties(r) AS run, b.draft AS draft", id=ids["capped"])
    assert run["draft"] is True
    kept = run["run"]
    assert (kept["status"], kept["error"], kept["error_step"], kept["agent"], kept["user"], kept["draft"]) == (
        "failed", "loop_cap", "revise", "codex", "zach", True)
    assert kept["started"] and kept["finished"] and kept["entries"] == 12 and kept["bundle_id"]
    [paused] = store.rows("MATCH (r:Run {run_id: $id}) RETURN r.started AS started, r.finished AS finished, r.status AS status", id=ids["calm"])
    assert paused["status"] == "done" and paused["started"] < paused["finished"]

    entries = store.rows("MATCH (e:Entry {run_id: $id}) RETURN properties(e) AS e ORDER BY e.seq", id=ids["batched"])
    check = next(e["e"] for e in entries if e["e"]["step"] == "check")
    assert (check["batched"], check["batch_size"], check["model"], check["loop"], check["loops"]) == (
        True, 3, "jev-1", "review", ["revise 0", "review 0"])
    assert check["model_seconds"] >= 0 and check["seconds"] >= 0 and check["bundle_id"] == entries[0]["e"]["bundle_id"]
    fix = next(e["e"] for e in entries if e["e"]["step"] == "fix")
    assert (fix["agent"], fix.get("session")) == ("tests", None) and fix["waited_seconds"] >= 0, "a null is no property"
    exits = [(e["e"]["step"], e["e"]["exit"], e["e"].get("exit_where"), e["e"]["iterations"]) for e in entries if "exit" in e["e"]]
    assert exits == [("review", "items", None, 3), ("review", "items", None, 3), ("revise", "until", "summarize_check", 2)]
    [cap] = store.rows("MATCH (e:Entry {run_id: $id, kind: 'Loop'}) RETURN e.exit AS exit, e.exit_where AS exit_at", id=ids["capped"])
    assert cap == {"exit": "cap", "exit_at": "head"}

    at = store.rows("MATCH (e:Entry {run_id: $id})-[:AT]->(n) RETURN count(e) AS linked, count(DISTINCT n.bundle_id) AS bundles", id=ids["batched"])
    assert at == [{"linked": len(entries), "bundles": 1}], "every entry stands on its step or loop, in the bundle it ran"
    agent = store.rows("MATCH (:Entry {run_id: $id})-[:GAVE]->(a:Answer) RETURN a.name AS name, a.value AS value, a.source AS source, "
                       "a.confidence AS confidence ORDER BY name", id=ids["agent"])
    assert agent == [{"name": "billing", "value": True, "source": "agent", "confidence": None},
                     {"name": "tone", "value": "angry", "source": "agent", "confidence": None}], "an agent's answer has no confidence"


def test_the_named_governance_queries(scene, served):
    store, ids = scene
    assert [q["query"] for q in governance.listing()] == list(governance.QUERIES)
    fired = governance.run(store, "confidence-fired")
    assert fired == [{"name": "billing_support", "route": "by_tone", "reason": "below", "fired": 1, "run_ids": [ids["fired"]]}]
    assert governance.run(store, "confidence-fired", agent="codex") == [] and governance.run(store, "confidence-fired", session="s1") == fired
    assert governance.run(store, "confidence-fired", window=1) == [], "only the newest run is looked at"

    failing = governance.run(store, "failing-aggregations")
    assert [(r["name"], r["step"], r["aggregation"], r["computed"], r["failed"]) for r in failing] == [
        ("fixed_policy", "summarize_check", "all_hold", 5, 4), ("dynamic_policy", "summarize_check", "all_hold", 2, 1)]
    assert [r["name"] for r in governance.run(store, "failing-aggregations", user="ci")] == ["dynamic_policy"]

    asked = governance.run(store, "model-answers", name="billing_support")
    assert [(r["question"], r["answers"], r["lowest_confidence"]) for r in asked] == [("tone", 2, 0.6), ("billing", 2, 0.94)]
    assert asked[0]["mean_confidence"] == pytest.approx((0.6 + 0.95) / 2)

    assert governance.run(store, "agent-routes") == [
        {"name": "billing_support_agent", "route": "by_tone", "reads": "tone", "labels": ["angry", "calm"], "runs": 1}]

    from aip.client.server import Server, ServerError

    api = Server("http://testserver", token="reader", session=served)
    assert [q["path"] for q in api.governance()] == [f"/governance/{q}" for q in governance.QUERIES]
    assert api.governance("confidence-fired", name="billing_support", limit=5) == fired
    with pytest.raises(ServerError) as unknown:
        api.governance("hand-answers")
    assert (unknown.value.status, unknown.value.kind) == (404, "not_found")
