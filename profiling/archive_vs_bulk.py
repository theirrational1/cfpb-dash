"""M0-16: archive vs bulk overlap by complaint_id and per-field mismatches on shared ids.

Run: uv run python -m profiling.archive_vs_bulk
"""

import duckdb

from core.log import configure_logging
from profiling.interim import BULK_COLUMNS
from profiling.report import REPORT_DIR, Sections, connect, md_table, write_report

SHARED_FIELDS = [c for c in BULK_COLUMNS if c != "Complaint ID"]


def overlap_sql() -> str:
    return """SELECT coalesce(substr(b."Date received", 1, 4), substr(a."Date received", 1, 4))
                       AS year,
                     count(*) FILTER (WHERE a."Complaint ID" IS NOT NULL
                                        AND b."Complaint ID" IS NOT NULL) AS in_both,
                     count(*) FILTER (WHERE b."Complaint ID" IS NULL) AS archive_only,
                     count(*) FILTER (WHERE a."Complaint ID" IS NULL) AS bulk_only
              FROM archive a FULL JOIN bulk b ON a."Complaint ID" = b."Complaint ID"
              GROUP BY 1 ORDER BY 1"""


def mismatch_sql() -> str:
    counts = ",\n".join(
        f'count(*) FILTER (WHERE a."{c}" IS DISTINCT FROM b."{c}") AS "{c}"' for c in SHARED_FIELDS
    )
    return f"""WITH m AS (
                 SELECT substr(b."Date received", 1, 4) AS year, count(*) AS shared_ids, {counts}
                 FROM archive a JOIN bulk b ON a."Complaint ID" = b."Complaint ID"
                 GROUP BY 1)
               UNPIVOT m ON COLUMNS(* EXCLUDE (year, shared_ids)) INTO NAME field VALUE mismatches
               """


def mismatch_pct_sql() -> str:
    return f"""WITH u AS ({mismatch_sql()})
               PIVOT (SELECT field, year, round(100.0 * mismatches / shared_ids, 2) AS pct FROM u)
               ON year USING any_value(pct) GROUP BY field ORDER BY field"""


def sections(con: duckdb.DuckDBPyConnection) -> Sections:
    return [
        (
            "Archive duplicates",
            md_table(
                con,
                """SELECT count(*) AS archive_rows, count(DISTINCT "Complaint ID") AS distinct_ids,
                          count(*) - count(DISTINCT "Complaint ID") AS repeated_rows
                   FROM narratives""",
            ),
        ),
        ("Overlap by complaint_id, by year received", md_table(con, overlap_sql())),
        (
            "Field mismatch % on shared ids, by year received (bulk)",
            "Share of complaints in both sources whose field differs (NULL-safe).\n\n"
            + md_table(con, mismatch_pct_sql()),
        ),
    ]


def main() -> None:
    configure_logging()
    write_report(
        REPORT_DIR / "06_archive_vs_bulk.md",
        "Archive vs bulk (M0-16)",
        "profiling.archive_vs_bulk",
        sections(connect()),
    )


if __name__ == "__main__":
    main()
