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


def test_mf_env_selects_the_readonly_target():
    from core.warehouse import REPO_ROOT

    lines = (REPO_ROOT / "mf.env").read_text().splitlines()
    assert "CFPB_DBT_TARGET=readonly" in lines
    assert not any(line.startswith("CFPB_DBT_TARGET") for line in (REPO_ROOT / "dbt.env").open())
