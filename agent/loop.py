"""Minimal tool-calling loop: the model may only obtain numbers through query_metric.

Provenance is taken from the tool results, never from the model's text.
"""

import json
import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from agent.adapters.base import Message, ToolSpec
from agent.adapters.gateway import Gateway
from agent.tools.catalog import load_catalog
from agent.tools.query_metric import Provenance, query_metric
from core.warehouse import Warehouse

logger = logging.getLogger(__name__)

PROMPT_VERSION = "system.v1"
PROMPT_PATH = Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.md"
TOOL_ARGS = {"metrics", "group_by", "filters", "time_range"}
FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


class NoGovernedNumbersError(RuntimeError):
    """The model produced a final answer without calling query_metric."""


@dataclass(frozen=True)
class Answer:
    answer: str
    value: int | float | None
    provenance: list[Provenance]
    value_traced: bool  # value is one of the metric values query_metric returned
    steps: int


def tool_specs(warehouse: Warehouse) -> list[ToolSpec]:
    return [
        {
            "type": "function",
            "function": {
                "name": "query_metric",
                "description": "Query governed complaint metrics. The only source of numbers.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "metrics": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": sorted(load_catalog(warehouse).metrics),
                            },
                        },
                        "group_by": {"type": "array", "items": {"type": "string"}},
                        "filters": {
                            "type": "object",
                            "additionalProperties": {"type": "string"},
                            "description": "Equality filters, e.g. {'complaint__company': 'X'}",
                        },
                        "time_range": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 2,
                            "maxItems": 2,
                            "description": "[start, end] ISO dates, inclusive",
                        },
                    },
                    "required": ["metrics"],
                },
            },
        }
    ]


def parse_final(content: str) -> tuple[str, int | float | None]:
    text = content.strip()
    fenced = FENCE.match(text)
    data = json.loads(fenced.group(1) if fenced else text)
    return data["answer"], data["value"]


def _call_tool(name: str, args: dict[str, Any], warehouse: Warehouse):
    if name != "query_metric":
        raise ValueError(f"model called unknown tool {name!r}")
    unexpected = set(args) - TOOL_ARGS
    if unexpected:
        raise ValueError(f"query_metric got unexpected arguments {sorted(unexpected)}")
    time_range = args.get("time_range")
    return query_metric(
        args["metrics"],
        group_by=args.get("group_by"),
        filters=args.get("filters"),
        time_range=(time_range[0], time_range[1]) if time_range else None,
        warehouse=warehouse,
    )


def run(question: str, gateway: Gateway, warehouse: Warehouse, max_steps: int = 6) -> Answer:
    messages: list[Message] = [
        {"role": "system", "content": PROMPT_PATH.read_text()},
        {"role": "user", "content": question},
    ]
    tools = tool_specs(warehouse)
    provenance: list[Provenance] = []
    returned_values: set[float] = set()

    for step in range(1, max_steps + 1):
        result = gateway.chat(messages, tools, prompt_version=PROMPT_VERSION)
        if not result.tool_calls:
            if not provenance:
                raise NoGovernedNumbersError(f"final answer without query_metric: {result.content}")
            answer, value = parse_final(result.content or "")
            traced = value is None or float(value) in returned_values
            logger.info("answer after %d steps (value_traced=%s): %s", step, traced, answer)
            return Answer(answer, value, provenance, traced, step)

        messages.append(
            {
                "role": "assistant",
                "content": result.content or "",
                "tool_calls": [
                    {"id": c.id, "type": "function",
                     "function": {"name": c.name, "arguments": c.arguments_json}}
                    for c in result.tool_calls
                ],
            }
        )  # fmt: skip
        for call in result.tool_calls:
            out = _call_tool(call.name, call.arguments, warehouse)
            provenance.append(out.provenance)
            for row in out.rows:
                returned_values.update(
                    float(v)
                    for k, v in row.items()
                    if k in out.provenance.metrics and v is not None
                )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps({"rows": out.rows, "provenance": asdict(out.provenance)}),
                }
            )
    raise RuntimeError(f"agent hit the step limit ({max_steps}) without a final answer")
