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
