"""Raw CFPB CSV contract and checked CSV -> Parquet conversion (all columns kept as text).

A conversion fails loudly if the header differs from the expected columns or if DuckDB's row
count differs from an independent stdlib csv record count.
"""

import csv
import logging
import zipfile
from pathlib import Path

import duckdb

from ingestion.schema_check import check_fields

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

MAX_LINE_SIZE = 1 << 25  # 32 MiB; narratives can be long

csv.field_size_limit(1 << 30)


def sql_str(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def count_csv_records(csv_path: Path) -> tuple[list[str], int]:
    """Header and data-record count via the stdlib parser (independent of DuckDB)."""
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        return header, sum(1 for _ in reader)


def extract_single_member(zip_path: Path, work_dir: Path) -> Path:
    work_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        members = z.namelist()
        if len(members) != 1:
            raise ValueError(f"{zip_path}: expected exactly one member, found {members}")
        return Path(z.extract(members[0], work_dir))


def csv_to_parquet(csv_path: Path, expected_columns: list[str], out: Path, source_name: str) -> int:
    """Write `out` with every CSV column as text plus `source_file`. Returns the row count."""
    header, expected_rows = count_csv_records(csv_path)
    check_fields(header, expected_columns, source_name)

    con = duckdb.connect()
    con.execute(
        f"""COPY (
            SELECT *, {sql_str(source_name)} AS source_file
            FROM read_csv({sql_str(csv_path)}, all_varchar=true, header=true,
                          strict_mode=true, delim=',', quote='"', escape='"',
                          max_line_size={MAX_LINE_SIZE})
        ) TO {sql_str(out)} (FORMAT parquet, COMPRESSION zstd)"""
    )
    desc = con.execute(f"SELECT * FROM read_parquet({sql_str(out)}) LIMIT 0").description
    columns = [d[0] for d in desc]
    if columns != [*expected_columns, "source_file"]:
        raise ValueError(f"{out}: columns {columns} != expected")
    result = con.execute(f"SELECT count(*) FROM read_parquet({sql_str(out)})").fetchone()
    if result is None or result[0] != expected_rows:
        raise ValueError(f"{source_name}: parquet rows {result} != csv records {expected_rows}")
    logger.info("%s -> %s (%d rows)", source_name, out, expected_rows)
    return expected_rows
