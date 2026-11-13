"""`aip agent`: a chat model outside the run, answering the pauses of `assist` (plan aip#29, A3;
`docs/agent.md`). This is all of it:

    r = client.run("assist", {"task": task, "outcome": outcome}, agent="agent", session=session)
    while isinstance(r, Paused):
        r = client.resume(r, answers=chat(r))       # one model call per pause, no tools

AIP does no orchestration and the runtime never calls a chat model. A procedure pauses at a
`Task_Agent`; this module asks the configured model (`aip config agent`) for the answer, with
the task's prompt, the state it reads and the text of its references, and resumes the run with
it. The model has no tools: it answers with JSON and nothing else, and everything it can do is a
step of `assist` (whose `act` script holds the only verbs: search, runs, run, resume, publish,
finish). An answer the run refuses goes back to the model with the reason, up to three times;
then the run is left paused, as it is, for whoever answers next.

A session is a conversation with the person: the first `ask` in it starts `assist` on the task,
and each later one starts it again on the same task, with `outcome` saying "You asked: <the last
run's note>. The person answered: <text>", so the model has its own question and the reply. The
current session of a shell is kept under `~/.aip/agent/` (`AIP_HOME` moves it), by the shell's
process id; `new` starts another. Every run it starts, and every run `assist` starts beneath it,
carries `agent: agent` and the session, so `aip runs --session ID` is the audit.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from aip.chat import ChatClient, ChatError
from aip.errors import AipError

JSON = dict[str, Any]

ASSIST = "assist"
AGENT = "agent"                 # the identity's `agent` on every run `aip agent` starts and every answer it gives
MAX_REFUSALS = 3
COMPLETION_TOKENS = 32000

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


class AgentError(AipError):
    """`aip agent` cannot start: no model key, no task, or a session id it cannot use."""
    kind = "invalid_input"


@dataclass
class Outcome:
    """Where `ask` left the session. `status` is the last run's: `done` (with `note`, the
    answer or the question for the person, and `result`), `paused` (the model's answer was
    refused past its retries or its endpoint failed: `reason`, and `pause`, the paused
    object for whoever answers next) or `failed` (`error`, the CLI's error object). `runs` is
    every run this call started, `calls` and `tokens` what the model spent."""
    session: str
    status: str
    run_id: str | None
    note: str = ""
    result: JSON | None = None
    pause: JSON | None = None
    error: JSON | None = None
    reason: str | None = None
    runs: list[str] = field(default_factory=list)
    calls: int = 0
    tokens: int = 0

    def to_json(self) -> JSON:
        out: JSON = {"session": self.session, "status": self.status, "run_id": self.run_id, "note": self.note}
        for key in ("result", "pause", "error", "reason"):
            if getattr(self, key) is not None:
                out[key] = getattr(self, key)
        out.update(runs=self.runs, model_calls=self.calls, tokens=self.tokens)
        return out


# --------------------------------------------------------------------------- sessions


def agent_dir(home: Path | None = None) -> Path:
    from aip.model.cache import aip_home

    return Path(home if home is not None else aip_home()) / AGENT


def shell_id() -> str:
    """Which shell this command is part of: its parent process (the shell that ran `aip`)."""
    return str(os.getppid())


def new_session_id() -> str:
    return f"agent-{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"


class Sessions:
    """`~/.aip/agent/`: `shells/<pid>` names the current session of a shell, and
    `sessions/<id>.json` holds a session: its task, the runs it started, the last run's id,
    status and note."""

    def __init__(self, home: Path | None = None):
        self.root = agent_dir(home)

    def _file(self, session: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", session):
            raise AgentError(f"{session!r} cannot be a session id: letters, digits, and . _ : - only")
        return self.root / "sessions" / f"{session}.json"

    def current(self, shell: str) -> str | None:
        path = self.root / "shells" / shell
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return text if text and self._file(text).is_file() else None

    def choose(self, shell: str, session: str) -> None:
        path = self.root / "shells" / shell
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(session + "\n", encoding="utf-8")

    def load(self, session: str) -> JSON | None:
        try:
            return json.loads(self._file(session).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def save(self, session: str, data: JSON) -> None:
        path = self._file(session)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")


def continuation(note: str, text: str) -> str:
    """The `outcome` a later call in a session starts `assist` with."""
    note = (note or "").strip()
    return f"You asked: {note}. The person answered: {text}" if note else f"The person answered: {text}"


# --------------------------------------------------------------------------- the message


def task_message(paused: Any, references: dict[str, str]) -> str:
    """The user message: every task of the pause as it carries it, with the text of the files it
    references, and the shape of the answer."""
    tasks = paused.tasks
    lines = [f"# Procedure step: {paused.step}" + (f" ({len(tasks)} tasks)" if len(tasks) > 1 else "")]
    for task in tasks:
        data = task.data
        if len(tasks) > 1:
            lines += ["", f"## Task {task.index}"]
        passes = " / ".join(f"{p['loop']} pass {p['pass']}" for p in data.get("passes") or [])
        if passes:
            last = "; the last pass the loop allows" if data.get("last_pass") else ""
            lines.append(f"Loop: {passes}{last}")
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
    return "\n".join(lines).rstrip() + "\n"


def parse_answer(text: str) -> Any:
    """The JSON object a reply holds: the whole reply, or the one fenced or braced object in it."""
    text = text.strip()
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
    raise ValueError("the reply holds no JSON object")


def references_of(client: Any, paused: Any) -> dict[str, str]:
    """The text of every file the pause's tasks reference, from the run's bundle."""
    wanted = {r.get("path") for t in paused.tasks for r in t.references if r.get("path")}
    if not wanted:
        return {}
    from aip.client import bundles
    from aip.client.runs import RunFile

    handle = RunFile.load(client.run_file(paused))
    bundle = bundles.load(handle.bundle_id, client.home)
    return {f.path: f.data.decode("utf-8", errors="replace") for f in bundle.files if f.path in wanted}


def pause_view(client: Any, paused: Any) -> JSON:
    """A pause as `assist`'s planner reads it: the paused object, each task's references with
    their text."""
    texts = references_of(client, paused)
    body = paused.to_json()
    for task in body.get("tasks") or []:
        task["references"] = [{**r, "text": texts.get(r.get("path"))} for r in task.get("references") or []]
    return body


# --------------------------------------------------------------------------- the agent


class Agent:
    """Drives `assist` (or `procedure`) with a chat model answering its pauses. `client` is an
    `aip.Client`; `chat` a `ChatClient` (default: the configured endpoint, `aip config
    agent`), `model` the model's name; `on_event` gets a dict per thing worth a progress line."""

    def __init__(self, client: Any, chat: ChatClient | Any = None, model: str | None = None, *,
                 on_event: Callable[[JSON], None] | None = None, procedure: str | Path = ASSIST, home: Path | None = None):
        s = client.settings
        if chat is None and not s.agent_configured:
            from aip.client.config import AGENT_HINT

            raise AgentError(f"aip agent needs a chat model to answer the pauses: {AGENT_HINT}")
        self.client = client
        self.chat = chat if chat is not None else ChatClient(s.agent_model_endpoint, s.agent_model_key)
        self.model = model or s.agent_model
        self.on_event = on_event
        self.procedure = procedure
        self.sessions = Sessions(home if home is not None else client.home)

    def _event(self, **event: Any) -> None:
        if self.on_event is not None:
            self.on_event(event)

    def ask(self, text: str, *, session: str | None = None, new: bool = False, shell: str | None = None) -> Outcome:
        """One turn with the person: start `assist` on `text` (a new session's task, or the
        person's reply in a session that has one), answer its pauses until it is done, fails,
        or an answer cannot be made to hold. `session` picks a session (made if it does not
        exist); else `new` starts one, else this shell's current one is continued."""
        if not isinstance(text, str) or not text.strip():
            raise AgentError("aip agent needs a task: what is to be done, in your words")
        shell = shell or shell_id()
        session = session or (None if new else self.sessions.current(shell)) or new_session_id()
        self.sessions.choose(shell, session)
        state = self.sessions.load(session) or {"session": session, "task": None, "runs": []}
        if state.get("task"):
            inputs = {"task": state["task"], "outcome": continuation(state.get("note") or "", text)}
        else:
            state["task"] = text
            inputs = {"task": text, "outcome": ""}
        self._event(event="session", session=session, continued=bool(state.get("runs")))
        out = self._drive(session, inputs)
        state["runs"] = list(state.get("runs") or []) + out.runs
        state.update(run_id=out.run_id, status=out.status, note=out.note)
        self.sessions.save(session, state)
        return out

    def _drive(self, session: str, inputs: JSON) -> Outcome:
        from aip.sdk import Done, Paused, RunError

        on_step = (lambda line: self._event(event="step", **line)) if self.on_event else None
        out = Outcome(session, "failed", None)
        target = self.procedure
        if self.client.server is None and target == ASSIST:      # no catalog to name it in: the bundle aip ships
            from aip.server.builtins import builtin_files

            target = next(str(p) for p in builtin_files() if p.stem == ASSIST)
        try:
            result = self.client.run(target, inputs, agent=AGENT, session=session, on_step=on_step)
            out.run_id = result.run_id
            out.runs.append(result.run_id)
            while isinstance(result, Paused):
                answered = self.answer(result, session, out, on_step)
                if answered is None:
                    out.status, out.pause = "paused", result.to_json()
                    return out
                result = answered
        except RunError as exc:
            if exc.run_id and exc.run_id not in out.runs:
                out.runs.append(exc.run_id)
            out.run_id = exc.run_id or out.run_id
            out.status, out.error = "failed", exc.to_json()
            out.note = exc.error.get("message") or ""
            return out
        assert isinstance(result, Done)
        out.status, out.result = "done", result.result
        note = result.result.get("note")
        out.note = note if isinstance(note, str) else json.dumps(result.result, ensure_ascii=False)
        return out

    def answer(self, paused: Any, session: str, out: Outcome, on_step: Any = None) -> Any:
        """Ask the model for the pause's answers and resume the run with them: the next result,
        or None when no answer would hold (the reason is in `out.reason`, the run left paused).
        A `RunError` the resume raises for the run itself (a step after this one failed) goes up."""
        from aip.sdk import RunError

        messages: list[JSON] = [{"role": "system", "content": SYSTEM},
                                {"role": "user", "content": task_message(paused, references_of(self.client, paused))}]
        refusals = 0
        while True:
            began = time.monotonic()
            try:
                reply = self.chat.complete(self.model, messages, None, COMPLETION_TOKENS)
            except ChatError as exc:
                out.reason = f"the model's endpoint failed: {exc}"
                return None
            seconds = round(time.monotonic() - began, 3)
            out.calls += 1
            spent = reply.prompt_tokens + reply.completion_tokens
            out.tokens += spent
            self._event(event="answer", step=paused.step, run_id=paused.run_id, tokens=spent, seconds=seconds)
            messages.append({"role": "assistant", "content": reply.content})
            work = {"model": reply.model or self.model, "seconds": seconds,
                    "tokens": {"prompt": reply.prompt_tokens, "completion": reply.completion_tokens}}
            try:
                answers = parse_answer(reply.content)
                return self.client.resume(paused, answers, agent=AGENT, session=session, on_step=on_step,
                                          work={str(paused.tasks[0].index): work})
            except ValueError as exc:
                why = str(exc)
            except RunError as exc:
                if exc.stopped:          # the answer went in and the run stopped on an error after it
                    raise
                why = exc.error.get("message") or exc.error.get("error") or str(exc)
                errors = exc.error.get("errors")
                if isinstance(errors, list) and errors:
                    why = "; ".join(str(e) for e in errors)
            if refusals >= MAX_REFUSALS:
                out.reason = f"the model's answer at {paused.step} was refused {refusals + 1} times; the last time: {why}"
                self._event(event="gave_up", step=paused.step, run_id=paused.run_id, reason=why)
                return None
            refusals += 1
            self._event(event="refused", step=paused.step, run_id=paused.run_id, reason=why)
            messages.append({"role": "user", "content": f"That answer was refused: {why}. Reply with the corrected JSON object only."})


__all__ = ["AGENT", "ASSIST", "Agent", "AgentError", "MAX_REFUSALS", "Outcome", "Sessions", "continuation", "new_session_id",
           "parse_answer", "pause_view", "references_of", "shell_id", "task_message"]
