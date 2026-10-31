"""Local Qwen via Ollama's OpenAI-compatible API (http://localhost:11434/v1)."""

import json
import logging
import urllib.request
from typing import Any

from agent.adapters.base import ChatResult, Message, ToolCall, ToolSpec, Usage

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "qwen3.5:9b-q4_K_M"
BASE_URL = "http://localhost:11434/v1"
TAGS_URL = "http://localhost:11434/api/tags"
_FETCH = object()


def ollama_digest(model: str) -> str:
    """The local model's digest, so a re-pulled tag doesn't reuse stale cache entries."""
    with urllib.request.urlopen(TAGS_URL) as resp:
        models = json.load(resp)["models"]
    for m in models:
        if m["name"] == model:
            return m["digest"]
    raise LookupError(f"model {model!r} is not pulled in Ollama ({[m['name'] for m in models]})")


class OllamaAdapter:
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        client: Any = None,
        digest: Any = _FETCH,
        max_tokens: int = 1024,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = 0
        self.think = False
        if client is None:
            from openai import OpenAI

            client = OpenAI(base_url=BASE_URL, api_key="ollama")  # key is ignored by Ollama
        self._client = client
        self.digest = ollama_digest(model) if digest is _FETCH else digest

    def config(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "digest": self.digest,
            "base_url": BASE_URL,
            "temperature": self.temperature,
            "think": self.think,
            "max_tokens": self.max_tokens,
        }

    def chat(self, messages: list[Message], tools: list[ToolSpec]) -> ChatResult:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "extra_body": {"think": self.think},  # Ollama-specific: no reasoning trace
        }
        if tools:
            kwargs["tools"] = tools
        response = self._client.chat.completions.create(**kwargs)
        message = response.choices[0].message
        calls = [
            ToolCall(id=c.id, name=c.function.name, arguments_json=c.function.arguments)
            for c in (message.tool_calls or [])
        ]
        usage = Usage(response.usage.prompt_tokens, response.usage.completion_tokens)
        return ChatResult(content=message.content, tool_calls=calls, usage=usage, model=self.model)
