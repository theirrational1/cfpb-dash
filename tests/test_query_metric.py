import duckdb
import pytest

from agent.tools.query_metric import ToolArgumentError, _where, query_metric

COMPANY = "CAPITAL ONE FINANCIAL CORPORATION"
CO = {"complaint__company": COMPANY}


def _sql_count(warehouse, start: str, end: str) -> int:
    con = duckdb.connect(str(warehouse.duckdb_path), read_only=True)
    row = con.execute(
        "SELECT count(*) FROM fct_complaints WHERE company = ? AND date_received BETWEEN ? AND ?",
        [COMPANY, start, end],
    ).fetchone()
    assert row is not None
    return row[0]


def test_returns_governed_numbers_with_provenance(warehouse):
    result = query_metric(
        ["complaint_count"],
        group_by=["metric_time__month"],
        filters=CO,
        time_range=("2026-01-01", "2026-03-31"),
        warehouse=warehouse,
    )
    con = duckdb.connect(str(warehouse.duckdb_path), read_only=True)
    expected = con.execute(
        """SELECT strftime(date_trunc('month', date_received), '%Y-%m'), count(*)
           FROM fct_complaints
           WHERE company = ? AND date_received BETWEEN '2026-01-01' AND '2026-03-31'
           GROUP BY 1 ORDER BY 1""",
        [COMPANY],
    ).fetchall()
    assert [
        (str(r["metric_time__month"])[:7], r["complaint_count"]) for r in result.rows
    ] == expected
    assert all(isinstance(r["complaint_count"], int) for r in result.rows)

    p = result.provenance
    assert p.metrics == ["complaint_count"]
    assert p.group_by == ["metric_time__month"]
    assert p.filters == CO
    assert p.time_range == ("2026-01-01", "2026-03-31")
    assert p.columns == ["metric_time__month", "complaint_count"]
    assert p.snapshot_date == "2026-10-31"


def test_inclusive_day_range_matches_sql(warehouse):
    result = query_metric(
        ["complaint_count"],
        filters=CO,
        time_range=("2026-03-01", "2026-03-31"),
        warehouse=warehouse,
    )
    assert result.rows == [{"complaint_count": _sql_count(warehouse, "2026-03-01", "2026-03-31")}]


def test_quote_in_filter_value_is_escaped():
    assert _where("complaint__company", "O'Brien") == (
        "{{ Dimension('complaint__company') }} = 'O''Brien'"
    )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        # review #2: a time filter silently became a one-day filter
        ({"filters": {"metric_time__month": "2026-03-01"}}, "time_range"),
        # review #1: a coarse grain widened the range past what provenance claimed
        (
            {"group_by": ["metric_time__year"], "time_range": ("2026-03-01", "2026-03-31")},
            "align",
        ),
        (
            {"group_by": ["metric_time__month"], "time_range": ("2026-03-15", "2026-03-20")},
            "align",
        ),
        # review #7: partial / inverted / non-ISO dates
        ({"time_range": ("2026-03", "2026-03")}, "YYYY-MM-DD"),
        ({"time_range": ("2026-03-31", "2026-03-01")}, "start"),
        ({"time_range": ("03/01/2026", "2026-03-31")}, "YYYY-MM-DD"),
        # review #10: bare metric_time has an implicit grain
        ({"group_by": ["metric_time"]}, "grain"),
        ({"group_by": ["metric_time__month", "metric_time__year"]}, "one time grain"),
        # names: template injection, bad syntax, unknown to the semantic layer
        ({"filters": {"complaint__company": "{{ Dimension('x') }}"}}, "braces"),
        ({"filters": {"complaint__company) OR (1=1": "x"}}, "dimension"),
        ({"filters": {"complaint__state": "CA"}}, "dimension"),
        ({"group_by": ["complaint__zip_code"]}, "group_by"),
        # review 2 #4: values and periods the data doesn't have used to return a traced 0
        ({"filters": {"complaint__company": "Citibank"}}, "CITIBANK, N.A."),
        ({"filters": {"complaint__company": "O'Brien Bank"}}, "not in the data"),
        ({"time_range": ("2027-01-01", "2027-12-31")}, "outside the data"),
        ({"time_range": ("2024-12-31", "2025-01-31")}, "outside the data"),
        (
            {"group_by": ["metric_time__month"], "time_range": ("2020-01-01", "2020-12-31")},
            "outside the data",
        ),
    ],
)
def test_rejects_unsafe_or_misleading_arguments(warehouse, kwargs, message):
    with pytest.raises(ToolArgumentError, match=message):
        query_metric(["complaint_count"], warehouse=warehouse, **kwargs)


def test_aligned_coarse_range_is_allowed_and_correct(warehouse):
    result = query_metric(
        ["complaint_count"],
        group_by=["metric_time__quarter"],
        filters=CO,
        time_range=("2026-01-01", "2026-03-31"),
        warehouse=warehouse,
    )
    assert [r["complaint_count"] for r in result.rows] == [
        _sql_count(warehouse, "2026-01-01", "2026-03-31")
    ]


def test_unknown_metric_is_a_tool_argument_error(warehouse):
    with pytest.raises(ToolArgumentError, match="no_such_metric"):
        query_metric(["no_such_metric"], warehouse=warehouse)


@pytest.mark.parametrize(
    "kwargs",
    [
        # review 2 #2: model-shaped mistakes must be ToolArgumentError, not crash the eval run
        {"metrics": ["complaint_count", "complaint_count"]},
        {"metrics": "complaint_count"},
        {"metrics": [["complaint_count"]]},
        {"metrics": ["complaint_count"], "group_by": [1]},
        {"metrics": ["complaint_count"], "group_by": "metric_time__month"},
        {"metrics": ["complaint_count"], "filters": "abc"},
        {"metrics": ["complaint_count"], "filters": {"complaint__company": 3}},
        {"metrics": ["complaint_count"], "time_range": ["2026-03-01"]},
        {"metrics": ["complaint_count"], "time_range": [20260301, 20260331]},
        {
            "metrics": ["complaint_count"],
            "group_by": ["metric_time__month"],
            "time_range": ["2026-01-01", "9999-12-31"],
        },
    ],
)
def test_malformed_arguments_are_tool_argument_errors(warehouse, kwargs):
    with pytest.raises(ToolArgumentError):
        query_metric(warehouse=warehouse, **kwargs)


def test_empty_result_is_zero_rows_not_a_crash(warehouse):
    con = duckdb.connect(str(warehouse.duckdb_path), read_only=True)
    row = con.execute(
        """SELECT min(date_day) FROM metricflow_time_spine
           WHERE date_day NOT IN (SELECT date_received FROM fct_complaints)"""
    ).fetchone()
    assert row is not None
    day = str(row[0])
    result = query_metric(
        ["complaint_count"],
        group_by=["complaint__company"],
        time_range=(day, day),
        warehouse=warehouse,
    )
    assert result.rows == []
    assert result.provenance.columns == ["complaint__company", "complaint_count"]


def test_partly_covered_edge_period_is_allowed_and_coverage_is_in_provenance(warehouse):
    """Data starts 2025-01-02: January 2025 by month is allowed; provenance says what's covered."""
    result = query_metric(
        ["complaint_count"],
        group_by=["metric_time__month"],
        filters=CO,
        time_range=("2025-01-01", "2025-01-31"),
        warehouse=warehouse,
    )
    assert [r["complaint_count"] for r in result.rows] == [
        _sql_count(warehouse, "2025-01-01", "2025-01-31")
    ]
    assert result.provenance.data_range == ("2025-01-02", "2026-06-30")
