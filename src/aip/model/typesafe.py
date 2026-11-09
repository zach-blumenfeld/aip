"""The decision model: an endpoint with the TypeSafe API shape, as a `Resolver` (`aip.model.resolver`).

A `Decide` step's questions become TypeSafe's `Noul`, `Choice` and `Score` questions, the
`Read` keys go as the `state` to judge (with the run's history beside them when the step says
`History true`), and the reply's answers come back as the answer objects of spec 2.4
(`aip.model.answers`): a `true_or_false` from the `noul`, a `choice` with its `confidence` and
`probabilities`, a `score` whose `value` is the most probable level with the expected value as
`score`. The model's `legend` is dropped; it repeats the question's criteria.

The model is an endpoint, not a vendor (plan question 7): `typesafe-sdk` speaks to `url`
(`base_url`), which defaults to TypeSafe's own, `DEFAULT_URL`, so any service with that shape
serves. The URL and the key come from `aip config` (`decision_model: {url, api_key}`) or the
environment, `AIP_DECISION_MODEL` and `AIP_DECISION_MODEL_KEY`; `TYPESAFE_API_KEY` is not read.
`TypeSafeResolver.from_environment()` returns None when neither a URL nor a key is given, which
the engine takes as "no decision model configured". A client may be injected (`client=`) for
tests and connection reuse; otherwise one is opened per call. The record names what answered as
`{"model": <the reply's model>, "endpoint": <url>}`."""

from __future__ import annotations

import os
from typing import Any

from aip.model import answers
from aip.model.resolver import Decision, DecisionRequest
from aip.model.types import JSON

URL_ENV = "AIP_DECISION_MODEL"
KEY_ENV = "AIP_DECISION_MODEL_KEY"
DEFAULT_URL = "https://api.typesafe.ai"
NAME = "typesafe"


def question_payload(request: DecisionRequest) -> dict[str, Any]:
    """TypeSafe's question objects, by name, for the request's questions."""
    from typesafe_sdk import Choice, Noul, Score

    out: dict[str, Any] = {}
    for q in request.questions:
        criteria = dict(q.criteria)
        if q.type == "true_or_false":
            noul_criteria = {k: v for k, v in criteria.items() if k in ("true", "false")}
            out[q.name] = Noul(instructions=q.instruction, criteria=noul_criteria or None)
        elif q.type == "choice":
            out[q.name] = Choice(instructions=q.instruction, criteria={label: criteria.get(label) for label in (q.labels or [])})
        elif q.type == "score":
            out[q.name] = Score(instructions=q.instruction, criteria=[criteria.get(label) or label for label in (q.labels or [])])
        else:
            raise ValueError(f"{q.name} has type {q.type}, which is not a question type")
    return out


def state_payload(request: DecisionRequest) -> JSON:
    """What the model judges: the `Read` keys as `state`, the history beside them when sent."""
    payload: JSON = {"state": request.state}
    if request.history is not None:
        payload["history"] = request.history
    return payload


def answer_object(answer: JSON) -> JSON:
    """One of TypeSafe's answers (`{"type": "noul" | "choice" | "score", ...}`) as the answer
    object the state holds (spec 2.4)."""
    match answer.get("type"):
        case "noul":
            return answers.true_or_false(float(answer["noul"]))
        case "choice":
            return {"value": answer["choice"], "confidence": float(answer["confidence"]),
                    "probabilities": {str(k): float(v) for k, v in answer["probabilities"].items()}}
        case "score":
            probabilities = {str(k): float(v) for k, v in answer["probabilities"].items()}
            level = int(max(probabilities, key=probabilities.get))
            return {"value": level, "confidence": float(answer["confidence"]), "score": float(answer["score"]),
                    "probabilities": probabilities}
    raise ValueError(f"unknown answer type {answer.get('type')!r}")


class TypeSafeResolver:
    """Answers decisions at an endpoint with the TypeSafe API shape. `client` is an injected
    client (anything with `system_one(state=, questions=)`); otherwise one is opened per decision
    on `url` (default `DEFAULT_URL`) with `api_key`."""

    name = NAME

    def __init__(self, client: Any = None, api_key: str | None = None, url: str | None = None, model: str | None = None):
        self.client = client
        self.api_key = api_key
        self.url = (url or DEFAULT_URL).rstrip("/")
        self.model = model

    @classmethod
    def from_environment(cls, client: Any = None, api_key: str | None = None, url: str | None = None) -> "TypeSafeResolver | None":
        """A resolver when a client is injected, or a key or a URL is given or set in the
        environment (`AIP_DECISION_MODEL_KEY`, `AIP_DECISION_MODEL`); else None: no model."""
        url = url or os.environ.get(URL_ENV) or None
        if client is not None:
            return cls(client, url=url)
        key = api_key or os.environ.get(KEY_ENV) or None
        return cls(api_key=key, url=url) if key or url else None

    def ask(self, request: DecisionRequest) -> JSON:
        """The model's reply as JSON: `{"model", "usage", "answers": {name: {...}}}`."""
        questions = question_payload(request)
        payload = state_payload(request)
        if self.client is not None:
            result = self.client.system_one(state=payload, questions=questions)
        else:
            from typesafe_sdk import TypeSafeClient

            with TypeSafeClient(api_key=self.api_key, model=self.model, base_url=self.url) as client:
                result = client.system_one(state=payload, questions=questions)
        return result if isinstance(result, dict) else result.model_dump(mode="json")

    def decide(self, request: DecisionRequest) -> Decision:
        result = self.ask(request)
        given = result.get("answers") or {}
        return Decision(result.get("model") or NAME, {name: answer_object(given[name]) for name in given}, self.url)


__all__ = ["URL_ENV", "KEY_ENV", "DEFAULT_URL", "NAME", "TypeSafeResolver", "question_payload", "state_payload", "answer_object"]
