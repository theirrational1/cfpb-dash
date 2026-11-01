"""M2-07: every complaint resolves to one canonical company (100% match rate)."""

import duckdb


def _q(wh, sql):
    return duckdb.connect(str(wh.duckdb_path), read_only=True).execute(sql).fetchall()


def test_every_complaint_resolves_to_a_canonical_company(eras_warehouse):
    assert _q(
        eras_warehouse,
        """SELECT count(*) FROM int_complaints i
           LEFT JOIN dim_company d USING (company_key) WHERE d.company_key IS NULL""",
    ) == [(0,)]
    assert _q(
        eras_warehouse,
        "SELECT sum(n_complaints) = (SELECT count(*) FROM int_complaints) FROM dim_company",
    ) == [(True,)]


def test_padded_raw_names_resolve_to_the_trimmed_company(eras_warehouse):
    rows = _q(
        eras_warehouse,
        f"""SELECT DISTINCT r."Company", d.company_name
            FROM read_parquet('{eras_warehouse.raw_parquet}') r
            JOIN int_complaints i ON i.complaint_id = CAST(r."Complaint ID" AS BIGINT)
            JOIN dim_company d USING (company_key)
            WHERE r."Company" <> trim(r."Company")""",
    )
    assert rows and all(raw.strip().upper() == name.upper() for raw, name in rows)
