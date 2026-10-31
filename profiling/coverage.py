"""M0-15: narrative coverage by month = share of bulk complaints with a non-empty archive narrative.

Run: uv run python -m profiling.coverage
"""

import duckdb

from core.log import configure_logging
from profiling.report import REPORT_DIR, Sections, connect, md_table, write_report

TOP_PRODUCTS = 6


def coverage_sql(period: str = "month", product_filter: str = "TRUE") -> str:
    length = {"month": 7, "year": 4}[period]
    return f"""SELECT substr(b."Date received", 1, {length}) AS {period},
                      count(*) AS complaints,
                      count(n.complaint_id) AS with_narrative,
                      round(100.0 * count(n.complaint_id) / count(*), 2) AS coverage_pct
               FROM bulk b LEFT JOIN narrative n ON n.complaint_id = b."Complaint ID"
               WHERE {product_filter} GROUP BY 1 ORDER BY 1"""


def product_quarter_sql() -> str:
    return f"""WITH top AS (
                 SELECT b."Product" AS product FROM narrative n
                 JOIN bulk b ON b."Complaint ID" = n.complaint_id
                 GROUP BY 1 ORDER BY count(*) DESC LIMIT {TOP_PRODUCTS}),
               q AS (
                 SELECT b."Product" AS product,
                        substr(b."Date received", 1, 4) || '-Q'
                          || ((substr(b."Date received", 6, 2)::INT + 2) // 3) AS quarter,
                        n.complaint_id IS NOT NULL AS has_narrative
                 FROM bulk b LEFT JOIN narrative n ON n.complaint_id = b."Complaint ID"
                 WHERE b."Product" IN (SELECT product FROM top)
                   AND b."Date received" >= '2023-01-01')
               PIVOT q ON product
               USING round(100.0 * avg(has_narrative::INT), 1)
               GROUP BY quarter ORDER BY quarter"""


def sections(con: duckdb.DuckDBPyConnection) -> Sections:
    return [
        ("Coverage by year", md_table(con, coverage_sql("year"))),
        ("Coverage by month", md_table(con, coverage_sql("month"))),
        (
            f"Coverage % by quarter since 2023, top {TOP_PRODUCTS} narrative products",
            md_table(con, product_quarter_sql()),
        ),
    ]


def main() -> None:
    configure_logging()
    write_report(
        REPORT_DIR / "05_coverage.md",
        "Narrative coverage by month (M0-15)",
        "profiling.coverage",
        sections(connect()),
    )


if __name__ == "__main__":
    main()
