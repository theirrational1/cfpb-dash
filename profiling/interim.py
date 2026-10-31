"""Build working Parquet copies of the raw zips in data/interim/ for profiling.

All columns stay text (all_varchar): this is the Audit pass, so nothing is typed or renamed.
Each zip must hold exactly one CSV whose header matches the expected columns, and the Parquet
row count must equal an independent stdlib csv record count; otherwise the build fails.

Run: uv run python -m profiling.interim
"""

import csv
import json
import logging
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from core.log import configure_logging
from ingestion.manifest import load_manifest

logger = logging.getLogger(__name__)

BULK_COLUMNS = [
    "Date received",
    "Product",
    "Sub-product",
    "Issue",
    "Sub-issue",
    "Company public response",
    "Company",
    "State",
    "ZIP code",
    "Tags",
    "Submitted via",
    "Date sent to company",
    "Company response to consumer",
    "Timely response?",
    "Complaint ID",
]
NARRATIVE_COLUMNS = [*BULK_COLUMNS[:5], "Consumer complaint narrative", *BULK_COLUMNS[5:]]

RAW_DIR = Path("data/raw")
INTERIM_DIR = Path("data/interim")
MAX_LINE_SIZE = 1 << 25  # 32 MiB; narratives can be long

csv.field_size_limit(1 << 30)


def _sql_str(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def count_csv_records(csv_path: Path) -> tuple[list[str], int]:
    """Header and data-record count via the stdlib parser (independent of DuckDB)."""
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        return header, sum(1 for _ in reader)


def _extract_single_member(zip_path: Path, work_dir: Path) -> Path:
    with zipfile.ZipFile(zip_path) as z:
        members = z.namelist()
        if len(members) != 1:
            raise ValueError(f"{zip_path}: expected exactly one member, found {members}")
        return Path(z.extract(members[0], work_dir))


def build_parquet(
    zip_paths: list[Path], expected_columns: list[str], out_dir: Path, work_dir: Path
) -> int:
    """Write out_dir/<zip stem>.parquet per zip (plus a source_file column). Returns total rows."""
    if out_dir.exists():
        raise FileExistsError(f"{out_dir} already exists; delete it to rebuild")
    out_dir.mkdir(parents=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    total = 0
    for zip_path in zip_paths:
        csv_path = _extract_single_member(zip_path, work_dir)
        header, expected_rows = count_csv_records(csv_path)
        if header != expected_columns:
            raise ValueError(f"{zip_path}: header {header} != expected {expected_columns}")

        out = out_dir / f"{zip_path.stem}.parquet"
        con.execute(
            f"""COPY (
                SELECT *, {_sql_str(zip_path.name)} AS source_file
                FROM read_csv({_sql_str(csv_path)}, all_varchar=true, header=true,
                              strict_mode=true, delim=',', quote='"', escape='"',
                              max_line_size={MAX_LINE_SIZE})
            ) TO {_sql_str(out)} (FORMAT parquet, COMPRESSION zstd)"""
        )
        desc = con.execute(f"SELECT * FROM read_parquet({_sql_str(out)}) LIMIT 0").description
        columns = [d[0] for d in desc]
        if columns != [*expected_columns, "source_file"]:
            raise ValueError(f"{out}: columns {columns} != expected")
        result = con.execute(f"SELECT count(*) FROM read_parquet({_sql_str(out)})").fetchone()
        if result is None or result[0] != expected_rows:
            raise ValueError(f"{zip_path}: parquet rows {result} != csv records {expected_rows}")

        csv_path.unlink()
        logger.info("%s -> %s (%d rows)", zip_path.name, out, expected_rows)
        total += expected_rows
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
