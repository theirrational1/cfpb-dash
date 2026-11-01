"""M3-03: peer groups (eligibility threshold, complaint-volume tiers) match reference SQL and
the versioned params files."""

import duckdb
import yaml

from agent.tools.query_metric import query_metric
from core.warehouse import DBT_DIR, REPO_ROOT


def _yaml(path):
    return yaml.safe_load(path.read_text())


def test_dbt_vars_mirror_the_versioned_params():
    dbt_vars = _yaml(DBT_DIR / "dbt_project.yml")["vars"]
    threshold = _yaml(REPO_ROOT / "params" / "min_volume_threshold.v1.yaml")
    tiers = _yaml(REPO_ROOT / "params" / "volume_tiers.v1.yaml")
    assert (dbt_vars["min_volume_threshold_version"], dbt_vars["min_volume_threshold"]) == (
        threshold["version"], threshold["min_complaints"])  # fmt: skip
    assert (dbt_vars["volume_tiers_version"], dbt_vars["volume_tier_labels"]) == (
        tiers["version"], tiers["labels"])  # fmt: skip


def test_eligibility_matches_reference_sql(warehouse, eras_warehouse):
    for wh in (warehouse, eras_warehouse):
        con = duckdb.connect(str(wh.duckdb_path), read_only=True)
        expected = con.execute(
            """WITH w AS (
                   SELECT cast(date_trunc('month', cast(snapshot_date AS DATE))
                               - INTERVAL 12 MONTH AS DATE) AS s,
                          cast(date_trunc('month', cast(snapshot_date AS DATE))
                               - INTERVAL 1 DAY AS DATE) AS e
                   FROM warehouse_snapshot)
               SELECT company_key, product_family,
                      count(*) FILTER (WHERE date_received BETWEEN w.s AND w.e) AS n
               FROM fct_complaints, w GROUP BY ALL ORDER BY ALL"""
        ).fetchall()
        got = con.execute(
            """SELECT company_key, product_family, complaints_trailing_12m, peer_status
               FROM dim_company_product ORDER BY 1, 2"""
        ).fetchall()
        assert [r[:3] for r in got] == expected
        assert all((r[3] == "eligible") == (r[2] >= 100) for r in got)


def test_window_is_the_12_full_months_before_the_snapshot_month(warehouse):
    con = duckdb.connect(str(warehouse.duckdb_path), read_only=True)
    assert con.execute(
        "SELECT DISTINCT CAST(window_start AS VARCHAR), CAST(window_end AS VARCHAR) "
        "FROM dim_company_product"
    ).fetchall() == [("2025-10-01", "2026-09-30")]  # snapshot 2026-10-31


def test_metrics_filter_by_peer_status_and_tier(warehouse):
    """Through the governed path: a rate for eligible high-tier companies equals SQL."""
    result = query_metric(
        ["relief_rate"],
        group_by=["complaint__company"],
        filters={"company_product__peer_status": "eligible"},
        warehouse=warehouse,
    )
    con = duckdb.connect(str(warehouse.duckdb_path), read_only=True)
    expected = dict(
        con.execute(
            """SELECT f.company, sum(CASE WHEN is_relief THEN 1 ELSE 0 END)
                                 / nullif(count(is_relief), 0)
               FROM fct_complaints f JOIN dim_company_product d USING (company_product_key)
               WHERE d.peer_status = 'eligible' GROUP BY 1"""
        ).fetchall()
    )
    assert {r["complaint__company"]: r["relief_rate"] for r in result.rows} == expected
    tiers = query_metric(["complaint_count"], group_by=["company_product__volume_tier"],
                         warehouse=warehouse).rows  # fmt: skip
    assert {r["company_product__volume_tier"] for r in tiers} == {"high", "middle", "low"}
