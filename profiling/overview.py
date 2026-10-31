"""M0-08: row counts by year, product, company; null rates, cardinality, castability (bulk).

Run: uv run python -m profiling.overview
"""

import duckdb

from core.log import configure_logging
from profiling.interim import BULK_COLUMNS
from profiling.report import REPORT_DIR, Sections, connect, md_table, write_report


def _q(col: str) -> str:
    return '"' + col.replace('"', '""') + '"'


def field_stats_sql(table: str, columns: list[str]) -> str:
    parts = [
        f"""SELECT {i} AS ord, '{c}' AS field,
               count(*) - count({_q(c)}) AS nulls,
               round(100.0 * (count(*) - count({_q(c)})) / count(*), 2) AS null_pct,
               count(*) FILTER (WHERE trim({_q(c)}) = '') AS blank_strings,
               approx_count_distinct({_q(c)}) AS approx_distinct,
               min({_q(c)}) AS min, max({_q(c)}) AS max,
               max(length({_q(c)})) AS max_len
           FROM {table}"""
        for i, c in enumerate(columns)
    ]
    return " UNION ALL ".join(parts) + " ORDER BY ord"


def sections(con: duckdb.DuckDBPyConnection) -> Sections:
    pct = "round(100.0 * count(*) / sum(count(*)) OVER (), 2) AS pct"
    return [
        (
            "Totals",
            md_table(
                con,
                """SELECT count(*) AS rows, count(DISTINCT "Complaint ID") AS distinct_ids,
                          count(*) - count("Complaint ID") AS null_ids
                   FROM bulk""",
            ),
        ),
        (
            "Rows by year received",
            md_table(
                con,
                f"""SELECT substr("Date received", 1, 4) AS year, count(*) AS rows, {pct}
                    FROM bulk GROUP BY 1 ORDER BY 1""",
            ),
        ),
        (
            "Rows by product",
            md_table(
                con,
                f"""SELECT "Product" AS product, count(*) AS rows, {pct}
                    FROM bulk GROUP BY 1 ORDER BY 2 DESC""",
            ),
        ),
        (
            "Top 50 companies",
            md_table(
                con,
                f"""SELECT "Company" AS company, count(*) AS rows, {pct}
                    FROM bulk GROUP BY 1 ORDER BY 2 DESC LIMIT 50""",
            ),
        ),
        (
            "Per-field nulls and cardinality",
            "approx_distinct is HyperLogLog (±~2%). min/max are string order.\n\n"
            + md_table(con, field_stats_sql("bulk", BULK_COLUMNS)),
        ),
        (
            "Castability",
            md_table(
                con,
                """SELECT
                     count(*) FILTER (WHERE "Date received" IS NOT NULL
                       AND try_cast("Date received" AS DATE) IS NULL) AS bad_date_received,
                     count(*) FILTER (WHERE "Date sent to company" IS NOT NULL
                       AND try_cast("Date sent to company" AS DATE) IS NULL) AS bad_date_sent,
                     min(try_cast("Date received" AS DATE)) AS min_received,
                     max(try_cast("Date received" AS DATE)) AS max_received,
                     count(*) FILTER (WHERE try_cast("Date sent to company" AS DATE)
                       < try_cast("Date received" AS DATE)) AS sent_before_received,
                     count(*) FILTER (WHERE "Complaint ID" IS NOT NULL
                       AND try_cast("Complaint ID" AS BIGINT) IS NULL) AS non_integer_ids,
                     count(*) - count(DISTINCT "Complaint ID") AS duplicate_ids
                   FROM bulk""",
            ),
        ),
        (
            "Low-cardinality fields",
            "\n\n".join(
                f"**{c}**\n\n"
                + md_table(
                    con,
                    f"SELECT {_q(c)} AS value, count(*) AS rows, {pct} FROM bulk "
                    "GROUP BY 1 ORDER BY 2 DESC",
                )
                for c in ("Timely response?", "Submitted via", "Tags")
            ),
        ),
        (
            "ZIP code patterns",
            md_table(
                con,
                f"""SELECT CASE
                       WHEN "ZIP code" IS NULL THEN '(null)'
                       WHEN regexp_full_match("ZIP code", '[0-9]{{5}}') THEN '5 digits'
                       WHEN regexp_full_match("ZIP code", '[0-9]{{3}}XX') THEN '3 digits + XX'
                       ELSE 'other' END AS pattern,
                     count(*) AS rows, {pct}
                   FROM bulk GROUP BY 1 ORDER BY 2 DESC""",
            ),
        ),
    ]


def main() -> None:
    configure_logging()
    con = connect()
    write_report(
        REPORT_DIR / "01_overview.md", "Bulk overview (M0-08)", "profiling.overview", sections(con)
    )


if __name__ == "__main__":
    main()
