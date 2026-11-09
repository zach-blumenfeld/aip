"""The decision model behind a `Decide` step, as the engine sees it.

A resolver is anything with a `name` and a `decide(request)` method that returns the answers:
one answer object per question (`aip.model.answers`), under the question's name, and the name
of the model that gave them. The engine renders the questions, projects the state, calls the
resolver once per decision, checks the answers against the questions and writes the one
decision key. A resolver that raises fails the step, or hands it to the agent when the step says
`Agent_Fallback true`.

`ScriptedResolver` is the test resolver this milestone ships: the answers are given up front,
per step, as answer objects or as a function of the request. The TypeSafe resolver arrives with
the next milestone and implements the same two members."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable

from aip.model.procedure import Question
from aip.model.types import JSON


@dataclass
class DecisionRequest:
    """What a decision asks the model: the step, its questions with their instructions rendered
    (`{key}` filled in from the state), the `Read` keys as `state` (the thing to judge), and the
    run's history when the step says `History true`."""
    step: str
    questions: list[Question]
    state: JSON
    history: list[JSON] | None = None

    def question(self, name: str) -> Question | None:
        return next((q for q in self.questions if q.name == name), None)


@dataclass
class Decision:
    """A resolver's reply: the model's name and one answer object per question."""
    model: str
    answers: JSON


@runtime_checkable
class Resolver(Protocol):
    name: str

    def decide(self, request: DecisionRequest) -> Decision: ...


Script = JSON | Callable[[DecisionRequest], JSON]


@dataclass
class ScriptedResolver:
    """Answers decisions from a script: `answers` maps a step name to its answer objects, or to
    a function of the request that returns them; a function alone answers every step. A step
    with no script raises `KeyError`, which the engine treats as the model failing. Every
    request is kept in `requests` for assertions."""

    answers: dict[str, Script] | Callable[[DecisionRequest], JSON]
    name: str = "scripted"
    requests: list[DecisionRequest] = field(default_factory=list)

    def decide(self, request: DecisionRequest) -> Decision:
        self.requests.append(request)
        if callable(self.answers):
            given: Any = self.answers(request)
        else:
            script = self.answers[request.step]
            given = script(request) if callable(script) else script
        return Decision(self.name, dict(given))


__all__ = ["DecisionRequest", "Decision", "Resolver", "ScriptedResolver"]
