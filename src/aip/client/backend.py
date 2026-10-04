"""What the runner talks to. One method shape, two homes.

`LocalBackend` wraps a Procedure in-process, which is what `aip run <skill-dir>` uses.
`HttpBackend` posts the same arguments to an AIP server's execution endpoints and
returns the same responses, so the runner does not know which one it has.

Every call is addressed the same way: `after` is the step the client just completed
(None to start) and `payload` is the input for whatever comes next.
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Protocol

JSON = Dict[str, Any]


class Backend(Protocol):
    def describe(self) -> JSON: ...

    def peek(self, after: str | None, payload: JSON) -> JSON | None:
        """Describe the node that will receive `payload` after `after`, routers resolved."""

    def run(self, after: str | None, payload: JSON, history: List[JSON], thresholds: Dict[str, float] | None) -> JSON: ...

    def answer_decision(self, after: str | None, payload: JSON, history: List[JSON], answers: JSON) -> JSON:
        """The client answers the receiving decision step's questions itself."""

    def has_decision_model(self) -> bool: ...


class LocalBackend:
    def __init__(self, skill_dir: Path, client: Any = None, python: Path | None = None):
        from aip.spec.loader import load_procedure

        self.skill_dir = Path(skill_dir)
        self._client = client
        self.procedure = load_procedure(self.skill_dir, client=client, python=python)

    def describe(self) -> JSON:
        return self.procedure.describe()

    def peek(self, after: str | None, payload: JSON) -> JSON | None:
        from aip.model import describe_next

        node, _ = self.procedure.resolve(after, payload)
        return describe_next(node)

    def run(self, after: str | None, payload: JSON, history: List[JSON], thresholds: Dict[str, float] | None) -> JSON:
        return self.procedure.run(after, payload, history, thresholds).to_dict()

    def answer_decision(self, after: str | None, payload: JSON, history: List[JSON], answers: JSON) -> JSON:
        from aip.model import Decision

        node, entries = self.procedure.resolve(after, payload)
        if not isinstance(node, Decision):
            raise KeyError(f"the step after {after!r} is not a decision")
        return node.accept_manual(payload, [*history, *entries], answers).to_dict()

    def has_decision_model(self) -> bool:
        return self._client is not None or bool(os.environ.get("TYPESAFE_API_KEY"))


class HttpBackend:
    """The five `Backend` methods over `/procedures/{ref}/...` (design §8).

    `server` is a URL or a `Server`; `name` is `name`, `name@<revision>`, or `name@latest`.
    The first call resolves the ref to an exact revision and every later call uses it, so a
    run never straddles a re-pin. `run` and `answer_decision` carry the `run_id` the server
    assigned (or the one a resumed run file brought), and `run_file_fields()` is what the
    runner writes into the run file so `resume` can rebuild this backend.
    """

    def __init__(self, server: Any, token: str | None = None, name: str = "", *,
                 run_id: str | None = None, session: Any = None):
        from aip.client.server import Server

        self.server = server if isinstance(server, Server) else Server(str(server), token, session=session)
        self.ref = name
        self.name, _, self.revision = name.partition("@")
        if self.revision in ("", "latest"):
            self.revision = None
        self.run_id = run_id
        self._decision_model: bool | None = None

    def _resolve(self) -> None:
        """Pin `ref` to an exact revision and learn the server's capabilities, once."""
        if self._decision_model is None:
            caps = self.server.capabilities(self.ref)
            self.name, self.revision = caps["name"], caps["revision"]
            self.ref = f"{self.name}@{self.revision}"
            self._decision_model = bool(caps["decision_model"])

    def describe(self) -> JSON:
        self._resolve()
        return self.server.info(self.ref)

    def peek(self, after: str | None, payload: JSON) -> JSON | None:
        self._resolve()
        return self.server.post(f"/procedures/{self.ref}/peek", {"after": after, "payload": payload})

    def run(self, after: str | None, payload: JSON, history: List[JSON], thresholds: Dict[str, float] | None) -> JSON:
        self._resolve()
        return self._record(self.server.post(f"/procedures/{self.ref}/step", {
            "after": after, "payload": payload, "history": history, "thresholds": thresholds or None,
            "run_id": self.run_id}))

    def answer_decision(self, after: str | None, payload: JSON, history: List[JSON], answers: JSON) -> JSON:
        self._resolve()
        return self._record(self.server.post(f"/procedures/{self.ref}/answer", {
            "after": after, "payload": payload, "history": history, "answers": answers, "run_id": self.run_id}))

    def _record(self, response: JSON) -> JSON:
        self.run_id = response.get("run_id", self.run_id)
        return response

    def has_decision_model(self) -> bool:
        self._resolve()
        return bool(self._decision_model)

    def run_file_fields(self) -> JSON:
        self._resolve()
        return {"server": self.server.url, "name": self.name, "revision": self.revision, "run_id": self.run_id}
