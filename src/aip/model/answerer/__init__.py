"""The answerer: an agent made of Chat Completions and AIP (plan aip-dev#1, A1; `docs/answerer.md`).

When a run asks for it (`aip run ... --answer-with model`), the `Task_Agent` pauses are answered by
a model, one short tool-using chat per task, with the procedure as the plan and the run as the
memory between chats. `chat.py` is the one HTTP client (OpenAI Chat Completions with function
calling, no provider SDK), `tools.py` the tools confined to the run's working directory, and
`answerer.py` the loop. The SDK drives it (`aip.Client.run(..., answer_with="model")`).
"""

from aip.model.answerer.answerer import MAX_REFUSALS, Answered, GaveUp, ModelAnswerer, language_page, parse_answer, task_message
from aip.model.answerer.chat import ChatClient, ChatError, Completion
from aip.model.answerer.tools import DEFINITIONS, NAMES, Tools

ANSWER_WITH = ("model",)

__all__ = ["ANSWER_WITH", "Answered", "ChatClient", "ChatError", "Completion", "DEFINITIONS", "GaveUp", "MAX_REFUSALS", "ModelAnswerer",
           "NAMES", "Tools", "language_page", "parse_answer", "task_message"]
