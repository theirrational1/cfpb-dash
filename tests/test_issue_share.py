"""Issue share metrics (M3): generated from the seed, and matching reference SQL."""

import math

import duckdb
import pytest

from agent.tools.query_metric import query_metric
from core.issue_share import (
    COMPLAINTS_YML,
    OUT,
    canonical_issues,
    render,
    render_complaints_yml,
    slug,
)


def test_generated_yaml_is_current_with_the_seed():
    assert OUT.read_text() == render(), "run: uv run python -m core.issue_share"
    current = COMPLAINTS_YML.read_text()
    assert render_complaints_yml(current) == current, "run: uv run python -m core.issue_share"
    assert len(canonical_issues()) == 16  # 15 current + the legacy pre-2017 fraud value


@pytest.fixture(params=["warehouse", "eras_warehouse"])
def wh(request):
    return request.getfixturevalue(request.param)


def test_issue_shares_match_reference_sql_and_sum_to_one(wh):
    metrics = [f"issue_share_{slug(i)}" for i in canonical_issues()]
    rows = query_metric(metrics, group_by=["complaint__company"], warehouse=wh).rows
    con = duckdb.connect(str(wh.duckdb_path), read_only=True)
    for row in rows:
        if all(row[m] is None for m in metrics):
            continue  # no credit card complaint with a known issue
        shares = [float(row[m] or 0) for m in metrics]
        assert math.isclose(sum(shares), 1.0, abs_tol=1e-9), row
        for issue, metric in zip(canonical_issues(), metrics, strict=True):
            expected = con.execute(
                """SELECT count(*) FILTER (WHERE credit_card_issue = ?)
                          / count(credit_card_issue)
                   FROM fct_complaints WHERE company = ? AND product_family = 'credit_card'""",
                [issue, row["complaint__company"]],
            ).fetchone()
            assert expected is not None
            assert math.isclose(float(row[metric] or 0), expected[0], abs_tol=1e-9), (issue, row)
