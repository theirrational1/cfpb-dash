"""M0-09: distinct company_response (and public response) values by year received (bulk).

Run: uv run python -m profiling.company_response
"""

import duckdb

from core.log import configure_logging
from profiling.report import REPORT_DIR, Sections, connect, md_table, write_report


def by_year_sql(column: str) -> str:
    return f"""PIVOT (SELECT substr("Date received", 1, 4) AS year, "{column}" AS value FROM bulk)
               ON year USING count(*) GROUP BY value ORDER BY value NULLS FIRST"""


def sections(con: duckdb.DuckDBPyConnection) -> Sections:
    return [
        (
            "Company response to consumer: totals",
            md_table(
                con,
                """SELECT "Company response to consumer" AS value, count(*) AS rows,
                          round(100.0 * count(*) / sum(count(*)) OVER (), 2) AS pct
                   FROM bulk GROUP BY 1 ORDER BY 2 DESC""",
            ),
        ),
        (
            "Company response to consumer: rows by year received",
            md_table(con, by_year_sql("Company response to consumer")),
        ),
        (
            "Company public response: rows by year received",
            md_table(con, by_year_sql("Company public response")),
        ),
    ]


def main() -> None:
    configure_logging()
    write_report(
        REPORT_DIR / "02_company_response.md",
        "Company response values over time (M0-09)",
        "profiling.company_response",
        sections(connect()),
    )


if __name__ == "__main__":
    main()
