"""Answer objects (spec 2.4): what a decision model's reply becomes in the state, built here
so a resolver (the scripted one in `aip.model.resolver`, the TypeSafe one later) and the tests
write the same shapes.

| type            | value                          | model fields                                   |
|-----------------|--------------------------------|------------------------------------------------|
| `true_or_false` | a boolean                      | `noul`, the probability of yes; `confidence` is |2·noul − 1| |
| `choice`        | a label                        | `confidence`; `probabilities`, label to probability |
| `score`         | the most probable level's label | `confidence`; `score`, the expected level (a float, levels counted from 0); `probabilities`, label to probability |

An answer an agent produced in a `Task_Agent` is `{"value": ...}` and nothing else; a script's
may carry the model fields it computed (`aip.model.types.ANSWER_FIELDS`). `probability_of` reads
the probability an answer puts on a condition (`== value`), the number a bar (`With
Probability_Above`) is on; it is `noul` or `1 − noul` for a `true_or_false` and
`probabilities[label]` for the others, and None when the answer carries no probabilities. A
route's `Confidence_Below` reads `confidence`, a different number."""

from __future__ import annotations

from typing import Any

from aip.model.types import JSON


def true_or_false(noul: float) -> JSON:
    """A `true_or_false` answer from the probability of yes."""
    return {"value": noul >= 0.5, "confidence": round(abs(2 * noul - 1), 6), "noul": noul}


def choice(probabilities: dict[str, float], value: str | None = None) -> JSON:
    """A `choice` answer from the probability of every label; the value is the most probable
    label unless given, and the confidence is `choice_confidence` of its probability."""
    label = value if value is not None else max(probabilities, key=probabilities.get)
    return {"value": label, "confidence": choice_confidence(probabilities[label], len(probabilities)),
            "probabilities": dict(probabilities)}


def score(probabilities: dict[str, float], value: str | None = None) -> JSON:
    """A `score` answer from the probability of every level, by label in the rubric's order
    (`{"low": 0.1, "medium": 0.2, "high": 0.7}`); the value is the most probable level's label
    unless given, `score` the expected level, the levels counted from 0, and the confidence
    `score_confidence` around the value's level."""
    probs = {str(k): float(v) for k, v in probabilities.items()}
    label = value if value is not None else max(probs, key=probs.get)
    expected = sum(i * p for i, p in enumerate(probs.values()))
    return {"value": label, "confidence": score_confidence(list(probs.values()), list(probs).index(label)),
            "score": round(expected, 6), "probabilities": probs}


# The decision model's own statistics (TypeSafe, https://docs.typesafe.ai/confidence; spec 2.5),
# so an answer built here, by a test or a stand-in model, carries the confidence the real model
# would give the same probabilities: 1 when all of it is on one outcome, 0 at an even spread.

def choice_confidence(p: float, n: int) -> float:
    """How far the chosen label's probability `p` sits above an even split over `n` labels:
    `(n·p − 1) / (n − 1)`, floored at 0; `|2p − 1|` for two labels, and `p` as `n` grows."""
    return 1.0 if n < 2 else round(max(0.0, (n * p - 1) / (n - 1)), 6)


def score_confidence(probabilities: list[float], level: int) -> float:
    """One minus the probability-weighted distance, in levels, from `level` (the most likely),
    over the same distance for an even spread measured from the middle level; floored at 0."""
    n = len(probabilities)
    if n < 2:
        return 1.0
    even = sum(abs(i - (n - 1) / 2) for i in range(n)) / n
    spread = sum(p * abs(i - level) for i, p in enumerate(probabilities))
    return round(max(0.0, 1 - spread / even), 6)


def probability_of(answer: JSON, type: str, value: Any) -> float | None:
    """The probability `answer` puts on `== value`: `noul` or `1 − noul` for a `true_or_false`,
    the label's entry in `probabilities` otherwise; None when the answer has none."""
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


__all__ = ["true_or_false", "choice", "score", "choice_confidence", "score_confidence", "probability_of"]
