"""Ingest a CFPB bulk file (zip or CSV) into the raw Parquet that dbt reads, plus snapshot.json.

snapshot.json carries the provenance every answer cites (source, sha256, snapshot date).
Run: uv run python -m ingestion.bulk --source data/raw/bulk/<file>.csv.zip
"""

import argparse
import json
import logging
import os
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from core.log import configure_logging
from core.warehouse import REPO_ROOT
from ingestion.manifest import load_manifest, sha256_file
from ingestion.raw_csv import BULK_COLUMNS, csv_to_parquet, extract_single_member, sql_str

logger = logging.getLogger(__name__)

RAW_MANIFEST = REPO_ROOT / "data" / "raw" / "MANIFEST.json"
DEFAULT_OUT = REPO_ROOT / "data" / "warehouse" / "raw" / "complaints.parquet"


def _manifest_date(source: Path, manifest_path: Path) -> str | None:
    if not manifest_path.is_file():
        return None
    for entry in load_manifest(manifest_path)["files"]:
        if (manifest_path.parent / entry["path"]).resolve() == source.resolve():
            return entry["retrieved_at"]
    return None


def _already_ingested(source: Path, out: Path, snapshot_date: str) -> dict[str, Any] | None:
    snapshot = out.parent / "snapshot.json"
    if not (snapshot.is_file() and out.is_file()):
        return None
    info = json.loads(snapshot.read_text())
    if (info["source_sha256"], info["snapshot_date"]) != (sha256_file(source), snapshot_date):
        return None
    row = duckdb.connect().execute(f"SELECT count(*) FROM read_parquet({sql_str(out)})").fetchone()
    return info if row is not None and row[0] == info["rows"] else None


def _generated_at(source: Path) -> str:
    if source.suffix == ".zip":
        with zipfile.ZipFile(source) as z:
            [member] = z.infolist()
            stamp = datetime(*member.date_time, tzinfo=UTC)  # zip times carry no zone: UTC
    else:
        stamp = datetime.fromtimestamp(source.stat().st_mtime, tz=UTC)
    return stamp.isoformat(timespec="seconds")


def _dropped_since_previous(out: Path, new: Path) -> tuple[str | None, int]:
    """Complaint IDs in the bulk file being replaced that the new one no longer has."""
    snapshot = out.parent / "snapshot.json"
    if not (out.is_file() and snapshot.is_file()):
        return None, 0
    row = (
        duckdb.connect()
        .execute(
            f"""SELECT count(*) FROM (
                SELECT "Complaint ID" FROM read_parquet({sql_str(out)})
                EXCEPT SELECT "Complaint ID" FROM read_parquet({sql_str(new)}))"""
        )
        .fetchone()
    )
    dropped = row[0] if row else 0
    if dropped:
        logger.warning("%d complaint IDs in the previous bulk file are not in the new one", dropped)
    return json.loads(snapshot.read_text())["source_sha256"], dropped


def ingest(
    source: Path,
    out: Path,
    snapshot_date: str | None,
    work_dir: Path,
    manifest_path: Path = RAW_MANIFEST,
    force: bool = False,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Convert `source` to `out` (replacing it) and write out.parent/snapshot.json.

    generated_at is when CFPB produced the data (UTC): the CSV's timestamp inside the zip, or
    the file's mtime for a bare CSV unless given. Staging orders complaint versions by it.
    Replacing a previous bulk file records how many complaint IDs dropped out of it.

    Idempotent: if snapshot.json already records this source (sha256) and snapshot date and
    `out` holds that many rows, nothing is rewritten (unless `force`)."""
    snapshot_date = snapshot_date or _manifest_date(source, manifest_path)
    if snapshot_date is None:
        raise ValueError(f"{source} is not in {manifest_path}; pass snapshot_date explicitly")
    existing = _already_ingested(source, out, snapshot_date)
    if existing is not None and not force:
        logger.info("%s already ingested into %s (snapshot %s); skipping", source, out,
                    snapshot_date)  # fmt: skip
        return existing

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    generated_at = generated_at or _generated_at(source)
    if source.suffix == ".zip":
        csv_path = extract_single_member(source, work_dir)
        rows = csv_to_parquet(csv_path, BULK_COLUMNS, tmp, source.name)
        csv_path.unlink()
        if not any(work_dir.iterdir()):
            work_dir.rmdir()
    else:
        rows = csv_to_parquet(source, BULK_COLUMNS, tmp, source.name)
    previous_sha, dropped = _dropped_since_previous(out, tmp)
    info = {
        "source_path": str(source),
        "source_sha256": sha256_file(source),
        "snapshot_date": snapshot_date,
        "generated_at": generated_at,
        "rows": rows,
        "previous_sha256": previous_sha,
        "dropped_since_previous": dropped,
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    # Both files are complete before either is replaced; dbt's
    # assert_staging_rows_match_snapshot test catches any remaining mismatch.
    snap_tmp = out.parent / "snapshot.json.tmp"
    snap_tmp.write_text(json.dumps(info, indent=2) + "\n")
    os.replace(tmp, out)
    os.replace(snap_tmp, out.parent / "snapshot.json")
    logger.info("ingested %s: %d rows, snapshot %s", source, rows, snapshot_date)
    return info


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--snapshot-date", help="required if the source is not in MANIFEST.json")
    parser.add_argument("--force", action="store_true", help="rebuild even if already ingested")
    args = parser.parse_args()
    ingest(args.source, args.out, args.snapshot_date, work_dir=args.out.parent / "_work",
           force=args.force)  # fmt: skip


if __name__ == "__main__":
    main()
