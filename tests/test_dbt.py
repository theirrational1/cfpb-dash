import duckdb


def _con(warehouse):
    return duckdb.connect(str(warehouse.duckdb_path), read_only=True)


def test_fact_has_one_row_per_fixture_complaint(warehouse):
    con = _con(warehouse)
    assert con.execute(
        "SELECT count(*), count(DISTINCT complaint_id) FROM fct_complaints"
    ).fetchall() == [(1002, 1002)]


def test_staging_types_and_limit(warehouse):
    con = _con(warehouse)
    cols = dict(
        con.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = 'stg_complaints'"
        ).fetchall()
    )
    assert cols["complaint_id"] == "BIGINT"
    assert cols["date_received"] == "DATE"
    assert cols["date_sent_to_company"] == "DATE"
    # CLEANER Limit, docs/decisions/nulls.md: ZIP is dropped at staging
    assert "zip_code" not in cols and "ZIP code" not in cols
    assert "source_file" not in cols


STAGING_COLUMNS = [
    ("complaint_id", "BIGINT"),
    ("date_received", "DATE"),
    ("date_sent_to_company", "DATE"),
    ("product", "VARCHAR"),
    ("sub_product", "VARCHAR"),
    ("issue", "VARCHAR"),
    ("sub_issue", "VARCHAR"),
    ("company", "VARCHAR"),
    ("state", "VARCHAR"),
    ("is_older_american", "BOOLEAN"),
    ("is_servicemember", "BOOLEAN"),
    ("submitted_via", "VARCHAR"),
    ("company_response", "VARCHAR"),
    ("company_public_response", "VARCHAR"),
    ("public_response_available", "BOOLEAN"),
    ("timely", "BOOLEAN"),
]


def test_staging_contract_pins_columns_and_types(eras_warehouse):
    """M2-04: the model contract fixes the column list (ZIP excluded) and types."""
    cols = (
        _con(eras_warehouse)
        .execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = 'stg_complaints' ORDER BY ordinal_position"
        )
        .fetchall()
    )
    assert cols == STAGING_COLUMNS


def test_staging_trims_company_and_types_timely(eras_warehouse):
    con = _con(eras_warehouse)
    assert con.execute(
        "SELECT count(*) FROM stg_complaints WHERE company <> trim(company)"
    ).fetchone() == (0,)
    raw_padded = con.execute(
        f"""SELECT count(*) FROM read_parquet('{eras_warehouse.raw_parquet}')
            WHERE "Company" <> trim("Company")"""
    ).fetchone()
    assert raw_padded is not None and raw_padded[0] > 0  # the fixture does exercise it
    assert con.execute("SELECT DISTINCT timely FROM stg_complaints ORDER BY 1").fetchall() == [
        (False,),
        (True,),
    ]


def test_mf_env_selects_the_readonly_target():
    from core.warehouse import REPO_ROOT

    lines = (REPO_ROOT / "mf.env").read_text().splitlines()
    assert "CFPB_DBT_TARGET=readonly" in lines
    assert not any(line.startswith("CFPB_DBT_TARGET") for line in (REPO_ROOT / "dbt.env").open())


def test_fact_restricts_to_one_row_per_staged_complaint_with_canonical_company(eras_warehouse):
    con = _con(eras_warehouse)
    assert con.execute(
        """SELECT (SELECT count(*) FROM fct_complaints), (SELECT count(*) FROM stg_complaints),
                  (SELECT count(*) FROM fct_complaints f JOIN dim_company d USING (company_key)
                   WHERE f.company <> d.company_name)"""
    ).fetchone() == (478, 478, 0)
    cols = [r[0] for r in con.execute("DESCRIBE fct_complaints").fetchall()]
    for col in ("product_family", "credit_card_issue", "company_key", "is_relief",
                "forwarding_lag_days", "public_response"):  # fmt: skip
        assert col in cols
