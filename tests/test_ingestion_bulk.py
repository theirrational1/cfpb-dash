import json
import zipfile

import duckdb
import pytest

from ingestion.bulk import ingest
from ingestion.manifest import sha256_file


def _rows(parquet) -> int:
    result = duckdb.connect().execute(f"SELECT count(*) FROM read_parquet('{parquet}')").fetchone()
    assert result is not None
    return result[0]


def test_ingest_csv_writes_parquet_and_snapshot(fixture_csv, tmp_path):
    out = tmp_path / "raw" / "complaints.parquet"
    info = ingest(fixture_csv, out, snapshot_date="2026-10-31", work_dir=tmp_path / "work")

    assert _rows(out) == 1002
    snapshot = json.loads((out.parent / "snapshot.json").read_text())
    assert snapshot == info
    assert snapshot["rows"] == 1002
    assert snapshot["snapshot_date"] == "2026-10-31"
    assert snapshot["source_sha256"] == sha256_file(fixture_csv)
    assert fixture_csv.exists(), "a CSV source is never deleted"


def test_ingest_zip_source(fixture_csv, tmp_path):
    zp = tmp_path / "complaints.csv.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.write(fixture_csv, "complaints.csv")
    out = tmp_path / "raw" / "complaints.parquet"
    ingest(zp, out, snapshot_date="2026-10-31", work_dir=tmp_path / "work")
    assert _rows(out) == 1002
    assert zp.exists()
    assert not list((tmp_path / "work").glob("*.csv")), "extracted copy is removed"


def test_ingest_fails_on_schema_drift(tmp_path, fixture_csv):
    drifted = tmp_path / "drifted.csv"
    text = fixture_csv.read_text()
    drifted.write_text(text.replace("Timely response?", "Timely", 1))
    with pytest.raises(ValueError, match="header"):
        ingest(drifted, tmp_path / "out.parquet", snapshot_date="2026-10-31", work_dir=tmp_path)


def test_ingest_requires_snapshot_date_for_unlisted_source(fixture_csv, tmp_path):
    with pytest.raises(ValueError, match="snapshot_date"):
        ingest(fixture_csv, tmp_path / "out.parquet", snapshot_date=None, work_dir=tmp_path)


def test_reingesting_the_same_source_is_a_no_op(fixture_csv, tmp_path):
    out = tmp_path / "raw" / "complaints.parquet"
    first = ingest(fixture_csv, out, snapshot_date="2026-10-31", work_dir=tmp_path / "w")
    mtimes = (out.stat().st_mtime_ns, (out.parent / "snapshot.json").stat().st_mtime_ns)

    again = ingest(fixture_csv, out, snapshot_date="2026-10-31", work_dir=tmp_path / "w")
    assert again == first
    assert (out.stat().st_mtime_ns, (out.parent / "snapshot.json").stat().st_mtime_ns) == mtimes

    forced = ingest(fixture_csv, out, "2026-10-31", work_dir=tmp_path / "w", force=True)
    assert forced["built_at"] >= first["built_at"]
    assert out.stat().st_mtime_ns != mtimes[0]


def test_a_changed_source_or_snapshot_date_replaces_the_output(fixture_csv, tmp_path):
    out = tmp_path / "raw" / "complaints.parquet"
    ingest(fixture_csv, out, snapshot_date="2026-10-31", work_dir=tmp_path / "w")
    assert ingest(fixture_csv, out, "2026-11-01", work_dir=tmp_path / "w")["snapshot_date"] == (
        "2026-11-01"
    )
    half = tmp_path / "half.csv"
    lines = fixture_csv.read_text().splitlines(keepends=True)
    half.write_text("".join(lines[:501]))
    assert ingest(half, out, "2026-11-01", work_dir=tmp_path / "w")["rows"] == 500
    assert _rows(out) == 500


def test_a_damaged_output_is_rebuilt(fixture_csv, tmp_path):
    out = tmp_path / "raw" / "complaints.parquet"
    ingest(fixture_csv, out, snapshot_date="2026-10-31", work_dir=tmp_path / "w")
    out.unlink()
    ingest(fixture_csv, out, snapshot_date="2026-10-31", work_dir=tmp_path / "w")
    assert _rows(out) == 1002


def test_snapshot_records_when_cfpb_generated_the_file(fixture_csv, tmp_path):
    """Review 3 #1: versions are ordered by when the data was produced, not by a date."""
    zp = tmp_path / "complaints.csv.zip"
    with zipfile.ZipFile(zp, "w") as z:
        info = zipfile.ZipInfo("complaints.csv", date_time=(2026, 10, 31, 9, 15, 40))
        z.writestr(info, fixture_csv.read_bytes())
    out = tmp_path / "raw" / "complaints.parquet"
    assert ingest(zp, out, "2026-10-31", work_dir=tmp_path / "w")["generated_at"] == (
        "2026-10-31T09:15:40+00:00"
    )
    csv_info = ingest(fixture_csv, tmp_path / "b" / "c.parquet", "2026-10-31", work_dir=tmp_path,
                      generated_at="2026-10-31T00:00:00+00:00")  # fmt: skip
    assert csv_info["generated_at"] == "2026-10-31T00:00:00+00:00"


def test_replacing_a_bulk_file_counts_the_complaints_that_dropped_out(fixture_csv, tmp_path):
    """Review 3 #2: complaints only in the previous bulk file used to vanish uncounted."""
    out = tmp_path / "raw" / "complaints.parquet"
    first = ingest(fixture_csv, out, "2026-10-31", work_dir=tmp_path / "w")
    assert first["dropped_since_previous"] == 0 and first["previous_sha256"] is None
    half = tmp_path / "half.csv"
    lines = fixture_csv.read_text().splitlines(keepends=True)
    half.write_text("".join(lines[:501]))
    second = ingest(half, out, "2026-11-01", work_dir=tmp_path / "w")
    assert second["dropped_since_previous"] == 502
    assert second["previous_sha256"] == first["source_sha256"]
