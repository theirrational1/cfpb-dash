"""M0-10: product / sub-product / issue labels over time (input to the M2-06 mapping layer).

Run: uv run python -m profiling.labels
"""

import duckdb

from core.log import configure_logging
from profiling.report import REPORT_DIR, Sections, connect, md_table, write_report


def lifespan_sql(keys: list[str]) -> str:
    """First/last year each label combination appears, with a status flag vs the data span."""
    cols = ", ".join(f'"{k}"' for k in keys)
    return f"""WITH t AS (
                 SELECT {cols}, substr("Date received", 1, 4) AS year FROM bulk),
               span AS (SELECT min(year) AS lo, max(year) AS hi FROM t)
               SELECT {cols}, min(year) AS first_year, max(year) AS last_year,
                      count(*) AS rows,
                      CASE WHEN max(year) < any_value(span.hi) THEN 'retired'
                           WHEN min(year) > any_value(span.lo) THEN 'introduced'
                           ELSE 'whole span' END AS status
               FROM t, span GROUP BY {cols} ORDER BY {cols}"""


def sections(con: duckdb.DuckDBPyConnection) -> Sections:
    return [
        ("Products", md_table(con, lifespan_sql(["Product"]))),
        ("Product × sub-product", md_table(con, lifespan_sql(["Product", "Sub-product"]))),
        ("Product × issue", md_table(con, lifespan_sql(["Product", "Issue"]))),
    ]


def main() -> None:
    configure_logging()
    write_report(
        REPORT_DIR / "03_labels.md",
        "Product and issue labels over time (M0-10)",
        "profiling.labels",
        sections(connect()),
    )


if __name__ == "__main__":
    main()
