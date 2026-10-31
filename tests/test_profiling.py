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


def test_duplicate_rate_hand_computed(make_interim):
    from profiling import narratives

    bulk = [_bulk(str(i), "2024-01-01") for i in range(1, 6)]
    archive = [
        _narr("1", "2024-01-01", "My card was charged XXXX twice on 01/02/2024."),
        _narr("2", "2024-01-01", "my card  was CHARGED xxxx twice on 03/04/2025"),
        _narr("3", "2024-01-01", "A completely different complaint."),
        _narr("4", "2024-01-01", None),  # no narrative: excluded
        _narr("5", "2024-01-01", "   "),  # blank: excluded
    ]
    con = connect(make_interim(bulk, archive))
    # 3 narratives; ids 1 and 2 normalise to the same text -> 2 of 3 = 66.67%
    assert con.execute(narratives.dup_rate_sql()).fetchall() == [(3, 2, 66.67)]


def test_coverage_by_month_hand_computed(make_interim):
    from profiling import coverage

    bulk = [
        _bulk("1", "2024-01-05"),
        _bulk("2", "2024-01-20"),
        _bulk("3", "2024-02-01"),
        _bulk("4", "2024-02-02"),
    ]
    archive = [
        _narr("1", "2024-01-05", "text one"),
        _narr("1", "2024-01-05", "text one", source_file="other.zip"),  # repeated id
        _narr("3", "2024-02-01", ""),  # empty narrative does not count
        _narr("9", "2024-02-01", "not in bulk"),
    ]
    con = connect(make_interim(bulk, archive))
    assert con.execute(coverage.coverage_sql("month")).fetchall() == [
        ("2024-01", 2, 1, 50.0),
        ("2024-02", 2, 0, 0.0),
    ]


def test_coverage_product_quarter_hand_computed(make_interim):
    from profiling import coverage

    bulk = [
        _bulk("1", "2024-01-05"),
        _bulk("2", "2024-02-20"),
        _bulk("3", "2024-04-01"),
        _bulk("4", "2024-04-02", product="Mortgage"),
        _bulk("5", "2022-12-31"),  # before 2023: excluded
    ]
    archive = [_narr("1", "2024-01-05", "a"), _narr("3", "2024-04-01", "b")]
    con = connect(make_interim(bulk, archive))
    # Only Credit card has narratives -> only column; Q1: 1 of 2, Q2: 1 of 1
    assert con.execute(coverage.product_quarter_sql()).fetchall() == [
        ("2024-Q1", 50.0),
        ("2024-Q2", 100.0),
    ]


def test_archive_vs_bulk_hand_computed(make_interim):
    from profiling import archive_vs_bulk

    bulk = [_bulk("1", "2024-01-01"), _bulk("2", "2024-01-01"), _bulk("3", "2024-01-01")]
    archive = [
        _narr("2", "2024-01-01", "t"),
        _narr("3", "2024-01-01", "t", company="Acme Renamed"),
        _narr("4", "2024-01-01", "t"),
    ]
    con = connect(make_interim(bulk, archive))
    assert con.execute(archive_vs_bulk.overlap_sql()).fetchall() == [("2024", 2, 1, 1)]
    mism = {f: (n, s) for _, s, f, n in con.execute(archive_vs_bulk.mismatch_sql()).fetchall()}
    assert mism["Company"] == (1, 2)
    assert mism["Product"] == (0, 2)
    # report helpers render without error
    assert (
        "Company"
        in dict(archive_vs_bulk.sections(con))[
            "Field mismatch % on shared ids, by year received (bulk)"
        ]
    )


def test_provisional_product_family(make_interim):
    bulk = [
        _bulk(
            "1", "2020-01-01", product="Credit card or prepaid card", **{"Sub-product": "Gift card"}
        ),
        _bulk(
            "2",
            "2020-01-01",
            product="Credit card or prepaid card",
            **{"Sub-product": "Store credit card"},
        ),
        _bulk("3", "2016-01-01", product="Consumer Loan", **{"Sub-product": "Vehicle loan"}),
        _bulk("4", "2016-01-01", product="Consumer Loan", **{"Sub-product": "Installment loan"}),
        _bulk("5", "2016-01-01", product="Bank account or service"),
        _bulk("6", "2024-01-01", product="Credit reporting or other personal consumer reports"),
    ]
    con = connect(make_interim(bulk, []))
    got = dict(con.execute('SELECT "Complaint ID", product_family FROM bulk_f').fetchall())
    assert got == {
        "1": "Prepaid card",
        "2": "Credit card",
        "3": "Vehicle loan or lease",
        "4": "Payday or personal loan",
        "5": "Checking or savings",
        "6": "Credit reporting",
    }
