"""M3-02: every governed metric equals hand-written SQL on fct_complaints, on both fixture
warehouses, ungrouped and at two groupings. Numbers come from query_metric (the governed
path); the SQL here is the independent reference, never used by the product."""

import math

import duckdb
import pytest

from agent.tools.query_metric import query_metric

RESPONDED = "company_response IS NOT NULL AND company_response <> 'In progress'"
OPT_OUT = "Company chooses not to provide a public response"

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
    "public_response_rate": (
        f"sum(CASE WHEN public_response NOT IN ('none_given', '{OPT_OUT}') THEN 1 ELSE 0 END)"
        " / nullif(count(public_response), 0)"
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
