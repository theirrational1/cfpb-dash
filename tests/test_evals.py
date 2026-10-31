import json

import duckdb
import pytest

from agent.adapters.base import ChatResult, ToolCall, Usage
from agent.adapters.fake import FakeAdapter
from agent.adapters.gateway import BudgetExceeded
from evals.harness.cases import load_cases
from evals.harness.runner import run_suite
from evals.harness.scoring import score

COMPANY = "CITIBANK, N.A."
CASES_TOML = f'''
[[cases]]
id = "e1-t1"
question = "How many complaints did {COMPANY} receive in March 2026?"
ground_truth_sql = """
SELECT count(*) FROM fct_complaints
WHERE company = '{COMPANY}' AND date_received BETWEEN '2026-03-01' AND '2026-03-31'
"""

[[cases]]
id = "e1-t2"
question = "Same question, wrong answer"
ground_truth_sql = "SELECT 7"

[[cases]]
id = "e1-t3"
question = "Answers without the tool"
ground_truth_sql = "SELECT 7"
'''


def _call() -> ChatResult:
    args = {
        "metrics": ["complaint_count"],
        "filters": {"complaint__company": COMPANY},
        "time_range": ["2026-03-01", "2026-03-31"],
    }
    return ChatResult(None, [ToolCall("c1", "query_metric", args)], Usage(100, 10), "fake")


def _final(value) -> ChatResult:
    return ChatResult(json.dumps({"answer": "x", "value": value}), [], Usage(120, 8), "fake")


@pytest.fixture
def cases_file(tmp_path):
    path = tmp_path / "e1.toml"
    path.write_text(CASES_TOML)
    return path


def test_load_cases(cases_file):
    cases = load_cases(cases_file)
    assert [c.id for c in cases] == ["e1-t1", "e1-t2", "e1-t3"]
    assert "fct_complaints" in cases[0].ground_truth_sql


def test_score_is_exact():
    assert score(5, 5) == "pass"
    assert score(5.0, 5) == "pass"
    assert score(6, 5) == "fail"
    assert score(None, 5) == "fail"


def test_run_suite_scores_pass_fail_error(warehouse, cases_file, tmp_path):
    # truth for case 1 on the fixture warehouse (the harness computes it the same way)
    row = (
        duckdb.connect(str(warehouse.duckdb_path), read_only=True)
        .execute(load_cases(cases_file)[0].ground_truth_sql)
        .fetchone()
    )
    assert row is not None
    n = row[0]
    fake = FakeAdapter([_call(), _final(n), _call(), _final(999), _final(7)])
    summary = run_suite(
        load_cases(cases_file),
        fake,
        warehouse,
        suite="e1",
        split="dev",
        results_dir=tmp_path / "results",
        ops_dir=tmp_path / "ops",
        budget_usd=1.0,
    )

    assert [r["status"] for r in summary["cases"]] == ["pass", "fail", "error"]
    assert summary["accuracy"] == pytest.approx(1 / 3)
    assert summary["cases"][2]["error"].startswith("NoGovernedNumbersError")
    lines = (tmp_path / "results" / f"{summary['run_id']}.jsonl").read_text().splitlines()
    records = [json.loads(line) for line in lines]
    assert records[-1]["kind"] == "summary"
    for r in records[:-1]:
        assert r["model"] == "fake"
        assert r["prompt_version"] == "system.v1"
        assert r["snapshot_date"] == "2026-10-31"
        assert "cost_usd" in r and "input_tokens" in r
    assert records[0]["input_tokens"] == 220  # 100 + 120, from the usage table


def test_budget_cap_stops_run_and_keeps_partial_results(
    warehouse, cases_file, tmp_path, monkeypatch
):
    monkeypatch.setattr("agent.adapters.gateway.cost_usd", lambda model, u: 0.5)
    fake = FakeAdapter([_call(), _final(1), _call(), _final(1)])
    with pytest.raises(BudgetExceeded):
        run_suite(
            load_cases(cases_file),
            fake,
            warehouse,
            suite="e1",
            split="dev",
            results_dir=tmp_path / "results",
            ops_dir=tmp_path / "ops",
            budget_usd=1.0,
        )
    [results] = list((tmp_path / "results").glob("*.jsonl"))
    assert len(results.read_text().splitlines()) == 1  # case 1 recorded before the cap hit
