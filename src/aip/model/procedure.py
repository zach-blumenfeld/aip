"""The whole graph and the single server operation, `Procedure.run`."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from aip.model.resources import ResourceLoader
from aip.model.steps import (
    BaseStep, EndStep, Execution, Meta, Node, Router, StepResponse, describe_next,
)
from aip.model.types import JSON, validate_input


@dataclass(kw_only=True)
class Procedure:
    """
    The whole graph. Binds meta, loader, and interpreter to every reachable node and
    exposes the single server operation, `run`.

    python: interpreter for Execution steps (built from Meta.environment on `server create`)
    """
    meta: Meta
    start: BaseStep
    loader: ResourceLoader | None = None
    python: Path | None = None
    nodes: Dict[str, Node] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self._walk(self.start)

    def _walk(self, node: Node | None) -> None:
        if node is None:
            return
        if node.name in self.nodes:
            if self.nodes[node.name] is not node:
                raise ValueError(f"Duplicate step name {node.name!r}")
            return
        self.nodes[node.name] = node
        if isinstance(node, BaseStep):
            if node.meta is None:
                node.meta = self.meta
            if node.loader is None:
                node.loader = self.loader
            if isinstance(node, Execution) and node.python is None:
                node.python = self.python
            self._walk(node.inputsTo)
        elif isinstance(node, Router):
            if len(node.branches) < 2:
                raise ValueError(f"Router {node.name!r} needs at least two branches")
            for target in node.branches.values():
                self._walk(target)

    @property
    def end(self) -> EndStep | None:
        return next((n for n in self.nodes.values() if isinstance(n, EndStep)), None)

    def describe(self) -> JSON:
        """For `aip info`: meta plus the start and end shapes."""
        return {
            "meta": {"name": self.meta.name, "description": self.meta.description, "version": self.meta.version},
            "start": describe_next(self.start),
            "end": describe_next(self.end),
            "steps": {name: node.kind for name, node in self.nodes.items()},
        }

    def run(self, after: str | None, payload: JSON, history: List[JSON] | None = None,
            thresholds: Dict[str, float] | None = None) -> StepResponse:
        """
        The single server operation.

        after:   name of the step the client just completed, or None to start
        payload: the client's accepted input for whatever comes next
        history: the history the client carried in
        """
        history = list(history or [])
        if after is None:
            node: Node | None = self.start
        else:
            prev = self.nodes.get(after)
            if not isinstance(prev, BaseStep):
                raise KeyError(f"No runnable step named {after!r}")
            node = prev.inputsTo

        # Server-side traversal: walk routers on the client's accepted input.
        while isinstance(node, Router):
            target = node.route(payload)
            history.append({"step": node.name, "kind": node.kind,
                            "input": {node.branch_on: payload[node.branch_on]}, "result": {"to": target.name}})
            node = target

        if node is None or isinstance(node, EndStep):
            end = node or EndStep()
            validate_input(end.name, end.inputs, payload)
            history.append({"step": end.name, "kind": end.kind, "input": payload, "result": payload})
            return StepResponse(ran=end.name, kind=end.kind, result=payload, suggested=payload,
                                review=[], next=None, history=history)

        return node.accept(payload, history, thresholds=thresholds)
