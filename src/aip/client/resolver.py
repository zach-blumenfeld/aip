"""The client resolves decisions: with its own decision model, next to the agent, not on the server.

A run's loop (`aip.model.engine`, on the server or in this process) stops at every decision
with a pause: the questions, the step's declared inputs as `state` (and the run's `history`
when the step asks for it), and the author's `thresholds`. When a TypeSafe key is configured
on this client (`TYPESAFE_API_KEY`, else `aip config --decision-model KEY`), `Resolver.resolve`
asks the model and either answers the decision, every question clear of its threshold, or
returns a `review` pause for the agent: the model's `proposed_answers` and the questions under
their thresholds. The agent answers a review with overrides only (`{}` accepts), and
`Resolver.reviewed` turns that into the final answers. With no key the decision pause is
printed as it is and the agent answers it in the model's place.

Every answer goes back to the loop with its attribution, which the history records:
`{"resolver": "typesafe"|"manual", "model", "confidence": {question: float}|None, "reviewed"}`,
plus `proposed` (the model's answers) when a review was answered.
"""

from __future__ import annotations

import os
from typing import Annotated, Any, Dict, Union

from pydantic import Field, TypeAdapter
from typesafe_sdk import Choice, Noul, Score, TypeSafeClient

from aip.model.steps import Decision, confidence, flag, manual
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
    return "decision model: none; every decision pauses for you to answer (`aip config --decision-model KEY`)"


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
        """`{"answer", "attribution"}` when every question cleared its threshold, else the review pause
        (`{"kind": "review", ...}`), which keeps the model's attribution under `resolution`."""
        result = self.ask(pause)
        answers = result["answers"]
        missing = [q for q in pause["questions"] if q not in answers]
        if missing:
            raise OutputValidationError(pause["step"], [f"the decision model gave no answer for {missing}"],
                                        missing=missing)
        proposed = {name: Decision.collapse(answers[name]) for name in pause["questions"]}
        attribution = {"resolver": "typesafe", "model": result.get("model"),
                       "confidence": {name: confidence(answers[name]) for name in pause["questions"]},
                       "reviewed": False}
        flagged = flag({name: answers[name] for name in pause["questions"]}, pause.get("thresholds") or {})
        if not flagged:
            return {"answer": proposed, "attribution": attribution}
        return {"kind": "review", "step": pause["step"], "state": pause["state"], "proposed_answers": proposed,
                "review": flagged, "resolution": attribution}


def reviewed(pause: JSON, overrides: JSON | None) -> JSON:
    """The final answers to a review pause and their attribution: the proposed answers with the
    agent's overrides over them. Raises `OutputValidationError` for an answer that overrides
    anything but the step's questions (the pause stands)."""
    if overrides is None:
        raise OutputValidationError(pause["step"], [
            f"resume needs an answer for the paused review step {pause['step']!r} (--input <answer.json>; "
            "{} accepts the proposed answers)"], missing=list(pause["proposed_answers"]))
    proposed = pause["proposed_answers"]
    unknown = [k for k in overrides if k not in proposed]
    if unknown:
        raise OutputValidationError(pause["step"], [f"not questions of step {pause['step']!r}: {unknown}; "
                                                    f"override only {list(proposed)}"], invalid=unknown)
    attribution = {**pause["resolution"], "reviewed": True, "proposed": dict(proposed)}
    return {"answer": {**proposed, **overrides}, "attribution": attribution}


__all__ = ["KEY_ENV", "Resolver", "configured_key", "manual", "reviewed", "status"]
