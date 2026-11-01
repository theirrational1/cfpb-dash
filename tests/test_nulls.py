"""M2-05: every decision in docs/decisions/nulls.md, checked on the eras fixture (real rows
for each null pattern). The dbt tests enforce the same rules on every build."""

import duckdb
import pytest

from core.warehouse import run_cli


def _q(wh, sql):
    return duckdb.connect(str(wh.duckdb_path), read_only=True).execute(sql).fetchall()


def test_public_response_blank_on_closed_or_untimely_is_none_given(eras_warehouse):
    rows = _q(
        eras_warehouse,
        """SELECT DISTINCT company_public_response FROM stg_complaints
           WHERE date_received >= '2015-01-01' AND company_response IS NOT NULL
             AND company_response <> 'In progress' AND company_public_response IS NULL""",
    )
    assert rows == []
    assert _q(
        eras_warehouse,
        """SELECT count(*) > 0 FROM stg_complaints WHERE company_public_response = 'none_given'
           AND company_response = 'Untimely response'""",
    ) == [(True,)]


def test_public_response_stays_null_when_unknown_or_structural(eras_warehouse):
    # only pre-2015 (structural), In progress (not yet available) or status-missing rows
    assert _q(
        eras_warehouse,
        """SELECT count(*) FROM stg_complaints WHERE company_public_response IS NULL
           AND NOT (date_received < '2015-01-01' OR company_response = 'In progress'
                    OR company_response IS NULL)""",
    ) == [(0,)]
    assert _q(
        eras_warehouse,
        """SELECT DISTINCT public_response_available FROM stg_complaints
           WHERE date_received < '2015-01-01'""",
    ) == [(False,)]
    assert _q(
        eras_warehouse,
        """SELECT count(*) FROM stg_complaints
           WHERE company_response = 'In progress' AND company_public_response IS NOT NULL""",
    ) == [(0,)]


def test_tags_become_explicit_booleans(eras_warehouse):
    rows = _q(
        eras_warehouse,
        f"""SELECT r."Tags", s.is_older_american, s.is_servicemember, count(*)
           FROM stg_complaints s JOIN read_parquet('{eras_warehouse.raw_parquet}') r
             ON s.complaint_id = CAST(r."Complaint ID" AS BIGINT)
           GROUP BY ALL ORDER BY 1 NULLS FIRST""",
    )
    assert [r[:3] for r in rows] == [
        (None, False, False),
        ("Older American", True, False),
        ("Older American, Servicemember", True, True),
        ("Servicemember", False, True),
    ]


def test_state_codes_are_known_and_null_is_kept(eras_warehouse):
    assert _q(
        eras_warehouse,
        """SELECT count(*) FROM stg_complaints
           WHERE state IS NOT NULL AND state NOT IN (SELECT state_code FROM us_state_codes)""",
    ) == [(0,)]
    assert _q(eras_warehouse, "SELECT count(*) > 0 FROM stg_complaints WHERE state IS NULL") == [
        (True,)
    ]


@pytest.mark.parametrize(
    ("var", "column"),
    [("issue_null_cap", "issue"), ("company_response_null_cap", "company_response")],
)
def test_rare_error_nulls_have_a_cap_that_fails_the_build(eras_warehouse, var, column):
    """The fixture has 6 null issues and 5 null statuses: under the real caps, over a cap of 1."""
    run_cli(
        "dbt", ["test", "--select", "stg_complaints", "--exclude", "tag:full_data"], eras_warehouse
    )
    with pytest.raises(RuntimeError, match=f"null_count_at_most_stg_complaints_{column}"):
        run_cli(
            "dbt",
            [
                "test",
                "--select",
                "stg_complaints",
                "--exclude",
                "tag:full_data",
                "--vars",
                f"{{{var}: 1}}",
            ],
            eras_warehouse,
        )
