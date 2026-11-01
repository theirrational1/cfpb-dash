"""M2-03: bulk + API pulls -> staging keeps the latest version of each complaint; complaints
missing from the latest pull of their day are removed and counted."""

import csv
import json

import duckdb
import pytest

from agent.tools.query_metric import read_snapshot_stamp
from core.warehouse import Warehouse, run_cli
from ingestion.bulk import ingest
from ingestion.incremental import build, pull
from ingestion.raw_csv import BULK_COLUMNS
from tests.test_incremental import DAYS, NOW, FakeApi

REMOVED_ID = "999999999"


@pytest.fixture(scope="module")
def upsert_wh(tmp_path_factory, dbt_project):
    root = tmp_path_factory.mktemp("upsert")
    raw = root / "raw_landing"
    raw.mkdir()
    (raw / "MANIFEST.json").write_text(
        json.dumps({"manifest_version": 1, "generated_at": "x", "notes": "t", "files": []})
    )
    pull(DAYS, raw, raw / "MANIFEST.json", fetch=FakeApi(), now=NOW, sleep=lambda s: None)
    wh = Warehouse(root / "wh", project_dir=dbt_project)
    build(raw / "api", wh.api_parquet, wh.api_pull_days)

    # bulk captured before the pull: only 2026-10-20, the first complaint still In progress,
    # plus one complaint the API no longer returns for that day
    cols = ", ".join(f'"{c}"' for c in BULK_COLUMNS)
    rows = (
        duckdb.connect()
        .execute(
            f"""SELECT {cols} FROM read_parquet('{wh.api_parquet}')
                WHERE pulled_day = '2026-10-20' ORDER BY "Complaint ID" """
        )
        .fetchall()
    )
    i_status, i_id = (
        BULK_COLUMNS.index("Company response to consumer"),
        BULK_COLUMNS.index("Complaint ID"),
    )
    changed_id = rows[0][i_id]
    bulk = [list(r) for r in rows]
    bulk[0][i_status] = "In progress"
    removed = list(rows[1])
    removed[i_id] = REMOVED_ID
    bulk.append(removed)
    bulk_csv = root / "bulk.csv"
    with bulk_csv.open("w", newline="") as f:
        csv.writer(f).writerows([BULK_COLUMNS, *bulk])
    ingest(bulk_csv, wh.raw_parquet, snapshot_date="2026-10-31", work_dir=root / "work")
    run_cli("dbt", ["build", "--exclude", "tag:full_data"], wh)
    return wh, changed_id, rows[0][i_status]


def _q(wh, sql):
    return duckdb.connect(str(wh.duckdb_path), read_only=True).execute(sql).fetchall()


def test_late_arriving_complaints_are_added(upsert_wh):
    wh, _, _ = upsert_wh
    assert _q(wh, "SELECT count(*) FROM fct_complaints") == [(30,)]  # 13 + 10 + 7 from the API
    assert _q(wh, "SELECT count(DISTINCT date_received) FROM fct_complaints") == [(3,)]


def test_a_changed_record_takes_the_latest_pull(upsert_wh):
    wh, changed_id, api_status = upsert_wh
    assert api_status != "In progress"
    sql = f"SELECT company_response FROM fct_complaints WHERE complaint_id = {changed_id}"
    assert _q(wh, sql) == [(api_status,)]


def test_a_complaint_missing_from_the_latest_pull_of_its_day_is_removed_and_counted(upsert_wh):
    wh, _, _ = upsert_wh
    assert _q(wh, f"SELECT count(*) FROM fct_complaints WHERE complaint_id = {REMOVED_ID}") == [
        (0,)
    ]
    assert _q(wh, "SELECT complaint_id, last_seen_in FROM stg_removed_complaints") == [
        (int(REMOVED_ID), "bulk")
    ]


def test_provenance_dates_the_warehouse_by_its_latest_pull(upsert_wh):
    wh, _, _ = upsert_wh
    assert read_snapshot_stamp(wh)["snapshot_date"] == "2026-11-01"
    assert _q(wh, "SELECT bulk_snapshot_date, api_pulls, removed_rows FROM warehouse_snapshot") == [
        ("2026-10-31", 1, 1)
    ]
