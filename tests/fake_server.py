"""An in-memory AIP server speaking the contract `aip.client.server` lists, so the client's
tests run before the server milestone (aip-dev#1, S1) implements it for real. It stands in
for an httpx session: `Server(url, session=FakeServer())`. S1's contract tests replace it with
the FastAPI app under `TestClient`; the shapes here are what the client expects of them.

The catalog is `name -> [revisions]`, each revision a bundle id; the bundles themselves are kept
as bytes and read back with `aip.compiler.read_bundle` for their name and description, so this
needs Relate like everything that touches a bundle."""

from __future__ import annotations

import json as jsonlib
import tempfile
from pathlib import Path
from typing import Any

from aip.compiler import read_bundle

from aip.model import Procedure
from aip.sdk import describe_procedure

JSON = dict[str, Any]


class FakeResponse:
    def __init__(self, status: int, body: Any = None, content: bytes | None = None):
        self.status_code = status
        self._body = body
        self.content = content if content is not None else jsonlib.dumps(body).encode("utf-8")

    def json(self) -> Any:
        if self._body is None:
            raise ValueError("no JSON body")
        return self._body

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", "replace")


class Unreachable(Exception):
    """What a session raises when nothing answers."""


class DownSession:
    """A session whose server is down: every request raises."""

    def request(self, method: str, path: str, **kwargs: Any):
        import httpx

        raise httpx.ConnectError(f"[Errno 61] Connection refused ({method} {path})")


class FakeServer:
    def __init__(self, token_names: dict[str, str] | None = None):
        self.bundles: dict[str, bytes] = {}
        self.descriptions: dict[str, JSON] = {}
        self.catalog: dict[str, list[JSON]] = {}       # name -> [{"revision", "bundle_id", "retired"}]
        self.pins: dict[str, str] = {}
        self.runs: dict[str, JSON] = {}
        self.requests: list[tuple[str, str]] = []
        self.token_names = token_names or {}

    # ------------------------------------------------------------ the session's method

    def request(self, method: str, path: str, headers: JSON | None = None, params: JSON | None = None, json: Any = None,
                content: bytes | None = None, **_: Any) -> FakeResponse:
        self.requests.append((method, path))
        headers, params = headers or {}, params or {}
        parts = [p for p in path.split("/") if p]
        try:
            if parts == ["catalog"] and method == "GET":
                return FakeResponse(200, [self._entry(name) for name in sorted(self.catalog)])
            if parts == ["catalog", "search"]:
                return FakeResponse(200, self._search(params.get("q", ""), int(params.get("limit", 10))))
            if parts == ["catalog"] and method == "POST":
                return FakeResponse(200, self._publish(content or b""))
            if parts == ["bundles"] and method == "POST":
                bundle_id = self._store(content or b"")
                return FakeResponse(200, {"bundle_id": bundle_id, "existed": bundle_id in self.bundles})
            if len(parts) == 2 and parts[0] == "catalog" and method == "GET":
                name, revision, bundle_id = self._resolve(parts[1])
                if headers.get("Accept") == "application/octet-stream":
                    return FakeResponse(200, None, self.bundles[bundle_id])
                return FakeResponse(200, {**self.descriptions[bundle_id], "name": name, "revision": revision, "bundle_id": bundle_id,
                                          "draft": False})
            if len(parts) == 3 and parts[0] == "catalog" and parts[2] in ("pin", "retire"):
                return FakeResponse(200, self._pin_or_retire(parts[1], parts[2], json or {}))
            if parts == ["runs"] and method == "POST":
                if (json or {}).get("bundle_id") not in self.bundles:
                    return self._error(404, "unknown_bundle", f"the store holds no bundle {(json or {}).get('bundle_id')}")
                return FakeResponse(200, self._record(json or {}, headers.get("Authorization")))
            if parts == ["runs"] and method == "GET":
                return FakeResponse(200, self._runs(params))
            if len(parts) == 2 and parts[0] == "runs":
                if parts[1] not in self.runs:
                    return self._error(404, "not_found", f"no run {parts[1]}")
                return FakeResponse(200, self.runs[parts[1]])
            if parts == ["governance"]:
                return FakeResponse(200, [{"query": "hand-answers", "description": "decisions the agent answered"}])
            if len(parts) == 2 and parts[0] == "governance":
                return FakeResponse(200, [{"query": parts[1], "params": {k: v for k, v in params.items()}}])
        except KeyError as exc:
            return self._error(404, "not_found", str(exc.args[0]) if exc.args else "not found")
        return self._error(404, "not_found", f"no route {method} {path}")

    @staticmethod
    def _error(status: int, kind: str, message: str, **extra: Any) -> FakeResponse:
        return FakeResponse(status, {"error": {"kind": kind, "message": message, **extra}})

    # ------------------------------------------------------------ the catalog

    def _store(self, data: bytes) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "upload.rl"
            path.write_bytes(data)
            bundle = read_bundle(path)
        if bundle.id not in self.bundles:
            self.bundles[bundle.id] = data
            with Procedure.load(bundle) as procedure:
                self.descriptions[bundle.id] = describe_procedure(procedure)
        return bundle.id

    def _publish(self, data: bytes) -> JSON:
        existed = None
        bundle_id = self._store(data)
        name = self.descriptions[bundle_id]["name"]
        revisions = self.catalog.setdefault(name, [])
        for r in revisions:
            if r["bundle_id"] == bundle_id:
                existed = r
        if existed is None:
            existed = {"revision": str(len(revisions) + 1), "bundle_id": bundle_id, "retired": False}
            revisions.append(existed)
            return {"name": name, "revision": existed["revision"], "bundle_id": bundle_id, "existed": False}
        return {"name": name, "revision": existed["revision"], "bundle_id": bundle_id, "existed": True}

    def _live(self, name: str) -> list[JSON]:
        return [r for r in self.catalog.get(name, []) if not r["retired"]]

    def _entry(self, name: str) -> JSON:
        live = self._live(name)
        latest = live[-1]["revision"] if live else None
        resolves = self.pins.get(name) or latest
        bundle_id = next((r["bundle_id"] for r in self.catalog[name] if r["revision"] == resolves), None)
        return {"name": name, "description": self.descriptions[bundle_id]["description"] if bundle_id else None,
                "pinned": self.pins.get(name), "latest": latest, "resolves": resolves,
                "revisions": [dict(r) for r in reversed(self.catalog[name])]}

    def _resolve(self, ref: str) -> tuple[str, str, str]:
        name, _, revision = ref.partition("@")
        if name not in self.catalog:
            raise KeyError(f"no procedure {name!r}")
        if not revision or revision == "latest":
            revision = self._entry(name)["resolves"]
            if revision is None:
                raise KeyError(f"{name} has no live revision")
        found = next((r for r in self.catalog[name] if r["revision"] == revision), None)
        if found is None:
            raise KeyError(f"no revision {revision} of {name}")
        return name, revision, found["bundle_id"]

    def _search(self, query: str, limit: int) -> list[JSON]:
        hits = []
        for name in sorted(self.catalog):
            entry = self._entry(name)
            if entry["resolves"] is None:
                continue
            _, revision, bundle_id = self._resolve(name)
            text = (name + " " + (entry["description"] or "")).lower()
            score = sum(1.0 for word in query.lower().split() if word in text)
            if score:
                hits.append({"name": name, "revision": revision, "bundle_id": bundle_id, "score": score,
                             "description": entry["description"]})
        return sorted(hits, key=lambda h: -h["score"])[:limit]

    def _pin_or_retire(self, name: str, action: str, body: JSON) -> JSON:
        if name not in self.catalog:
            raise KeyError(f"no procedure {name!r}")
        revision = body.get("revision")
        if action == "pin":
            if revision is None:
                self.pins.pop(name, None)
            else:
                self.pins[name] = str(revision)
            return {"name": name, "pinned": self.pins.get(name)}
        for r in self.catalog[name]:
            if r["revision"] == str(revision):
                r["retired"] = True
        return {"name": name, "revision": revision, "retired": True}

    # ------------------------------------------------------------ runs

    def _record(self, run: JSON, authorization: str | None) -> JSON:
        token = authorization.removeprefix("Bearer ").strip() if authorization else None
        user = self.token_names.get(token) if token else None
        stored = {**run, "identity": {**(run.get("identity") or {}), "user": user}}
        self.runs[run["run_id"]] = stored
        return {"run_id": run["run_id"], "user": user}

    def _runs(self, params: JSON) -> list[JSON]:
        rows = list(self.runs.values())
        for key in ("name", "status"):
            if params.get(key):
                rows = [r for r in rows if r.get(key) == params[key]]
        for key in ("agent", "session"):
            if params.get(key):
                rows = [r for r in rows if (r.get("identity") or {}).get(key) == params[key]]
        rows.sort(key=lambda r: r.get("updated") or "", reverse=True)
        return [{"run_id": r["run_id"], "name": r.get("name"), "revision": r.get("revision"), "status": r.get("status"),
                 "draft": r.get("draft"), "identity": r.get("identity"), "created": r.get("created"), "updated": r.get("updated")}
                for r in rows[:int(params.get("limit", 50))]]
