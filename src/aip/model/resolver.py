"""The decision model behind a `Decide` step, as the engine sees it.

A resolver is anything with a `name` and a `decide(request)` method that returns the answers:
one answer object per question (`aip.model.answers`), under the question's name, and the name
of the model that gave them. The engine renders the questions, projects the state, calls the
resolver once per decision, checks the answers against the questions and writes the one
decision key. A resolver that raises fails the step (`decision_model_failed`), and no resolver
at all fails it too (`no_decision_model`): every `Decide` is a model's (spec 2.4).

A batch of `For` passes whose body is one `Decide` is one request with every pass's questions,
each name suffixed with the pass index (`follows__3`; `aip.model.steps.batch_request`), and the
resolver answers each as it would any question; the engine maps the names back and the record
never shows them (runtime.md, Batching).

`ScriptedResolver` is the test resolver: the answers are given up front, per step, as answer
objects or as a function of the request. `aip.model.typesafe.TypeSafeResolver` is the decision
model, an endpoint with the TypeSafe API shape, implementing the same two members."""

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
    """A resolver's reply: the model's name, one answer object per question, and the endpoint
    that answered (None for a resolver that is not a service, such as the scripted one)."""
    model: str
    answers: JSON
    endpoint: str | None = None

    def answered_by(self) -> JSON:
        """What the record says answered a decision (runtime.md, The record)."""
        return {"model": self.model, "endpoint": self.endpoint}


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
    request is kept in `requests` for assertions.

    In a batched request the questions are `follows__0`, `follows__1`, ...; answer objects given
    under the plain name answer every pass alike, and a function sees the suffixed names and
    each question's own rendered instruction (`question_base` strips the suffix)."""

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
        given = dict(given)
        out: JSON = {}
        for q in request.questions:
            if q.name in given:
                out[q.name] = given[q.name]
            elif question_base(q.name) in given:
                out[q.name] = given[question_base(q.name)]
        bases = {question_base(q.name) for q in request.questions}
        for name, answer in given.items():  # anything else the script gave stays, for the engine to refuse
            if name not in out and name not in bases:
                out[name] = answer
        return Decision(self.name, out)


def question_base(name: str) -> str:
    """The author's question name under a batch suffix: `follows__3` → `follows`."""
    base, sep, suffix = name.rpartition("__")
    return base if sep and suffix.isdigit() else name


__all__ = ["DecisionRequest", "Decision", "Resolver", "ScriptedResolver", "question_base"]
