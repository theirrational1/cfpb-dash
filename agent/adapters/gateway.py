"""The single path for model calls: cache, budget cap, usage + cost logging (AGENTS.md).

Order matters: the price is looked up and the worst-case cost checked against the budget
BEFORE the call; usage is logged straight after it, before anything can fail.
"""

import hashlib
import json
import logging
from dataclasses import asdict, dataclass

from agent.adapters.base import ChatAdapter, ChatResult, Message, ToolCall, ToolSpec, Usage
from agent.adapters.cache import JsonCache
from agent.adapters.pricing import cost_usd
from agent.adapters.usage import UsageLog

logger = logging.getLogger(__name__)

CHARS_PER_TOKEN_LOW = 3  # conservative (real is ~4): over-estimates input tokens


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Budget:
    cap_usd: float
    spent_usd: float = 0.0

    def check(self, worst_case_usd: float) -> None:
        if self.spent_usd + worst_case_usd > self.cap_usd:
            raise BudgetExceeded(
                f"budget: spent ${self.spent_usd:.2f} + worst case ${worst_case_usd:.2f} "
                f"exceeds cap ${self.cap_usd:.2f}"
            )


def estimate_input_tokens(messages: list[Message], tools: list[ToolSpec]) -> int:
    return len(json.dumps([messages, tools])) // CHARS_PER_TOKEN_LOW + 1


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
        use_cache: bool = True,
    ) -> None:
        self.adapter = adapter
        self.usage = usage
        self.cache = cache
        self.run_id = run_id
        self.budget = budget
        self.use_cache = use_cache
        self.cache_hits = 0

    def chat(
        self, messages: list[Message], tools: list[ToolSpec], prompt_version: str
    ) -> ChatResult:
        model = self.adapter.model
        cost_usd(model, Usage(0, 0))  # unknown price -> fail before spending anything
        payload = {"adapter": self.adapter.config(), "prompt_version": prompt_version,
                   "messages": messages, "tools": tools}  # fmt: skip
        key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

        cached = self.cache.get(key) if self.use_cache else None
        if cached is not None:
            self.cache_hits += 1
            self.usage.record(self.run_id, model, prompt_version, Usage(0, 0), 0.0, True)
            logger.info("cache hit %s (%s)", key[:12], model)
            return _from_dict(cached)

        if self.budget is not None:
            worst = Usage(estimate_input_tokens(messages, tools), self.adapter.max_tokens)
            self.budget.check(cost_usd(model, worst))
        result = self.adapter.chat(messages, tools)
        cost = cost_usd(model, result.usage)
        self.usage.record(self.run_id, model, prompt_version, result.usage, cost, False)
        if self.budget is not None:
            self.budget.spent_usd += cost
        self.cache.put(key, asdict(result))
        logger.info(
            "model call %s: in=%d out=%d cost=$%.6f",
            model, result.usage.input_tokens, result.usage.output_tokens, cost,
        )  # fmt: skip
        return result
