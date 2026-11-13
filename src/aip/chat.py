"""The one chat call aip makes, for `aip agent` (`aip.agent`): OpenAI Chat Completions
(`POST {url}/chat/completions`), the shape OpenAI, Anthropic (`https://api.anthropic.com/v1`),
Gemini, Azure's v1 surface, Groq, Mistral, OpenRouter, Ollama and vLLM all serve. No provider
SDK and no streaming: one request, one JSON reply, its first choice's message and its usage.
The runtime never calls it: a run pauses, and whoever drives the run answers."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import httpx

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
    """`complete(model, messages, tools)` against one endpoint. `session` is an httpx client to
    send through (tests); `retries` is how often a 429 or a 5xx is tried again, with a pause
    that doubles each time."""

    def __init__(self, url: str, key: str | None, *, session: httpx.Client | None = None, timeout: float = 600.0,
                 retries: int = 3, backoff: float = 2.0):
        self.url = url.rstrip("/")
        self.key = key
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


__all__ = ["ChatClient", "ChatError", "Completion"]
