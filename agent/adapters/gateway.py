"""The single path for model calls: cache, budget cap, usage + cost logging (AGENTS.md)."""

import hashlib
import json
import logging
from dataclasses import asdict, dataclass

from agent.adapters.base import ChatAdapter, ChatResult, Message, ToolCall, ToolSpec, Usage
from agent.adapters.cache import JsonCache
from agent.adapters.pricing import cost_usd
from agent.adapters.usage import UsageLog

logger = logging.getLogger(__name__)


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Budget:
    cap_usd: float
    spent_usd: float = 0.0

    def check(self) -> None:
        if self.spent_usd >= self.cap_usd:
            raise BudgetExceeded(
                f"budget cap reached: spent ${self.spent_usd:.2f} of ${self.cap_usd:.2f}"
            )


def _from_dict(d: dict) -> ChatResult:
    return ChatResult(
        content=d["content"],
        tool_calls=[ToolCall(**c) for c in d["tool_calls"]],
        usage=Usage(**d["usage"]),
        model=d["model"],
    )


class Gateway:
    def __init__(
        self,
        adapter: ChatAdapter,
        usage: UsageLog,
        cache: JsonCache,
        run_id: str,
        budget: Budget | None = None,
    ) -> None:
        self.adapter = adapter
        self.usage = usage
        self.cache = cache
        self.run_id = run_id
        self.budget = budget

    def chat(
        self, messages: list[Message], tools: list[ToolSpec], prompt_version: str
    ) -> ChatResult:
        model = self.adapter.model
        payload = {"model": model, "prompt_version": prompt_version, "messages": messages,
                   "tools": tools}  # fmt: skip
        key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

        cached = self.cache.get(key)
        if cached is not None:
            self.usage.record(self.run_id, model, prompt_version, Usage(0, 0), 0.0, True)
            logger.info("cache hit %s (%s)", key[:12], model)
            return _from_dict(cached)

        if self.budget is not None:
            self.budget.check()
        result = self.adapter.chat(messages, tools)
        cost = cost_usd(model, result.usage)
        if self.budget is not None:
            self.budget.spent_usd += cost
        self.usage.record(self.run_id, model, prompt_version, result.usage, cost, False)
        self.cache.put(key, asdict(result))
        logger.info(
            "model call %s: in=%d out=%d cost=$%.6f",
            model, result.usage.input_tokens, result.usage.output_tokens, cost,
        )  # fmt: skip
        return result
