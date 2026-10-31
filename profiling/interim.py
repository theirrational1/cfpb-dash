"""Build working Parquet copies of the raw zips in data/interim/ for profiling.

All columns stay text (all_varchar): this is the Audit pass, so nothing is typed or renamed.
Each zip must hold exactly one CSV whose header matches the expected columns, and the Parquet
row count must equal an independent stdlib csv record count; otherwise the build fails.

Run: uv run python -m profiling.interim
"""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from core.log import configure_logging
from ingestion.manifest import load_manifest
from ingestion.raw_csv import (
    BULK_COLUMNS,
    NARRATIVE_COLUMNS,
    csv_to_parquet,
    extract_single_member,
)

logger = logging.getLogger(__name__)

RAW_DIR = Path("data/raw")
INTERIM_DIR = Path("data/interim")


def build_parquet(
    zip_paths: list[Path], expected_columns: list[str], out_dir: Path, work_dir: Path
) -> int:
    """Write out_dir/<zip stem>.parquet per zip (plus a source_file column). Returns total rows."""
    if out_dir.exists():
        raise FileExistsError(f"{out_dir} already exists; delete it to rebuild")
    out_dir.mkdir(parents=True)
    total = 0
    for zip_path in zip_paths:
        csv_path = extract_single_member(zip_path, work_dir)
        out = out_dir / f"{zip_path.stem}.parquet"
        total += csv_to_parquet(csv_path, expected_columns, out, zip_path.name)
        csv_path.unlink()
    return total


def main() -> None:
    configure_logging()
    manifest = load_manifest(RAW_DIR / "MANIFEST.json")
    bulk = [e for e in manifest["files"] if e["path"].startswith("bulk/")]
    narratives = [e for e in manifest["files"] if e["path"].startswith("narratives/")]
    if len(bulk) != 1:
        raise ValueError(f"expected exactly one bulk file in the manifest, found {len(bulk)}")

    work_dir = INTERIM_DIR / "_work"
    built = {}
    for name, entries, columns in (
        ("bulk", bulk, BULK_COLUMNS),
        ("narratives", narratives, NARRATIVE_COLUMNS),
    ):
        rows = build_parquet(
            [RAW_DIR / e["path"] for e in entries], columns, INTERIM_DIR / name, work_dir
        )
        built[name] = {
            "parquet_dir": f"{name}/",
            "rows": rows,
            "sources": [{k: e[k] for k in ("path", "sha256", "retrieved_at")} for e in entries],
        }
    work_dir.rmdir()
    info = {"built_at": datetime.now(UTC).isoformat(timespec="seconds"), **built}
    (INTERIM_DIR / "INTERIM.json").write_text(json.dumps(info, indent=2) + "\n")
    logger.info("interim build done: %s", {k: v["rows"] for k, v in built.items()})


if __name__ == "__main__":
    main()
