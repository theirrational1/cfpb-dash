"""Ingest a CFPB bulk file (zip or CSV) into the raw Parquet that dbt reads, plus snapshot.json.

snapshot.json carries the provenance every answer cites (source, sha256, snapshot date).
Run: uv run python -m ingestion.bulk --source data/raw/bulk/<file>.csv.zip
"""

import argparse
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.log import configure_logging
from ingestion.manifest import load_manifest, sha256_file
from ingestion.raw_csv import BULK_COLUMNS, csv_to_parquet, extract_single_member

logger = logging.getLogger(__name__)

RAW_MANIFEST = Path("data/raw/MANIFEST.json")
DEFAULT_OUT = Path("data/warehouse/raw/complaints.parquet")


def _manifest_date(source: Path, manifest_path: Path) -> str | None:
    if not manifest_path.is_file():
        return None
    for entry in load_manifest(manifest_path)["files"]:
        if (manifest_path.parent / entry["path"]).resolve() == source.resolve():
            return entry["retrieved_at"]
    return None


def ingest(
    source: Path,
    out: Path,
    snapshot_date: str | None,
    work_dir: Path,
    manifest_path: Path = RAW_MANIFEST,
) -> dict[str, Any]:
    """Convert `source` to `out` (replacing it) and write out.parent/snapshot.json."""
    snapshot_date = snapshot_date or _manifest_date(source, manifest_path)
    if snapshot_date is None:
        raise ValueError(f"{source} is not in {manifest_path}; pass snapshot_date explicitly")

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    if source.suffix == ".zip":
        csv_path = extract_single_member(source, work_dir)
        rows = csv_to_parquet(csv_path, BULK_COLUMNS, tmp, source.name)
        csv_path.unlink()
        if not any(work_dir.iterdir()):
            work_dir.rmdir()
    else:
        rows = csv_to_parquet(source, BULK_COLUMNS, tmp, source.name)
    os.replace(tmp, out)

    info = {
        "source_path": str(source),
        "source_sha256": sha256_file(source),
        "snapshot_date": snapshot_date,
        "rows": rows,
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    (out.parent / "snapshot.json").write_text(json.dumps(info, indent=2) + "\n")
    logger.info("ingested %s: %d rows, snapshot %s", source, rows, snapshot_date)
    return info


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--snapshot-date", help="required if the source is not in MANIFEST.json")
    args = parser.parse_args()
    ingest(args.source, args.out, args.snapshot_date, work_dir=args.out.parent / "_work")


if __name__ == "__main__":
    main()
