"""M3-04: the coverage source table states freshness, every counted exclusion and the fixed
caveats; each count equals hand-written SQL on the eras fixture (real rows of each pattern)."""

import duckdb
import pytest

COUNTS = {
    "complaints": "count(*)",
    "open_in_progress": "count(*) FILTER (WHERE company_response = 'In progress')",
    "not_closed_untimely": "count(*) FILTER (WHERE company_response = 'Untimely response')",
    "status_missing": "count(*) FILTER (WHERE company_response IS NULL)",
    "relief_outcome_unknown": "count(*) FILTER (WHERE company_response = 'Closed')",
    "relief_kind_unknown": "count(*) FILTER (WHERE company_response = 'Closed with relief')",
    "issue_missing": "count(*) FILTER (WHERE issue IS NULL)",
    "public_response_before_2015": "count(*) FILTER (WHERE date_received < '2015-01-01')",
    "sub_product_unknown": "count(*) FILTER (WHERE sub_product IS NULL)",
}


@pytest.fixture(scope="module")
def coverage(eras_warehouse):
    con = duckdb.connect(str(eras_warehouse.duckdb_path), read_only=True)
    rows = con.execute("SELECT item, scope, value, note FROM data_coverage").fetchall()
    return con, {(item, scope): (value, note) for item, scope, value, note in rows}


@pytest.mark.parametrize("item", sorted(COUNTS))
def test_exclusion_counts_match_reference_sql(coverage, item):
    con, cov = coverage
    row = con.execute(f"SELECT {COUNTS[item]} FROM fct_complaints").fetchone()
    assert row is not None and row[0] > 0, f"the eras fixture should exercise {item}"
    assert cov[(item, "all")][0] == str(row[0])


def test_freshness_and_cutoff(coverage):
    _, cov = coverage
    assert cov[("snapshot_date", "all")][0] == "2026-10-31"
    assert cov[("data_start", "all")][0] == "2011-12-07"
    assert cov[("narrative_cutoff", "all")][0] == "2026-06-30"
    generated = cov[("bulk_generated_at", "all")][0]
    assert generated.endswith("Z") and "T" in generated  # UTC, machine-independent
    assert cov[("latest_pull_as_of", "all")][0] is None  # bulk only


def test_peer_eligibility_counts_cover_every_family(coverage):
    con, cov = coverage
    families = [
        r[0] for r in con.execute("SELECT DISTINCT product_family FROM fct_complaints").fetchall()
    ]
    for family in families:
        eligible = int(cov[("eligible_companies", family)][0])
        below = int(cov[("below_threshold_companies", family)][0])
        n = con.execute(
            "SELECT count(*) FROM dim_company_product WHERE product_family = ?", [family]
        ).fetchone()
        assert n is not None and eligible + below == n[0]


def test_fixed_caveats_are_stated(coverage):
    _, cov = coverage
    notes = " ".join(note for (item, _), (_, note) in cov.items() if item.startswith("caveat"))
    for phrase in ("under $10B", "not a statistical sample", "unverified", "not rates"):
        assert phrase in notes
