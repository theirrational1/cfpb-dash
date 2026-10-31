import io
import json
import zipfile
from datetime import date

import pytest

from ingestion.fetch_bulk import fetch_bulk
from ingestion.manifest import verify_manifest

RETRIEVED = date(2026, 1, 2)


@pytest.fixture
def source_zip(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("complaints.csv", "complaint_id,company\n1,Acme Bank\n")
    path = tmp_path / "source" / "complaints.csv.zip"
    path.parent.mkdir()
    path.write_bytes(buf.getvalue())
    return path


def test_fetch_writes_file_and_manifest_entry(tmp_raw_dir, source_zip):
    url = source_zip.as_uri()
    dest = fetch_bulk(url, tmp_raw_dir, RETRIEVED)

    assert dest == tmp_raw_dir / "bulk" / "complaints_2026-01-02.csv.zip"
    assert dest.read_bytes() == source_zip.read_bytes()
    assert not dest.with_name(dest.name + ".part").exists()

    manifest = json.loads((tmp_raw_dir / "MANIFEST.json").read_text())
    entry = manifest["files"][-1]
    assert entry["path"] == "bulk/complaints_2026-01-02.csv.zip"
    assert entry["source_url"] == url
    assert entry["retrieved_at"] == "2026-01-02"
    assert verify_manifest(tmp_raw_dir / "MANIFEST.json") == []


def test_fetch_refuses_to_overwrite(tmp_raw_dir, source_zip):
    fetch_bulk(source_zip.as_uri(), tmp_raw_dir, RETRIEVED)
    with pytest.raises(FileExistsError):
        fetch_bulk(source_zip.as_uri(), tmp_raw_dir, RETRIEVED)


def test_fetch_rejects_non_zip(tmp_raw_dir, tmp_path):
    bogus = tmp_path / "not_a_zip.csv.zip"
    bogus.write_bytes(b"<html>error page</html>")
    with pytest.raises(ValueError, match="not a zip"):
        fetch_bulk(bogus.as_uri(), tmp_raw_dir, RETRIEVED)
    assert not (tmp_raw_dir / "bulk" / "complaints_2026-01-02.csv.zip").exists()
