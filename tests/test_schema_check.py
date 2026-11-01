from pathlib import Path

import pytest

from ingestion.raw_csv import BULK_COLUMNS
from ingestion.schema_check import SchemaDriftError, check_fields


def test_exact_match_passes():
    check_fields(list(BULK_COLUMNS), BULK_COLUMNS, "bulk.csv")


def _drift(actual, expected=BULK_COLUMNS, **kw) -> str:
    with pytest.raises(SchemaDriftError) as e:
        check_fields(actual, expected, "bulk.csv", **kw)
    return str(e.value)


def test_added_field():
    msg = _drift([*BULK_COLUMNS, "Consumer consent provided?"])
    assert "added ['Consumer consent provided?']" in msg and "bulk.csv" in msg


def test_removed_field():
    msg = _drift([c for c in BULK_COLUMNS if c != "Tags"])
    assert "removed ['Tags']" in msg


def test_renamed_field_is_named_as_a_likely_rename():
    msg = _drift([("Timely" if c == "Timely response?" else c) for c in BULK_COLUMNS])
    assert "likely renamed ['Timely response?' -> 'Timely']" in msg


def test_reordered_fields():
    msg = _drift([BULK_COLUMNS[1], BULK_COLUMNS[0], *BULK_COLUMNS[2:]])
    assert "order changed" in msg


def test_duplicated_field():
    assert "duplicated ['Tags']" in _drift([*BULK_COLUMNS, "Tags"])


def test_unordered_comparison_ignores_order_but_not_names():
    check_fields(list(reversed(BULK_COLUMNS)), BULK_COLUMNS, "keys", ordered=False)
    msg = _drift([*BULK_COLUMNS, "narrative"], ordered=False)
    assert "added ['narrative']" in msg


def test_bulk_ingest_reports_drift_by_name(tmp_path: Path, fixture_csv):
    from ingestion.bulk import ingest

    drifted = tmp_path / "drifted.csv"
    text = fixture_csv.read_text()
    drifted.write_text(text.replace("Timely response?", "Timely", 1))
    with pytest.raises(SchemaDriftError, match=r"'Timely response\?' -> 'Timely'"):
        ingest(drifted, tmp_path / "out.parquet", snapshot_date="2026-10-31", work_dir=tmp_path)
