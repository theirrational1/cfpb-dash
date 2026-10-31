"""Adapter interface. Messages and tools use the OpenAI chat format; adapters translate."""

from dataclasses import dataclass
from typing import Any, Protocol

Message = dict[str, Any]
ToolSpec = dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


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

    def chat(self, messages: list[Message], tools: list[ToolSpec]) -> ChatResult: ...
