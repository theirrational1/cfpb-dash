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


GROWTH = {"complaint_growth_mom": 1, "complaint_growth_yoy": 12}  # offset in months


@pytest.mark.parametrize(("dims", "sql_dim"), [([], None), (["complaint__product_family"],
                                                            "product_family")])  # fmt: skip
@pytest.mark.parametrize("metric", sorted(GROWTH))
def test_growth_matches_reference_sql(wh, metric, dims, sql_dim):
    """Monthly counts are zero-filled over the data's months; growth is null after a 0."""
    governed = query_metric([metric], group_by=[*dims, "metric_time__month"], warehouse=wh)
    got = {_key(r, [*dims, "metric_time__month"]): r[metric] for r in governed.rows}

    g = f"{sql_dim}, " if sql_dim else ""
    part = f"PARTITION BY {sql_dim} " if sql_dim else ""
    con = duckdb.connect(str(wh.duckdb_path), read_only=True)
    rows = con.execute(f"""
        WITH months AS (
            SELECT DISTINCT date_trunc('month', date_day) AS m FROM metricflow_time_spine),
        groups AS (SELECT DISTINCT {sql_dim or "1"} AS g FROM fct_complaints),
        counts AS (
            SELECT {g}date_trunc('month', date_received) AS m, count(*) AS n
            FROM fct_complaints GROUP BY ALL),
        filled AS (
            SELECT {"groups.g AS " + sql_dim + ", " if sql_dim else ""}months.m,
                   coalesce(counts.n, 0) AS n
            FROM months CROSS JOIN groups
            LEFT JOIN counts ON counts.m = months.m
                {"AND counts." + sql_dim + " = groups.g" if sql_dim else ""})
        SELECT {g}strftime(m, '%Y-%m'),
               (n - lag(n, {GROWTH[metric]}) OVER ({part}ORDER BY m))
                 / nullif(lag(n, {GROWTH[metric]}) OVER ({part}ORDER BY m), 0)
        FROM filled""").fetchall()
    expected = {tuple(r[:-1]): r[-1] for r in rows}
    assert got, metric
    bad = {k: (v, expected.get(k)) for k, v in got.items() if not _same(v, expected.get(k))}
    assert not bad, f"{metric}: {list(bad.items())[:5]}"
