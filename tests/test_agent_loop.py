import json

import duckdb
import pytest

from agent.adapters.base import ChatResult, ToolCall, Usage
from agent.adapters.cache import JsonCache
from agent.adapters.fake import FakeAdapter
from agent.adapters.gateway import Gateway
from agent.adapters.usage import UsageLog
from agent.errors import FinalAnswerError, StepLimitError, ToolArgumentError
from agent.loop import NoGovernedNumbersError, parse_final, run, untraced_numbers

COMPANY = "CITIBANK, N.A."
ARGS = {
    "metrics": ["complaint_count"],
    "filters": {"complaint__company": COMPANY},
    "time_range": ["2026-03-01", "2026-03-31"],
}


def _tool_call() -> ChatResult:
    return ChatResult(
        content=None,
        tool_calls=[ToolCall.of("c1", "query_metric", ARGS)],
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
    with pytest.raises(StepLimitError, match="step limit"):
        run("loop forever", gw, warehouse, max_steps=3)


def test_parse_final_accepts_fenced_json_and_rejects_prose():
    assert parse_final('```json\n{"answer": "x", "value": 3}\n```') == ("x", 3)
    with pytest.raises(FinalAnswerError):
        parse_final("There were 3 complaints.")


@pytest.mark.parametrize(
    "text",
    [
        '{"answer": "x", "value": "1002"}',  # string, not a number
        '{"answer": "x", "value": true}',  # bool is not a number
        '{"answer": "x"}',  # missing value
        '["not", "an", "object"]',
    ],
)
def test_parse_final_rejects_non_numeric_values(text):
    with pytest.raises(FinalAnswerError):
        parse_final(text)


def _answer(tmp_path, warehouse, final: str):
    _, gw = _gateway(tmp_path, [_tool_call(), _final(final)])
    return run("How many complaints did Citibank receive in March 2026?", gw, warehouse)


def test_null_value_is_not_traced(warehouse, tmp_path):
    """Review #8: value null used to count as traced."""
    a = _answer(tmp_path, warehouse, '{"answer": "Citi got 999 complaints.", "value": null}')
    assert a.value_traced is False
    assert a.untraced_numbers == [999.0]


def test_numbers_in_answer_text_must_trace(warehouse, tmp_path):
    n = _march_count(warehouse)
    ok = _answer(
        tmp_path / "a",
        warehouse,
        json.dumps({"answer": f"In March 2026 {COMPANY} received {n:,} complaints.", "value": n}),
    )
    assert ok.value_traced and ok.untraced_numbers == []  # 2026 is in the question
    bad = _answer(
        tmp_path / "b",
        warehouse,
        json.dumps({"answer": f"{n} complaints, up 12% on February.", "value": n}),
    )
    assert bad.value_traced and bad.untraced_numbers == [12.0]


def test_untraced_numbers_helper():
    assert untraced_numbers("1,234 and 5.5% and -3", allowed={1234.0}) == [5.5, -3.0]


def test_bad_tool_arguments_are_typed_model_errors(warehouse, tmp_path):
    bad_calls = [
        ToolCall("c", "query_metric", "{not json"),
        ToolCall.of("c", "query_metric", {**ARGS, "time_range": ["2026-03-01"]}),  # review #6
        ToolCall.of("c", "query_metric", {**ARGS, "sql": "select 1"}),
        ToolCall.of("c", "run_sql", {"q": "select 1"}),
    ]
    for call in bad_calls:
        result = ChatResult(content=None, tool_calls=[call], usage=Usage(1, 1), model="fake")
        _, gw = _gateway(tmp_path / call.arguments_json[:5].replace("/", "_"), [result])
        with pytest.raises(ToolArgumentError):
            run("q", gw, warehouse)


def test_model_cannot_launder_a_number_through_a_filter_value(warehouse, tmp_path):
    """Review 2 #3: numbers in filter values were whitelisted, and the model writes filters."""
    launder = ToolCall.of(
        "c2", "query_metric", {**ARGS, "filters": {"complaint__company": "up 999 percent"}}
    )
    script = [
        _tool_call(),
        ChatResult(None, [launder], Usage(1, 1), "fake"),
        _final('{"answer": "16 complaints, up 999% year over year.", "value": 16}'),
    ]
    _, gw = _gateway(tmp_path, script)
    with pytest.raises(ToolArgumentError, match="not in the data"):
        run("How many complaints did Citibank receive in March 2026?", gw, warehouse)


def test_time_range_contributes_only_its_date_parts(warehouse, tmp_path):
    n = _march_count(warehouse)
    # 1, 3 and 31 are parts of 2026-03-01..2026-03-31 (the regex used to read them as -3, -31)
    text = f"{n} complaints from 1 to 31 March (month 3) 2026, not {n * 3}."
    a = _answer(tmp_path, warehouse, json.dumps({"answer": text, "value": n}))
    assert a.untraced_numbers == [float(n * 3)]
