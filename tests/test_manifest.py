import hashlib
import json
from pathlib import Path

import pytest

from ingestion.manifest import (
    REQUIRED_KEYS,
    append_entry,
    load_manifest,
    sha256_file,
    verify_manifest,
)

REPO_MANIFEST = Path(__file__).resolve().parents[1] / "data" / "raw" / "MANIFEST.json"


def _rewrite(raw_dir: Path, mutate) -> None:
    path = raw_dir / "MANIFEST.json"
    manifest = json.loads(path.read_text())
    mutate(manifest)
    path.write_text(json.dumps(manifest, indent=2) + "\n")


def test_sha256_file_matches_hashlib(tmp_path):
    f = tmp_path / "x.bin"
    payload = b"a" * (3 * (1 << 20) + 7)  # spans several chunks
    f.write_bytes(payload)
    assert sha256_file(f) == hashlib.sha256(payload).hexdigest()


def test_verify_passes_on_matching_files(tmp_raw_dir):
    assert verify_manifest(tmp_raw_dir / "MANIFEST.json") == []


def test_verify_detects_changed_byte(tmp_raw_dir):
    f = tmp_raw_dir / "bulk" / "sample.csv"
    data = bytearray(f.read_bytes())
    data[0] ^= 1  # same size, different content
    f.write_bytes(bytes(data))
    problems = verify_manifest(tmp_raw_dir / "MANIFEST.json")
    assert len(problems) == 1
    assert "sha256 mismatch" in problems[0]
    assert "bulk/sample.csv" in problems[0]


def test_verify_detects_size_mismatch(tmp_raw_dir):
    with (tmp_raw_dir / "bulk" / "sample.csv").open("ab") as f:
        f.write(b"extra\n")
    problems = verify_manifest(tmp_raw_dir / "MANIFEST.json")
    assert any("size mismatch" in p for p in problems)


def test_verify_detects_missing_file(tmp_raw_dir):
    (tmp_raw_dir / "bulk" / "sample.csv").unlink()
    problems = verify_manifest(tmp_raw_dir / "MANIFEST.json")
    assert problems == ["missing: bulk/sample.csv"]


def test_load_rejects_duplicate_paths(tmp_raw_dir):
    _rewrite(tmp_raw_dir, lambda m: m["files"].append(dict(m["files"][0])))
    with pytest.raises(ValueError, match="duplicate path"):
        load_manifest(tmp_raw_dir / "MANIFEST.json")


def test_load_rejects_missing_keys(tmp_raw_dir):
    _rewrite(tmp_raw_dir, lambda m: m["files"][0].pop("sha256"))
    with pytest.raises(ValueError, match="sha256"):
        load_manifest(tmp_raw_dir / "MANIFEST.json")


def _new_entry(raw_dir: Path) -> dict:
    payload = b"new file\n"
    (raw_dir / "bulk" / "new.csv").write_bytes(payload)
    return {
        "path": "bulk/new.csv",
        "source": "fixture",
        "source_url": "https://example.invalid/new.csv",
        "retrieved_at": "2026-01-02",
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def test_append_entry_keeps_format_and_verifies(tmp_raw_dir):
    manifest_path = tmp_raw_dir / "MANIFEST.json"
    append_entry(
        manifest_path,
        _new_entry(tmp_raw_dir),
        generated_at="2026-01-02T00:00:00+00:00",
        notes="updated",
    )
    text = manifest_path.read_text()
    manifest = json.loads(text)
    assert text == json.dumps(manifest, indent=2) + "\n"
    assert [f["path"] for f in manifest["files"]] == ["bulk/sample.csv", "bulk/new.csv"]
    assert manifest["generated_at"] == "2026-01-02T00:00:00+00:00"
    assert manifest["notes"] == "updated"
    assert manifest["manifest_version"] == 1
    assert verify_manifest(manifest_path) == []


def test_append_entry_refuses_duplicate(tmp_raw_dir):
    manifest_path = tmp_raw_dir / "MANIFEST.json"
    entry = _new_entry(tmp_raw_dir)
    append_entry(manifest_path, entry, generated_at="2026-01-02T00:00:00+00:00")
    before = manifest_path.read_text()
    with pytest.raises(ValueError, match="duplicate path"):
        append_entry(manifest_path, entry, generated_at="2026-01-03T00:00:00+00:00")
    assert manifest_path.read_text() == before


def test_repo_manifest_is_well_formed():
    """Runs in CI: the tracked manifest parses and every entry has all required keys."""
    manifest = load_manifest(REPO_MANIFEST)
    assert manifest["files"], "manifest lists no files"
    for entry in manifest["files"]:
        assert set(REQUIRED_KEYS) <= entry.keys()
        assert len(entry["sha256"]) == 64
