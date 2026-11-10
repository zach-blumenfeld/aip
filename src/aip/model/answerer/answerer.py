"""runah's model answering one task: a short, tool-using chat whose last message is the answer.

The system prompt is the language on one page (`skills/aip/references/language.md`) under the
rules of the loop; the user message is the task as a pause carries it: the prompt, the state it
reads, the references, and the shape of the answer. The model calls tools (`tools.py`) until it
replies with no call; that reply is the answer, a JSON object of the step's `Produce` keys. It is
checked as `aip resume` checks one (`check`), and a refusal goes back to the model with the
message, up to `max_refusals` times. A task that runs out of refusals, tool calls or tokens, or
whose endpoint fails, is given up (`GaveUp`): the run stays paused for whoever answers next.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from aip.model.answerer.chat import ChatClient, ChatError
from aip.model.answerer.tools import BUNDLE_PREFIX, DEFINITIONS, Tools, summary

JSON = dict[str, Any]

MAX_REFUSALS = 3
AGENT = "runah"               # `answered_by.agent` of every task the model answers
COMPLETION_TOKENS = 16384

RULES = """You answer one task of a procedure that an AIP runtime is running. The procedure is the plan:
the steps before this one produced the state you are given, and the steps after it check and use
what you answer. Do this task and only this task, as its prompt says, then answer.

How you work:
- You have tools: read_file, list_files, search, write_file, compile. Every path is relative to
  the run's working directory and stays inside it. The procedure's own files (its assets and
  references) are readable as `bundle:<path>`, e.g. `bundle:references/help.md`; they cannot be
  written.
- Read what the task points you at before you write. Write files only where the task says.
- `compile` checks an AIP program folder and lists the compiler's diagnostics; use it on any
  procedure you write or change before you answer.
- You have at most {max_tool_calls} tool calls for this task. Be direct.

How you answer:
- When the task is done, reply with one JSON object and nothing else: no prose around it, no code
  fence needed. It holds exactly the keys under "Answer with", each a value of its type. A
  true_or_false, choice or score key is its bare value (`true`, `"angry"`).
- If your answer is refused you are told why; correct it and answer again.

The AIP procedure language, for tasks that read or write procedures:

{language}"""


@dataclass
class Answered:
    """A task the model answered: the answer as checked, and the fields of the record entry
    (`answered_by` `{"agent": "runah", "model": the id the endpoint reported}`, `work`
    `"observed"`, `tool_calls`, `tokens`, `model_seconds`, `refusals`)."""
    answer: JSON
    record: JSON


@dataclass
class GaveUp(Exception):
    """The model did not produce an answer that holds; `reason` says why, `record` what it
    spent getting there."""
    reason: str
    record: JSON = field(default_factory=dict)

    def __str__(self) -> str:
        return self.reason


def language_page() -> str:
    from aip.compiler.resources import skill_dir

    path = skill_dir() / "references" / "language.md"
    return path.read_text(encoding="utf-8") if path.is_file() else "(the language page is not installed with this aip)"


def task_message(step: str, task: JSON, tasks: int, hint: str) -> str:
    """The user message: the task as the pause carries it."""
    where = f" (task {task['index'] + 1} of {tasks})" if tasks > 1 else ""
    passes = " / ".join(f"{p['loop']} pass {p['pass']}" for p in task.get("passes") or [])
    lines = [f"# Task: {step}{where}"]
    if passes:
        last = "; the last pass the loop allows" if task.get("last_pass") else ""
        lines.append(f"Loop: {passes}{last}")
    lines += ["", task.get("prompt") or "", "", "## State it reads", "```json", json.dumps(task.get("state") or {}, indent=1,
                                                                                            ensure_ascii=False), "```"]
    references = task.get("references") or []
    if references:
        lines += ["", "## References (read one with read_file when the task calls for it)"]
        lines += [f"- {BUNDLE_PREFIX}{r['path']}: {r.get('description') or ''}".rstrip(": ") for r in references]
    lines += ["", "## Answer with", "```json", json.dumps(task.get("answer_with") or {}), "```"]
    if task.get("labels"):
        lines += ["Labels: " + json.dumps(task["labels"])]
    lines += [hint[0].upper() + hint[1:] + "." if hint else ""]
    return "\n".join(lines).rstrip() + "\n"


def parse_answer(text: str) -> Any:
    """The JSON object a reply holds: the whole reply, or the one fenced or braced object in it."""
    text = text.strip()
    candidates = [text]
    fenced = re.findall(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    candidates += fenced
    if "{" in text and "}" in text:
        candidates.append(text[text.index("{"):text.rindex("}") + 1])
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
    raise ValueError("the reply holds no JSON object")


class ModelAnswerer:
    """Answers tasks with one chat each. `chat` is the endpoint; `model` the model's name;
    `workdir` the run's working directory; `bundle_root` the procedure's unpacked files;
    `on_event` gets a dict per tool call and per refusal (the `--progress` lines)."""

    def __init__(self, chat: ChatClient, model: str, workdir: Path, bundle_root: Path | None = None, *,
                 max_tool_calls: int = 40, max_tokens: int = 500_000, max_refusals: int = MAX_REFUSALS,
                 on_event: Callable[[JSON], None] | None = None, timer: Callable[[], float] = time.monotonic,
                 language: str | None = None):
        self.chat = chat
        self.model = model
        self.tools = Tools(workdir, bundle_root)
        self.max_tool_calls = max_tool_calls
        self.max_tokens = max_tokens
        self.max_refusals = max_refusals
        self.on_event = on_event
        self.timer = timer
        self.system = RULES.format(max_tool_calls=max_tool_calls, language=language if language is not None else language_page())

    def _event(self, event: JSON) -> None:
        if self.on_event is not None:
            self.on_event(event)

    def answer(self, step: str, task: JSON, tasks: int, hint: str, check: Callable[[Any], JSON]) -> Answered:
        """One chat for one task. `check` takes the answer and returns it as the step would
        store it, or raises with `.errors` (the engine's `InvalidOutput`)."""
        messages: list[JSON] = [{"role": "system", "content": self.system},
                                {"role": "user", "content": task_message(step, task, tasks, hint)}]
        calls: list[JSON] = []
        tokens = {"prompt": 0, "completion": 0}
        spent = {"model_seconds": 0.0}
        refusals = 0
        index = task["index"]
        reported: list[str] = []

        def record() -> JSON:
            model = reported[-1] if reported else self.model
            return {"answered_by": {"agent": AGENT, "model": model}, "work": "observed", "tool_calls": calls,
                    "tokens": {**tokens, "total": tokens["prompt"] + tokens["completion"]},
                    "model_seconds": round(spent["model_seconds"], 3), "refusals": refusals}

        while True:
            asked = self.timer()
            try:
                reply = self.chat.complete(self.model, messages, DEFINITIONS, COMPLETION_TOKENS)
            except ChatError as exc:
                raise GaveUp(f"runah's model failed: {exc}", record()) from exc
            spent["model_seconds"] += max(self.timer() - asked, 0.0)
            if reply.model:
                reported.append(reply.model)
            tokens["prompt"] += reply.prompt_tokens
            tokens["completion"] += reply.completion_tokens
            message = {"role": "assistant", "content": reply.content or None}
            if reply.tool_calls:
                message["tool_calls"] = reply.tool_calls
            messages.append(message)
            if reply.tool_calls:
                for call in reply.tool_calls:
                    function = call.get("function") or {}
                    name, arguments = function.get("name") or "", function.get("arguments")
                    if len(calls) >= self.max_tool_calls:
                        raise GaveUp(f"runah's model reached its cap of {self.max_tool_calls} tool calls on one task without "
                                     "answering (`aip config runah --max-tool-calls-per-task N`)", record())
                    began = self.timer()
                    result = self.tools.call(name, arguments)
                    entry = {"name": name, "args": summary(name, arguments), "seconds": round(max(self.timer() - began, 0.0), 3)}
                    if result.startswith("error: "):
                        entry["error"] = result[len("error: "):][:200]
                    calls.append(entry)
                    self._event({"event": "tool", "step": step, "task": index, "tool": name, "args": entry["args"],
                                 "seconds": entry["seconds"], **({"error": entry["error"]} if "error" in entry else {})})
                    messages.append({"role": "tool", "tool_call_id": call.get("id") or "", "content": result})
                if tokens["prompt"] + tokens["completion"] >= self.max_tokens:
                    raise GaveUp(f"runah's model spent its cap of {self.max_tokens} tokens on one task without answering "
                                 "(`aip config runah --max-tokens-per-task N`)", record())
                continue
            if tokens["prompt"] + tokens["completion"] >= self.max_tokens:
                raise GaveUp(f"runah's model spent its cap of {self.max_tokens} tokens on one task "
                             "(`aip config runah --max-tokens-per-task N`)", record())
            try:
                answer = parse_answer(reply.content)
                checked = check(answer)
            except ValueError as exc:
                why = [str(exc)]
            except Exception as exc:  # the engine's InvalidOutput: every reason the answer does not hold
                why = list(getattr(exc, "errors", None) or [str(exc)])
            else:
                return Answered(answer, record())
            if refusals >= self.max_refusals:
                raise GaveUp(f"runah's model's answer was refused {refusals + 1} times; the last time: {'; '.join(why)}", record())
            refusals += 1
            self._event({"event": "refused", "step": step, "task": index, "errors": why})
            messages.append({"role": "user", "content": "That answer was refused: " + "; ".join(why) + ". Reply with the corrected "
                             "JSON object only."})


__all__ = ["AGENT", "Answered", "GaveUp", "ModelAnswerer", "language_page", "parse_answer", "task_message", "MAX_REFUSALS"]
