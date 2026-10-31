"""Scripted adapter for tests and CI: replays ChatResults in order, records every call.

A script item may be a callable taking the messages, for answers that depend on tool results.
"""

from collections.abc import Callable
from typing import Any

from agent.adapters.base import ChatResult, Message, ToolSpec

ScriptItem = ChatResult | Callable[[list[Message]], ChatResult]


class FakeAdapter:
    max_tokens = 1024

    def __init__(
        self,
        script: list[ScriptItem],
        model: str = "fake",
        settings: dict[str, Any] | None = None,
    ) -> None:
        self.model = model
        self._settings = settings or {}
        self._script = list(script)
        self.calls: list[tuple[list[Message], list[ToolSpec]]] = []

    def config(self) -> dict[str, Any]:
        return {"model": self.model, "max_tokens": self.max_tokens, **self._settings}

    def chat(self, messages: list[Message], tools: list[ToolSpec]) -> ChatResult:
        self.calls.append((messages, tools))
        if not self._script:
            raise RuntimeError(f"FakeAdapter script exhausted after {len(self.calls) - 1} calls")
        item = self._script.pop(0)
        return item if isinstance(item, ChatResult) else item(messages)
