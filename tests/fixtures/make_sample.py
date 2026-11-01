"""Regenerate the committed test fixtures from the local interim bulk Parquet.

complaints_sample.csv: ~1,000 credit card complaints from the 3 largest issuers, received
2025-01-01..2026-06-30.
complaints_eras.csv: ~600 complaints across every product label and year (2 each), every
credit card (product, sub-product, issue) label, and every null / odd-value pattern in
docs/decisions/nulls.md (for mapping and null-handling tests).

Both sample deterministically by md5(complaint_id), keep the raw 15-column header and blank
ZIP. Needs data/interim (uv run python -m profiling.interim).
Run: uv run python -m tests.fixtures.make_sample
"""

import logging
from pathlib import Path

import duckdb

from core.log import configure_logging
from ingestion.raw_csv import BULK_COLUMNS

logger = logging.getLogger(__name__)

OUT = Path(__file__).parent / "complaints_sample.csv"
ERAS_OUT = Path(__file__).parent / "complaints_eras.csv"
BULK_GLOB = "data/interim/bulk/*.parquet"
PER_COMPANY = 334
WINDOW = ("2025-01-01", "2026-07-01")
CREDIT_CARD_LABELS = ("Credit card", "Credit card or prepaid card")
# (name, predicate, rows): null and odd-value patterns from docs/decisions/nulls.md
PATTERNS = [
    ("issue_null", '"Issue" IS NULL', 6),
    ("response_null", '"Company response to consumer" IS NULL', 5),
    ("in_progress", "\"Company response to consumer\" = 'In progress'", 5),
    ("untimely", "\"Company response to consumer\" = 'Untimely response'", 5),
    ("bare_closed", "\"Company response to consumer\" = 'Closed'", 3),
    ("closed_with_relief", "\"Company response to consumer\" = 'Closed with relief'", 3),
    ("closed_without_relief", "\"Company response to consumer\" = 'Closed without relief'", 3),
    ("public_response_pre2015", "\"Date received\" < '2015-01-01'", 3),
    ("public_response_blank_closed",
     "\"Company public response\" IS NULL AND \"Date received\" >= '2016-01-01'"
     " AND \"Company response to consumer\" LIKE 'Closed%'", 5),
    ("public_response_old_optout", "\"Company public response\" = 'Company chooses not to provide"
     " a public response'", 3),
    ("tag_older", "\"Tags\" = 'Older American'", 3),
    ("tag_service", "\"Tags\" = 'Servicemember'", 3),
    ("tag_both", "\"Tags\" = 'Older American, Servicemember'", 3),
    ("lag_minus_one", 'CAST("Date sent to company" AS DATE) < CAST("Date received" AS DATE)', 3),
    ("state_null", '"State" IS NULL', 3),
    ("state_military", "\"State\" IN ('AA', 'AE', 'AP')", 3),
    ("state_umi", "\"State\" = 'UNITED STATES MINOR OUTLYING ISLANDS'", 2),
    ("company_whitespace", '"Company" <> trim("Company")', 3),
    ("checking_no_subproduct",
     "\"Product\" = 'Checking or savings account' AND \"Sub-product\" IS NULL", 3),
]  # fmt: skip


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
    con = duckdb.connect()
    con.execute(f"COPY ({sql}) TO '{OUT}' (HEADER, DELIMITER ',')")
    logger.info("wrote %s", OUT)

    patterns = " UNION ALL ".join(
        f"""(SELECT "Complaint ID" FROM b WHERE {pred} ORDER BY md5("Complaint ID") LIMIT {n})"""
        for _, pred, n in PATTERNS
    )
    cc = ", ".join(f"'{label}'" for label in CREDIT_CARD_LABELS)
    eras = f"""
        WITH b AS (SELECT * FROM read_parquet('{BULK_GLOB}')),
        by_year AS (
            SELECT "Complaint ID" FROM b
            QUALIFY row_number() OVER (
                PARTITION BY "Product", left("Date received", 4)
                ORDER BY md5("Complaint ID")) <= 2),
        cc_labels AS (
            SELECT "Complaint ID" FROM b WHERE "Product" IN ({cc})
            QUALIFY row_number() OVER (
                PARTITION BY "Product", "Sub-product", "Issue"
                ORDER BY md5("Complaint ID")) = 1),
        ids AS (
            SELECT * FROM by_year UNION SELECT * FROM cc_labels UNION SELECT * FROM ({patterns}))
        SELECT {cols} FROM b WHERE "Complaint ID" IN (SELECT * FROM ids)
        ORDER BY "Date received", "Complaint ID"
    """
    con.execute(f"COPY ({eras}) TO '{ERAS_OUT}' (HEADER, DELIMITER ',')")
    logger.info("wrote %s", ERAS_OUT)


if __name__ == "__main__":
    main()
