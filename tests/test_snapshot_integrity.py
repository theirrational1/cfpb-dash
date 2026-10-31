"""Review findings 3, 4, 6: provenance must describe the data actually queried, a copied
(frozen) warehouse must be self-contained, and readers must not lock each other out."""

import csv
import shutil

import duckdb

from agent.tools.query_metric import query_metric
from core.warehouse import Warehouse
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


def test_query_metric_works_while_another_reader_holds_the_warehouse(warehouse):
    reader = duckdb.connect(str(warehouse.duckdb_path), read_only=True)
    try:
        assert _count(warehouse) > 0
    finally:
        reader.close()
