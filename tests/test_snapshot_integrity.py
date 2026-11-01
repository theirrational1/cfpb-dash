"""Review findings 3, 4, 6: provenance must describe the data actually queried, a copied
(frozen) warehouse must be self-contained, and readers must not lock each other out."""

import csv
import shutil

import duckdb
import pytest

from agent.tools.query_metric import query_metric, read_snapshot_stamp
from core.warehouse import Warehouse, run_cli
from evals.harness.cases import Case
from evals.harness.runner import ground_truth
from ingestion.bulk import ingest
from tests.conftest import build_warehouse

CITI = {"complaint__company": "CITIBANK, N.A."}
MARCH = ("2026-03-01", "2026-03-31")
CASE = Case(
    "t",
    "q",
    """SELECT count(*) FROM stg_complaints WHERE company = 'CITIBANK, N.A.'
       AND date_received BETWEEN '2026-03-01' AND '2026-03-31'""",
)


def _half_fixture(fixture_csv, dest):
    with fixture_csv.open(newline="") as f:
        rows = list(csv.reader(f))
    with dest.open("w", newline="") as f:
        csv.writer(f).writerows(rows[: len(rows) // 2])
    return dest


def _count(wh) -> int:
    value = query_metric(["complaint_count"], filters=CITI, time_range=MARCH, warehouse=wh)
    n = value.rows[0]["complaint_count"]
    assert isinstance(n, int)
    return n


def test_frozen_copy_is_self_contained_and_provenance_follows_the_build(
    tmp_path, fixture_csv, dbt_project
):
    original = build_warehouse(tmp_path / "wh", fixture_csv, "2026-10-31", dbt_project)
    before = (_count(original), ground_truth(CASE, original))
    assert before[0] == before[1] > 0

    # freeze: copy the whole warehouse directory
    frozen = Warehouse(tmp_path / "frozen", project_dir=dbt_project)
    shutil.copytree(original.root, frozen.root)

    # re-ingest different data into the ORIGINAL and do not rebuild it
    ingest(
        _half_fixture(fixture_csv, tmp_path / "half.csv"),
        original.raw_parquet,
        snapshot_date="2026-11-01",
        work_dir=tmp_path / "work",
    )

    # the frozen copy is unaffected: same numbers, same ground truth, same provenance
    assert (_count(frozen), ground_truth(CASE, frozen)) == before
    p = query_metric(["complaint_count"], warehouse=frozen).provenance
    assert p.snapshot_date == "2026-10-31"

    # the un-rebuilt original still labels its (old) data with the old snapshot, not the new file
    p = query_metric(["complaint_count"], warehouse=original).provenance
    assert p.snapshot_date == "2026-10-31"


def _with_extra_row(fixture_csv, dest, new_id: bool, company: str | None = None):
    """Fixture plus a copy of its first row: same id (duplicate) or a new id; company edited."""
    with fixture_csv.open(newline="") as f:
        rows = list(csv.reader(f))
    extra = list(rows[1])
    if new_id:
        extra[rows[0].index("Complaint ID")] = "999999999"
    if company is not None:
        extra[rows[0].index("Company")] = company
    with dest.open("w", newline="") as f:
        csv.writer(f).writerows([*rows, extra])
    return dest


def test_failed_rebuild_never_labels_old_numbers_with_the_new_snapshot(
    tmp_path, fixture_csv, dbt_project
):
    """Review 2 #1: the stamp used to rebuild even when the fact table was skipped."""
    wh = build_warehouse(tmp_path / "wh", fixture_csv, "2026-10-31", dbt_project)
    stamp = read_snapshot_stamp(wh)
    assert (stamp["data_start"], stamp["data_end"]) == ("2025-01-02", "2026-06-30")

    ingest(
        _with_extra_row(fixture_csv, tmp_path / "bad.csv", new_id=True, company=""),
        wh.raw_parquet,
        snapshot_date="2026-12-01",
        work_dir=tmp_path / "work",
    )
    with pytest.raises(RuntimeError, match="not_null_stg_complaints_company"):
        run_cli("dbt", ["build", "--exclude", "tag:full_data"], wh)

    # staging moved (1003 rows) but the fact and stamp did not: refuse, don't mislabel
    with duckdb.connect(str(wh.duckdb_path), read_only=True) as con:
        assert con.execute("SELECT snapshot_date FROM warehouse_snapshot").fetchall() == [
            ("2026-10-31",)
        ]
    with pytest.raises(RuntimeError, match="inconsistent"):
        read_snapshot_stamp(wh)
    with pytest.raises(RuntimeError, match="inconsistent"):
        query_metric(["complaint_count"], warehouse=wh)


def test_duplicate_inside_one_load_fails_before_staging_and_keeps_the_old_build(
    tmp_path, fixture_csv, dbt_project
):
    """Staging keeps the latest version per complaint; a duplicate within one load must fail
    the build, not be deduplicated away."""
    wh = build_warehouse(tmp_path / "wh", fixture_csv, "2026-10-31", dbt_project)
    ingest(
        _with_extra_row(fixture_csv, tmp_path / "dup.csv", new_id=False),
        wh.raw_parquet,
        snapshot_date="2026-12-01",
        work_dir=tmp_path / "work",
    )
    with pytest.raises(RuntimeError, match="assert_one_version_per_load"):
        run_cli("dbt", ["build", "--exclude", "tag:full_data"], wh)
    # staging and everything after it were skipped: old numbers, old label, consistent
    assert read_snapshot_stamp(wh)["snapshot_date"] == "2026-10-31"
    assert _count(wh) > 0


def test_query_metric_works_while_another_reader_holds_the_warehouse(warehouse):
    reader = duckdb.connect(str(warehouse.duckdb_path), read_only=True)
    try:
        assert _count(warehouse) > 0
    finally:
        reader.close()
