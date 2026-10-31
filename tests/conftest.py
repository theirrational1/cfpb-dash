import hashlib
import json
from pathlib import Path

import pytest

FIXTURE_BYTES = b"complaint_id,company\n1,Acme Bank\n"


@pytest.fixture
def tmp_raw_dir(tmp_path: Path) -> Path:
    """A tiny raw landing dir: one file plus a MANIFEST.json that matches it."""
    data_file = tmp_path / "bulk" / "sample.csv"
    data_file.parent.mkdir()
    data_file.write_bytes(FIXTURE_BYTES)
    manifest = {
        "manifest_version": 1,
        "generated_at": "2026-01-01T00:00:00+00:00",
        "notes": "fixture",
        "files": [
            {
                "path": "bulk/sample.csv",
                "source": "fixture",
                "source_url": "https://example.invalid/sample.csv",
                "retrieved_at": "2026-01-01",
                "size_bytes": len(FIXTURE_BYTES),
                "sha256": hashlib.sha256(FIXTURE_BYTES).hexdigest(),
            }
        ],
    }
    (tmp_path / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return tmp_path
