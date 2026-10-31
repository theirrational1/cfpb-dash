import duckdb

from profiling import overview
from profiling.report import connect, md_table, write_report


def _bulk(cid: str, received: str, product: str = "Credit card", company: str = "Acme", **kw):
    return {
        "Complaint ID": cid,
        "Date received": received,
        "Date sent to company": received,
        "Product": product,
        "Company": company,
        **kw,
    }


def test_md_table_formats_cells():
    con = duckdb.connect()
    out = md_table(con, "SELECT 'a|b' AS s, 1234 AS n, 1.5::DOUBLE AS f, NULL AS z")
    assert out.splitlines() == [
        "| s | n | f | z |",
        "|---|---|---|---|",
        "| a\\|b | 1,234 | 1.50 | ∅ |",
    ]


def test_connect_requires_interim(tmp_path):
    import pytest

    with pytest.raises(FileNotFoundError, match="profiling.interim"):
        connect(tmp_path)


def test_overview_runs_and_counts(make_interim, tmp_path):
    root = make_interim(
        [_bulk("1", "2024-01-02"), _bulk("2", "2025-03-04", product="Mortgage"), _bulk("2", "bad")],
        [],
    )
    con = connect(root)
    secs = dict(overview.sections(con))
    assert "| 3 | 2 | 0 |" in secs["Totals"]  # rows, distinct ids, null ids
    castability = secs["Castability"].splitlines()[2]
    assert castability.startswith("| 1 | 1 |")  # "bad" row: received and sent both unparseable
    out = tmp_path / "r.md"
    write_report(out, "T", "profiling.overview", list(secs.items()), root)
    assert out.read_text().startswith("# T\n\nSnapshot: `bulk/x.csv.zip`")
