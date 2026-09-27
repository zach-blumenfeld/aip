"""What the runner talks to. One method shape, two homes.

`LocalBackend` wraps a Procedure in-process, which is what `aip run <skill-dir>` uses.
An HTTP backend will post the same arguments to the AIP server and return the same
response; the runner will not change.

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
