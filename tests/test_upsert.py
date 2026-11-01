"""M2-03 upsert: bulk + API pulls -> staging keeps the newest version of each complaint (by
when CFPB produced the data, `as_of`); a complaint that a newer complete source covering its
day no longer contains is removed and counted. Pull fixture as_of: 2026-10-31T17:00Z."""

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

STATUS, ID = BULK_COLUMNS.index("Company response to consumer"), BULK_COLUMNS.index("Complaint ID")
EXTRA_ID = "888888888"
REMOVED = "SELECT complaint_id, last_seen_in FROM stg_removed_complaints"


def _scenario(root, dbt_project, generated_at, snapshot_date, drop_one_pulled=False):
    """Bulk = the pull's 2026-10-20 rows with the first status edited and one extra complaint
    (optionally missing one pulled complaint); pulls cover 2026-10-20..22."""
    raw = root / "raw_landing"
    raw.mkdir(parents=True)
    (raw / "MANIFEST.json").write_text(
        json.dumps({"manifest_version": 1, "generated_at": "x", "notes": "t", "files": []})
    )
    pull(DAYS, raw, raw / "MANIFEST.json", fetch=FakeApi(), now=NOW, sleep=lambda s: None)
    wh = Warehouse(root / "wh", project_dir=dbt_project)
    build(raw / "api", wh.api_parquet, wh.api_pull_days)
    cols = ", ".join(f'"{c}"' for c in BULK_COLUMNS)
    rows = [list(r) for r in duckdb.connect().execute(
        f"""SELECT {cols} FROM read_parquet('{wh.api_parquet}')
            WHERE pulled_day = '2026-10-20' ORDER BY "Complaint ID" """).fetchall()]  # fmt: skip
    pulled_status = rows[0][STATUS]
    bulk = [list(r) for r in rows]
    bulk[0][STATUS] = "Closed with monetary relief" if pulled_status != (
        "Closed with monetary relief") else "Closed with explanation"  # fmt: skip
    extra = list(rows[1])
    extra[ID] = EXTRA_ID
    bulk.append(extra)
    dropped = bulk.pop(2)[ID] if drop_one_pulled else None
    bulk_csv = root / "bulk.csv"
    with bulk_csv.open("w", newline="") as f:
        csv.writer(f).writerows([BULK_COLUMNS, *bulk])
    ingest(bulk_csv, wh.raw_parquet, snapshot_date, work_dir=root / "work",
           generated_at=generated_at)  # fmt: skip
    run_cli("dbt", ["build", "--exclude", "tag:full_data"], wh)
    return {"wh": wh, "changed_id": rows[0][ID], "pulled_status": pulled_status,
            "bulk_status": bulk[0][STATUS], "dropped_id": dropped}  # fmt: skip


@pytest.fixture(scope="module")
def pull_newer(tmp_path_factory, dbt_project):
    """Bulk produced 2026-10-30, before the pull's data (as_of 2026-10-31 17:00Z)."""
    return _scenario(tmp_path_factory.mktemp("pull_newer"), dbt_project,
                     "2026-10-30T09:00:00+00:00", "2026-10-30")  # fmt: skip


@pytest.fixture(scope="module")
def bulk_newer(tmp_path_factory, dbt_project):
    """Review 3 #1/#2: bulk produced later the same UTC day as the pull, and it no longer
    contains one complaint the pull returned."""
    return _scenario(tmp_path_factory.mktemp("bulk_newer"), dbt_project,
                     "2026-10-31T20:00:00+00:00", "2026-10-31", drop_one_pulled=True)  # fmt: skip


def _q(wh, sql):
    return duckdb.connect(str(wh.duckdb_path), read_only=True).execute(sql).fetchall()


def _status(s, complaint_id):
    sql = f"SELECT company_response FROM fct_complaints WHERE complaint_id = {complaint_id}"
    return _q(s["wh"], sql)


def test_late_arriving_complaints_are_added(pull_newer):
    assert _q(pull_newer["wh"], "SELECT count(*) FROM fct_complaints") == [(30,)]  # 13+10+7


def test_a_newer_pull_wins_and_removes_what_it_no_longer_returns(pull_newer):
    assert _status(pull_newer, pull_newer["changed_id"]) == [(pull_newer["pulled_status"],)]
    assert _q(pull_newer["wh"], REMOVED) == [(int(EXTRA_ID), "bulk")]


def test_a_newer_bulk_file_wins_keeps_its_new_complaints_and_removes_deleted_ones(bulk_newer):
    assert _status(bulk_newer, bulk_newer["changed_id"]) == [(bulk_newer["bulk_status"],)]
    extra = f"SELECT count(*) FROM fct_complaints WHERE complaint_id = {EXTRA_ID}"
    assert _q(bulk_newer["wh"], extra) == [(1,)]
    assert _q(bulk_newer["wh"], REMOVED) == [(int(bulk_newer["dropped_id"]), "api")]
    # days after the bulk file's last received day are still covered only by the pull
    assert _q(bulk_newer["wh"], "SELECT count(*) FROM fct_complaints") == [(30,)]  # 13-1+1 +10+7


def test_snapshot_date_is_the_eastern_date_of_the_newest_data(pull_newer, bulk_newer):
    """Review 3 #3: not the UTC date a pull happened to run (NOW is 2026-11-01T06:00Z)."""
    assert read_snapshot_stamp(pull_newer["wh"])["snapshot_date"] == "2026-10-31"
    stamp = "SELECT bulk_snapshot_date, api_pulls, removed_rows FROM warehouse_snapshot"
    assert _q(pull_newer["wh"], stamp) == [("2026-10-30", 1, 1)]
    assert read_snapshot_stamp(bulk_newer["wh"])["snapshot_date"] == "2026-10-31"
