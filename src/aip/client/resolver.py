"""The client resolves decisions: with its own decision model, next to the agent, not on the server.

A run's loop (`aip.model.engine`, on the server or in this process) stops at every decision
with a pause: the questions, the step's declared inputs as `state` (and the run's `history`
when the step asks for it), the questions whose `confidence` the step emits, and whether the
author allows a manual answer (`fallback`). When a TypeSafe key is configured on this client
(`TYPESAFE_API_KEY`, else `aip config --decision-model KEY`), `Resolver.resolve` asks the model
and answers the decision. With no key, a decision with `fallback: true` is printed as it is and
the agent answers it in the model's place; a decision with `fallback: false` stops the run with
`no_decision_model` (`no_decision_model()` builds the error object) until a model is configured
and the run is resumed.

Every answer goes back to the loop with its attribution, which the history records:
`{"resolver": "typesafe"|"manual", "model", "confidence": {question: float}|None}`. A model's
confidence is the one number of `aip.model.steps.confidence` (`|2p - 1|` for a noul, the model's
own for a choice or score), the same the step writes to the state as `<question>_confidence`
for the questions it names; a manual answer has none and writes no confidence key.
"""

from __future__ import annotations

import os
from typing import Annotated, Any, Dict, Union

from pydantic import Field, TypeAdapter
from typesafe_sdk import Choice, Noul, Score, TypeSafeClient

from aip.model.steps import Decision, confidence, manual
from aip.model.types import OutputValidationError

JSON = Dict[str, Any]

KEY_ENV = "TYPESAFE_API_KEY"

_QUESTION = TypeAdapter(Annotated[Union[Noul, Choice, Score], Field(discriminator="type")])


def configured_key() -> str | None:
    """The decision model's key on this client: `TYPESAFE_API_KEY`, else the config file's."""
    from aip.client.server import load_config

    return os.environ.get(KEY_ENV) or (load_config().get("decision_model") or {}).get("api_key") or None


def status() -> str:
    """One line for `aip config`: which model resolves decisions on this client, or that none does."""
    from aip.client.server import config_path

    if os.environ.get(KEY_ENV):
        return f"decision model: TypeSafe (from {KEY_ENV})"
    if configured_key():
        return f"decision model: TypeSafe (from {config_path()})"
    return ("decision model: none; a decision with `fallback: true` pauses for you to answer, any other stops "
            "the run with `no_decision_model` (`aip config --decision-model KEY`)")


def no_decision_model(pause: JSON) -> JSON:
    """The error object for a decision this client cannot answer: no decision model is configured
    and the step does not allow a manual answer. The run waits at the decision; configure a model
    (`TYPESAFE_API_KEY`, or `aip config --decision-model KEY`) and resume it."""
    step = pause["step"]
    return {"error": "no_decision_model", "step": step,
            "message": f"step {step!r} is a decision with `fallback: false` and this client has no decision model: "
                       f"set {KEY_ENV} or run `aip config --decision-model KEY`, then resume the run",
            "fallback": False}


class Resolver:
    """Answers decision pauses with TypeSafe. `client` is an injected TypeSafe client (tests,
    connection reuse); otherwise one is opened per decision with `api_key`."""

    def __init__(self, client: Any = None, api_key: str | None = None):
        self.client = client
        self.api_key = api_key

    @classmethod
    def configured(cls, client: Any = None) -> "Resolver | None":
        """A resolver when this client has a decision model (an injected client or a key), else None."""
        if client is not None:
            return cls(client)
        key = configured_key()
        return cls(api_key=key) if key else None

    def ask(self, pause: JSON) -> JSON:
        """The model's raw response to a decision pause, as JSON."""
        questions = {name: _QUESTION.validate_python(q) for name, q in pause["questions"].items()}
        payload: JSON = {"state": pause["state"]}
        if pause.get("history"):
            payload["history"] = pause["history"]
        if self.client is not None:
            result = self.client.system_one(state=payload, questions=questions)
        else:
            with TypeSafeClient(api_key=self.api_key) as client:
                result = client.system_one(state=payload, questions=questions)
        return result.model_dump(mode="json")

    def resolve(self, pause: JSON) -> JSON:
        """`{"answer", "attribution"}`: each answer collapsed to its value, and the model's
        attribution with a confidence per question."""
        result = self.ask(pause)
        answers = result["answers"]
        missing = [q for q in pause["questions"] if q not in answers]
        if missing:
            raise OutputValidationError(pause["step"], [f"the decision model gave no answer for {missing}"],
                                        missing=missing)
        answer = {name: Decision.collapse(answers[name]) for name in pause["questions"]}
        attribution = {"resolver": "typesafe", "model": result.get("model"),
                       "confidence": {name: confidence(answers[name]) for name in pause["questions"]}}
        return {"answer": answer, "attribution": attribution}


__all__ = ["KEY_ENV", "Resolver", "configured_key", "manual", "no_decision_model", "status"]
