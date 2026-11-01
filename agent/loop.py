"""Minimal tool-calling loop: the model may only obtain numbers through query_metric.

Provenance is taken from the tool results, never from the model's text. Every number in the
final answer (the `value` and any number in the text) is checked against what the tools
returned; numbers that also appear in the question (e.g. a year) are allowed.
"""

import json
import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from agent.adapters.base import Message, ToolCall, ToolSpec
from agent.adapters.gateway import Gateway
from agent.errors import FinalAnswerError, NoGovernedNumbersError, StepLimitError, ToolArgumentError
from agent.tools.catalog import load_catalog
from agent.tools.query_metric import MetricResult, Provenance, query_metric
from core.warehouse import Warehouse

logger = logging.getLogger(__name__)

PROMPT_VERSION = "system.v1"
PROMPT_PATH = Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.md"
TOOL_ARGS = {"metrics", "group_by", "filters", "time_range"}
FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)
NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")

__all__ = ["NoGovernedNumbersError", "Answer", "run", "parse_final", "untraced_numbers"]


@dataclass(frozen=True)
class Answer:
    answer: str
    value: int | float | None
    provenance: list[Provenance]
    value_traced: bool  # value is not None and is a metric value query_metric returned
    untraced_numbers: list[float]  # numbers in the text not returned by tools nor in the question
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
                            "description": "[start, end] YYYY-MM-DD, both inclusive",
                        },
                    },
                    "required": ["metrics"],
                },
            },
        }
    ]


def numbers_in(text: str) -> list[float]:
    return [float(m.replace(",", "")) for m in NUMBER.findall(text)]


def untraced_numbers(text: str, allowed: set[float]) -> list[float]:
    return [n for n in numbers_in(text) if n not in allowed]


def parse_final(content: str) -> tuple[str, int | float | None]:
    text = content.strip()
    fenced = FENCE.match(text)
    try:
        data = json.loads(fenced.group(1) if fenced else text)
    except json.JSONDecodeError as e:
        raise FinalAnswerError(f"final answer is not JSON: {content!r}") from e
    if not isinstance(data, dict) or set(data) != {"answer", "value"}:
        raise FinalAnswerError(f"final answer must be {{answer, value}}, got {data!r}")
    answer, value = data["answer"], data["value"]
    if not isinstance(answer, str):
        raise FinalAnswerError(f"answer must be a string, got {answer!r}")
    if value is not None and (isinstance(value, bool) or not isinstance(value, int | float)):
        raise FinalAnswerError(f"value must be a number or null, got {value!r}")
    return answer, value


def _call_tool(call: ToolCall, warehouse: Warehouse) -> MetricResult:
    if call.name != "query_metric":
        raise ToolArgumentError(f"model called unknown tool {call.name!r}")
    try:
        args = call.arguments
    except json.JSONDecodeError as e:
        raise ToolArgumentError(f"tool arguments are not JSON: {call.arguments_json!r}") from e
    if not isinstance(args, dict) or "metrics" not in args:
        raise ToolArgumentError(f"query_metric needs an object with `metrics`, got {args!r}")
    unexpected = set(args) - TOOL_ARGS
    if unexpected:
        raise ToolArgumentError(f"query_metric got unexpected arguments {sorted(unexpected)}")
    return query_metric(  # query_metric type-checks every argument (ToolArgumentError)
        args["metrics"],
        group_by=args.get("group_by"),
        filters=args.get("filters"),
        time_range=args.get("time_range"),
        warehouse=warehouse,
    )


def run(question: str, gateway: Gateway, warehouse: Warehouse, max_steps: int = 6) -> Answer:
    messages: list[Message] = [
        {"role": "system", "content": PROMPT_PATH.read_text()},
        {"role": "user", "content": question},
    ]
    tools = tool_specs(warehouse)
    provenance: list[Provenance] = []
    metric_values: set[float] = set()
    context_numbers: set[float] = set(numbers_in(question))

    for step in range(1, max_steps + 1):
        result = gateway.chat(messages, tools, prompt_version=PROMPT_VERSION)
        if not result.tool_calls:
            if not provenance:
                raise NoGovernedNumbersError(f"final answer without query_metric: {result.content}")
            answer, value = parse_final(result.content or "")
            traced = value is not None and float(value) in metric_values
            untraced = untraced_numbers(answer, metric_values | context_numbers)
            logger.info("answer after %d steps (value_traced=%s, untraced=%s): %s",
                        step, traced, untraced, answer)  # fmt: skip
            return Answer(answer, value, provenance, traced, untraced, step)

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
            out = _call_tool(call, warehouse)
            provenance.append(out.provenance)
            for row in out.rows:
                for k, v in row.items():
                    if k in out.provenance.metrics and v is not None:
                        metric_values.add(float(v))
                    elif isinstance(v, str):  # dimension values, e.g. dates in grouped rows
                        context_numbers.update(numbers_in(v))
            for v in out.provenance.filters.values():  # real values: query_metric checks them
                context_numbers.update(numbers_in(v))
            for t in out.provenance.time_range:  # validated YYYY-MM-DD: only its date parts
                if t:
                    context_numbers.update(float(part) for part in t.split("-"))
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps({"rows": out.rows, "provenance": asdict(out.provenance)}),
                }
            )
    raise StepLimitError(f"agent hit the step limit ({max_steps}) without a final answer")
