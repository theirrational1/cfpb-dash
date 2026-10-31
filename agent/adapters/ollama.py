"""Local Qwen via Ollama's OpenAI-compatible API (http://localhost:11434/v1)."""

import json
import logging
from typing import Any

from agent.adapters.base import ChatResult, Message, ToolCall, ToolSpec, Usage

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "qwen3.5:9b-q4_K_M"
BASE_URL = "http://localhost:11434/v1"


class OllamaAdapter:
    def __init__(self, model: str = DEFAULT_MODEL, client: Any = None) -> None:
        self.model = model
        if client is None:
            from openai import OpenAI

            client = OpenAI(base_url=BASE_URL, api_key="ollama")  # key is ignored by Ollama
        self._client = client

    def chat(self, messages: list[Message], tools: list[ToolSpec]) -> ChatResult:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "extra_body": {"think": False},  # Ollama-specific: no reasoning trace
        }
        if tools:
            kwargs["tools"] = tools
        response = self._client.chat.completions.create(**kwargs)
        message = response.choices[0].message
        calls = [
            ToolCall(id=c.id, name=c.function.name, arguments=json.loads(c.function.arguments))
            for c in (message.tool_calls or [])
        ]
        usage = Usage(response.usage.prompt_tokens, response.usage.completion_tokens)
        return ChatResult(content=message.content, tool_calls=calls, usage=usage, model=self.model)
