"""M0-12: evaluate each product family against the narrative-product rule (PRD / TASKS M0-12).

Rule: ≥20K narratives, ≥15 companies above the volume threshold, no single issue >50%.
Cutoff and threshold are CANDIDATES until signed off (M0-13, M0-15).
Run: uv run python -m profiling.product_rule
"""

import duckdb

from core.log import configure_logging
from profiling.report import REPORT_DIR, Sections, connect, md_table, write_report

CANDIDATE_CUTOFF_EXCLUSIVE = "2026-07-01"  # narratives received before this date
CANDIDATE_THRESHOLD = 100  # complaints per company, trailing 12 months
CURRENT_ERA_START = "2023-09-01"  # after the Aug 2023 relabel; issue labels are comparable
MIN_NARRATIVES, MIN_COMPANIES, MAX_ISSUE_PCT = 20_000, 15, 50.0


def rule_sql(
    cutoff: str = CANDIDATE_CUTOFF_EXCLUSIVE,
    threshold: int = CANDIDATE_THRESHOLD,
    era_start: str = CURRENT_ERA_START,
) -> str:
    return f"""
    WITH nb AS (
        SELECT b.product_family, b."Company" AS company, b."Issue" AS issue,
               b."Date received" AS received
        FROM narrative n JOIN bulk_f b ON b."Complaint ID" = n.complaint_id
        WHERE b."Date received" < '{cutoff}'),
    vol AS (
        SELECT product_family, count(*) AS narratives,
               count(*) FILTER (WHERE received >= '{era_start}') AS narratives_current_era
        FROM nb GROUP BY 1),
    issues AS (
        SELECT product_family, issue, count(*) AS n,
               100.0 * count(*) / sum(count(*)) OVER (PARTITION BY product_family) AS pct
        FROM nb WHERE received >= '{era_start}' GROUP BY 1, 2
        QUALIFY row_number() OVER (PARTITION BY product_family ORDER BY n DESC, issue) = 1),
    w AS (
        SELECT date_trunc('month', max("Date received"::DATE)) AS hi FROM bulk),
    comp AS (
        SELECT product_family, count(*) AS companies_ge_threshold FROM (
            SELECT product_family, "Company", count(*) AS n FROM bulk_f, w
            WHERE "Date received"::DATE >= hi - INTERVAL 12 MONTH AND "Date received"::DATE < hi
            GROUP BY ALL) WHERE n >= {threshold} GROUP BY 1)
    SELECT v.product_family, v.narratives, v.narratives_current_era,
           coalesce(c.companies_ge_threshold, 0) AS companies_ge_threshold,
           i.issue AS top_issue_current_era, round(i.pct, 1) AS top_issue_pct,
           v.narratives >= {MIN_NARRATIVES}
             AND coalesce(c.companies_ge_threshold, 0) >= {MIN_COMPANIES}
             AND coalesce(i.pct, 100) <= {MAX_ISSUE_PCT} AS passes_rule
    FROM vol v LEFT JOIN comp c USING (product_family) LEFT JOIN issues i USING (product_family)
    ORDER BY v.narratives DESC"""


def sections(con: duckdb.DuckDBPyConnection) -> Sections:
    note = (
        f"Candidate cutoff: narratives received before {CANDIDATE_CUTOFF_EXCLUSIVE}. "
        f"Candidate threshold: ≥{CANDIDATE_THRESHOLD} complaints per company in the trailing "
        f"12 months. Top issue measured on narratives received from {CURRENT_ERA_START}. "
        "Bank-analyst relevance is a human call, not computed. Families are PROVISIONAL."
    )
    return [("Product rule", note + "\n\n" + md_table(con, rule_sql()))]


def main() -> None:
    configure_logging()
    write_report(
        REPORT_DIR / "08_product_rule.md",
        "Narrative product rule (M0-12)",
        "profiling.product_rule",
        sections(connect()),
    )


if __name__ == "__main__":
    main()
