import duckdb

from profiling.interim import BULK_COLUMNS, count_csv_records


def test_fixture_has_raw_header_and_expected_shape(fixture_csv):
    header, rows = count_csv_records(fixture_csv)
    assert header == BULK_COLUMNS
    assert rows == 1002
    stats = (
        duckdb.connect()
        .execute(
            f"""SELECT count(DISTINCT "Company"), count(DISTINCT "Product"),
                       min("Date received"), max("Date received"), count("ZIP code")
                FROM read_csv('{fixture_csv}', all_varchar=true)"""
        )
        .fetchall()
    )
    assert stats == [(3, 1, "2025-01-02", "2026-06-30", 0)]
