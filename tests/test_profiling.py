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


def test_company_response_pivot(make_interim):
    from profiling import company_response

    rows = [
        _bulk("1", "2024-01-01", **{"Company response to consumer": "Closed with explanation"}),
        _bulk("2", "2024-02-01", **{"Company response to consumer": "Closed with explanation"}),
        _bulk("3", "2025-01-01", **{"Company response to consumer": "In progress"}),
    ]
    con = connect(make_interim(rows, []))
    table = dict(company_response.sections(con))[
        "Company response to consumer: rows by year received"
    ]
    assert "| Closed with explanation | 2 | 0 |" in table
    assert "| In progress | 0 | 1 |" in table


def test_label_lifespan_flags(make_interim):
    from profiling import labels

    rows = [
        _bulk("1", "2020-01-01", product="Old product"),
        _bulk("2", "2020-01-01", product="Both"),
        _bulk("3", "2025-01-01", product="Both"),
        _bulk("4", "2025-01-01", product="New product"),
    ]
    con = connect(make_interim(rows, []))
    table = dict(labels.sections(con))["Products"]
    assert "| Old product | 2020 | 2020 | 1 | retired |" in table
    assert "| Both | 2020 | 2025 | 2 | whole span |" in table
    assert "| New product | 2025 | 2025 | 1 | introduced |" in table


def _narr(cid: str, received: str, txt: str | None, company: str = "Acme", **kw):
    return {
        "Complaint ID": cid,
        "Date received": received,
        "Date sent to company": received,
        "Product": "Credit card",
        "Company": company,
        "Consumer complaint narrative": txt,
        **kw,
    }
