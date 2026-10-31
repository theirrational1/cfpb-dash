import duckdb
import pytest

from agent.tools.query_metric import query_metric

COMPANY = "CAPITAL ONE FINANCIAL CORPORATION"


def test_returns_governed_numbers_with_provenance(warehouse):
    result = query_metric(
        ["complaint_count"],
        group_by=["metric_time__month"],
        filters={"complaint__company": COMPANY},
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
    assert p.filters == {"complaint__company": COMPANY}
    assert p.time_range == ("2026-01-01", "2026-03-31")
    assert p.snapshot_date == "2026-10-31"


def test_quote_in_filter_value_is_escaped(warehouse):
    result = query_metric(
        ["complaint_count"], filters={"complaint__company": "O'Brien Bank"}, warehouse=warehouse
    )
    assert result.rows in ([], [{"complaint_count": None}], [{"complaint_count": 0}])


@pytest.mark.parametrize(
    "filters",
    [
        {"complaint__company": "{{ Dimension('x') }}"},  # template injection
        {"complaint__company) OR (1=1": "x"},  # bad dimension name
    ],
)
def test_rejects_unsafe_filters(warehouse, filters):
    with pytest.raises(ValueError):
        query_metric(["complaint_count"], filters=filters, warehouse=warehouse)


def test_unknown_metric_fails_loudly(warehouse):
    with pytest.raises(RuntimeError, match="no_such_metric"):
        query_metric(["no_such_metric"], warehouse=warehouse)
