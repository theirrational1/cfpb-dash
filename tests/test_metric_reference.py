"""M3-02: every governed metric equals hand-written SQL on fct_complaints, on both fixture
warehouses, ungrouped and at two groupings. Numbers come from query_metric (the governed
path); the SQL here is the independent reference, never used by the product."""

import math

import duckdb
import pytest

from agent.tools.query_metric import query_metric

RESPONDED = "company_response IS NOT NULL AND company_response <> 'In progress'"
OPT_OUT = "Company chooses not to provide a public response"
PR_KNOWN = (
    "public_response IS NOT NULL AND date_received >= DATE '2015-01-01'"
    " AND company_response IS NOT NULL"
)

# metric -> SQL aggregate over fct_complaints (the reference definition)
REFERENCE = {
    "complaint_count": "count(*)",
    "relief_rate": "sum(CASE WHEN is_relief THEN 1 ELSE 0 END) / nullif(count(is_relief), 0)",
    "monetary_relief_rate": (
        "sum(CASE WHEN is_monetary_relief THEN 1 ELSE 0 END) / nullif(count(is_monetary_relief), 0)"
    ),
    "timely_response_rate": (
        f"sum(CASE WHEN timely AND {RESPONDED} THEN 1 ELSE 0 END)"
        f" / nullif(sum(CASE WHEN {RESPONDED} THEN 1 ELSE 0 END), 0)"
    ),
    # written from the stated definition, not the measure: from 2015, status recorded
    "public_response_rate": (
        f"sum(CASE WHEN {PR_KNOWN} AND public_response NOT IN ('none_given', '{OPT_OUT}')"
        f" THEN 1 ELSE 0 END) / nullif(sum(CASE WHEN {PR_KNOWN} THEN 1 ELSE 0 END), 0)"
    ),
    "forwarding_lag_days": "median(forwarding_lag_days)",
}

GROUPINGS = {
    "total": ([], []),
    "company_month": (
        ["complaint__company", "metric_time__month"],
        ["company", "strftime(date_trunc('month', date_received), '%Y-%m')"],
    ),
    "family_quarter": (
        ["complaint__product_family", "metric_time__quarter"],
        ["product_family", "strftime(date_trunc('quarter', date_received), '%Y-%m')"],
    ),
}


def _key(row: dict, dims: list[str]) -> tuple:
    return tuple(str(row[d])[:7] if d.startswith("metric_time") else row[d] for d in dims)


def _same(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(float(a), float(b), rel_tol=0, abs_tol=1e-9)


@pytest.fixture(params=["warehouse", "eras_warehouse"])
def wh(request):
    return request.getfixturevalue(request.param)


@pytest.mark.parametrize("grouping", sorted(GROUPINGS))
@pytest.mark.parametrize("metric", sorted(REFERENCE))
def test_metric_matches_reference_sql(wh, metric, grouping):
    dims, sql_dims = GROUPINGS[grouping]
    governed = query_metric([metric], group_by=dims, warehouse=wh)
    got = {_key(r, dims): r[metric] for r in governed.rows}

    select = ", ".join([*sql_dims, f"{REFERENCE[metric]} AS v"])
    group = f"GROUP BY {', '.join(str(i + 1) for i in range(len(sql_dims)))}" if sql_dims else ""
    con = duckdb.connect(str(wh.duckdb_path), read_only=True)
    expected = {tuple(r[:-1]): r[-1] for r in con.execute(
        f"SELECT {select} FROM fct_complaints {group}").fetchall()}  # fmt: skip

    if metric == "complaint_count" and dims:  # zero-filled: periods with no rows are 0
        got = {k: v for k, v in got.items() if v != 0}
    assert set(got) == set(expected), f"{metric}/{grouping}: different groups"
    bad = {k: (got[k], expected[k]) for k in expected if not _same(got[k], expected[k])}
    assert not bad, f"{metric}/{grouping}: {list(bad.items())[:5]}"


# metric -> (grain, months back): growth compares like for like (period to date)
GROWTH = {
    "complaint_growth_mom": ("month", 1),
    "complaint_growth_yoy": ("month", 12),
    "complaint_growth_yoy_quarterly": ("quarter", 12),
    "complaint_growth_yoy_annual": ("year", 12),
}


@pytest.mark.parametrize(("dims", "sql_dim"), [([], None), (["complaint__product_family"],
                                                            "product_family")])  # fmt: skip
@pytest.mark.parametrize("metric", sorted(GROWTH))
def test_growth_compares_the_same_days_and_matches_reference_sql(wh, metric, dims, sql_dim):
    """Review 4 #3: each period, through its last day with data, against the same days
    `months` earlier. Every period with data must be returned (exact key set)."""
    grain, months = GROWTH[metric]
    col = f"metric_time__{grain}"
    governed = query_metric([metric], group_by=[*dims, col], warehouse=wh)
    got = {_key(r, [*dims, col]): r[metric] for r in governed.rows}

    con = duckdb.connect(str(wh.duckdb_path), read_only=True)
    g = f"{sql_dim}, " if sql_dim else ""
    join = f"AND f.{sql_dim} = p.{sql_dim}" if sql_dim else ""
    rows = con.execute(f"""
        WITH bounds AS (SELECT min(date_received) AS lo, max(date_received) AS hi
                        FROM fct_complaints),
        periods AS (
            SELECT DISTINCT {g}date_trunc('{grain}', date_received) AS p FROM fct_complaints),
        spans AS (
            SELECT periods.*, least(p + INTERVAL 1 {grain} - INTERVAL 1 DAY, hi) AS last_day
            FROM periods, bounds)
        SELECT {"p." + sql_dim + ", " if sql_dim else ""}strftime(p.p, '%Y-%m'),
               count(*) FILTER (WHERE f.date_received BETWEEN p.p AND p.last_day) AS cur,
               count(*) FILTER (WHERE f.date_received BETWEEN p.p - INTERVAL {months} MONTH
                                AND p.last_day - INTERVAL {months} MONTH) AS earlier
        FROM spans p LEFT JOIN fct_complaints f ON TRUE {join}
        GROUP BY ALL""").fetchall()
    expected = {tuple(r[:-2]): (r[-2] - r[-1]) / r[-1] if r[-1] else None for r in rows}
    got_with_data = {k: v for k, v in got.items() if k in expected}
    assert set(got_with_data) == set(expected), f"{metric}: missing periods"
    bad = {k: (got[k], v) for k, v in expected.items() if not _same(got[k], v)}
    assert not bad, f"{metric}: {list(bad.items())[:5]}"


def test_partial_periods_are_flagged(warehouse):
    """The sample runs 2025-01-02..2026-06-30: both years are partial; 2026 is compared with
    the same days of 2025 and flagged."""
    result = query_metric(["complaint_growth_yoy_annual"], group_by=["metric_time__year"],
                          warehouse=warehouse)  # fmt: skip
    assert result.provenance.partial_periods == ["2025-01-01", "2026-01-01"]
    monthly = query_metric(["complaint_count"], group_by=["metric_time__month"],
                           warehouse=warehouse).provenance  # fmt: skip
    assert monthly.partial_periods == ["2025-01-01"]  # the first month starts on the 2nd
    yoy = query_metric(["complaint_growth_yoy"], group_by=["metric_time__month"],
                       warehouse=warehouse).provenance  # fmt: skip
    # every 2025 month compares with 2024 (before the data); 2026-01 compares with 2025-01,
    # which misses its first day (the sample starts 2025-01-02)
    assert yoy.partial_periods == [f"2025-{m:02d}-01" for m in range(1, 13)] + ["2026-01-01"]
