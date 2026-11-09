"""The TypeSafe resolver (`aip.model.typesafe`): the questions a `Decide` step becomes, the state
it sends, and the answer objects it makes of the reply (spec 2.4). A fake client stands in for
the service, so no key is needed."""

import unittest

from typesafe_sdk import Choice, Noul, Score, SystemOneResponse

from aip.model import DecisionRequest, TypeSafeResolver
from aip.model.procedure import Question
from aip.model.typesafe import KEY_ENV, answer_object, question_payload, state_payload

REPLY = {
    "model": "jev-1", "usage": {"input_tokens": 1, "output_tokens": 1},
    "answers": {"billing": {"type": "noul", "noul": 0.97},
                "tone": {"type": "choice", "choice": "calm", "confidence": 0.9, "probabilities": {"angry": 0.1, "calm": 0.9}},
                "urgency": {"type": "score", "score": 1.7, "confidence": 0.8, "legend": {0: "low", 1: "medium", 2: "high"},
                            "probabilities": {0: 0.1, 1: 0.1, 2: 0.8}}},
}


class FakeClient:
    def __init__(self, reply=REPLY):
        self.reply = reply
        self.calls = []

    def system_one(self, state, questions, **_):
        self.calls.append((state, questions))
        return SystemOneResponse.model_validate(self.reply)


def request(history=None):
    return DecisionRequest("triage", [
        Question("billing", "true_or_false", None, "Is this about a charge?", [("true", "Money changed hands."), ("false", "Anything else.")], 0),
        Question("tone", "choice", ["angry", "calm"], "How does the customer sound?", [("angry", "Demanding.")], 1),
        Question("urgency", "score", ["low", "medium", "high"], "How urgent?", [("high", "Service is down.")], 2),
    ], {"message": "Why was I charged twice?"}, history)


class TypeSafeResolverTests(unittest.TestCase):
    def test_the_questions_the_state_and_the_answers(self):
        client = FakeClient()
        decision = TypeSafeResolver(client).decide(request())
        [(state, questions)] = client.calls
        self.assertEqual(state, {"state": {"message": "Why was I charged twice?"}}, "the Read keys are what the model judges; no history unless asked")
        self.assertIsInstance(questions["billing"], Noul)
        self.assertEqual(questions["billing"].instructions, "Is this about a charge?")
        self.assertEqual(questions["billing"].criteria, {"true": "Money changed hands.", "false": "Anything else."})
        self.assertIsInstance(questions["tone"], Choice)
        self.assertEqual(questions["tone"].criteria, {"angry": "Demanding.", "calm": None}, "every label is a choice, described or not")
        self.assertIsInstance(questions["urgency"], Score)
        self.assertEqual(list(questions["urgency"].criteria), ["low", "medium", "Service is down."], "one level per label, the label itself when undescribed")
        self.assertEqual(decision.model, "jev-1")
        self.assertEqual(decision.answers["billing"], {"value": True, "confidence": 0.94, "noul": 0.97})
        self.assertEqual(decision.answers["tone"], {"value": "calm", "confidence": 0.9, "probabilities": {"angry": 0.1, "calm": 0.9}})
        self.assertEqual(decision.answers["urgency"], {"value": 2, "confidence": 0.8, "score": 1.7, "probabilities": {"0": 0.1, "1": 0.1, "2": 0.8}},
                         "the value is the most probable level; the legend is dropped")

    def test_the_history_goes_beside_the_state_when_the_step_asks(self):
        client = FakeClient()
        TypeSafeResolver(client).decide(request(history=[{"step": "start"}]))
        self.assertEqual(client.calls[0][0], {"state": {"message": "Why was I charged twice?"}, "history": [{"step": "start"}]})

    def test_payload_helpers_and_odd_answers(self):
        self.assertEqual(state_payload(request()), {"state": {"message": "Why was I charged twice?"}})
        self.assertEqual(set(question_payload(request())), {"billing", "tone", "urgency"})
        self.assertEqual(answer_object({"type": "noul", "noul": 0.2}), {"value": False, "confidence": 0.6, "noul": 0.2})
        with self.assertRaises(ValueError):
            answer_object({"type": "poem"})
        bare = Question("ok", "true_or_false", None, "Ok?", [], 0)
        self.assertIsNone(question_payload(DecisionRequest("s", [bare], {}))["ok"].criteria, "no criteria lines, no criteria")

    def test_from_environment(self):
        import os

        saved = os.environ.pop(KEY_ENV, None)
        try:
            self.assertIsNone(TypeSafeResolver.from_environment())
            self.assertEqual(TypeSafeResolver.from_environment(api_key="k").api_key, "k")
            os.environ[KEY_ENV] = "from-env"
            self.assertEqual(TypeSafeResolver.from_environment().api_key, "from-env")
            self.assertEqual(TypeSafeResolver.from_environment().name, "typesafe")
            self.assertIs(TypeSafeResolver.from_environment(client=FakeClient()).api_key, None)
        finally:
            if saved is None:
                os.environ.pop(KEY_ENV, None)
            else:
                os.environ[KEY_ENV] = saved


if __name__ == "__main__":
    unittest.main()
