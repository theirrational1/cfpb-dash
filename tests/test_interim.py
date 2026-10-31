import zipfile
from pathlib import Path

import duckdb
import pytest

from profiling.interim import build_parquet, count_csv_records

COLUMNS = ["Date received", "Consumer complaint narrative", "Complaint ID"]
CSV = (
    "Date received,Consumer complaint narrative,Complaint ID\n"
    '2024-01-02,"first line\nsecond line, with comma",1\n'
    "2024-01-03,,2\n"
    '2024-01-04,"she said ""hi""",3\n'
)


def _zip(path: Path, members: dict[str, str]) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        for name, text in members.items():
            z.writestr(name, text)
    return path


def test_count_csv_records_handles_multiline_fields(tmp_path):
    f = tmp_path / "x.csv"
    f.write_text(CSV)
    assert count_csv_records(f) == (COLUMNS, 3)


def test_build_parquet_round_trips_rows(tmp_path):
    zp = _zip(tmp_path / "a.zip", {"a.csv": CSV})
    out_dir = tmp_path / "out"
    rows = build_parquet([zp], COLUMNS, out_dir, work_dir=tmp_path / "work")

    assert rows == 3
    got = (
        duckdb.connect()
        .execute(f"select * from read_parquet('{out_dir}/*.parquet') order by \"Complaint ID\"")
        .fetchall()
    )
    assert got == [
        ("2024-01-02", "first line\nsecond line, with comma", "1", "a.zip"),
        ("2024-01-03", None, "2", "a.zip"),
        ("2024-01-04", 'she said "hi"', "3", "a.zip"),
    ]
    assert not any((tmp_path / "work").glob("*.csv")), "extracted CSV should be deleted"


def test_build_parquet_one_file_per_zip(tmp_path):
    zips = [_zip(tmp_path / f"{n}.zip", {f"{n}.csv": CSV}) for n in ("a", "b")]
    rows = build_parquet(zips, COLUMNS, tmp_path / "out", work_dir=tmp_path / "work")
    assert rows == 6
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["a.parquet", "b.parquet"]


def test_header_mismatch_raises(tmp_path):
    zp = _zip(tmp_path / "a.zip", {"a.csv": CSV.replace("Complaint ID", "Complaint Id")})
    with pytest.raises(ValueError, match="header"):
        build_parquet([zp], COLUMNS, tmp_path / "out", work_dir=tmp_path / "work")


def test_multi_member_zip_raises(tmp_path):
    zp = _zip(tmp_path / "a.zip", {"a.csv": CSV, "b.csv": CSV})
    with pytest.raises(ValueError, match="exactly one member"):
        build_parquet([zp], COLUMNS, tmp_path / "out", work_dir=tmp_path / "work")


def test_refuses_existing_output(tmp_path):
    zp = _zip(tmp_path / "a.zip", {"a.csv": CSV})
    (tmp_path / "out").mkdir()
    with pytest.raises(FileExistsError):
        build_parquet([zp], COLUMNS, tmp_path / "out", work_dir=tmp_path / "work")
