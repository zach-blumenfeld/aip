"""The one chat call aip makes, for `aip agent` (`aip.agent`), and the plumbing around it: the
message a pause becomes, the answer a reply holds, the correction a refusal sends back, what a
call spent, the session so far read from the record, and `answer_once`, the loop's body on its
own for `aip agent --answer`.

The call is OpenAI Chat Completions (`POST {url}/chat/completions`), the shape OpenAI, Anthropic
(`https://api.anthropic.com/v1`), Gemini, Azure's v1 surface, Groq, Mistral, OpenRouter, Ollama
and vLLM all serve. No provider SDK and no streaming: one request, one JSON reply, its first
choice's message and its usage. The runtime never calls it: a run pauses, and whoever drives the
run answers."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from aip.sdk import RunError

JSON = dict[str, Any]

RETRY_STATUSES = (408, 409, 429, 500, 502, 503, 504, 529)


class ChatError(Exception):
    """The endpoint refused the request or answered with something that is not a completion."""


@dataclass
class Completion:
    """The first choice's message (`content`, `tool_calls`), why it stopped, and the tokens the
    call cost."""
    message: JSON
    finish_reason: str | None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    raw: JSON = field(default_factory=dict, repr=False)
    seconds: float = 0.0

    @property
    def tool_calls(self) -> list[JSON]:
        return list(self.message.get("tool_calls") or [])

    @property
    def model(self) -> str | None:
        """The model id the endpoint says answered, which may name a dated snapshot of the one asked for."""
        value = self.raw.get("model")
        return value if isinstance(value, str) and value else None

    @property
    def content(self) -> str:
        content = self.message.get("content")
        if isinstance(content, list):  # some endpoints answer with parts
            return "".join(part.get("text", "") for part in content if isinstance(part, dict))
        return content or ""


class ChatClient:
    """`complete(model, messages, tools)` against one endpoint; called with the messages alone,
    `model` answers them and the completion says how long it took (`aip agent`'s `chat`).
    `session` is an httpx client to send through (tests); `retries` is how often a 429 or a 5xx
    is tried again, with a pause that doubles each time."""

    def __init__(self, url: str, key: str | None, model: str | None = None, *, session: httpx.Client | None = None,
                 timeout: float = 600.0, retries: int = 3, backoff: float = 2.0):
        self.url = url.rstrip("/")
        self.key = key
        self.model = model
        self.session = session or httpx.Client(timeout=timeout)
        self.retries = retries
        self.backoff = backoff

    def complete(self, model: str, messages: list[JSON], tools: list[JSON] | None = None, max_tokens: int = 16384) -> Completion:
        body: JSON = {"model": model, "messages": messages, "max_tokens": max_tokens}
        if tools:
            body["tools"] = tools
        headers = {"content-type": "application/json"}
        if self.key:
            headers["authorization"] = f"Bearer {self.key}"
        wait = self.backoff
        for attempt in range(self.retries + 1):
            try:
                reply = self.session.post(f"{self.url}/chat/completions", json=body, headers=headers)
            except httpx.HTTPError as exc:
                if attempt < self.retries:
                    time.sleep(wait)
                    wait *= 2
                    continue
                raise ChatError(f"{self.url}: {exc}") from exc
            if reply.status_code in RETRY_STATUSES and attempt < self.retries:
                time.sleep(wait)
                wait *= 2
                continue
            if reply.status_code >= 400:
                raise ChatError(f"{self.url} answered {reply.status_code}: {reply.text[:500]}")
            try:
                data = reply.json()
                choice = data["choices"][0]
                usage = data.get("usage") or {}
                return Completion(dict(choice["message"]), choice.get("finish_reason"), int(usage.get("prompt_tokens") or 0),
                                  int(usage.get("completion_tokens") or 0), data)
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                raise ChatError(f"{self.url} answered with something that is not a chat completion: {reply.text[:300]}") from exc
        raise ChatError(f"{self.url}: no answer after {self.retries + 1} tries")

    def __call__(self, messages: list[JSON]) -> Completion:
        began = time.monotonic()
        reply = self.complete(self.model or "", messages, None, COMPLETION_TOKENS)
        reply.seconds = round(time.monotonic() - began, 3)
        if reply.model is None and self.model:     # the endpoint did not say which model answered: the one asked
            reply.raw["model"] = self.model
        return reply


# --------------------------------------------------------------------------- aip agent's plumbing

COMPLETION_TOKENS = 32000
ASSIST, ANSWERS = "assist", 4          # the procedure `aip agent` drives; one answer, up to three corrections, as `aip.agent` has it
REFUSED = "That answer was refused: {}. Reply with the corrected JSON object only."

SYSTEM = """You are the agent answering the pauses of an AIP procedure. A procedure is a reviewed
plan of steps that the AIP runtime runs; at a Task_Agent step it pauses and hands you the task:
its prompt, the state it reads, the files it references, and the keys to answer with. You answer;
the runtime checks the answer against the step's declared keys and types and carries on. The steps
after yours use what you answer.

You have no tools. Everything you know is in the message; everything you do is your answer. When
the procedure needs something done in the world (a search, a run, a file written), it has a step
for it, and your answer is that step's input.

Reply with one JSON object and nothing else: no prose around it, no code fence needed. It holds
exactly the keys under "Answer with", each a value of its type. A true_or_false, choice or score
key is its bare value (`true`, `"angry"`); an object is a JSON object, a list a JSON array. If
your answer is refused you are told why; correct it and answer again."""


def message_for(client: Any, paused: Any) -> list[JSON]:
    """The messages a pause becomes: the system text, then every task with its prompt, the state
    it reads, the text of the files it references, and the shape of the answer."""
    references = references_of(client, paused)
    tasks = paused.tasks
    lines = [f"# Procedure step: {paused.step}" + (f" ({len(tasks)} tasks)" if len(tasks) > 1 else "")]
    for task in tasks:
        if len(tasks) > 1:
            lines += ["", f"## Task {task.index}"]
        passes = " / ".join(f"{p['loop']} pass {p['pass']}" for p in task.data.get("passes") or [])
        if passes:
            lines.append(f"Loop: {passes}" + ("; the last pass the loop allows" if task.data.get("last_pass") else ""))
        lines += ["", task.prompt, "", "## State it reads", "```json", json.dumps(task.state, indent=1, ensure_ascii=False), "```"]
        for ref in task.references:
            text = references.get(ref.get("path") or "")
            lines += ["", f"## Reference: {ref.get('path')}" + (f" ({ref['description']})" if ref.get("description") else "")]
            lines += [text if text is not None else "(this file is not in the bundle)"]
        lines += ["", "## Answer with", "```json", json.dumps(task.answer_with), "```"]
        if task.labels:
            lines.append("Labels: " + json.dumps(task.labels))
    if len(tasks) > 1:
        lines += ["", "Answer every task in one JSON object keyed by its task number: "
                  + json.dumps({str(t.index): "{...}" for t in tasks}) + "."]
    elif paused.hint:
        lines += ["", paused.hint[0].upper() + paused.hint[1:] + "."]
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "\n".join(lines).rstrip() + "\n"}]


def parse(reply: Completion) -> JSON:
    """The JSON object a reply holds: the whole reply, or the one fenced or braced object in it.
    A reply that holds none is refused as `resume` refuses an answer: a `RunError`
    (`invalid_output`, `stopped` False), so one loop handles both."""
    text = reply.content.strip()
    candidates = [text] + re.findall(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if "{" in text and "}" in text:
        candidates.append(text[text.index("{"):text.rindex("}") + 1])
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    raise RunError({"error": "invalid_output", "step": None, "message": "the reply holds no JSON object", "pass": None, "passes": []},
                   stopped=False)


def reason(exc: Exception) -> str:
    """Why an answer was refused, in the run's words."""
    error = getattr(exc, "error", None)
    if not isinstance(error, dict):
        return str(exc)
    if isinstance(error.get("errors"), list) and error["errors"]:
        return "; ".join(str(e) for e in error["errors"])
    return error.get("message") or error.get("error") or str(exc)


def refused(reply: Completion, exc: Exception) -> list[JSON]:
    """The model's refused reply and the correction that goes back to it. A `RunError` that
    `stopped` the run is no refusal (the answer went in; a later step failed): it is raised again."""
    if getattr(exc, "stopped", False):
        raise exc
    return [{"role": "assistant", "content": reply.content}, {"role": "user", "content": REFUSED.format(reason(exc))}]


def work_of(reply: Completion, paused: Any) -> JSON:
    """What the call spent, as `resume --work` takes it: the model, its seconds and tokens."""
    work: JSON = {"seconds": reply.seconds, "tokens": {"prompt": reply.prompt_tokens, "completion": reply.completion_tokens}}
    return {str(paused.tasks[0].index): {"model": reply.model, **work} if reply.model else work}


def history(client: Any, session: str, text: str) -> str:
    """`assist`'s `outcome`: the session so far, from the record. Its `assist` runs oldest first,
    each as its task and the note it ended with, then `text` as the person's answer; empty when
    the session has no runs, so `text` is a new task."""
    runs = client.runs(name=ASSIST, session=session)
    if not runs:
        return ""
    lines = []
    for row in reversed(runs):
        record = client.run_record(row.run_id)
        note = (record.result or {}).get("note") or (record.error or {}).get("message") or ""
        lines.append(f"The task was: {(record.data.get('state') or {}).get('task') or ''}")
        if note:
            lines.append(f"You asked: {note}")
    lines.append(f"The person answered: {text}")
    return "\n".join(lines)


def answer_once(client: Any, chat: Any, paused: Any, agent: str | None, session: str | None) -> tuple[Any, str | None]:
    """One pause of any run, answered as `aip.agent` answers each pause of `assist`: one answer,
    up to three corrections (`aip agent --answer`). Returns what the resume came to and None, or
    the run's `Paused` as it was and why the model gave up."""
    msg = message_for(client, paused)
    for _ in range(ANSWERS):
        reply = chat(msg)
        try:
            return client.resume(paused, parse(reply), agent=agent, session=session, work=work_of(reply, paused)), None
        except RunError as e:
            msg, why = msg + refused(reply, e), reason(e)
    return paused, f"the model's answer at {paused.step} was refused {ANSWERS} times; the last time: {why}"


def why_refused(client: Any, reply: Completion) -> str:
    """Why the model's latest reply was refused, once the loop gave up on it: it held no JSON
    object, else what `resume` said of it (`client.last_refusal`)."""
    try:
        parse(reply)
    except RunError as exc:
        return reason(exc)
    return reason(client.last_refusal) if client.last_refusal is not None else "no reason was given"


def refusal_of(messages: list[JSON]) -> str | None:
    """The reason the last message carries when it is a correction (`refused`), else None."""
    head, tail = REFUSED.split("{}")
    last = messages[-1]["content"] if len(messages) > 2 else ""
    return last[len(head):].removesuffix(tail) if isinstance(last, str) and last.startswith(head) else None


def references_of(client: Any, paused: Any) -> dict[str, str]:
    """The text of every file the pause's tasks reference, from the run's bundle."""
    wanted = {r.get("path") for t in paused.tasks for r in t.references if r.get("path")}
    if not wanted:
        return {}
    from aip.client import bundles
    from aip.client.runs import RunFile

    bundle = bundles.load(RunFile.load(client.run_file(paused)).bundle_id, client.home)
    return {f.path: f.data.decode("utf-8", errors="replace") for f in bundle.files if f.path in wanted}


def pause_view(client: Any, paused: Any) -> JSON:
    """A pause as `assist`'s planner reads it: the paused object, each task's references with their text."""
    texts = references_of(client, paused)
    body = paused.to_json()
    for task in body.get("tasks") or []:
        task["references"] = [{**r, "text": texts.get(r.get("path"))} for r in task.get("references") or []]
    return body


def observed(chat: Any, paused: Any, on_event: Any) -> Any:
    """`chat`, telling `on_event` of each call (`answer`: its tokens and seconds) and of the
    refusal each later call carries (`refused`): the progress lines of `aip agent --answer`."""
    def call(messages: list[JSON]) -> Completion:
        why = refusal_of(messages)
        if why is not None:
            on_event({"event": "refused", "step": paused.step, "run_id": paused.run_id, "reason": why})
        reply = chat(messages)
        on_event({"event": "answer", "step": paused.step, "run_id": paused.run_id,
                  "tokens": reply.prompt_tokens + reply.completion_tokens, "seconds": reply.seconds})
        return reply
    return call


__all__ = ["ANSWERS", "ASSIST", "COMPLETION_TOKENS", "ChatClient", "ChatError", "Completion", "SYSTEM", "answer_once", "history",
           "message_for", "observed", "parse", "pause_view", "reason", "references_of", "refusal_of", "refused", "why_refused", "work_of"]
