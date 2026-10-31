import csv

import duckdb
import pytest

from core.warehouse import run_cli

COMPANY = "CITIBANK, N.A."


def _mf_rows(warehouse, tmp_path, args: list[str]) -> list[dict[str, str]]:
    out = tmp_path / "mf.csv"
    run_cli("mf", ["query", *args, "--csv", str(out)], warehouse)
    with out.open(newline="") as f:
        return list(csv.DictReader(f))


@pytest.mark.parametrize("company", [COMPANY, "SYNCHRONY FINANCIAL"])
def test_complaint_count_by_month_matches_sql(warehouse, tmp_path, company):
    rows = _mf_rows(
        warehouse,
        tmp_path,
        [
            "--metrics", "complaint_count",
            "--group-by", "metric_time__month",
            "--where", f"{{{{ Dimension('complaint__company') }}}} = '{company}'",
        ],
    )  # fmt: skip
    got = {r["metric_time__month"][:7]: int(r["complaint_count"]) for r in rows}

    con = duckdb.connect(str(warehouse.duckdb_path), read_only=True)
    expected = dict(
        con.execute(
            """SELECT strftime(date_trunc('month', date_received), '%Y-%m'), count(*)
               FROM fct_complaints WHERE company = ? GROUP BY 1""",
            [company],
        ).fetchall()
    )
    assert got == expected
    assert sum(got.values()) == 334


def test_complaint_count_total_matches_sql(warehouse, tmp_path):
    rows = _mf_rows(warehouse, tmp_path, ["--metrics", "complaint_count"])
    assert [int(r["complaint_count"]) for r in rows] == [1002]


def test_validate_configs(warehouse):
    run_cli("mf", ["validate-configs"], warehouse)


def test_months_without_complaints_are_zero_not_missing(tmp_path, fixture_csv, dbt_project):
    """Review #13: an empty month must be 0 in the metric, so charts don't join across gaps."""
    from tests.conftest import build_warehouse

    with fixture_csv.open() as f:
        lines = f.readlines()
    gap = tmp_path / "gap.csv"  # drop every 2025-06 complaint
    gap.write_text("".join(line for line in lines if not line.startswith("2025-06")))
    wh = build_warehouse(tmp_path / "wh", gap, "2026-10-31", dbt_project)

    rows = _mf_rows(
        wh, tmp_path, ["--metrics", "complaint_count", "--group-by", "metric_time__month"]
    )
    by_month = {r["metric_time__month"][:7]: int(r["complaint_count"]) for r in rows}
    assert by_month["2025-06"] == 0
    assert min(by_month) == "2025-01" and max(by_month) == "2026-06"  # spine bounded to data
