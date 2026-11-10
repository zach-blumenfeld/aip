"""The server's contract, the calls `aip.client.server` lists, through the client that makes
them, over each backend: the same suite on Relate and, with `NEO4J_URI` set, on Neo4j.

Publish merges a bundle by id and assigns the next revision under the procedure's name; an
upload with no revision is a draft; a run is recorded only against a bundle the store holds,
with the identity fields and the server's `user`; a reference hands its `.rl` back, the
bundle's own subgraph, which verifies like any bundle."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import aip
from aip import sdk
from aip.client import bundles
from aip.client.runs import RunFile
from aip.client.server import Server, ServerError
from aip.compiler import compile_folder, example_dir, read_bundle, relate, write_bundle
from scenes import CALM, POLICIES, client, record
from served import BillingModel, Served

EXAMPLE = example_dir("billing-support")
AGENT = example_dir("billing-support-agent")


def rl(folder: Path, tmp: Path) -> tuple[str, bytes]:
    """A folder compiled: its bundle id and the bytes of its `.rl`."""
    bundle, diagnostics = compile_folder(folder)
    assert bundle is not None, [str(d) for d in diagnostics]
    path = write_bundle(bundle, tmp / f"{bundle.id[:8]}.rl")
    return bundle.id, path.read_bytes()


def reworded(tmp: Path, name: str = "billing-support") -> Path:
    """The example with one description changed: the same procedure name, another bundle id."""
    folder = tmp / "reworded" / name
    shutil.copytree(example_dir(name), folder)
    source = folder / "procedure.aip"
    text = source.read_text()
    assert "Turn an inbound billing message" in text
    source.write_text(text.replace("Turn an inbound billing message", "Turn an incoming billing message", 1))
    return folder


def server(served, token: str | None = "secret") -> Server:
    return Server("http://testserver", token=token, session=served)


# --------------------------------------------------------------------- the catalog


def test_publish_merges_by_id_and_numbers_the_revisions(served, tmp_path):
    api = server(served)
    first_id, first = rl(EXAMPLE, tmp_path)
    assert api.publish(first) == {"name": "billing_support", "revision": "1", "bundle_id": first_id, "existed": False}
    assert api.publish(first) == {"name": "billing_support", "revision": "1", "bundle_id": first_id, "existed": True}, \
        "the same bundle is the same revision: a no-op"
    second_id, second = rl(reworded(tmp_path), tmp_path)
    assert second_id != first_id
    assert api.publish(second) == {"name": "billing_support", "revision": "2", "bundle_id": second_id, "existed": False}

    [entry] = api.list()
    assert (entry["name"], entry["pinned"], entry["latest"], entry["resolves"]) == ("billing_support", None, "2", "2")
    assert [(r["revision"], r["bundle_id"], r["retired"]) for r in entry["revisions"]] == [("2", second_id, False), ("1", first_id, False)]
    assert all(r["published_at"] for r in entry["revisions"])
    assert entry["description"].startswith("Turn an incoming billing message"), "the description of what the name resolves to"

    described = api.describe("billing_support")
    assert (described["name"], described["revision"], described["bundle_id"], described["draft"]) == ("billing_support", "2", second_id, False)
    assert described["inputs"] == {"message": "string"} and [s["name"] for s in described["steps"]][:2] == ["start", "triage"]
    assert api.describe("billing_support@1")["bundle_id"] == first_id
    assert api.describe("billing_support@latest")["revision"] == "2"


def test_pin_retire_and_what_a_name_resolves_to(served, tmp_path):
    api = server(served)
    first_id, first = rl(EXAMPLE, tmp_path)
    second_id, second = rl(reworded(tmp_path), tmp_path)
    api.publish(first)
    api.publish(second)

    assert api.pin("billing_support", "1") == {"name": "billing_support", "pinned": "1"}
    assert api.describe("billing_support")["revision"] == "1", "the pin wins"
    assert api.describe("billing_support@latest")["revision"] == "2", "@latest ignores it"
    assert (api.list()[0]["pinned"], api.list()[0]["resolves"]) == ("1", "1")
    assert api.pin("billing_support", None) == {"name": "billing_support", "pinned": None}
    assert api.describe("billing_support")["revision"] == "2"

    assert api.retire("billing_support", "2") == {"name": "billing_support", "revision": "2", "retired": True}
    entry = api.list()[0]
    assert (entry["latest"], entry["resolves"]) == ("1", "1") and entry["revisions"][0]["retired"] is True
    assert api.describe("billing_support")["bundle_id"] == first_id
    assert api.describe("billing_support@2")["retired"] is True, "a retired revision still answers by its number"
    # S3: retire wins over pin. Retiring the pinned revision clears the pin, and a retired revision is not pinned.
    api.pin("billing_support", "1")
    api.retire("billing_support", "1")
    entry = api.list()[0]
    assert (entry["pinned"], entry["latest"], entry["resolves"]) == (None, None, None)
    assert entry["description"].startswith("Turn an incoming billing message"), "a name with nothing live keeps its newest description"
    with pytest.raises(ServerError) as pinned:
        api.pin("billing_support", "2")
    assert (pinned.value.status, pinned.value.kind) == (409, "retired") and "billing_support@2 is retired" in pinned.value.message
    with pytest.raises(ServerError) as none_live:
        api.describe("billing_support")
    assert (none_live.value.status, none_live.value.kind) == (404, "not_found")
    assert none_live.value.message.startswith("billing_support has no live revision: all 2 are retired")
    with pytest.raises(ServerError) as hyphen:                      # the folder's spelling, with the published one offered
        api.describe("billing-support")
    assert hyphen.value.message == "no procedure 'billing-support'; did you mean `billing_support`?"
    with pytest.raises(ServerError) as unknown:
        api.describe("nothing-here")
    assert unknown.value.message == "no procedure 'nothing-here'"
    assert api.search("billing") == [], "search covers what each name resolves to"
    assert api.publish(second)["revision"] == "2" and api.describe("billing_support")["revision"] == "2", \
        "publishing a retired revision's bundle again brings it back"

    for call in (lambda: api.describe("nothing_here"), lambda: api.describe("billing_support@9"),
                 lambda: api.pin("billing_support", "9"), lambda: api.retire("billing_support", "9"),
                 lambda: api.pin("nothing_here", "1"), lambda: api.bundle("nothing_here")):
        with pytest.raises(ServerError) as missing:
            call()
        assert (missing.value.status, missing.value.kind) == (404, "not_found")


def test_search_ranks_what_each_name_resolves_to(served, tmp_path):
    api = server(served)
    for name in ("billing-support", "dynamic-policy", "ticket-triage"):
        api.publish(rl(example_dir(name), tmp_path)[1])
    hits = api.search("charged twice refunds")
    assert hits and hits[0]["name"] == "billing_support" and hits[0]["revision"] == "1" and hits[0]["score"] > 0
    assert set(hits[0]) == {"name", "revision", "bundle_id", "score", "description"}
    assert api.search("policies")[0]["name"] == "dynamic_policy", "stemmed: policies finds policy"
    assert api.search("dynamic_policy")[0]["name"] == "dynamic_policy", "an exact name wins"
    assert api.search("zebra") == [] and api.search("") == []
    assert len(api.search("the task a ticket", limit=1)) == 1


def test_a_reference_hands_its_bundle_back(served, tmp_path):
    """`GET /catalog/{ref}` with `Accept: application/octet-stream`: the bundle's own subgraph as
    a new `.rl`, which verifies, has the id it was published under, and exports the same folder;
    the runs recorded against it stay in the store."""
    ids = record(served, tmp_path)
    api = server(served)
    compiled, _ = compile_folder(EXAMPLE)
    back = tmp_path / "back.rl"
    back.write_bytes(api.bundle("billing_support"))
    bundle = read_bundle(back)                                       # verifies: tampering would raise
    assert bundle.id == compiled.id and bundle.source == compiled.source
    assert bundle.graph.canonical() == compiled.graph.canonical()
    assert [(f.path, f.data, f.mode) for f in bundle.files] == [(f.path, f.data, f.mode) for f in compiled.files]
    with relate.open(back) as conn:
        labels = {label for row in conn.execute("MATCH (n) RETURN labels(n) AS labels") for label in row["labels"]}
    assert not labels & {"Run", "Entry", "Answer", "Bundle", "Revision", "Name"}, "nothing of the server's travels in the bundle"
    assert served.store.run(ids["fired"])["bundle_id"] == compiled.id

    # the client's pull and get go through it
    c = client(served)
    shutil.rmtree(bundles.bundles_dir())
    pulled = c.pull("billing_support@1")
    assert pulled.fetched and pulled.bundle_id == compiled.id
    fetched = c.get("dynamic_policy", tmp_path / "out")
    assert (fetched.path / "procedure.aip").read_bytes() == (example_dir("dynamic-policy") / "procedure.aip").read_bytes()
    assert c.compile(fetched.path).bundle_id == fetched.bundle_id, "what comes back compiles to the id it was published under"


def test_a_reference_and_a_bundle_hand_their_graph_back_as_json(served, tmp_path):
    """`GET /catalog/{ref}/graph` and `GET /bundles/{id}/graph`: the bundle's nodes and edges as
    `aip compile --json` prints them, with the source and the files' text, which is what the
    console draws a procedure from and shows as its source."""
    record(served, tmp_path)
    compiled, _ = compile_folder(EXAMPLE)
    reply = served.http.get("/catalog/billing_support/graph", headers={"Authorization": "Bearer secret"})
    assert reply.status_code == 200
    body = reply.json()
    assert (body["name"], body["revision"], body["draft"], body["bundle_id"]) == ("billing_support", "1", False, compiled.id)
    nodes = {n["id"]: n for n in body["graph"]["nodes"]}
    assert nodes["procedure"]["properties"]["source"] == compiled.source
    assert nodes["file:assets/policy.md"]["properties"]["text"].startswith("# Refund policy")
    assert {(e["type"], e["start"], e["end"]) for e in body["graph"]["edges"]} == {(e.type, e.start, e.end) for e in compiled.graph.edges}
    assert sorted(nodes) == sorted(n.id for n in compiled.graph.nodes)

    by_id = served.http.get(f"/bundles/{compiled.id}/graph", headers={"Authorization": "Bearer secret"}).json()
    assert by_id["graph"] == body["graph"] and by_id["revision"] == "1" and by_id["draft"] is False

    bundle_id, data = rl(reworded(tmp_path), tmp_path)
    server(served).draft(data)
    draft = served.http.get(f"/bundles/{bundle_id}/graph", headers={"Authorization": "Bearer secret"}).json()
    assert draft["draft"] is True and draft["revision"] is None and draft["name"] == "billing_support"
    assert served.http.get("/bundles/nope/graph", headers={"Authorization": "Bearer secret"}).status_code == 404
    assert served.http.get("/catalog/nope/graph", headers={"Authorization": "Bearer secret"}).status_code == 404


# ------------------------------------------------------------------------- drafts


def test_an_upload_with_no_revision_is_a_draft(served, tmp_path):
    api = server(served)
    bundle_id, data = rl(AGENT, tmp_path)
    assert api.draft(data) == {"bundle_id": bundle_id, "name": "billing_support_agent", "existed": False, "draft": True}
    assert api.draft(data)["existed"] is True
    assert api.list() == [] and api.search("billing") == [], "a draft is not in the catalog"
    with pytest.raises(ServerError):
        api.describe("billing_support_agent")
    [held] = api.get("/bundles", drafts=True)
    assert (held["bundle_id"], held["name"], held["draft"], held["revision"]) == (bundle_id, "billing_support_agent", True, None)
    described = api.get(f"/bundles/{bundle_id}")
    assert (described["name"], described["draft"], described["inputs"]) == ("billing_support_agent", True, {"message": "string"})
    back = tmp_path / "draft.rl"
    back.write_bytes(api.request("GET", f"/bundles/{bundle_id}", headers={"Accept": "application/octet-stream"}).content)
    assert read_bundle(back).id == bundle_id

    # publishing promotes it: the store held the bundle, and now it has a number
    assert api.publish(data) == {"name": "billing_support_agent", "revision": "1", "bundle_id": bundle_id, "existed": True}
    assert api.get("/bundles", drafts=True) == [] and api.get("/bundles", drafts=False)[0]["revision"] == "1"
    assert api.draft(data) == {"bundle_id": bundle_id, "name": "billing_support_agent", "existed": True, "draft": False}
    assert api.describe("billing_support_agent")["draft"] is False


def test_an_upload_that_is_not_a_bundle_is_refused(served, tmp_path):
    api = server(served)
    for path, data in (("/catalog", b"not a bundle"), ("/bundles", b"not a bundle"), ("/catalog", b"")):
        with pytest.raises(ServerError) as refused:
            api.post_bytes(path, data)
        assert (refused.value.status, refused.value.kind) == (422, "not_a_bundle"), refused.value
        assert "upload" in str(refused.value) and str(tmp_path) not in str(refused.value)
    bundle, _ = compile_folder(EXAMPLE)
    edited = write_bundle(bundle, tmp_path / "edited.rl")
    with relate.open(edited, read_only=False) as conn:
        conn.execute("MATCH (s:Step {name: 'reply'}) SET s.description = 'Reply with whatever the customer wants.'")
    with pytest.raises(ServerError) as tampered:
        api.publish(edited.read_bytes())
    assert (tampered.value.status, tampered.value.kind) == (422, "bundle_tampered")
    assert api.list() == [] and api.get("/bundles") == [], "nothing was stored"


# --------------------------------------------------------------------------- runs


def run_of(bundle_id: str, **over) -> dict:
    return {"run_id": "run-0001", "bundle_id": bundle_id, "name": "billing_support", "revision": "1", "draft": False, "status": "paused",
            "started": "2026-11-09T12:00:00.000+00:00", "finished": None, "created": "2026-11-09T12:00:00.000+00:00",
            "updated": "2026-11-09T12:00:01.000+00:00", "identity": {"agent": "claude", "session": "s1", "user": "mallory"},
            "position": "step:reply", "state": {"message": CALM}, "loops": {}, "pause": {"kind": "task", "step": "reply", "tasks": [{}]},
            "error": None, "result": None, "batch": 10,
            "history": [{"step": "start", "kind": "Start", "pass": None, "passes": [], "at": "2026-11-09T12:00:00.000+00:00",
                         "seconds": 0.001, "input": {"message": CALM}, "result": {}}], **over}


def test_a_run_needs_a_bundle_the_store_holds(served, tmp_path):
    api = server(served)
    bundle_id, data = rl(EXAMPLE, tmp_path)
    with pytest.raises(ServerError) as unknown:
        api.record(run_of(bundle_id))
    assert (unknown.value.status, unknown.value.kind) == (404, "unknown_bundle") and bundle_id in str(unknown.value)
    with pytest.raises(ServerError) as missing:
        api.get("/runs/run-0001")
    assert missing.value.status == 404
    api.draft(data)
    assert api.record(run_of(bundle_id)) == {"run_id": "run-0001", "user": "zach", "draft": True, "revision": None}, \
        "the store says what the bundle is: held with no revision, whatever the run claimed"
    assert (api.run("run-0001")["draft"], api.run("run-0001")["revision"]) == (True, None)
    assert api.publish(data)["revision"] == "1"
    assert api.record(run_of(bundle_id, draft=True, revision=None)) == {"run_id": "run-0001", "user": "zach", "draft": False, "revision": "1"}, \
        "and once it is published, a run of it is a run of that revision"
    for bad in ({"run_id": "x"}, {"bundle_id": None}, {"history": "nope"}):
        with pytest.raises(ServerError) as invalid:
            api.record({**run_of(bundle_id), **bad})
        assert (invalid.value.status, invalid.value.kind) == (422, "invalid_request")


def test_a_run_is_upserted_whole_at_every_stop(served, tmp_path):
    api = server(served)
    bundle_id, data = rl(EXAMPLE, tmp_path)
    api.publish(data)
    posted = run_of(bundle_id)
    api.record(posted)
    stored = api.run("run-0001")
    assert stored == {**posted, "identity": {"agent": "claude", "session": "s1", "user": "zach"}}, \
        "the record comes back as posted, with the user the token stands for, whatever the client claimed"

    more = [*posted["history"],
            {"step": "triage", "kind": "Decide", "pass": None, "passes": [], "at": "2026-11-09T12:00:00.500+00:00", "seconds": 0.4,
             "model_seconds": 0.39, "history_sent": False, "answered_by": {"model": "jev-1", "endpoint": "https://api.typesafe.ai"},
             "input": {"message": CALM}, "result": {"billing": {"value": True, "confidence": 0.94, "noul": 0.97}}},
            {"step": "end", "kind": "End", "pass": None, "passes": [], "at": "2026-11-09T12:00:02.000+00:00", "seconds": 0.0,
             "input": {}, "result": {"message": CALM}}]
    done = run_of(bundle_id, status="done", finished="2026-11-09T12:00:02.000+00:00", updated="2026-11-09T12:00:02.000+00:00",
                  pause=None, position=None, result={"message": CALM}, history=more)
    api.record(done)
    api.record(done)                                                                 # a stop posted twice changes nothing
    stored = api.run("run-0001")
    assert stored["status"] == "done" and stored["history"] == more and stored["pause"] is None
    count = served.store.rows("MATCH (r:Run {run_id: 'run-0001'})-[:HAS_ENTRY]->(e:Entry) RETURN count(e) AS entries")
    assert count == [{"entries": 3}] and len(api.runs()) == 1

    rewritten = [more[0], {**more[1], "seconds": 0.5}]                                # not what a client does; the store still follows
    api.record(run_of(bundle_id, history=rewritten))
    assert api.run("run-0001")["history"] == rewritten
    path = served.store.rows("MATCH (a:Entry {run_id: 'run-0001'})-[:THEN]->(b:Entry) RETURN a.seq AS a, b.seq AS b, b.seconds AS seconds")
    assert path == [{"a": 0, "b": 1, "seconds": 0.5}]


def test_runs_through_the_client_carry_identity_and_drafts(served, tmp_path):
    ids = record(served, tmp_path)
    api = server(served)
    fired = api.run(ids["fired"])
    assert (fired["name"], fired["revision"], fired["draft"], fired["status"]) == ("billing_support", "1", False, "done")
    assert fired["identity"] == {"agent": "claude", "session": "s1", "user": "zach"}
    assert [e["step"] for e in fired["history"]] == ["start", "triage", "by_tone", "escalate", "end"]
    local = RunFile.load(aip.Client().run_file(ids["fired"])).recording()
    assert {**fired, "updated": None} == {**local, "updated": None}, "the server's record is the run file's"
    assert api.run(ids["batched"])["identity"] == {"agent": "tests", "session": None, "user": "ci"}, "each token has its own name"

    policy = api.run(ids["policy"])
    assert (policy["name"], policy["revision"], policy["draft"]) == ("fixed_policy", None, True), "a folder's run is a draft's"
    [draft] = api.get("/bundles", drafts=True)
    assert (draft["name"], draft["bundle_id"]) == ("fixed_policy", policy["bundle_id"])
    assert [e["name"] for e in api.list()] == ["billing_support", "billing_support_agent", "dynamic_policy"]

    rows = api.runs()
    assert [r["run_id"] for r in rows] == [ids[k] for k in ("batched", "capped", "policy", "agent", "calm", "fired")], "newest first"
    assert set(rows[0]) >= {"run_id", "name", "revision", "status", "draft", "identity", "started", "finished", "created", "updated"}
    assert all(r["started"] for r in rows), "`aip runs` prints when each started"

    def listed(**filters):
        return {r["run_id"] for r in api.get("/runs", **filters)}

    assert listed(name="billing_support") == {ids["fired"], ids["calm"]}
    assert listed(status="failed") == {ids["capped"]}
    assert listed(agent="codex") == {ids["agent"], ids["policy"], ids["capped"]}
    assert listed(session="s2") == {ids["agent"], ids["policy"]}
    assert listed(user="ci") == {ids["batched"]}
    assert listed(draft=True) == {ids["policy"], ids["capped"]} and len(listed(draft=False)) == 4
    assert listed(agent="codex", session="s2", name="fixed_policy") == {ids["policy"]}
    assert [r["run_id"] for r in api.get("/runs", limit=2)] == [ids["batched"], ids["capped"]]
    assert listed(agent="nobody") == set()

    summaries = client(served).runs(agent="claude")
    assert all(isinstance(r, sdk.RunSummary) for r in summaries) and {r.run_id for r in summaries} == {ids["fired"], ids["calm"]}


# --------------------------------------------------------------------------- auth


def test_tokens_have_scopes_and_names(served, tmp_path):
    bundle_id, data = rl(EXAMPLE, tmp_path)
    with pytest.raises(ServerError) as none:
        server(served, token=None).list()
    assert (none.value.status, none.value.kind) == (401, "missing_token")
    with pytest.raises(ServerError) as wrong:
        server(served, token="guess").list()
    assert (wrong.value.status, wrong.value.kind) == (401, "invalid_token")

    reader, runner = server(served, "reader"), server(served, "runner")
    assert reader.list() == []
    for call in (lambda: reader.publish(data), lambda: reader.draft(data), lambda: reader.record(run_of(bundle_id)),
                 lambda: runner.publish(data), lambda: runner.pin("billing_support", "1")):
        with pytest.raises(ServerError) as forbidden:
            call()
        assert (forbidden.value.status, forbidden.value.kind) == (403, "forbidden")
    assert runner.draft(data)["draft"] is True
    assert runner.record(run_of(bundle_id)) == {"run_id": "run-0001", "user": "ci", "draft": True, "revision": None}
    assert reader.run("run-0001")["identity"]["user"] == "ci"


def test_an_open_server_records_no_user(backend, tmp_path):
    served = Served(backend)
    done = client(served, BillingModel(0.6), token=None).run(EXAMPLE, {"message": CALM}, workdir=tmp_path)
    assert done.recorded is True and served.runs[done.run_id]["identity"] == {"agent": "tests", "session": None, "user": None}


# ------------------------------------------------------------------ built-in bundles


def test_built_in_bundles_are_published_once_per_store(backend, tmp_path):
    from aip.server.builtins import builtin_files, publish_builtins

    shipped = tmp_path / "bundles"
    shipped.mkdir()
    bundle, _ = compile_folder(example_dir("dynamic-policy"))
    write_bundle(bundle, shipped / "dynamic_policy.rl")
    store = backend.store
    assert [f.name for f in builtin_files()] == ["make_procedure.rl"]
    assert publish_builtins(store, tmp_path / "none") == [] and store.offered() == []

    assert publish_builtins(store, shipped) == [{"name": "dynamic_policy", "revision": "1", "bundle_id": bundle.id, "existed": False}]
    assert [e["name"] for e in store.catalog()] == ["dynamic_policy"] and store.offered() == [bundle.id]
    store.retire("dynamic_policy", "1")
    assert publish_builtins(store, shipped) == [], "offered once: a start does not undo what was done by hand"
    assert store.catalog()[0]["latest"] is None

    newer, _ = compile_folder(reworded(tmp_path, "billing-support"))
    write_bundle(newer, shipped / "billing_support.rl")
    assert [p["name"] for p in publish_builtins(store, shipped)] == ["billing_support"], "an upgrade that carries a new one publishes it"
    assert sorted(store.offered()) == sorted([bundle.id, newer.id])


# ------------------------------------------------------------- the Relate store file


@pytest.mark.skipif(not relate.available(), reason=relate.INSTALL_HINT)
def test_the_relate_store_is_one_file_that_outlives_the_server(tmp_path):
    from aip.server.backends.relate import RelateBackend

    path = tmp_path / "data" / "store.rl"
    first = Served(RelateBackend(path))
    ids = record(first, tmp_path)
    kept = first.store.run(ids["batched"])
    first.close()
    assert [p.name for p in (tmp_path / "data").iterdir()] == [relate.store_file(path).name], "one file under the data directory"

    again = Served(RelateBackend(path))
    assert [e["name"] for e in again.store.catalog()] == ["billing_support", "billing_support_agent", "dynamic_policy"]
    assert again.store.run(ids["batched"]) == kept and len(again.store.runs()) == 6
    assert kept["state"]["policies"] == POLICIES
    back = tmp_path / "back.rl"
    back.write_bytes(server(again, None).bundle("dynamic_policy"))
    assert read_bundle(back).name == "dynamic_policy"
    again.close()
