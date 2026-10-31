"""Recompute every checksum in data/raw/MANIFEST.json. Slow (GBs of I/O); needs local data.

Run with: uv run pytest -m data
"""

from pathlib import Path

import pytest

from ingestion.manifest import load_manifest, verify_manifest

REPO_MANIFEST = Path(__file__).resolve().parents[1] / "data" / "raw" / "MANIFEST.json"


@pytest.mark.data
def test_all_raw_files_match_manifest():
    assert load_manifest(REPO_MANIFEST)["files"], "manifest lists no files"
    assert verify_manifest(REPO_MANIFEST) == []
