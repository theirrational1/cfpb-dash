"""M0-13: complaints per company per product family, to draft the minimum-volume threshold.

Uses the trailing 12 full months before the snapshot's last (partial) month.
Run: uv run python -m profiling.threshold
"""

import duckdb

from core.log import configure_logging
from profiling.report import REPORT_DIR, Sections, connect, md_table, write_report

CANDIDATES = (25, 50, 100, 250, 500, 1000)

WINDOW = """window_bounds AS (
    SELECT date_trunc('month', max("Date received"::DATE)) - INTERVAL 12 MONTH AS lo,
           date_trunc('month', max("Date received"::DATE)) AS hi FROM bulk)"""


def per_company_cte(trailing: bool) -> str:
    where = '"Date received"::DATE >= lo AND "Date received"::DATE < hi' if trailing else "TRUE"
    return f"""WITH {WINDOW},
        pc AS (SELECT product_family, "Company" AS company, count(*) AS n
               FROM bulk_f, window_bounds WHERE {where} GROUP BY ALL)"""


def distribution_sql(trailing: bool = True) -> str:
    ge = ",\n".join(f"count(*) FILTER (WHERE n >= {t}) AS ge_{t}" for t in CANDIDATES)
    return f"""{per_company_cte(trailing)}
        SELECT product_family, count(*) AS companies, sum(n) AS complaints,
               quantile_cont(n, 0.5) AS p50, quantile_cont(n, 0.9) AS p90,
               quantile_cont(n, 0.99) AS p99, {ge}
        FROM pc GROUP BY 1 ORDER BY complaints DESC"""


def coverage_share_sql() -> str:
    cols = ",\n".join(
        f"round(100.0 * sum(n) FILTER (WHERE n >= {t}) / sum(n), 1) AS pct_ge_{t}"
        for t in CANDIDATES
    )
    return f"""{per_company_cte(True)}
        SELECT product_family, {cols} FROM pc GROUP BY 1 ORDER BY sum(n) DESC"""


def precision_sql() -> str:
    rows = ", ".join(f"({t})" for t in CANDIDATES)
    return f"""SELECT n, round(100 * 1.96 * sqrt(0.25 / n), 1) AS ci95_halfwidth_pp_at_50pct,
                      round(100 * 1.96 * sqrt(0.1 * 0.9 / n), 1) AS ci95_halfwidth_pp_at_10pct
               FROM (VALUES {rows}) t(n) ORDER BY n"""


def sections(con: duckdb.DuckDBPyConnection) -> Sections:
    lo, hi = con.execute(f"WITH {WINDOW} SELECT lo::DATE, hi::DATE FROM window_bounds").fetchall()[
        0
    ]
    note = (
        f"Window: {lo} ≤ received < {hi}. Product families are the PROVISIONAL "
        "profiling mapping (`profiling.report.PRODUCT_FAMILY`), not the M2-06 seed."
    )
    return [
        (
            "Companies per product family, trailing 12 months",
            note + "\n\n" + md_table(con, distribution_sql(trailing=True)),
        ),
        (
            "Share of the family's complaints from companies at or above each threshold",
            md_table(con, coverage_share_sql()),
        ),
        ("Companies per product family, all time", md_table(con, distribution_sql(trailing=False))),
        (
            "Rate precision by sample size",
            "Worst-case (rate near 50%) and a 10% rate. Normal approximation.\n\n"
            + md_table(con, precision_sql()),
        ),
    ]


def main() -> None:
    configure_logging()
    write_report(
        REPORT_DIR / "07_threshold.md",
        "Minimum-volume threshold evidence (M0-13)",
        "profiling.threshold",
        sections(connect()),
    )


if __name__ == "__main__":
    main()
