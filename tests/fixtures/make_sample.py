"""Regenerate tests/fixtures/complaints_sample.csv from the local interim bulk Parquet.

~1,000 credit card complaints from the 3 largest issuers, received 2025-01-01..2026-06-30,
sampled deterministically by md5(complaint_id). Raw 15-column header; ZIP values blanked.
Needs data/interim (uv run python -m profiling.interim).
Run: uv run python -m tests.fixtures.make_sample
"""

import logging
from pathlib import Path

import duckdb

from core.log import configure_logging
from profiling.interim import BULK_COLUMNS

logger = logging.getLogger(__name__)

OUT = Path(__file__).parent / "complaints_sample.csv"
BULK_GLOB = "data/interim/bulk/*.parquet"
PER_COMPANY = 334
WINDOW = ("2025-01-01", "2026-07-01")


def main() -> None:
    configure_logging()
    cols = ", ".join('NULL AS "ZIP code"' if c == "ZIP code" else f'"{c}"' for c in BULK_COLUMNS)
    sql = f"""
        WITH cc AS (
            SELECT * FROM read_parquet('{BULK_GLOB}')
            WHERE "Product" = 'Credit card'
              AND "Date received" >= '{WINDOW[0]}' AND "Date received" < '{WINDOW[1]}'),
        top AS (SELECT "Company" FROM cc GROUP BY 1 ORDER BY count(*) DESC LIMIT 3),
        picked AS (
            SELECT * FROM cc WHERE "Company" IN (SELECT "Company" FROM top)
            QUALIFY row_number() OVER (
                PARTITION BY "Company" ORDER BY md5("Complaint ID")) <= {PER_COMPANY})
        SELECT {cols} FROM picked ORDER BY "Date received", "Complaint ID"
    """
    duckdb.connect().execute(f"COPY ({sql}) TO '{OUT}' (HEADER, DELIMITER ',')")
    logger.info("wrote %s", OUT)


if __name__ == "__main__":
    main()
