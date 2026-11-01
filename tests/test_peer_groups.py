"""M3-03: peer groups (eligibility threshold, complaint-volume tiers) match reference SQL and
the versioned params files."""

import duckdb
import pytest
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


SYNCHRONY, CITI = "SYNCHRONY FINANCIAL", "CITIBANK, N.A."


@pytest.fixture(scope="module")
def mixed_warehouse(tmp_path_factory, fixture_csv, dbt_project):
    """Review 4 #5: eligible and below-threshold companies in one family, and a credit card
    complaint with no issue. Derived from the committed sample: Synchrony keeps only 50
    complaints in the trailing window (2025-10..2026-09); one Citibank issue is blanked."""
    import csv

    from tests.conftest import build_warehouse

    with fixture_csv.open(newline="") as f:
        rows = list(csv.reader(f))
    header, body = rows[0], rows[1:]
    company, received, issue = (header.index(c) for c in ("Company", "Date received", "Issue"))
    kept, synchrony_in_window = [], 0
    for r in body:
        if r[company] == SYNCHRONY and r[received] >= "2025-10-01":
            synchrony_in_window += 1
            if synchrony_in_window > 50:
                continue
        kept.append(r)
    first_citi = next(r for r in kept if r[company] == CITI)
    first_citi[issue] = ""
    root = tmp_path_factory.mktemp("mixed")
    path = root / "mixed.csv"
    with path.open("w", newline="") as f:
        csv.writer(f).writerows([header, *kept])
    return build_warehouse(root / "wh", path, "2026-10-31", dbt_project)


def _sql(wh, sql, params=()):
    return duckdb.connect(str(wh.duckdb_path), read_only=True).execute(sql, list(params)).fetchall()


def test_the_peer_filter_actually_filters(mixed_warehouse):
    status = dict(_sql(mixed_warehouse, """SELECT d.company_name, p.peer_status
        FROM dim_company_product p JOIN dim_company d USING (company_key)"""))  # fmt: skip
    assert status == {SYNCHRONY: "below_threshold", CITI: "eligible",
                      "CAPITAL ONE FINANCIAL CORPORATION": "eligible"}  # fmt: skip
    eligible = query_metric(["relief_rate"], group_by=["complaint__company"],
                            filters={"company_product__peer_status": "eligible"},
                            warehouse=mixed_warehouse).rows  # fmt: skip
    everyone = query_metric(["relief_rate"], group_by=["complaint__company"],
                            warehouse=mixed_warehouse).rows  # fmt: skip
    assert {r["complaint__company"] for r in eligible} == {
        CITI,
        "CAPITAL ONE FINANCIAL CORPORATION",
    }
    assert len(everyone) == 3


def test_per_tier_values_match_reference_sql(mixed_warehouse):
    """Two eligible companies -> tiers high and middle only; below-threshold has no tier."""
    got = {r["company_product__volume_tier"]: r["complaint_count"] for r in query_metric(
        ["complaint_count"], group_by=["company_product__volume_tier"],
        warehouse=mixed_warehouse).rows}  # fmt: skip
    expected = dict(_sql(mixed_warehouse, """SELECT p.volume_tier, count(*) FROM fct_complaints f
        JOIN dim_company_product p USING (company_product_key) GROUP BY 1"""))  # fmt: skip
    assert got == expected and set(got) == {"high", "middle", None}


def test_issue_share_excludes_the_null_issue(mixed_warehouse):
    """Review 4 #6: the null-issue path was never exercised."""
    from core.issue_share import canonical_issues, slug

    metrics = [f"issue_share_{slug(i)}" for i in canonical_issues()]
    [row] = query_metric(metrics, filters={"complaint__company": CITI},
                         warehouse=mixed_warehouse).rows  # fmt: skip
    [(known, total)] = _sql(
        mixed_warehouse,
        """SELECT count(credit_card_issue), count(*)
        FROM fct_complaints WHERE company = ? AND product_family = 'credit_card'""",
        [CITI],
    )
    assert known == total - 1
    for issue, metric in zip(canonical_issues(), metrics, strict=True):
        [(n,)] = _sql(
            mixed_warehouse,
            """SELECT count(*) FROM fct_complaints
            WHERE company = ? AND credit_card_issue = ?""",
            [CITI, issue],
        )
        assert abs(float(row[metric] or 0) - n / known) < 1e-9, issue
    [(missing,)] = _sql(mixed_warehouse, "SELECT value FROM data_coverage "
                        "WHERE item = 'issue_missing' AND scope = 'credit_card'")  # fmt: skip
    assert missing == "1"
