"""Answer objects (spec 2.4): what a decision model's reply becomes in the state, built here
so a resolver (the scripted one in `aip.model.resolver`, the TypeSafe one later) and the tests
write the same shapes.

| type            | value                          | model fields                                   |
|-----------------|--------------------------------|------------------------------------------------|
| `true_or_false` | a boolean                      | `noul`, the probability of yes; `confidence` is |2·noul − 1| |
| `choice`        | a label                        | `confidence`; `probabilities`, label to probability |
| `score`         | the most probable level (int)  | `confidence`; `score`, the expected value; `probabilities`, level to probability |

A hand-given answer is `{"value": ...}` and nothing else (`by_hand`). `probability_of` reads the
probability an answer puts on a condition (`== value`), the number an aggregation's bar is on;
it is `noul` or `1 − noul` for a `true_or_false` and `probabilities[label]` for the others, and
None when the answer carries no probabilities."""

from __future__ import annotations

from typing import Any

from aip.model.types import JSON


def true_or_false(noul: float) -> JSON:
    """A `true_or_false` answer from the probability of yes."""
    return {"value": noul >= 0.5, "confidence": round(abs(2 * noul - 1), 6), "noul": noul}


def choice(probabilities: dict[str, float], value: str | None = None) -> JSON:
    """A `choice` answer from the probability of every label; the value is the most probable
    label unless given, and the confidence is its probability."""
    label = value if value is not None else max(probabilities, key=probabilities.get)
    return {"value": label, "confidence": probabilities[label], "probabilities": dict(probabilities)}


def score(probabilities: dict[int | str, float], value: int | None = None) -> JSON:
    """A `score` answer from the probability of every level (0-based); the value is the most
    probable level unless given, `score` the expected level."""
    probs = {str(k): float(v) for k, v in probabilities.items()}
    level = value if value is not None else int(max(probs, key=probs.get))
    expected = sum(int(k) * p for k, p in probs.items())
    return {"value": level, "confidence": probs[str(level)], "score": round(expected, 6), "probabilities": probs}


def by_hand(value: Any) -> JSON:
    """An answer the agent gave: a value and nothing else."""
    return {"value": value}


def probability_of(answer: JSON, type: str, value: Any) -> float | None:
    """The probability `answer` puts on `== value`: `noul` or `1 − noul` for a `true_or_false`,
    the label's or level's entry in `probabilities` otherwise; None when the answer has none."""
    if type == "true_or_false":
        p = answer.get("noul")
        if p is None:
            probs = answer.get("probabilities")
            p = probs.get("true") if isinstance(probs, dict) else None
        if p is None:
            return None
        return float(p) if value is True else 1 - float(p)
    probs = answer.get("probabilities")
    if not isinstance(probs, dict):
        return None
    p = probs.get(str(value))
    return None if p is None else float(p)


__all__ = ["true_or_false", "choice", "score", "by_hand", "probability_of"]
