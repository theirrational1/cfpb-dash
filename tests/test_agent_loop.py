import json

import duckdb
import pytest

from agent.adapters.base import ChatResult, ToolCall, Usage
from agent.adapters.cache import JsonCache
from agent.adapters.fake import FakeAdapter
from agent.adapters.gateway import Gateway
from agent.adapters.usage import UsageLog
from agent.loop import NoGovernedNumbersError, parse_final, run

COMPANY = "CITIBANK, N.A."
ARGS = {
    "metrics": ["complaint_count"],
    "filters": {"complaint__company": COMPANY},
    "time_range": ["2026-03-01", "2026-03-31"],
}


def _tool_call() -> ChatResult:
    return ChatResult(
        content=None,
        tool_calls=[ToolCall(id="c1", name="query_metric", arguments=ARGS)],
        usage=Usage(100, 20),
        model="fake",
    )


def _final(text: str) -> ChatResult:
    return ChatResult(content=text, tool_calls=[], usage=Usage(150, 30), model="fake")


def _gateway(tmp_path, script):
    fake = FakeAdapter(script)
    gw = Gateway(fake, UsageLog(tmp_path / "u.duckdb"), JsonCache(tmp_path / "c"), run_id="t")
    return fake, gw


def _march_count(warehouse) -> int:
    con = duckdb.connect(str(warehouse.duckdb_path), read_only=True)
    row = con.execute(
        """SELECT count(*) FROM fct_complaints
           WHERE company = ? AND date_received BETWEEN '2026-03-01' AND '2026-03-31'""",
        [COMPANY],
    ).fetchone()
    assert row is not None
    return row[0]


def test_answer_uses_tool_and_carries_tool_provenance(warehouse, tmp_path):
    n = _march_count(warehouse)
    final = json.dumps({"answer": f"{COMPANY} received {n} complaints in March 2026.", "value": n})
    fake, gw = _gateway(tmp_path, [_tool_call(), _final(final)])

    answer = run("How many complaints did Citibank receive in March 2026?", gw, warehouse)

    assert answer.value == n
    [p] = answer.provenance
    assert p.metrics == ["complaint_count"]
    assert p.filters == {"complaint__company": COMPANY}
    assert p.time_range == ("2026-03-01", "2026-03-31")
    assert p.snapshot_date == "2026-10-31"
    # the model saw the governed result as a tool message
    tool_msg = fake.calls[1][0][-1]
    assert tool_msg["role"] == "tool" and tool_msg["tool_call_id"] == "c1"
    assert json.loads(tool_msg["content"])["rows"] == [{"complaint_count": n}]


def test_answer_without_tool_call_is_rejected(warehouse, tmp_path):
    _, gw = _gateway(tmp_path, [_final('{"answer": "About 50.", "value": 50}')])
    with pytest.raises(NoGovernedNumbersError):
        run("How many complaints did Citibank receive?", gw, warehouse)


def test_step_limit(warehouse, tmp_path):
    _, gw = _gateway(tmp_path, [_tool_call()] * 3)
    with pytest.raises(RuntimeError, match="step limit"):
        run("loop forever", gw, warehouse, max_steps=3)


def test_parse_final_accepts_fenced_json_and_rejects_prose():
    assert parse_final('```json\n{"answer": "x", "value": 3}\n```') == ("x", 3)
    with pytest.raises(json.JSONDecodeError):
        parse_final("There were 3 complaints.")
