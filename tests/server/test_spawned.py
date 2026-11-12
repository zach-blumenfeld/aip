"""Runs started from runs, in the store (plan aip#29, R7): a child's `parent` puts `parent_run`,
`parent_step`, `parent_pass` and `depth` on its `Run` node, the parent's `Execute` entry for that
step and pass is linked to it by `SPAWNED` whichever of the two is posted first, the parent's
record lists its `children`, and the audit query `spawned-runs` counts them."""

from __future__ import annotations

from aip.compiler import compile_folder, example_dir
from aip.server import audit
from aip.server.app import describe_bundle


def entry(step: str, kind: str, pass_: int | None = None) -> dict:
    return {"step": step, "kind": kind, "pass": pass_, "passes": [{"loop": "work", "pass": pass_}] if pass_ is not None else [],
            "at": "2026-11-12T10:00:00.000+00:00", "input": {}, "result": {}}


def posted(run_id: str, bundle_id: str, name: str, history: list[dict], **more) -> dict:
    return {"run_id": run_id, "bundle_id": bundle_id, "name": name, "status": "done", "identity": {"agent": "tests"},
            "started": "2026-11-12T10:00:0" + str(1 + ("late" in run_id)) + ".000+00:00", "updated": "2026-11-12T10:01:00.000+00:00",
            "history": history, **more}


def test_a_child_is_linked_to_the_entry_that_started_it_whichever_comes_first(backend):
    store = backend.store
    bundle, _ = compile_folder(example_dir("assist"))
    store.draft(bundle, describe_bundle(bundle))
    parent_history = [entry("start", "Start"), entry("search", "Execute"), entry("plan", "Task_Agent", 0), entry("act", "Execute", 0),
                      entry("plan", "Task_Agent", 1), entry("act", "Execute", 1)]

    early = posted("child-early", bundle.id, "first_child", [entry("start", "Start")],
                   parent={"run_id": "parent-r7", "step": "act", "pass": 0}, depth=1, tokens={"own": 300, "children": 0, "total": 300})
    store.record(early)                                               # before its parent has the entry
    store.record(posted("parent-r7", bundle.id, "assist", parent_history[:4], tokens={"own": 50, "children": 300, "total": 350}))
    late = posted("child-late", bundle.id, "second_child", [entry("start", "Start")], status="failed",
                  parent={"run_id": "parent-r7", "step": "act", "pass": 1}, depth=1)
    store.record(posted("parent-r7", bundle.id, "assist", parent_history))
    store.record(late)                                                # after it
    store.record(posted("parent-r7", bundle.id, "assist", parent_history))   # posted again: no second edge

    rows = store.rows("MATCH (p:Run)-[:HAS_ENTRY]->(e:Entry)-[s:SPAWNED]->(c:Run) "
                      "RETURN p.run_id AS parent, e.step AS step, e.pass AS pass, c.run_id AS child ORDER BY child")
    assert rows == [{"parent": "parent-r7", "step": "act", "pass": 0, "child": "child-early"},
                    {"parent": "parent-r7", "step": "act", "pass": 1, "child": "child-late"}]
    node = store.rows("MATCH (c:Run {run_id: 'child-early'}) RETURN c.parent_run AS run, c.parent_step AS step, "
                      "c.parent_pass AS pass, c.depth AS depth, c.tokens AS tokens")[0]
    assert node == {"run": "parent-r7", "step": "act", "pass": 0, "depth": 1, "tokens": 300}

    record = store.run("parent-r7")
    assert [(c["run_id"], c["name"], c["status"], c["step"], c["pass"], c["tokens"]) for c in record["children"]] == [
        ("child-early", "first_child", "done", "act", 0, 300), ("child-late", "second_child", "failed", "act", 1, 0)]
    assert store.run("child-early")["parent"] == {"run_id": "parent-r7", "step": "act", "pass": 0}
    assert "children" not in store.run("child-early"), "a run with none says nothing of children"

    spawned = audit.run(store, "spawned-runs", name="assist")
    assert [(r["name"], r["step"], r["procedure"], r["runs"], r["done"], r["failed"], r["tokens"]) for r in spawned] == [
        ("assist", "act", "first_child", 1, 1, 0, 300), ("assist", "act", "second_child", 1, 0, 1, 0)]
