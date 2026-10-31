"""Scripted adapter for tests and CI: replays ChatResults in order, records every call."""

from agent.adapters.base import ChatResult, Message, ToolSpec


class FakeAdapter:
    model = "fake"

    def __init__(self, script: list[ChatResult]) -> None:
        self._script = list(script)
        self.calls: list[tuple[list[Message], list[ToolSpec]]] = []

    def chat(self, messages: list[Message], tools: list[ToolSpec]) -> ChatResult:
        self.calls.append((messages, tools))
        if not self._script:
            raise RuntimeError(f"FakeAdapter script exhausted after {len(self.calls) - 1} calls")
        return self._script.pop(0)
