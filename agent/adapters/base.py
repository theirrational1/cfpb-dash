"""Adapter interface. Messages and tools use the OpenAI chat format; adapters translate.

Adapters must not raise after a model call has been paid for: tool arguments stay as the raw
JSON string the model produced, and are parsed (and validated) by the agent loop.
"""

import json
from dataclasses import dataclass
from typing import Any, Protocol

Message = dict[str, Any]
ToolSpec = dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments_json: str

    @property
    def arguments(self) -> Any:
        """Parsed arguments; raises json.JSONDecodeError if the model produced invalid JSON."""
        return json.loads(self.arguments_json)

    @classmethod
    def of(cls, id: str, name: str, arguments: dict[str, Any]) -> "ToolCall":
        return cls(id, name, json.dumps(arguments))


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class ChatResult:
    content: str | None
    tool_calls: list[ToolCall]
    usage: Usage
    model: str


class ChatAdapter(Protocol):
    model: str
    max_tokens: int

    def config(self) -> dict[str, Any]:
        """Everything besides the input that affects the output (part of the cache key)."""
        ...

    def chat(self, messages: list[Message], tools: list[ToolSpec]) -> ChatResult: ...
