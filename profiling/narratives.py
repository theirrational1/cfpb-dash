"""M0-11: narrative counts by product and company; exact-duplicate (template) rate estimate.

Product and company come from the bulk file (current state); the archive supplies text only.
Run: uv run python -m profiling.narratives
"""

import duckdb

from core.log import configure_logging
from profiling.report import REPORT_DIR, Sections, connect, md_table, write_report

# Lower-bound template detector: strip CFPB masks (XXXX) and digits, lowercase,
# drop punctuation, collapse whitespace. Near-duplicates are M6-01.
NORMALISED = """trim(regexp_replace(regexp_replace(lower(regexp_replace(regexp_replace(
    txt, '[Xx]{2,}', ' ', 'g'), '[0-9]+', ' ', 'g')), '[^a-z ]+', ' ', 'g'), ' +', ' ', 'g'))"""

DUP_CTE = f"""WITH d AS (
    SELECT n.complaint_id, b."Product" AS product,
           count(*) OVER (PARTITION BY {NORMALISED}) AS group_size
    FROM narrative n LEFT JOIN bulk b ON b."Complaint ID" = n.complaint_id)"""


def dup_rate_sql(by_product: bool = False) -> str:
    key = "product, " if by_product else ""
    group = (
        "GROUP BY product HAVING count(*) >= 1000 ORDER BY narratives DESC" if by_product else ""
    )
    return f"""{DUP_CTE}
        SELECT {key}count(*) AS narratives,
               count(*) FILTER (WHERE group_size > 1) AS in_duplicate_groups,
               round(100.0 * count(*) FILTER (WHERE group_size > 1) / count(*), 2) AS dup_pct
        FROM d {group}"""


def sections(con: duckdb.DuckDBPyConnection) -> Sections:
    joined = """FROM narrative n LEFT JOIN bulk b ON b."Complaint ID" = n.complaint_id"""
    return [
        (
            "Archive totals",
            md_table(
                con,
                """SELECT (SELECT count(*) FROM narratives) AS archive_rows,
                          (SELECT count(*) FROM archive) AS distinct_ids,
                          (SELECT count(*) FROM narrative) AS ids_with_narrative,
                          (SELECT count(*) FROM narrative n ANTI JOIN bulk b
                             ON b."Complaint ID" = n.complaint_id) AS narrative_ids_not_in_bulk""",
            ),
        ),
        (
            "Narratives by product (bulk label)",
            md_table(
                con,
                f"""SELECT coalesce(b."Product", '(not in bulk)') AS product,
                           count(*) AS narratives,
                           count(DISTINCT b."Company") AS companies
                    {joined} GROUP BY 1 ORDER BY 2 DESC""",
            ),
        ),
        (
            "Top 50 companies by narratives",
            md_table(
                con,
                f"""SELECT b."Company" AS company, count(*) AS narratives
                    {joined} WHERE b."Company" IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 50""",
            ),
        ),
        (
            "Exact-duplicate rate after normalisation (lower bound)",
            "Normalisation: remove `XXXX` masks and digits, lowercase, drop punctuation, "
            "collapse whitespace. A narrative counts as duplicated if its normalised text "
            "matches at least one other.\n\n" + md_table(con, dup_rate_sql()),
        ),
        ("Duplicate rate by product (≥1,000 narratives)", md_table(con, dup_rate_sql(True))),
    ]


def main() -> None:
    configure_logging()
    write_report(
        REPORT_DIR / "04_narratives.md",
        "Narratives and template rate (M0-11)",
        "profiling.narratives",
        sections(connect()),
    )


if __name__ == "__main__":
    main()
