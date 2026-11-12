"""runah's answerer: an agent made of Chat Completions and AIP (plan aip#29, A1 and A2; `docs/runah.md`).

In a run started or carried on with `aip runah`, the `Task_Agent` pauses are answered by a chat
model, one short tool-using chat per task, with the procedure as the plan and the run as the
memory between chats. `chat.py` is the one HTTP client (OpenAI Chat Completions with function
calling, no provider SDK), `tools.py` the tools confined to the run's working directory, and
`answerer.py` the loop. The SDK drives it (`aip.Client.runah`).
"""

from aip.model.answerer.answerer import AGENT, MAX_REFUSALS, Answered, GaveUp, ModelAnswerer, language_page, parse_answer, task_message
from aip.model.answerer.chat import ChatClient, ChatError, Completion
from aip.model.answerer.tools import DEFINITIONS, NAMES, Tools

__all__ = ["AGENT", "Answered", "ChatClient", "ChatError", "Completion", "DEFINITIONS", "GaveUp", "MAX_REFUSALS", "ModelAnswerer",
           "NAMES", "Tools", "language_page", "parse_answer", "task_message"]
