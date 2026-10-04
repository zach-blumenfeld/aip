"""HTTP API tests (design §4.2) over the filesystem backend through FastAPI's test client.

Publish, search, info, files (manifest, one file, hash-verified tar), pin and retire, the
bearer-token scopes, and a full traversal of `billing-support` through `/peek`, `/step`,
and `/answer` reproducing the `running.md` worked example: the angry branch runs the
script on the server, the calm branch pauses as a client task, and every step lands in
the run the server records.
"""

import hashlib
import io
import json
import os
import tarfile
from pathlib import Path
from unittest import mock

import pytest
from fastapi.testclient import TestClient
from typesafe_sdk import SystemOneResponse

from aip.server.app import create_app, upload_of
from aip.server.backends.filesystem import FilesystemBackend
from aip.server.records import snapshot

EXAMPLE = Path(__file__).parent.parent.parent / "examples" / "billing-support"


class FakeJev:
    """A decision model whose answers are fixed: billing at `billing_p`, tone angry at `tone_p`."""

    def __init__(self, tone_p: float, billing_p: float = 0.97):
        self.tone_p, self.billing_p = tone_p, billing_p

    def system_one(self, state, questions, **_):
        return SystemOneResponse.model_validate_json(json.dumps({
            "model": "jev-1", "usage": {"input_tokens": 1, "output_tokens": 1},
            "answers": {
                "billing": {"type": "noul", "noul": self.billing_p},
                "tone": {"type": "choice", "choice": "angry" if self.tone_p >= 0.5 else "calm",
                         "confidence": max(self.tone_p, round(1 - self.tone_p, 6)),
                         "probabilities": {"angry": self.tone_p, "calm": round(1 - self.tone_p, 6)}},
            }}))


@pytest.fixture
def backend(tmp_path):
    return FilesystemBackend(tmp_path / "root")


@pytest.fixture
def no_key(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)


@pytest.fixture
def api(backend, no_key):
    return TestClient(create_app(backend), raise_server_exceptions=False)


@pytest.fixture(scope="module")
def example():
    return snapshot(EXAMPLE)


def publish(api, folder=EXAMPLE, **extra):
    return api.post("/catalog", json=upload_of(folder), **extra)


def tree(root: Path) -> dict:
    out = {}
    for path in sorted(root.rglob("*")):
        if path.is_dir() or path.name == ".DS_Store" or "__pycache__" in path.parts:
            continue
        out[path.relative_to(root).as_posix()] = (hashlib.sha256(path.read_bytes()).hexdigest(),
                                                  path.stat().st_mode & 0o777)
    return out


# ------------------------------------------------------------------------- catalog


def test_empty_catalog_and_error_envelope(api):
    assert api.get("/catalog").json() == []
    assert api.get("/catalog/search", params={"q": "refund"}).json() == []
    r = api.get("/catalog/nope")
    assert r.status_code == 404
    assert r.json() == {"error": {"kind": "not_found", "message": "no skill named 'nope'"}}
    r = api.get("/runs/nope")
    assert r.status_code == 404 and r.json()["error"]["kind"] == "not_found"
    r = api.post("/procedures/x/step", json={"after": 5})
    assert r.status_code == 422 and r.json()["error"]["kind"] == "invalid_request"


def test_publish_search_info_and_listing(api, example):
    r = publish(api)
    assert r.status_code == 201
    assert r.json()["name"] == "billing-support" and r.json()["revision"] == example.revision
    assert r.json()["warnings"] == []
    assert publish(api).json()["revision"] == example.revision                      # idempotent

    listing = api.get("/catalog").json()
    assert len(listing) == 1
    entry = listing[0]
    assert (entry["name"], entry["pinned"], entry["latest"]) == ("billing-support", None, example.revision)
    assert entry["description"] == example.description
    assert [r["revision"] for r in entry["revisions"]] == [example.revision]
    assert entry["revisions"][0]["published_at"] and entry["revisions"][0]["retired"] is False

    hits = api.get("/catalog/search", params={"q": "refund"}).json()
    assert hits[0]["name"] == "billing-support" and hits[0]["revision"] == example.revision
    assert hits[0]["score"] > 0 and hits[0]["description"] == example.description
    assert api.get("/catalog/search", params={"q": "zzz"}).json() == []

    for ref in ("billing-support", f"billing-support@{example.revision}", "billing-support@latest"):
        info = api.get(f"/catalog/{ref}").json()
        assert info["name"] == "billing-support" and info["revision"] == example.revision
    assert info["id"] == example.id and info["aip_version"] == "0.4a0" and info["retired"] is False
    assert info["meta"]["name"] == "billing-support"
    assert info["start"]["step"] == "triage" and info["start"]["inputs"] == {"message": "string"}
    assert set(info["start"]["questions"]) == {"billing", "tone"}
    assert info["end"] == {"step": "end", "kind": "end", "inputs": {"message": "string"}}
    assert info["steps"] == {"triage": "decision", "by-tone": "router", "escalate": "execution",
                             "reply": "client_task", "end": "end"}
    assert info["example_input"] == {"message": "<string>"}
    assert info["purpose"].startswith("Turn an inbound billing message")
    assert len(info["trigger_when"]) == 2 and len(info["do_not_use_when"]) == 1
    assert [s["name"] for s in info["step_details"]] == ["triage", "by-tone", "escalate", "reply", "end"]
    assert {"router": "by-tone", "value": "angry", "to": "escalate"} in info["branches"]
    assert {f["path"] for f in info["files"]} == {f.path for f in example.files}
    assert api.get("/catalog/billing-support@0000000000000000").status_code == 404


def test_publish_rejects_invalid_and_unsafe_uploads(api, tmp_path):
    import shutil

    broken = tmp_path / "broken"
    shutil.copytree(EXAMPLE, broken)
    (broken / "SKILL.md").write_text((broken / "SKILL.md").read_text()
                                     .replace("name: billing-support", "name: broken")
                                     .replace("inputs_to: by-tone", "inputs_to: nowhere"))
    r = publish(api, broken)
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["kind"] == "invalid_skill"
    assert any(i["kind"] == "unknown_step" or "nowhere" in i["message"] for i in err["issues"]), err["issues"]
    assert all(not i["path"].startswith("/") for i in err["issues"])          # temp folder not leaked

    r = api.post("/catalog", json={"files": [{"path": "../x", "bytes_b64": "aGk="}]})
    assert r.status_code == 422 and r.json()["error"]["kind"] == "invalid_request"
    r = api.post("/catalog", json={"files": [{"path": "README.md", "bytes_b64": "aGk="}]})
    assert r.status_code == 422 and r.json()["error"]["kind"] == "invalid_skill"
    r = api.post("/catalog", json={"files": [{"path": "SKILL.md", "bytes_b64": "!!!"}]})
    assert r.status_code == 422 and r.json()["error"]["kind"] == "invalid_request"
    assert api.get("/catalog").json() == []


# --------------------------------------------------------------------------- files


def test_files_manifest_single_file_and_tar(api, example, tmp_path):
    publish(api)
    manifest = api.get("/catalog/billing-support/files").json()
    assert {m["path"] for m in manifest} == {f.path for f in example.files}
    assert all(set(m) == {"path", "size", "sha256", "mode"} for m in manifest)

    r = api.get("/catalog/billing-support/files/scripts/escalate.py")
    assert r.status_code == 200 and r.content == (EXAMPLE / "scripts" / "escalate.py").read_bytes()
    assert r.headers["content-type"].startswith("text/x-python")
    assert api.get("/catalog/billing-support/files/nope.md").status_code == 404

    r = api.get("/catalog/billing-support/files", params={"archive": "tar"})
    assert r.status_code == 200 and r.headers["content-type"] == "application/x-tar"
    assert f'billing-support@{example.revision}.tar' in r.headers["content-disposition"]
    with tarfile.open(fileobj=io.BytesIO(r.content)) as tar:
        names = tar.getnames()
        tar.extractall(tmp_path / "out", filter="tar")
    assert ".aip-manifest.json" in names
    shipped = json.loads((tmp_path / "out" / ".aip-manifest.json").read_text())
    assert shipped["id"] == example.id and "content" not in shipped["files"][0]
    folder = tmp_path / "out" / "billing-support"
    for entry in shipped["files"]:
        assert hashlib.sha256((folder / entry["path"]).read_bytes()).hexdigest() == entry["sha256"], entry["path"]
    assert tree(folder) == tree(EXAMPLE)
    assert snapshot(folder).revision == example.revision                          # a lossless copy
    assert api.get("/catalog/billing-support/files", params={"archive": "zip"}).status_code == 422


# ---------------------------------------------------------------- pin and retire


def test_pin_and_retire(api, example, tmp_path):
    import shutil

    publish(api)
    second = tmp_path / "billing-support"
    shutil.copytree(EXAMPLE, second)
    (second / "assets" / "policy.md").write_text("revised policy\n")
    v2 = publish(api, second).json()["revision"]
    assert v2 != example.revision
    assert api.get("/catalog/billing-support").json()["revision"] == v2

    assert api.post("/catalog/billing-support/pin", json={"revision": example.revision}).status_code == 200
    assert api.get("/catalog/billing-support").json()["revision"] == example.revision
    assert api.get("/catalog/billing-support@latest").json()["revision"] == v2
    assert api.get("/catalog").json()[0]["pinned"] == example.revision
    assert api.post("/catalog/billing-support/pin", json={"revision": None}).status_code == 200
    assert api.get("/catalog/billing-support").json()["revision"] == v2

    assert api.post("/catalog/billing-support/retire", json={"revision": v2}).status_code == 200
    assert api.get("/catalog/billing-support").json()["revision"] == example.revision
    rows = {r["revision"]: r for r in api.get("/catalog").json()[0]["revisions"]}
    assert rows[v2]["retired"] is True and rows[example.revision]["retired"] is False
    assert api.post("/catalog/billing-support/retire", json={}).status_code == 422
    assert api.post("/catalog/billing-support/pin", json={"revision": "0000000000000000"}).status_code == 404
    assert api.post("/catalog/nope/retire", json={"revision": v2}).status_code == 404


# ---------------------------------------------------------------------------- auth


def test_bearer_token_scopes(backend, no_key):
    app = create_app(backend, tokens={"rw": {"read", "publish"}, "ro": {"read"}})
    api = TestClient(app, client=("203.0.113.7", 40000))
    r = publish(api)
    assert r.status_code == 401 and r.json()["error"]["kind"] == "missing_token"
    assert api.get("/catalog").status_code == 401
    r = publish(api, headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401 and r.json()["error"]["kind"] == "invalid_token"
    r = publish(api, headers={"Authorization": "Bearer ro"})
    assert r.status_code == 403 and r.json()["error"]["kind"] == "forbidden"
    assert publish(api, headers={"Authorization": "Bearer rw"}).status_code == 201
    assert api.get("/catalog", headers={"Authorization": "Bearer ro"}).status_code == 200
    assert api.get("/catalog/billing-support", headers={"Authorization": "Bearer ro"}).status_code == 200
    r = api.post("/catalog/billing-support/pin", json={"revision": None}, headers={"Authorization": "Bearer ro"})
    assert r.status_code == 403

    # a loopback client needs no token
    local = TestClient(app, client=("127.0.0.1", 40000))
    assert local.get("/catalog").status_code == 200
    assert local.post("/catalog/billing-support/pin", json={"revision": None}).status_code == 200
    strict = TestClient(create_app(backend, tokens={"rw": {"read", "publish"}}, localhost_open=False),
                        client=("127.0.0.1", 40000))
    assert strict.get("/catalog").status_code == 401


# ----------------------------------------------------------------------- execution


def test_capabilities(backend, no_key):
    publish(TestClient(create_app(backend)))
    plain = TestClient(create_app(backend)).get("/procedures/billing-support/capabilities").json()
    assert plain == {"name": "billing-support", "revision": snapshot(EXAMPLE).revision,
                     "decision_model": False, "executes_scripts": True, "persists_runs": True}
    with_model = TestClient(create_app(backend, client=FakeJev(0.9))).get("/procedures/billing-support/capabilities").json()
    assert with_model["decision_model"] is True
    with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "k"}):
        assert TestClient(create_app(backend)).get("/procedures/billing-support/capabilities").json()["decision_model"]
    assert TestClient(create_app(backend)).get("/procedures/nope/capabilities").status_code == 404


def test_manual_traversal_angry_branch_runs_the_script_on_the_server(api, example):
    """running.md, "Without a decision model": the client answers triage itself, the router
    sends `angry` to the script, which runs here, and `end` closes the run."""
    publish(api)
    start = {"message": "I was charged twice!"}

    node = api.post("/procedures/billing-support/peek", json={"after": None, "payload": start}).json()
    assert (node["step"], node["kind"]) == ("triage", "decision")
    assert set(node["questions"]) == {"billing", "tone"} and node["inputs"] == {"message": "string"}
    assert node["questions"]["tone"]["criteria"]["angry"] == "Frustrated, demanding, or threatening to leave."

    r = api.post("/procedures/billing-support/step", json={"after": None, "payload": start, "history": []})
    assert r.status_code == 422
    assert r.json()["error"] == {"kind": "no_decision_model", "location": "triage",
                                 "message": r.json()["error"]["message"]}
    assert "/answer" in r.json()["error"]["message"]

    r = api.post("/procedures/billing-support/answer",
                 json={"after": None, "payload": start, "history": [], "answers": {"billing": True, "tone": "angry"}})
    assert r.status_code == 200, r.text
    first = r.json()
    assert (first["ran"], first["kind"], first["review"]) == ("triage", "decision", [])
    assert first["suggested"] == {"message": "I was charged twice!", "billing": True, "tone": "angry"}
    assert first["result"]["answers"]["tone"] == {"type": "choice", "manual": "angry"}
    assert first["next"]["kind"] == "router" and set(first["next"]["branches"]) == {"angry", "calm"}
    assert first["history"][0]["manual"] is True
    assert first["run_id"] and first["name"] == "billing-support" and first["revision"] == example.revision
    run_id = first["run_id"]

    run = api.get(f"/runs/{run_id}").json()
    assert run["status"] == "running" and [e["step"] for e in run["history"]] == ["triage"]

    # the router is walked server-side, then the script opens the ticket
    r = api.post("/procedures/billing-support/step",
                 json={"after": "triage", "payload": first["suggested"], "history": first["history"], "run_id": run_id})
    assert r.status_code == 200, r.text
    second = r.json()
    assert (second["ran"], second["kind"]) == ("escalate", "execution")
    assert second["result"]["queue"] == "tier2" and isinstance(second["result"]["ticket_id"], int)
    assert second["suggested"]["ticket_id"] == second["result"]["ticket_id"]
    assert second["next"] == {"step": "end", "kind": "end", "inputs": {"message": "string"}}
    assert [h["step"] for h in second["history"]] == ["triage", "by-tone", "escalate"]
    assert second["history"][1] == {"step": "by-tone", "kind": "router", "input": {"tone": "angry"},
                                    "result": {"to": "escalate"}}
    assert second["run_id"] == run_id

    r = api.post("/procedures/billing-support/step",
                 json={"after": "escalate", "payload": second["suggested"], "history": second["history"],
                       "run_id": run_id})
    assert r.status_code == 200, r.text
    last = r.json()
    assert last["next"] is None and last["kind"] == "end"
    assert last["result"] == second["suggested"]
    assert [h["step"] for h in last["history"]] == ["triage", "by-tone", "escalate", "end"]

    run = api.get(f"/runs/{run_id}").json()
    assert run["status"] == "done" and run["pause"] is None
    assert run["history"] == last["history"]
    assert (run["name"], run["revision"]) == ("billing-support", example.revision)
    listing = api.get("/runs").json()
    assert [r["run_id"] for r in listing] == [run_id]
    assert listing[0]["status"] == "done" and listing[0]["steps"] == 4
    assert api.get("/runs", params={"status": "paused"}).json() == []
    assert api.get("/runs", params={"name": "billing-support", "status": "done"}).json()[0]["run_id"] == run_id


def test_model_traversal_review_then_calm_branch_pauses_as_a_client_task(backend, no_key, example):
    """running.md, "With a decision model": tone comes back at 0.55 < 0.6 so the response carries a
    review; the client overrides to calm, the router sends it to the client task, the client
    does the task and `end` accepts the reply as an extra key."""
    api = TestClient(create_app(backend, client=FakeJev(0.55, 0.97)), raise_server_exceptions=False)
    publish(api)
    start = {"message": "I was charged twice!"}

    r = api.post("/procedures/billing-support/step", json={"after": None, "payload": start, "history": []})
    assert r.status_code == 200, r.text
    first = r.json()
    assert first["ran"] == "triage" and first["suggested"]["tone"] == "angry" and first["suggested"]["billing"] is True
    assert first["review"] == [{"question": "tone", "type": "choice", "confidence": 0.55,
                                "probabilities": {"angry": 0.55, "calm": 0.45}, "reason": "confidence below 0.6"}]
    assert first["result"]["answers"]["billing"]["noul"] == 0.97
    run_id = first["run_id"]
    run = api.get(f"/runs/{run_id}").json()
    assert run["status"] == "paused"
    assert run["pause"]["kind"] == "review" and run["pause"]["step"] == "triage"
    assert run["pause"]["expects"] == {"message": "string", "tone": "string"}
    assert api.get("/runs", params={"status": "paused"}).json()[0]["run_id"] == run_id

    # a threshold override for this call passes the same answer through without review
    r = api.post("/procedures/billing-support/step",
                 json={"after": None, "payload": start, "history": [], "thresholds": {"tone": 0.5}})
    assert r.status_code == 200 and r.json()["review"] == []
    assert r.json()["run_id"] != run_id                                              # a second run

    # the client overrides tone -> calm; the router sends it to the client task
    r = api.post("/procedures/billing-support/step",
                 json={"after": "triage", "payload": {**first["suggested"], "tone": "calm"},
                       "history": first["history"], "run_id": run_id})
    assert r.status_code == 200, r.text
    second = r.json()
    assert (second["ran"], second["kind"]) == ("reply", "client_task")
    assert "Duplicate charges are refunded in full" in second["result"]["task"]       # the policy asset
    assert "I was charged twice!" in second["result"]["task"]
    assert second["result"]["references"][0]["uri"] == "billing-support/references/help.md"
    assert second["suggested"] == {"message": "I was charged twice!", "billing": True, "tone": "calm"}
    assert second["next"] == {"step": "end", "kind": "end", "inputs": {"message": "string"}}
    assert second["history"][1] == {"step": "by-tone", "kind": "router", "input": {"tone": "calm"},
                                    "result": {"to": "reply"}}
    run = api.get(f"/runs/{run_id}").json()
    assert run["status"] == "paused" and run["pause"]["kind"] == "client_task"
    assert run["pause"]["step"] == "reply" and run["pause"]["expects"] == {"message": "string"}
    assert "Duplicate charges" in run["pause"]["task"]

    reply = "Sorry about the duplicate charge. A full refund is on its way within 5 business days."
    r = api.post("/procedures/billing-support/step",
                 json={"after": "reply", "payload": {**second["suggested"], "reply": reply},
                       "history": second["history"], "run_id": run_id})
    assert r.status_code == 200, r.text
    last = r.json()
    assert last["next"] is None and last["result"]["reply"] == reply and last["result"]["tone"] == "calm"
    assert [h["step"] for h in last["history"]] == ["triage", "by-tone", "reply", "end"]
    run = api.get(f"/runs/{run_id}").json()
    assert run["status"] == "done" and run["pause"] is None and len(run["history"]) == 4
    assert run["history"][0]["result"]["answers"]["tone"]["probabilities"] == {"angry": 0.55, "calm": 0.45}


def test_execution_errors(api, example):
    publish(api)
    r = api.post("/procedures/billing-support/answer",
                 json={"after": None, "payload": {"msg": "typo"}, "history": [], "answers": {"billing": True, "tone": "calm"}})
    assert r.status_code == 422
    assert r.json()["error"]["kind"] == "invalid_input" and r.json()["error"]["location"] == "triage"
    assert any("message" in e for e in r.json()["error"]["errors"])

    r = api.post("/procedures/billing-support/answer",
                 json={"after": None, "payload": {"message": "x"}, "history": [], "answers": {"billing": True}})
    assert r.status_code == 422 and "tone" in r.json()["error"]["message"]

    r = api.post("/procedures/billing-support/step",
                 json={"after": "triage", "payload": {"message": "x", "tone": "furious"}, "history": []})
    assert r.status_code == 422 and r.json()["error"]["location"] == "by-tone"

    r = api.post("/procedures/billing-support/step", json={"after": "nope", "payload": {}, "history": []})
    assert r.status_code == 422 and r.json()["error"]["kind"] == "invalid_request"

    r = api.post("/procedures/billing-support/answer",
                 json={"after": "triage", "payload": {"message": "x", "tone": "angry"}, "history": [],
                       "answers": {}})
    assert r.status_code == 422 and r.json()["error"]["kind"] == "not_a_decision"

    r = api.post("/procedures/billing-support/step",
                 json={"after": "triage", "payload": {"message": "x", "tone": "angry"}, "history": [],
                       "run_id": "nope"})
    assert r.status_code == 404
    assert api.get("/runs").json() == []                                       # nothing recorded for failures

    r = api.post("/procedures/nope/peek", json={"after": None, "payload": {}})
    assert r.status_code == 404
    assert api.post("/procedures/billing-support/peek",
                    json={"after": "escalate", "payload": {}}).json() == {"step": "end", "kind": "end",
                                                                          "inputs": {"message": "string"}}


def test_runs_endpoints(api, example):
    publish(api)
    r = api.post("/runs", json={"name": "billing-support"})
    assert r.status_code == 201
    run_id = r.json()["run_id"]
    assert r.json()["revision"] == example.revision
    run = api.get(f"/runs/{run_id}").json()
    assert run["status"] == "running" and run["history"] == [] and run["pause"] is None
    assert api.post("/runs", json={"name": "nope"}).status_code == 404
    assert api.post("/runs", json={"name": "billing-support", "revision": "0000000000000000"}).status_code == 404

    # a client that brought its own run id continues that run
    r = api.post("/procedures/billing-support/answer",
                 json={"after": None, "payload": {"message": "hi"}, "history": [],
                       "answers": {"billing": False, "tone": "calm"}, "run_id": run_id})
    assert r.status_code == 200 and r.json()["run_id"] == run_id
    assert [e["step"] for e in api.get(f"/runs/{run_id}").json()["history"]] == ["triage"]
    assert len(api.get("/runs").json()) == 1


def test_runs_answer_501_without_a_run_backend(backend, no_key):
    class CatalogOnly:
        catalog = backend.catalog

    api = TestClient(create_app(CatalogOnly()))
    publish(api)
    for r in (api.get("/runs"), api.get("/runs/x"), api.post("/runs", json={"name": "billing-support"})):
        assert r.status_code == 501 and r.json()["error"]["kind"] == "not_supported"
    assert api.get("/procedures/billing-support/capabilities").json()["persists_runs"] is False
    r = api.post("/procedures/billing-support/answer",
                 json={"after": None, "payload": {"message": "hi"}, "history": [],
                       "answers": {"billing": False, "tone": "calm"}})
    assert r.status_code == 200 and r.json()["run_id"] is None                 # the step still runs
