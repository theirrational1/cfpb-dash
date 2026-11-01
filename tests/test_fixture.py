import duckdb

from ingestion.raw_csv import BULK_COLUMNS, count_csv_records


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


def test_eras_fixture_covers_labels_eras_and_null_patterns(eras_csv):
    header, _ = count_csv_records(eras_csv)
    assert header == BULK_COLUMNS
    row = (
        duckdb.connect()
        .execute(
            f"""SELECT count(DISTINCT "Product"), min("Date received") < '2012-01-01',
                       count("ZIP code"),
                       count(*) FILTER (WHERE "Issue" IS NULL) > 0,
                       count(*) FILTER (WHERE "Company response to consumer" IS NULL) > 0,
                       count(*) FILTER (WHERE "Company response to consumer" = 'Closed') > 0,
                       count(DISTINCT "Tags")
                FROM read_csv('{eras_csv}', all_varchar=true)"""
        )
        .fetchone()
    )
    assert row == (21, True, 0, True, True, True, 3)


def test_eras_fixture_builds(eras_warehouse):
    con = duckdb.connect(str(eras_warehouse.duckdb_path), read_only=True)
    assert con.execute("SELECT count(*) FROM fct_complaints").fetchone() == (478,)
